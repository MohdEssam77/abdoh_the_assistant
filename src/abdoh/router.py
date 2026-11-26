"""Decide what to do with a request's text and produce the reply to speak.

A reply is a string, or (for Claude) an iterator of sentences that arrive while Claude is still
answering; the daemon speaks each one as soon as it comes.
"""

import itertools
import logging
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from abdoh.claude import skills
from abdoh.claude.brain import NOT_CONNECTED, BrainError
from abdoh.claude.reply import (
    ANSWER,
    BOARD_PDF,
    FORGET,
    IGNORE,
    LESSON,
    LISTEN,
    LOGS,
    LOOK,
    MEMORY_ACTIONS,
    RECALL,
    ROLE,
    SAVE_ITEM,
    SAVE_STEPS,
    SELF_EDIT_ACTIONS,
    UNDO_CHANGE,
    WATCH,
    speakable,
)
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
from abdoh.commands.steps import StepRecorder
from abdoh.config import Config
from abdoh.local_skills import LocalSkills
from abdoh.steps import split_steps
from abdoh.system_skills import Done, Question

log = logging.getLogger(__name__)

# How a request came after the wake word: True, or (score, voice check or None) when the wake
# engine said how clearly the name was heard and how sure it was the user.
Wake = bool | tuple[float, float | None]

UNKNOWN = "Sorry, I don't know that one yet."
SCREEN_OFF = "Looking at your screen is turned off in Abdoh's permissions."
LOOKING = "Looking at your screen"
REMEMBERING = "Remembering"
READING_LOG = "Reading my log"
# Watching the screen (abdoh/watch.py)
STOPPED_WATCHING = "Okay, I stopped watching your screen."
WATCH_OFF = ("off", "stop", "end", "done", "no", "none", "finished")
# What the user says while Abdoh watches: it comes with a picture of their screen.
WATCHING = (
    "(You're watching the user's screen: {goal}. {kind} The picture is their screen now. They "
    "said this without your name: usually to you, about what they're doing. If it's clearly "
    "meant for someone else in the room, write only the line ACTION ignore: not for me.)\n"
)
# What Claude speaks up about, and how the user changes it ("stop suggesting for now").
WATCH_KIND = {
    False: "You speak up about mistakes only. If they want suggestions too, write the line "
    "ACTION watch: {goal} | suggestions",
    True: "You speak up about mistakes and with suggestions. If they want no more suggestions, "
    "write the line ACTION watch: {goal} | mistakes",
}
# A picture of the screen during a watch, nobody having said anything.
WATCH_FRAME = (
    "(Watching the user's screen: {goal}. Here is their screen now{window}, {minutes} into the "
    "watch.{notes} Nobody asked anything: decide whether to speak up.) {when} Don't repeat what "
    "you already said. When the task is clearly done, say so in one sentence and write "
    "ACTION watch: off."
)
WATCH_WHEN = {
    False: "If they're doing fine, or nothing new that matters happened, write only the line "
    "ACTION ignore: fine. If they made a mistake, are about to, or seem stuck, say so in one or "
    "two short spoken sentences, and how to fix it.",
    True: "They want suggestions too. If they made a mistake, are about to, or seem stuck, say "
    "so in one or two short spoken sentences, and how to fix it. If you see something really "
    "worth mentioning for what they're doing (a better or cheaper choice, a warning, a useful "
    "tip), say it in one or two short spoken sentences. Otherwise, and that's most of the time, "
    "write only the line ACTION ignore: fine.",
}
# Claude gets your clipboard only when you mention it.
_CLIPBOARD = re.compile(r"\bclipboard\b|\b(?:what|the text|the thing|that) i (?:just )?copied\b")
CLIPBOARD_LIMIT = 4000
CLIPBOARD_NOTE = '\n\nThe user\'s clipboard contains:\n"""\n{text}\n"""'
COMMANDS_FILE_ERROR = "Your commands file has an error."
NOTHING_TO_SAVE = "I didn't just do anything I could save as a command."
# What you say right after a reply, without the wake word, may be meant for someone else.
ASIDE = (
    "(Said right after your last reply, without your name. It may be meant for someone else "
    "in the room. If it isn't meant for you, write only the line ACTION ignore: not for me, "
    "and nothing else.)\n"
)
# Said after the wake word, which a video, music or people talking nearby can set off by mistake.
# {heard}: how clearly the name was heard (see woken_note).
WOKEN = (
    "(Said right after your wake word{heard}. A video, music or people talking nearby sometimes "
    "set it off by mistake. If this clearly isn't said to you as the user's assistant (a line "
    "from a video or a song, or the user talking to someone else), write only the line "
    "ACTION ignore: not for me, and nothing else. A lone word or a scrap that asks nothing (a "
    'name, "yeah", half a sentence) isn\'t for you either, unless your name was heard clearly. '
    "If it could be a request or a question for you, answer it: when the user called you "
    "clearly in their own voice, it is meant for you.)\n"
)
# How the wake word's score reads to Claude: at least CLEAR_WAKE is "clearly", at least
# FAIR_WAKE "fairly clearly", below that "faintly".
CLEAR_WAKE, FAIR_WAKE = 0.8, 0.5
# A mode just asked something ("Run it on what's connected?") and the answer wasn't a plain yes
# or no: Claude decides whether this answers it.
ANSWER_NOTE = (
    '(Abdoh just asked the user: "{question}" If what they say now answers that, write only '
    "the line ACTION answer: yes or ACTION answer: no. Otherwise handle it as a new request.)\n"
)
# Abdoh heard you talk after its wake word but no words came out (daemon: heard_unclear).
UNCLEAR = "(Just before this, Abdoh heard the user speak but couldn't make out any words.)\n"
UNCLEAR_SECONDS = 60.0
# One of several things asked at once that nothing but Claude knows (abdoh/steps.py).
STEP = (
    'The user asked for several things at once: "{request}". Abdoh does them one by one and '
    "takes care of the others. Do only this one now: {step}"
)
# What Abdoh did by itself just before (the built-in skills, your commands), so Claude knows.
ABDOH_DID = (
    '(Just before this, Abdoh did this itself, without you, for the user\'s request "{request}": '
    "{steps}. ACTION save_steps would save those steps.)\n"
)
ABDOH_DID_SECONDS = 600.0
# Asked for a second time (abdoh/commands/repeats.py): Abdoh offers to make it a command, and
# Claude understands the answer.
OFFER = "Want me to save that as a command?"
OFFER_SECONDS = 60.0
OFFER_NOTE = (
    '(For the user\'s request "{request}" this was done: {steps}. They have asked for it '
    'before, so Abdoh asked them: "{offer}" What they say now answers that, or the question '
    "you asked about it. If it's yes and they said what to call it, write ACTION save_steps: "
    "<their phrase>. If it's yes without a name, don't choose one: ask in one short question "
    "what they'd like to say to start it, suggesting a short phrase. If it's no, just say "
    "okay. If they say something else, do that instead.)\n"
)
FOLLOW_UP = """For context, the previous exchange was:
User: {request}
Abdoh: {answer}

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
# Starting one of your roles without Claude: "act as my German teacher" (and the role's phrases).
# Anything else about roles (a made-up one, stopping in any words) is Claude's to understand.
_ROLE_ON = ("act as {name}", "act as my {name}", "act as a {name}", "act as an {name}",
            "be my {name}", "{name} role")  # fmt: skip

Reply = str | Iterator[str]


def woken_note(wake: Wake) -> str:
    """WOKEN, saying how clearly the name was heard when the wake engine told."""
    heard = ""
    if isinstance(wake, tuple):
        score, voice = wake
        how = "faintly"
        if score >= CLEAR_WAKE:
            how = "clearly"
        elif score >= FAIR_WAKE:
            how = "fairly clearly"
        heard = f", heard {how} ({score:.2f})"
        if voice is not None:
            heard += ", in the user's own voice"  # the voice check let it through
    return WOKEN.format(heard=heard)


@dataclass
class ClaudeTurn:
    """The last request Claude handled, for "remember that" and follow-up questions."""

    request: str
    answer: str = ""
    actions: list[tuple[str, str]] = field(default_factory=list)
    finished_at: float = 0.0
    ignored: bool = False  # it wasn't meant for Abdoh (ACTION ignore)
    by_abdoh: bool = False  # Abdoh did it by itself, without Claude
    failed: bool = False  # Claude couldn't answer (a usage limit, no connection)


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
        grab=None,
    ):
        self.cfg = cfg
        self.registry = registry
        self.brain = brain  # Claude (Brain) or None; may be replaced at runtime
        self.computer = computer  # media keys, timers, apps (abdoh.computer.Computer)
        self.on_thinking = on_thinking  # called when a slow (Claude) request starts
        self.on_activity: Callable[[str], None] = lambda text: None  # "Looking at your screen"
        self.on_memory: Callable[[], None] = lambda: None  # the memory changed (the page)
        # Claude changed a command, mode or role ("command", "mode", "role"): the pages refresh.
        self.on_self_edit: Callable[[str], None] = lambda kind: None
        self._editor = None  # abdoh.self_edit.SelfEditor, made when first needed
        # Shows what a role puts on the board: (card, text so far), one card per reply.
        self.on_board: Callable[[int, str], None] | None = None
        # "Save the board": the page sends the board to be printed (it has the drawings).
        self.on_board_pdf: Callable[[], None] = lambda: None
        self._cards = itertools.count(1)
        self._last_turn: ClaudeTurn | None = None
        self._turn_before: ClaudeTurn | None = None
        # What Abdoh did by itself for the request being handled (steps.StepRecorder notes it).
        self._done: list[tuple[str, str]] = []
        self._told: ClaudeTurn | None = None  # the turn of Abdoh's own Claude was told about
        self._offer: ClaudeTurn | None = None  # Abdoh asked whether to save this as a command
        self._offer_at = 0.0
        self._answering: ClaudeTurn | None = None  # the request being handled answers the offer
        self._in_steps = False  # one of several things asked at once is with Claude
        self.last_reply = ""  # what Abdoh said last, for "repeat that"
        self._run = run
        self._act = act
        self._capture = capture
        self._window = window
        self._grab = grab  # the screen as a picture, for watching it (None: the real screen)
        self.modes = None  # abdoh.modes.engine.ModeEngine, or None
        self.acting = None  # abdoh.roles.acting.Acting, or None
        self._builtins: dict[str, Callable[[], str]] = {}
        self._builtin_commands: list[Command] = []
        self._unclear_at: float | None = None  # when Abdoh last heard you but got no words
        self.watch = None  # abdoh.watch.Watch, made when Claude first watches the screen
        # A watch began (True) or ended (False): the daemon looks and listens, the window shows
        # it.
        self.on_watch: Callable[[bool], None] = lambda on: None
        # What Codoh is doing, while its page shows in Abdoh's window ("" otherwise): Claude
        # answers about it without looking at the screen (abdoh/codoh/manager.py, brief).
        self.codoh_note: Callable[[], str] = lambda: ""

    @property
    def computer(self):
        return self._computer

    @computer.setter
    def computer(self, computer) -> None:
        self._computer = computer
        self.local = None
        if computer is not None:
            self.local = LocalSkills(
                StepRecorder(computer, self._done.append),
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

    def heard_unclear(self) -> None:
        """You spoke after the wake word but no words came out: the next request to Claude, if
        it comes soon, says so (so "did you hear me?" gets an honest answer)."""
        self._unclear_at = time.monotonic()

    def _unclear_note(self) -> str:
        at, self._unclear_at = self._unclear_at, None
        if at is not None and time.monotonic() - at <= UNCLEAR_SECONDS:
            return UNCLEAR
        return ""

    def handle(self, text: str, aside: bool = False, woken: Wake = False) -> Reply:
        """Route one request. Returns the reply ("" means nothing to say). `aside`: said right
        after a reply without the wake word, so maybe to someone else; `woken`: said after the
        wake word, which may have been a mistake (True, or how clearly the name was heard:
        (score, voice check or None)). Claude decides in both cases."""
        prefix = COMMANDS_FILE_ERROR if self.registry.refresh() else ""
        request = strip_wake_words(text, self.wake_words)
        if not request:
            return prefix
        if self.watching:
            from abdoh.local_skills import stop_watching

            self.watch.heard_user()
            if stop_watching(request):
                log.info("Told to stop watching the screen")
                self.end_watch()
                return STOPPED_WATCHING
        told = self._told_to_stop(text, request, loose=bool(aside))
        if told is not None:
            return told
        original = remove_wake_words(text, self.wake_words) or request
        self._done.clear()
        offered = self._answering = self._open_offer()
        exact = match_command(request, self.registry.commands, 100)  # one of yours, as it is
        steps = [] if exact or offered else split_steps(original)
        if offered is not None and self.brain is not None:
            reply = self._answer_offer(offered, original)
        elif steps:
            reply = self._steps(steps, original, aside, woken)
        else:
            reply = self._route(request, original, aside, woken)
        if isinstance(reply, str):
            reply = self._did_it_myself(reply, original)
            if reply:
                self.last_reply = reply
            if not prefix:
                return reply  # keeps its kind: Question, Done or plain words
            asks = isinstance(reply, Question)
            reply = f"{prefix} {reply}".strip()
            return Question(reply) if asks else reply
        return _prepend(prefix, reply) if prefix else reply

    def _told_to_stop(self, text: str, request: str, loose: bool) -> str | None:
        """ "Stop listening", "shut up", "start listening", in any words: done at once, without
        Claude (None for anything else). Stopping says nothing. `loose`: said right after a
        reply without the wake word, so a "shut up" anywhere in it counts."""
        from abdoh.local_skills import start_request, stop_request

        told = stop_request(remove_wake_words(text, self.wake_words) or request, loose=loose)
        acting = self.acting
        if told == "stop_listening" and acting is not None and acting.keeps_listening:
            acting.set_listening(False)  # in a lesson: the wake word again; the role stays
            return ""
        if told == "stop_listening" and "stop_listening" in self._builtins:
            log.info("Told to stop listening")
            return self._builtins["stop_listening"]()
        if told:
            log.info("Told to be quiet: back to waiting for the wake word")
            return ""
        if start_request(request) and "start_listening" in self._builtins:
            return self._builtins["start_listening"]()
        return None

    def _route(
        self, request: str, original: str, aside: bool = False, woken: Wake = False
    ) -> Reply:
        # "Remember that" is Claude's to understand: what it just did becomes a command
        # (ACTION save_steps), something you told it goes to memory, or it asks which.
        reply = self._route_local(request, original)
        if reply is not None:
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
            prompt = self._codoh() + prompt
            if self.watching and self.cfg.claude.allow_screen:
                # Watching the screen: what they say comes with a picture of it
                note = self._watching_note() if aside else ""
                prompt = self._unclear_note() + self._abdoh_did_note() + note + prompt
                return self._ask(prompt, original, screen=True, aside=True)
            note = ASIDE if aside else woken_note(woken) if woken else ""
            prompt = self._unclear_note() + self._abdoh_did_note() + note + prompt
            return self._ask(prompt, original, aside=bool(aside or woken))

        # 6. Nothing matched
        return f"{UNKNOWN} {NOT_CONNECTED}"

    def _route_local(self, request: str, original: str) -> str | None:
        """What Abdoh does without Claude: the reply, or None when none of it fits."""
        # 0. "Yes" or "no" to a mode's question ("Run it on what's connected?")
        if self.modes is not None:
            answered = self.modes.answer(request)
            if answered is not None:
                return answered

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

        # 1c. One of your roles, by name ("act as my German teacher")
        if self.acting is not None:
            reply = self._role(request)
            if reply is not None:
                return reply

        # 2. Commands from commands.yaml
        found = match_command(request, self.registry.commands, self.cfg.match_threshold)
        if found:
            log.info("Matched command %r (score %.0f)", found.command.name, found.score)
            try:
                computer = StepRecorder(self.computer, self._done.append) if self.computer else None
                spoken = self._run(
                    found.command, self.cfg.allow_run, computer=computer, slots=found.slots
                )
                text = " ".join(spoken)
                if any(isinstance(line, Question) for line in spoken):
                    return Question(text)  # a mode asks first: listen for the answer
                return text or Done("")  # your own "say" actions are spoken
            except ActionError as e:
                return str(e)

        # 3. Built-in skills that need no Claude (timers, media keys, open an app, ...)
        if self.local is not None:
            reply = self.local.handle(request, original)
            if reply is not None:
                log.info("Local skill handled %r", request)
                return reply

        return None

    # ----- several things at once -----

    def _steps(self, steps: list[str], original: str, aside: bool, woken: Wake) -> Reply:
        """Several things in one request, done one by one, in order. Each goes the way it
        would alone (your commands, the built-in skills); what nothing else knows goes to
        Claude, with the whole request for context."""
        log.info("Several things, one by one: %s", " | ".join(steps))
        parts = []
        for step in steps:
            request = strip_wake_words(step, self.wake_words)
            if request:
                parts.append((request, remove_wake_words(step, self.wake_words) or request))
        replies: list[str] = []
        for i, (request, part) in enumerate(parts):
            reply = self._route_local(request, part)
            if reply is None:
                return self._steps_with_claude(replies, parts[i:], original, aside, woken)
            replies.append(reply)
            if isinstance(reply, Question):
                break  # it needs your answer before anything else
        return _together(replies)

    def _steps_with_claude(
        self,
        replies: list[str],
        rest: list[tuple[str, str]],
        original: str,
        aside: bool,
        woken: Wake,
    ) -> Iterator[str]:
        """The steps from the first one only Claude knows: each in turn, after the one before
        has finished (and was said)."""
        turn = ClaudeTurn(original)  # the whole request, for the done sound and follow-ups
        turn.actions += self._done  # what Abdoh did itself before this
        said: list[str] = []
        self._in_steps = True
        try:
            for reply in replies:
                if reply and not isinstance(reply, Done):
                    said.append(reply)
                    yield reply
            for i, (request, part) in enumerate(rest):
                before = len(self._done)
                reply = None if i == 0 else self._route_local(request, part)
                turn.actions += self._done[before:]
                if reply is None:
                    note = ASIDE if aside else woken_note(woken) if woken else ""
                    prompt = STEP.format(request=original, step=part)
                    prompt = self._unclear_note() + self._abdoh_did_note() + note + prompt
                    answer = self._ask(prompt, part, aside=bool(aside or woken))
                    for sentence in [answer] if isinstance(answer, str) else answer:
                        if sentence:
                            said.append(sentence)
                            yield sentence
                    claude = self.last_turn
                    if claude is not None and claude is not turn:
                        if claude.ignored:
                            turn.ignored = True
                            return  # not meant for Abdoh: nor is the rest
                        turn.actions += claude.actions
                    aside = woken = False  # meant for Abdoh: so is the rest
                elif reply and not isinstance(reply, Done):
                    said.append(reply)
                    yield reply
                    if isinstance(reply, Question):
                        return
            self._in_steps = False
            offer = self._offer_after(turn, said)
            if offer:
                said.append(offer)
                yield offer
        finally:
            self._in_steps = False
            turn.answer = " ".join(said)
            turn.finished_at = time.monotonic()
            self.last_turn = turn

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
                said = modes.deactivate()
                self._done.append(("mode", "normal"))
                return said
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
            said = modes.activate(found[0].name)
            self._done.append(("mode", found[0].name))
            return said
        except ActionError as e:
            return str(e)

    def _role(self, request: str) -> str | None:
        choices = [
            Command(r.name, [p.format(name=r.name.lower()) for p in _ROLE_ON] + list(r.phrases), [])
            for r in self.acting.roles()
        ]
        found = match(request, choices, max(MODE_MATCH, self.cfg.match_threshold))
        if not found:
            return None
        log.info("Role %r (score %.0f)", found[0].name, found[1])
        return Done(self.acting.switch(found[0].name))

    def _ask(self, prompt: str, request: str, screen: bool = False, aside: bool = False) -> Reply:
        if self.brain is None:
            return NOT_CONNECTED
        question = self.modes.open_question() if self.modes is not None else None
        if question:
            prompt = ANSWER_NOTE.format(question=question) + prompt
        self.on_thinking()
        return self._stream(self.brain, prompt, request, screen, aside, answer=bool(question))

    def _board(self) -> Callable[[str], None] | None:
        """A new card on the board for one reply: it grows while Claude writes it."""
        if self.on_board is None:
            return None
        card, show = next(self._cards), self.on_board
        return lambda text: show(card, text)

    def _stream(
        self,
        brain,
        prompt: str,
        request: str,
        screen: bool,
        aside: bool = False,
        answer: bool = False,
    ) -> Iterator[str]:
        """Claude's answer as sentences; runs the actions it asks for along the way."""
        turn = ClaudeTurn(request)
        problems: list[str] = []
        spoken: list[str] = []

        looks: list[str] = []  # Claude asked to see the screen
        recalls: list[str] = []  # ... or what was said in an earlier conversation
        logs: list[str] = []  # ... or Abdoh's own log

        def act(kind: str, arg: str) -> None:
            if kind == LOOK:
                looks.append(arg)
                return
            if kind == RECALL:
                recalls.append(arg)
                return
            if kind == LOGS:
                logs.append(arg)
                return
            if kind == WATCH:
                if self._watch_action(arg):
                    turn.actions.append((WATCH, arg))
                return
            if kind == IGNORE:
                log.info("Not meant for Abdoh: staying quiet")
                turn.ignored = True
                return
            if kind == BOARD_PDF:
                self.on_board_pdf()
                turn.actions.append((BOARD_PDF, arg))
                return
            if kind == ROLE:
                if self.acting is not None:
                    self.acting.switch(arg)
                    turn.actions.append((ROLE, arg))  # the done sound if no words
                return
            if kind in SELF_EDIT_ACTIONS:
                done, said = self._self_edit_action(kind, arg)
                problems.append(said)  # Abdoh says what it changed, or why it couldn't
                if done:
                    turn.actions.append((kind, arg))
                return
            if kind == SAVE_STEPS:
                done, said = self._save_steps(arg, turn)
                problems.append(said)  # "Saved. Next time just say: ...", or why not
                if done:
                    turn.actions.append((kind, arg))
                return
            if kind in MEMORY_ACTIONS:
                problem = self._memory_action(kind, arg)
                if problem:
                    problems.append(problem)
                else:
                    turn.actions.append((kind, arg))  # the done sound if no words
                return
            if kind == LISTEN:
                from abdoh.roles.acting import wants_on

                if self.acting is not None and self.acting.set_listening(wants_on(arg)):
                    turn.actions.append((LISTEN, arg))
                return
            if kind == ANSWER:
                name = self.modes.asked_mode() if self.modes is not None else ""
                said = self.modes.answer_from_claude(arg) if name else ""
                if name and self.modes.current == name:
                    turn.actions.append(("mode", name))  # it ran: the done sound if no words
                if said and not isinstance(said, Done):
                    problems.append(said)  # the mode's own words, or "Okay, I won't."
                return
            if kind == "lamp":
                self._lamps_before_role()
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
        if answer:
            allowed.append(ANSWER)
        if self.cfg.claude.actions:
            allowed.append(SAVE_STEPS)
        if self.cfg.memory:
            allowed.extend(MEMORY_ACTIONS)
            if self.cfg.keep_conversations and not screen:
                allowed.append(RECALL)  # once: the follow-up can't ask again
        if self.cfg.claude.allow_logs and not screen:
            allowed.append(LOGS)  # once, like recall
        if self.cfg.claude.allow_screen:
            allowed.append(WATCH)
        if self.cfg.claude.allow_self_edit:
            allowed.extend(SELF_EDIT_ACTIONS)
        if self.acting is not None:
            allowed.append(ROLE)
            if self.acting.current is not None and self.cfg.lesson_listen_seconds > 0:
                allowed.append(LISTEN)
            if self.acting.current is not None:
                allowed.append(BOARD_PDF)
        chunks = None
        try:
            image = self._capture() if screen else None
            chunks = brain.stream(prompt, image)
            for sentence in speakable(chunks, act, allowed=allowed, on_board=self._board()):
                if turn.ignored:
                    break  # not for Abdoh: nothing is said
                yield from _drain(problems)
                spoken.append(sentence)
                yield sentence
            yield from _drain(problems)
            if (recalls or logs) and not turn.ignored:
                chunks.close()
                if recalls:
                    chunks = self._recall(brain, recalls[0], request)
                else:
                    chunks = self._read_log(brain, logs[0], request)
                allowed = [a for a in allowed if a not in (RECALL, LOOK, LOGS)]
                for sentence in speakable(chunks, act, allowed=allowed, on_board=self._board()):
                    yield from _drain(problems)
                    spoken.append(sentence)
                    yield sentence
                yield from _drain(problems)
            elif looks and not turn.ignored:
                log.info("Claude asked to look at the screen: %s", looks[0])
                chunks.close()
                self.on_activity(LOOKING)
                window = self._window()
                image = self._capture()
                follow_up = skills.look_follow_up(request, window.title, window.program)
                chunks = brain.stream(follow_up, image)
                allowed = self.cfg.claude.actions
                for sentence in speakable(chunks, act, allowed=allowed, on_board=self._board()):
                    yield from _drain(problems)
                    spoken.append(sentence)
                    yield sentence
                yield from _drain(problems)
            if not turn.ignored and not self._in_steps:
                offer = self._offer_after(turn, spoken)
                if offer:
                    spoken.append(offer)
                    yield offer
            if self._answering is not None and spoken and _asks(spoken[-1]):
                if not turn.ignored and not turn.actions:  # "What should I call it?"
                    self._offer, self._offer_at = self._answering, time.monotonic()
        except (BrainError, ScreenCaptureError) as e:
            turn.failed = isinstance(e, BrainError)
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

    def _recall(self, brain, arg: str, request: str):
        """Claude asked what was said before (ACTION recall: what | when): it's asked again,
        with the exchanges kept that match."""
        from abdoh.conversations import FOLDER, Conversations
        from abdoh.recall import follow_up, split

        what, when = split(arg)
        log.info("Claude asked to recall %r (%s)", what, when or "the whole week")
        self.on_activity(REMEMBERING)
        kept = Conversations(self.cfg.app_dir / FOLDER, self.cfg.conversation_days)
        return brain.stream(follow_up(kept, what, when, request), None)

    # ----- watching the screen (abdoh/watch.py) -----

    @property
    def watching(self) -> bool:
        return self.watch is not None and self.watch.active

    def _watch_action(self, arg: str) -> bool:
        """ACTION watch: <goal> | <mistakes or suggestions> starts a watch, or changes the one
        that's on (it goes on); ACTION watch: off ends it."""
        if arg.strip().lower().rstrip(".") in WATCH_OFF:
            return self.end_watch()
        if not self.cfg.claude.allow_screen:
            return False
        from abdoh.watch import Watch, parse

        goal, suggest = parse(arg)
        if self.watch is None:
            self.watch = Watch(grab=self._grab, window=self._window)
        if self.watch.active:
            self.watch.change(goal, suggest)
        else:
            self.watch.start(goal, bool(suggest))
        self.on_watch(True)
        return True

    def _watching_note(self) -> str:
        """Said during a watch: what Claude is watching, and for what."""
        watch = self.watch
        kind = WATCH_KIND[watch.suggest].format(goal=watch.goal)
        return WATCHING.format(goal=watch.goal, kind=kind)

    def end_watch(self) -> bool:
        """Stop watching the screen (said, a button, or "stop listening"). False if no watch was
        on."""
        if self.watch is None or not self.watch.stop():
            return False
        self.on_watch(False)
        return True

    def watch_frame(self, image: bytes, title: str = "", program: str = "") -> Iterator[str]:
        """A picture of the screen during a watch: what Claude says about it (nothing when the
        user is doing fine). Doesn't count as a request ("remember that" doesn't see it)."""
        watch = self.watch
        if self.brain is None or watch is None or not watch.active:
            return
        window = ""
        if title:
            window = f' (the window in front: "{title}"' + (f", {program})" if program else ")")
        said = "; ".join(f'"{n}"' for n in watch.notes)
        prompt = WATCH_FRAME.format(
            goal=watch.goal,
            window=window,
            minutes=watch.minutes(),
            notes=f" What you said during the watch so far: {said}." if said else "",
            when=WATCH_WHEN[watch.suggest],
        )
        quiet = []

        def act(kind: str, arg: str) -> None:
            if kind == IGNORE:
                quiet.append(True)
            elif kind == WATCH:
                self._watch_action(arg)

        chunks = self.brain.stream(prompt, image)
        try:
            for sentence in speakable(chunks, act, allowed=[IGNORE, WATCH]):
                if quiet:
                    break
                yield sentence
        except BrainError as e:
            log.warning("Couldn't ask about the screen during the watch: %s", e)
        finally:
            chunks.close()

    def _read_log(self, brain, arg: str, request: str):
        """Claude asked to read Abdoh's log (ACTION logs: what | when): it's asked again, with
        the log of that time and how Abdoh is meant to work."""
        from abdoh import logs

        log.info("Claude asked to read the log: %s", arg)
        self.on_activity(READING_LOG)
        works = self._how_it_works(arg)
        return brain.stream(logs.follow_up(self.cfg, arg, request, works=works), None)

    def _how_it_works(self, arg: str) -> str:
        """How Abdoh is meant to work, for the log's follow-up: the general text, and the
        Catalog's features the question is about."""
        from abdoh import catalog, logs

        found = catalog.for_log(logs.search_words(arg))
        return logs.HOW_IT_WORKS + (f"\n{found}" if found else "")

    # ----- what Abdoh did itself, and asking for the same again -----

    def _did_it_myself(self, reply: str, original: str) -> str:
        """A request Abdoh handled without Claude: if it did something, that's the last turn
        ("remember that" keeps it), and the second time it's asked for, Abdoh offers to make it
        a command."""
        if not self._done:
            return reply
        turn = ClaudeTurn(original, str(reply), list(self._done), time.monotonic(), by_abdoh=True)
        self.last_turn = turn
        offer = self._offer_after(turn, [str(reply)])
        return Question(f"{reply} {offer}".strip()) if offer else reply

    def _offer_after(self, turn: ClaudeTurn, said: list[str]) -> str:
        """Note what took several steps (while memory is on). The second time it's asked for,
        and it isn't one of your commands, Abdoh offers to save it, unless the reply already
        asks something (Claude's own offer, say). Returns the offer, or ""."""
        if self._note_repeat(turn) != 2 or self._is_command(turn):
            return ""
        if said and _asks(said[-1]):
            return ""
        log.info("Asked for a second time: offering to save it as a command")
        self._offer, self._offer_at = turn, time.monotonic()
        return OFFER

    def _note_repeat(self, turn: ClaudeTurn) -> int:
        """Several actions for one request are noted (while memory is on). Returns how many
        times they have been asked for now (0: not noted)."""
        if not self.cfg.memory or turn.ignored or any(k == SAVE_STEPS for k, _ in turn.actions):
            return 0
        from abdoh.commands import repeats

        return repeats.record(self.cfg.app_dir / repeats.FILE, turn.request, _command_steps(turn))

    def _is_command(self, turn: ClaudeTurn) -> bool:
        from abdoh.commands.repeats import is_saved

        saved = [[(k, str(v)) for k, v in c.actions] for c in self.registry.commands]
        return is_saved(_command_steps(turn), saved)

    def _open_offer(self) -> ClaudeTurn | None:
        """The turn Abdoh just offered to save, if this may be the answer (once)."""
        offered, self._offer = self._offer, None
        if offered is not None and time.monotonic() - self._offer_at <= OFFER_SECONDS:
            return offered
        return None

    def _answer_offer(self, offered: ClaudeTurn, original: str) -> Reply:
        """The answer to "Want me to save that as a command?": Claude understands it."""
        self._told = offered
        note = OFFER_NOTE.format(
            request=offered.request, steps=_steps_text(_command_steps(offered)), offer=OFFER
        )
        return self._ask(note + self._with_context(original), original)

    def _lamps_before_role(self) -> None:
        """Claude sets the mood in a role: how the lamps were is noted first (once), and they
        go back when the role ends (daemon._role_changed)."""
        lamps = getattr(self.computer, "lamps", None)
        if lamps is None or self.acting is None or self.acting.current is None:
            return
        try:
            lamps.keep_for_later()
        except Exception:
            log.debug("Couldn't note how the lamps were", exc_info=True)

    def _abdoh_did_note(self) -> str:
        """Tell Claude (once) what Abdoh did by itself just before, so "keep that as chat time"
        or "turn it down a bit more" make sense to it."""
        turn = self.last_turn
        if turn is None or not turn.by_abdoh or turn is self._told:
            return ""
        if time.monotonic() - turn.finished_at > ABDOH_DID_SECONDS:
            return ""
        self._told = turn
        return ABDOH_DID.format(request=turn.request, steps=_steps_text(turn.actions))

    def _codoh(self) -> str:
        try:
            return self.codoh_note() or ""
        except Exception:  # never in the way of an answer
            log.debug("Couldn't read what Codoh is doing", exc_info=True)
            return ""

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

    def _self_editor(self):
        if self._editor is None:
            from abdoh.self_edit import SelfEditor

            apps = getattr(self.computer, "apps", None)
            self._editor = SelfEditor(
                self.cfg, find_app=apps.find if apps is not None else None, on_change=self._edited
            )
        return self._editor

    def _edited(self, kind: str) -> None:
        if kind == "command":
            self.registry.refresh(force=True)  # use it right away
        self.on_self_edit(kind)

    def _self_edit_action(self, kind: str, arg: str) -> tuple[bool, str]:
        """ACTION save_item, delete_item or undo_change: (done, what to say)."""
        from abdoh.self_edit import SelfEditError

        editor = self._self_editor()
        try:
            if kind == SAVE_ITEM:
                return True, editor.save(arg)
            if kind == UNDO_CHANGE:
                return True, editor.undo(arg)
            return True, editor.delete(arg)
        except SelfEditError as e:
            log.info("Couldn't %s %r: %s", kind, arg, e)
            return False, str(e)

    def _memory_action(self, kind: str, arg: str) -> str:
        """ACTION remember, lesson or forget. Returns "" when done, or what to say."""
        from abdoh.memory import Memory, MemoryChangeError

        memory = Memory(self.cfg.app_dir / "memory.yaml")
        try:
            if kind == FORGET:
                entry = memory.forget(arg)
                log.info("Forgot: %s", entry.text)
            else:
                entry = memory.add(arg, "lesson" if kind == LESSON else "fact")
                log.info("%s: %s", "Learned" if kind == LESSON else "Remembered", entry.text)
        except MemoryChangeError as e:
            log.info("Couldn't %s %r: %s", kind, arg, e)
            return str(e)
        self.on_memory()
        return ""

    @property
    def last_turn(self) -> ClaudeTurn | None:
        return self._last_turn

    @last_turn.setter
    def last_turn(self, turn: ClaudeTurn | None) -> None:
        if turn is not self._last_turn:
            self._turn_before = self._last_turn
        self._last_turn = turn

    def _to_save(self, current: ClaudeTurn) -> Iterator[ClaudeTurn | None]:
        """Whose steps ACTION save_steps saves, in order: this reply's; the request Abdoh
        offered to save, while that's being answered; the previous reply's, or the one before
        it when the previous reply only asked something ("what should I call it?")."""
        yield current
        yield self._answering
        last = self.last_turn
        yield last
        if last is not None and not _command_steps(last) and _asks(last.answer):
            yield self._turn_before

    def _save_steps(self, phrase: str, current: ClaudeTurn) -> tuple[bool, str]:
        """ACTION save_steps: what Claude did that worked, as a command you start by saying
        `phrase`: this reply's actions so far, else the previous reply's. It can be undone like
        Claude's other changes. Returns (done, what to say)."""
        turn = next((t for t in self._to_save(current) if _command_steps(t)), None)
        actions = _command_steps(turn)
        if turn is None or not actions:
            return False, NOTHING_TO_SAVE
        if self.registry.error:
            return False, f"{COMMANDS_FILE_ERROR} Fix it first, then try again."
        trigger = normalize(phrase) or normalize(turn.request)
        if match_command(trigger, self.registry.commands, 100):
            return False, f"You already have a command for {trigger}."
        taken = {c.name for c in self.registry.commands}
        path = self.registry.path
        try:
            self._self_editor().change(
                "command",
                trigger,
                path,
                lambda: append_command(path, trigger, actions, turn.request, taken),
            )
        except (ValueError, OSError) as e:
            log.error("Couldn't save the command: %s", e)
            return False, "Sorry, I couldn't save that to your commands file."
        log.info("Saved a command for %r: %s", trigger, actions)
        return True, f"Saved. Next time just say: {trigger}."


def _asks(text: str) -> bool:
    """Whether a reply ends with a question."""
    return text.rstrip(" \"'”’)").endswith("?")


def _steps_text(steps: list[tuple[str, str]]) -> str:
    return "; ".join(f"{kind}: {arg}" for kind, arg in steps)


def _command_steps(turn: ClaudeTurn | None) -> list[tuple[str, str]]:
    """What Claude did in a reply that a command can do (not remembering, looking or
    listening)."""
    from abdoh.commands.registry import ACTION_TYPES

    return [(k, a) for k, a in turn.actions if k in ACTION_TYPES] if turn is not None else []


def _together(replies: list[str]) -> str:
    """The replies of several local steps as one: what they said, or (when none said
    anything) done, with the done sound."""
    said = [r for r in replies if r and not isinstance(r, Done)]
    if said:
        text = " ".join(said)
        return Question(text) if replies and isinstance(replies[-1], Question) else text
    return Done(" ".join(r for r in replies if r))


def _drain(items: list[str]) -> Iterator[str]:
    while items:
        yield items.pop(0)


def _prepend(first: str, rest: Iterator[str]) -> Iterator[str]:
    yield first
    yield from rest
