"""Decide what to do with a request's text and produce the reply to speak.

A reply is a string, or (for Claude) an iterator of sentences that arrive while Claude is still
answering; the daemon speaks each one as soon as it comes.
"""

import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from abdoh.claude import skills
from abdoh.claude.brain import NOT_CONNECTED, BrainError
from abdoh.claude.reply import speakable
from abdoh.claude.screen import ScreenCaptureError, capture_screen
from abdoh.commands.actions import ActionError, claude_action, run_actions
from abdoh.commands.matcher import match, match_command, remove_wake_words, strip_wake_words
from abdoh.commands.registry import Command, CommandRegistry
from abdoh.config import Config
from abdoh.local_skills import LocalSkills

log = logging.getLogger(__name__)

UNKNOWN = "Sorry, I don't know that one yet."
COMMANDS_FILE_ERROR = "Your commands file has an error."

Reply = str | Iterator[str]


@dataclass
class ClaudeTurn:
    """The last request Claude handled, for "remember that" and follow-up questions."""

    request: str
    answer: str = ""
    actions: list[tuple[str, str]] = field(default_factory=list)
    finished_at: float = 0.0


class Router:
    def __init__(
        self,
        cfg: Config,
        registry: CommandRegistry,
        brain=None,
        run=run_actions,
        act=claude_action,
        capture=capture_screen,
        on_thinking: Callable[[], None] = lambda: None,
        computer=None,
    ):
        self.cfg = cfg
        self.registry = registry
        self.brain = brain  # Claude (Brain) or None; may be replaced at runtime
        self.computer = computer  # media keys, timers, apps (abdoh.computer.Computer)
        self.on_thinking = on_thinking  # called when a slow (Claude) request starts
        self.last_turn: ClaudeTurn | None = None
        self._run = run
        self._act = act
        self._capture = capture
        self._builtins: dict[str, Callable[[], str]] = {}
        self._builtin_commands: list[Command] = []

    @property
    def computer(self):
        return self._computer

    @computer.setter
    def computer(self, computer) -> None:
        self._computer = computer
        self.local = LocalSkills(computer) if computer is not None else None

    @property
    def wake_words(self) -> list[str]:
        return self.cfg.wake_words + self.cfg.wake_word_aliases

    def add_builtin(self, name: str, triggers: list[str], handler: Callable[[], str]) -> None:
        """Register a built-in voice command (checked before commands.yaml)."""
        self._builtins[name] = handler
        self._builtin_commands.append(Command(name, triggers, []))

    def builtin_name(self, text: str) -> str | None:
        """Name of the built-in command this text asks for, if any."""
        request = strip_wake_words(text, self.wake_words)
        found = match(request, self._builtin_commands, self.cfg.match_threshold)
        return found[0].name if found else None

    def handle(self, text: str) -> Reply:
        """Route one request. Returns the reply ("" means nothing to say)."""
        prefix = COMMANDS_FILE_ERROR if self.registry.refresh() else ""
        request = strip_wake_words(text, self.wake_words)
        if not request:
            return prefix
        reply = self._route(request, remove_wake_words(text, self.wake_words) or request)
        if isinstance(reply, str):
            return f"{prefix} {reply}".strip()
        return _prepend(prefix, reply) if prefix else reply

    def _route(self, request: str, original: str) -> Reply:
        # 1. Built-in commands (show window, pause, ...)
        builtin = match(request, self._builtin_commands, self.cfg.match_threshold)
        if builtin:
            log.info("Built-in command %r", builtin[0].name)
            return self._builtins[builtin[0].name]()

        # 2. Commands from commands.yaml
        found = match_command(request, self.registry.commands, self.cfg.match_threshold)
        if found:
            log.info("Matched command %r (score %.0f)", found.command.name, found.score)
            try:
                spoken = self._run(
                    found.command, self.cfg.allow_run, computer=self.computer, slots=found.slots
                )
                return " ".join(spoken)
            except ActionError as e:
                return str(e)

        # 3. Built-in skills that need no Claude (timers, media keys, open an app, ...)
        if self.local is not None:
            reply = self.local.handle(request)
            if reply is not None:
                log.info("Local skill handled %r", request)
                return reply

        # 4. Screen skills
        words = set(request.split())
        if skills.is_translate_request(words):
            target = skills.parse_target_language(request) or self.cfg.claude.translate_target
            prompt = skills.TRANSLATE_PROMPT.format(target=target)
            return self._ask(prompt, original, screen=True)
        if skills.is_summarize_request(words):
            return self._ask(skills.SUMMARIZE_PROMPT, original, screen=True)

        # 5. Ask Claude
        if self.brain is not None:
            return self._ask(original, original)

        # 6. Nothing matched
        return f"{UNKNOWN} {NOT_CONNECTED}"

    def _ask(self, prompt: str, request: str, screen: bool = False) -> Reply:
        if self.brain is None:
            return NOT_CONNECTED
        self.on_thinking()
        return self._stream(self.brain, prompt, request, screen)

    def _stream(self, brain, prompt: str, request: str, screen: bool) -> Iterator[str]:
        """Claude's answer as sentences; runs the actions it asks for along the way."""
        turn = ClaudeTurn(request)
        problems: list[str] = []
        spoken: list[str] = []

        def act(kind: str, arg: str) -> None:
            turn.actions.append((kind, arg))
            try:
                self._act(kind, arg, self.computer)
            except ActionError as e:
                problems.append(str(e))

        chunks = None
        try:
            image = self._capture() if screen else None
            chunks = brain.stream(prompt, image)
            for sentence in speakable(chunks, act):
                yield from _drain(problems)
                spoken.append(sentence)
                yield sentence
            yield from _drain(problems)
        except (BrainError, ScreenCaptureError) as e:
            yield str(e)
        finally:
            close = getattr(chunks, "close", None)
            if close:
                close()  # stops Claude if we were interrupted
            turn.answer = " ".join(spoken)
            turn.finished_at = time.monotonic()
            self.last_turn = turn


def _drain(items: list[str]) -> Iterator[str]:
    while items:
        yield items.pop(0)


def _prepend(first: str, rest: Iterator[str]) -> Iterator[str]:
    yield first
    yield from rest
