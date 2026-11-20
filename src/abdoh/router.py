"""Decide what to do with a request's text and produce the reply to speak.

A reply is a string, or (for Claude) an iterator of sentences that arrive while Claude is still
answering; the daemon speaks each one as soon as it comes.
"""

import logging
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from abdoh.claude import skills
from abdoh.claude.brain import NOT_CONNECTED, BrainError
from abdoh.claude.reply import IGNORE, LOOK, speakable
from abdoh.claude.screen import ScreenCaptureError, capture_screen, front_window
from abdoh.commands.actions import ActionError, claude_action, run_actions
from abdoh.commands.learn import append_command
from abdoh.commands.matcher import (
    match,
    match_command,
    normalize,
    remove_wake_words,
    strip_wake_words,
)
from abdoh.commands.registry import Command, CommandRegistry
from abdoh.config import Config
from abdoh.local_skills import LocalSkills
from abdoh.system_skills import Done, Question

log = logging.getLogger(__name__)

UNKNOWN = "Sorry, I don't know that one yet."
SCREEN_OFF = "Looking at your screen is turned off in Xanthos's permissions."
LOOKING = "Looking at your screen"
# Claude gets your clipboard only when you mention it.
_CLIPBOARD = re.compile(r"\bclipboard\b|\b(?:what|the text|the thing|that) i (?:just )?copied\b")
CLIPBOARD_LIMIT = 4000
CLIPBOARD_NOTE = '\n\nThe user\'s clipboard contains:\n"""\n{text}\n"""'
COMMANDS_FILE_ERROR = "Your commands file has an error."
NOTHING_TO_REMEMBER = (
    "There's nothing to remember yet. Ask me to do something, then say: remember that."
)
# What you say right after a reply, without the wake word, may be meant for someone else.
ASIDE = (
    "(Said right after your last reply, without your name. It may be meant for someone else "
    "in the room. If it isn't meant for you, write only the line ACTION ignore: not for me, "
    "and nothing else.)\n"
)
FOLLOW_UP = """For context, the previous exchange was:
User: {request}
Xanthos: {answer}

The user now says: {text}"""
# Modes: "movie mode", "switch to work mode", "back to normal", "which mode am I in".
_MODE_ON = (
    "{name} mode", "{name} mode on", "switch to {name} mode", "go to {name} mode",
    "change to {name} mode", "turn on {name} mode", "activate {name} mode", "start {name} mode",
    "enable {name} mode", "set {name} mode", "put on {name} mode", "{name} time",
)  # fmt: skip
_MODE_END = re.compile(
    r"(?:exit|leave|end|stop|quit|turn off|switch off|disable|cancel|close) "
    r"(?:the |this |current )?(?:(?P<name>[\w ]+?) )?mode"
    r"|(?P<name2>[\w ]+?) mode off|(?:go )?back to normal(?: mode)?"
    r"|normal mode"
)
# "Which mode am I in?", "what is the mode that is on now", "is any mode on", "current mode"
_MODE_WHICH = re.compile(
    r"(?:(?:which|what|whats)(?: is)?(?: the)? (?:current |active )?mode(?: that s| that is"
    r"| thats| is| am i| are we| do i have)? ?(?:on|active|running|in|using|enabled|is this"
    r"|this|right now|now)?(?: right now| now| at the moment| currently)?"
    r"|(?:am i|are we) in (?:a|any) mode(?: now| right now)?|is (?:a|any) mode on(?: now)?"
    r"|(?:the )?current mode|which mode is it|what mode is it)"
)
_MODE_LIST = re.compile(r"(?:what|which) modes (?:do i have|are there)|list (?:my |the )?modes")
MODE_MATCH = 90  # mode names are short: only a close match counts ("dark" isn't "park")
_REMEMBER = re.compile(
    r"(?:please )?(?:remember|save) (?:that|this|it)(?: (?:as|for) (?P<phrase>.+?))?(?: please)?"
)

Reply = str | Iterator[str]


@dataclass
class ClaudeTurn:
    """The last request Claude handled, for "remember that" and follow-up questions."""

    request: str
    answer: str = ""
    actions: list[tuple[str, str]] = field(default_factory=list)
    finished_at: float = 0.0
    ignored: bool = False  # it wasn't meant for Xanthos (ACTION ignore)


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
        window=front_window,
    ):
        self.cfg = cfg
        self.registry = registry
        self.brain = brain  # Claude (Brain) or None; may be replaced at runtime
        self.computer = computer  # media keys, timers, apps (abdoh.computer.Computer)
        self.on_thinking = on_thinking  # called when a slow (Claude) request starts
        self.on_activity: Callable[[str], None] = lambda text: None  # "Looking at your screen"
        self.last_turn: ClaudeTurn | None = None
        self.last_reply = ""  # what Xanthos said last, for "repeat that"
        self._run = run
        self._act = act
        self._capture = capture
        self._window = window
        self.modes = None  # abdoh.modes.engine.ModeEngine, or None
        self._builtins: dict[str, Callable[[], str]] = {}
        self._builtin_commands: list[Command] = []

    @property
    def computer(self):
        return self._computer

    @computer.setter
    def computer(self, computer) -> None:
        self._computer = computer
        self.local = None
        if computer is not None:
            self.local = LocalSkills(
                computer,
                last_reply=lambda: self.last_reply,
                allow_power=lambda: self.cfg.allow_power,
            )

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

    def handle(self, text: str, aside: bool = False) -> Reply:
        """Route one request. Returns the reply ("" means nothing to say). `aside`: said right
        after a reply without the wake word, so maybe to someone else (Claude decides)."""
        prefix = COMMANDS_FILE_ERROR if self.registry.refresh() else ""
        request = strip_wake_words(text, self.wake_words)
        if not request:
            return prefix
        reply = self._route(request, remove_wake_words(text, self.wake_words) or request, aside)
        if isinstance(reply, str):
            if reply:
                self.last_reply = reply
            if not prefix:
                return reply  # keeps its kind: Question, Done or plain words
            asks = isinstance(reply, Question)
            reply = f"{prefix} {reply}".strip()
            return Question(reply) if asks else reply
        return _prepend(prefix, reply) if prefix else reply

    def _route(self, request: str, original: str, aside: bool = False) -> Reply:
        # 0. "Remember that": save what Claude just did as a command
        remember = _REMEMBER.fullmatch(request)
        if remember:
            return self._remember(remember.group("phrase"))

        # 1. Built-in commands (show window, pause, ...)
        builtin = match(request, self._builtin_commands, self.cfg.match_threshold)
        if builtin:
            log.info("Built-in command %r", builtin[0].name)
            return self._builtins[builtin[0].name]()

        # 1b. Modes ("movie mode", "back to normal"): before your commands and the built-in
        # skills, so a mode called Dark wins over the dark theme.
        if self.modes is not None:
            reply = self._mode(request)
            if reply is not None:
                return reply

        # 2. Commands from commands.yaml
        found = match_command(request, self.registry.commands, self.cfg.match_threshold)
        if found:
            log.info("Matched command %r (score %.0f)", found.command.name, found.score)
            try:
                spoken = self._run(
                    found.command, self.cfg.allow_run, computer=self.computer, slots=found.slots
                )
                return " ".join(spoken) or Done("")  # your own "say" actions are spoken
            except ActionError as e:
                return str(e)

        # 3. Built-in skills that need no Claude (timers, media keys, open an app, ...)
        if self.local is not None:
            reply = self.local.handle(request, original)
            if reply is not None:
                log.info("Local skill handled %r", request)
                return reply

        # 4. Screen skills
        words = set(request.split())
        translate = skills.is_translate_request(words)
        if (translate or skills.is_summarize_request(words)) and not self.cfg.claude.allow_screen:
            return SCREEN_OFF
        if translate:
            target = skills.parse_target_language(request) or self.cfg.claude.translate_target
            prompt = skills.TRANSLATE_PROMPT.format(target=target)
            return self._ask(prompt, original, screen=True)
        if skills.is_summarize_request(words):
            return self._ask(skills.SUMMARIZE_PROMPT, original, screen=True)

        # 5. Ask Claude (with the previous exchange, if this may be a follow-up)
        if self.brain is not None:
            prompt = self._with_context(original) + self._clipboard(request)
            return self._ask(ASIDE + prompt if aside else prompt, original, aside=aside)

        # 6. Nothing matched
        return f"{UNKNOWN} {NOT_CONNECTED}"

    def _mode(self, request: str) -> str | None:
        modes = self.modes
        if _MODE_WHICH.fullmatch(request):
            return modes.describe()
        if _MODE_LIST.fullmatch(request):
            names = modes.names()
            if not names:
                return "You don't have any modes yet. Make one on the Modes page."
            return f"Your modes: {', '.join(names)}."
        ending = _MODE_END.fullmatch(request)
        if ending:
            name = ending["name"] or ending["name2"]
            if name and name not in ("the", "this", "current") and modes.find(name) is None:
                return None  # "turn off dark mode": not one of your modes
            if name and modes.find(name) and modes.current != modes.find(name).name:
                return f"{modes.find(name).name} mode isn't on."
            try:
                return modes.deactivate()
            except ActionError as e:
                return str(e)
        choices = [
            Command(m.name, [p.format(name=m.name.lower()) for p in _MODE_ON] + list(m.phrases), [])
            for m in modes.modes()
        ]
        found = match(request, choices, max(MODE_MATCH, self.cfg.match_threshold))
        if not found:
            return None
        log.info("Mode %r (score %.0f)", found[0].name, found[1])
        try:
            return modes.activate(found[0].name)
        except ActionError as e:
            return str(e)

    def _ask(self, prompt: str, request: str, screen: bool = False, aside: bool = False) -> Reply:
        if self.brain is None:
            return NOT_CONNECTED
        self.on_thinking()
        return self._stream(self.brain, prompt, request, screen, aside)

    def _stream(
        self, brain, prompt: str, request: str, screen: bool, aside: bool = False
    ) -> Iterator[str]:
        """Claude's answer as sentences; runs the actions it asks for along the way."""
        turn = ClaudeTurn(request)
        problems: list[str] = []
        spoken: list[str] = []

        looks: list[str] = []  # Claude asked to see the screen

        def act(kind: str, arg: str) -> None:
            if kind == LOOK:
                looks.append(arg)
                return
            if kind == IGNORE:
                log.info("Not meant for Xanthos: staying quiet")
                turn.ignored = True
                return
            try:
                self._act(kind, arg, self.computer)
                turn.actions.append((kind, arg))  # only what worked can be remembered
            except ActionError as e:
                problems.append(str(e))

        allowed = list(self.cfg.claude.actions)
        if self.cfg.claude.allow_screen and not screen:
            allowed.append(LOOK)  # at most once: the follow-up can't ask again
        if aside:
            allowed.append(IGNORE)
        chunks = None
        try:
            image = self._capture() if screen else None
            chunks = brain.stream(prompt, image)
            for sentence in speakable(chunks, act, allowed=allowed):
                if turn.ignored:
                    break  # not for Xanthos: nothing is said
                yield from _drain(problems)
                spoken.append(sentence)
                yield sentence
            yield from _drain(problems)
            if looks and not turn.ignored:
                log.info("Claude asked to look at the screen: %s", looks[0])
                chunks.close()
                self.on_activity(LOOKING)
                window = self._window()
                image = self._capture()
                follow_up = skills.look_follow_up(request, window.title, window.program)
                chunks = brain.stream(follow_up, image)
                for sentence in speakable(chunks, act, allowed=self.cfg.claude.actions):
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
            if turn.answer:
                self.last_reply = turn.answer
            turn.finished_at = time.monotonic()
            self.last_turn = turn

    def _clipboard(self, request: str) -> str:
        """Your clipboard, for Claude, when you talk about it ("translate what I copied")."""
        if not _CLIPBOARD.search(request) or self.computer is None:
            return ""
        try:
            text = self.computer.clipboard().strip()
        except (ActionError, AttributeError):
            return ""
        return CLIPBOARD_NOTE.format(text=text[:CLIPBOARD_LIMIT]) if text else ""

    def _with_context(self, text: str) -> str:
        if getattr(self.brain, "remembers", False):
            return text  # Claude Code keeps the conversation itself
        turn = self.last_turn
        window = self.cfg.claude.followup_seconds
        if turn and turn.answer and window > 0 and time.monotonic() - turn.finished_at <= window:
            return FOLLOW_UP.format(request=turn.request, answer=turn.answer, text=text)
        return text

    def _remember(self, phrase: str | None) -> str:
        turn = self.last_turn
        if turn is None or not turn.actions:
            return NOTHING_TO_REMEMBER
        if self.registry.error:
            return f"{COMMANDS_FILE_ERROR} Fix it first, then try again."
        if phrase in ("a command", "command", "a shortcut"):
            phrase = None
        trigger = normalize(phrase or turn.request)
        existing = match_command(trigger, self.registry.commands, 100)
        if existing:
            return f"You already have a command for {trigger}."
        taken = {c.name for c in self.registry.commands}
        try:
            name = append_command(self.registry.path, trigger, turn.actions, turn.request, taken)
        except (ValueError, OSError) as e:
            log.error("Couldn't save the command: %s", e)
            return "Sorry, I couldn't save that to your commands file."
        log.info("Saved command %r for %r: %s", name, trigger, turn.actions)
        self.registry.refresh(force=True)
        self.last_turn = None  # remembered; don't save it twice
        return f"Saved. Next time just say: {trigger}."


def _drain(items: list[str]) -> Iterator[str]:
    while items:
        yield items.pop(0)


def _prepend(first: str, rest: Iterator[str]) -> Iterator[str]:
    yield first
    yield from rest
