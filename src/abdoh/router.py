"""Decide what to do with a request's text and produce the reply to speak."""

import logging
from collections.abc import Callable

from abdoh.claude import skills
from abdoh.claude.client import NOT_CONNECTED, ClaudeError
from abdoh.claude.screen import ScreenCaptureError, capture_screen
from abdoh.commands.actions import ActionError, run_actions
from abdoh.commands.matcher import match, strip_wake_words
from abdoh.commands.registry import Command, CommandRegistry
from abdoh.config import Config

log = logging.getLogger(__name__)

UNKNOWN = "Sorry, I don't know that one yet."
COMMANDS_FILE_ERROR = "Your commands file has an error."
ONE_SEC = "One sec..."


class Router:
    def __init__(
        self,
        cfg: Config,
        registry: CommandRegistry,
        claude=None,
        run=run_actions,
        capture=capture_screen,
        notify: Callable[[str], None] = lambda text: None,
    ):
        self.cfg = cfg
        self.registry = registry
        self.claude = claude  # ClaudeClient or None; may be replaced at runtime
        self.notify = notify  # says interim messages like "One sec..."
        self._run = run
        self._capture = capture
        self._builtins: dict[str, Callable[[], str]] = {}
        self._builtin_commands: list[Command] = []

    def add_builtin(self, name: str, triggers: list[str], handler: Callable[[], str]) -> None:
        """Register a built-in voice command (checked before commands.yaml)."""
        self._builtins[name] = handler
        self._builtin_commands.append(Command(name, triggers, []))

    def builtin_name(self, text: str) -> str | None:
        """Name of the built-in command this text asks for, if any."""
        request = strip_wake_words(text, self.cfg.wake_words + self.cfg.wake_word_aliases)
        found = match(request, self._builtin_commands, self.cfg.match_threshold)
        return found[0].name if found else None

    def handle(self, text: str) -> str:
        """Route one request. Returns the reply text ("" means nothing to say)."""
        prefix = ""
        if self.registry.refresh():
            prefix = COMMANDS_FILE_ERROR + " "
        request = strip_wake_words(text, self.cfg.wake_words + self.cfg.wake_word_aliases)
        if not request:
            return prefix.strip()
        return (prefix + self._route(request)).strip()

    def _route(self, request: str) -> str:
        # 0. Built-in commands (show window, pause, ...)
        builtin = match(request, self._builtin_commands, self.cfg.match_threshold)
        if builtin:
            log.info("Built-in command %r", builtin[0].name)
            return self._builtins[builtin[0].name]()

        # 1. Commands from commands.yaml
        found = match(request, self.registry.commands, self.cfg.match_threshold)
        if found:
            command, score = found
            log.info("Matched command %r (score %.0f)", command.name, score)
            try:
                return " ".join(self._run(command, self.cfg.allow_run))
            except ActionError as e:
                return str(e)

        # 2. Built-in Claude skills
        words = set(request.split())
        if skills.is_translate_request(words):
            target = skills.parse_target_language(request) or self.cfg.claude.translate_target
            return self._claude(lambda c: skills.translate_screen(c, target, self._capture))
        if skills.is_summarize_request(words):
            return self._claude(lambda c: skills.summarize_screen(c, self._capture))

        # 3. Ask Claude
        if self.claude is not None:
            return self._claude(lambda c: c.ask(request))

        # 4. Nothing matched
        return f"{UNKNOWN} {NOT_CONNECTED}"

    def _claude(self, call) -> str:
        claude = self.claude
        if claude is None:
            return NOT_CONNECTED
        self.notify(ONE_SEC)
        try:
            return call(claude)
        except (ClaudeError, ScreenCaptureError) as e:
            return str(e)
