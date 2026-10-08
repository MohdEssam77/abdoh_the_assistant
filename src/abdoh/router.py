"""Decide what to do with a request's text and produce the reply to speak."""

import logging

from abdoh.claude.client import NOT_CONNECTED, ClaudeError
from abdoh.commands.actions import ActionError, run_actions
from abdoh.commands.matcher import match, strip_wake_words
from abdoh.commands.registry import CommandRegistry
from abdoh.config import Config

log = logging.getLogger(__name__)

UNKNOWN = "Sorry, I don't know that one yet."
COMMANDS_FILE_ERROR = "Your commands file has an error."


class Router:
    def __init__(self, cfg: Config, registry: CommandRegistry, claude=None, run=run_actions):
        self.cfg = cfg
        self.registry = registry
        self.claude = claude  # ClaudeClient or None; may be replaced at runtime
        self._run = run

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
        # 1. Commands from commands.yaml
        found = match(request, self.registry.commands, self.cfg.match_threshold)
        if found:
            command, score = found
            log.info("Matched command %r (score %.0f)", command.name, score)
            try:
                return " ".join(self._run(command, self.cfg.allow_run))
            except ActionError as e:
                return str(e)

        # 2. Claude skills (Story 7)

        # 3. Ask Claude
        if self.claude is not None:
            return self._claude(lambda: self.claude.ask(request))

        # 4. Nothing matched
        return f"{UNKNOWN} {NOT_CONNECTED}"

    def _claude(self, call) -> str:
        try:
            return call()
        except ClaudeError as e:
            return str(e)
