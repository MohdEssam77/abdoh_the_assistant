"""Turn Claude's streamed text into sentences to speak, running ACTION lines as they arrive.

Claude writes actions on their own lines before its spoken answer, e.g.

    ACTION open_url: https://www.python.org
    Opening the Python website.

Action lines run as soon as they are complete; everything else is cleaned of markdown and
yielded sentence by sentence, so Abdoh can start talking before the reply is finished.
"""

import logging
import re
from collections.abc import Callable, Iterable, Iterator

from abdoh import lights as _lights

log = logging.getLogger(__name__)

# The WiZ scenes, by name (abdoh/lights.py), for the lamp action's help.
_SCENES = ", ".join(n for n in _lights.SCENES if n not in _lights.WHITE_FIRST)
# What Claude is allowed to do, with the help text shown to it in the system prompt.
ACTION_HELP: dict[str, str] = {
    "open_url": "ACTION open_url: <url>   (a website, or a search such as "
    "https://www.google.com/search?q=weather+tomorrow)",
    "play_youtube": "ACTION play_youtube: <what to play>   (starts the top YouTube video for "
    "that search, e.g. lofi hip hop radio)",
    "open_app": "ACTION open_app: <app name>   (an installed program, e.g. Spotify)",
    "media": "ACTION media: <play_pause, next, previous, volume_up, volume_down or mute>",
    "timer": "ACTION timer: <duration>   (e.g. 10 minutes; Abdoh announces when it's done)",
    "volume": "ACTION volume: <0 to 100>   (sets the speakers to exactly that volume)",
    "brightness": "ACTION brightness: <0 to 100>   (the laptop screen's brightness)",
    "app_volume": "ACTION app_volume: <app> | <0 to 100>   (one app's volume in the Windows "
    "volume mixer, e.g. browser | 30 or Spotify | 0; browser means every web browser. Use it "
    "when they want one app quieter or louder rather than everything)",
    "remind": "ACTION remind: <when> | <what>   (when: 20 minutes, 17:30, or tomorrow at 9; "
    "what: the reminder in a few words, e.g. call your mother. Abdoh says it aloud then)",
    "note": "ACTION note: <text>   (adds a line to the user's notes)",
    "mode": "ACTION mode: <one of the user's modes, or normal>   (switches that mode on; normal "
    "puts back everything a mode changed)",
    "displays": "ACTION displays: <all | only 2 | 1 off | 3 on>   (turns the user's screens on "
    "and off, by number or name; at least one stays on)",
    "audio_output": "ACTION audio_output: <speakers>   (sends the sound to other speakers: "
    "headphones, speakers, or a name)",
    "dark_mode": "ACTION dark_mode: <on | off>   (Windows' dark theme)",
    "lamp": "ACTION lamp: <a lamp's name, or all> | <how>   (the user's smart lamps. How: on, "
    "off, a brightness (40%), a white (warm white, cool white, 3000k), a colour (red, amber, "
    "sky blue, lavender, hot pink... or #rrggbb), or a WiZ scene: " + _SCENES + "; slow or "
    "fast for the moving ones. Combine them: party fast 80%. One line per lamp gives each its "
    "own, like a two-tone look; a white-only lamp turns a colour into the nearest white)",
    "window": "ACTION window: <app> to <screen> [maximized, left, right or keep]   (moves an "
    "open app's window to one of the user's screens, by number or name, e.g. WhatsApp to 1 "
    "maximized or Chrome to the laptop left; this to <screen> moves the window in front; "
    "<app> to current keeps it on its screen; Abdoh's own window, the one with the board, is "
    "Abdoh: Abdoh to current maximized), or "
    "ACTION window: <minimize, maximize, restore, desktop or switch>   (the window in front, "
    "usually the app the user is working in, not Abdoh's)",
    "power": "ACTION power: <lock or screens_off>   (locks the computer, or turns the screens "
    "off until the mouse moves. Sleep, shut down and restart aren't actions: Abdoh does them "
    "when the user says so to it directly, e.g. shut down the computer, and asks first)",
}

# Not one of the user's switchable actions: Claude asks to see the screen (claude.allow_screen).
LOOK = "look"
# Claude asks what was said in an earlier conversation (abdoh/recall.py), while they're kept.
RECALL = "recall"
# Claude watches the screen while the user does something (abdoh/watch.py), or stops (off).
WATCH = "watch"
# Claude reads Abdoh's own log to explain what happened (abdoh/logs.py; claude.allow_logs).
LOGS = "logs"
# Said after a reply, but meant for someone else in the room: Claude stays quiet.
IGNORE = "ignore"
# Yes or no to the question Abdoh just asked (a mode that needs screens that aren't there).
ANSWER = "answer"
# Start a role ("act as my German teacher"), or end it (off). Not one of the switchable actions.
ROLE = "role"
# While a role is on: save the board as a PDF ("save the board").
BOARD_PDF = "board_pdf"
# Codoh, the coding page, by voice: a chat in a folder, a message for it, an answer
# (abdoh/codoh/voice.py).
CODOH = "codoh"
# Claude asks what Codoh is doing (its recent chats: state, to-do list, conversation), whatever
# the window shows (abdoh/codoh/report.py).
CODOH_STATE = "codoh_state"
# While a role is on: keep listening without the wake word (on), or only after it (off).
LISTEN = "listen"
# Memory (abdoh/memory.py), while it's on: a fact about the user, a lesson (what works on this
# computer), or forgetting one.
REMEMBER, LESSON, FORGET = "remember", "lesson", "forget"
MEMORY_ACTIONS = (REMEMBER, LESSON, FORGET)
# Abdoh changes its own commands, modes and roles (abdoh/self_edit.py, claude.allow_self_edit).
SAVE_ITEM, DELETE_ITEM, UNDO_CHANGE = "save_item", "delete_item", "undo_change"
# ... and its own everyday settings (abdoh/self_settings.py): never permissions or keys.
SETTING = "setting"
SELF_EDIT_ACTIONS = (SAVE_ITEM, DELETE_ITEM, UNDO_CHANGE)
# "Remember that" after Claude did something: those steps become one of the user's commands.
SAVE_STEPS = "save_steps"
# Only for requests from the phone (ABDOH_EPIC_11.md): a picture of the screen goes to it.
SHOW_SCREEN = "show_screen"
# ... and a file from the computer goes to it (abdoh/phone/files.py checks it).
SEND_FILE = "send_file"

_ACTION = re.compile(r"^ACTION\s+([A-Za-z_]+)\s*:\s*(.+)$")
# What a role shows instead of saying (code, equations, steps): between these, never spoken.
BOARD_START, BOARD_END = "[board]", "[/board]"
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_URL = re.compile(r"https?://\S+")


def clean_for_speech(text: str) -> str:
    """Remove markdown (and links) that would sound odd when read aloud."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"^\s*(#+|[-*•]|\d+\.)\s+", "", text, flags=re.M)
    text = _URL.sub("the link", text)
    text = re.sub(r"[*_`#]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _maybe_action(buffer: str) -> bool:
    """Could this unfinished line still turn out to be an ACTION line?"""
    start = buffer.lstrip()
    return start.startswith("ACTION") or "ACTION".startswith(start)


def speakable(
    chunks: Iterable[str],
    on_action: Callable[[str, str], None],
    allowed: Iterable[str] = tuple(ACTION_HELP),
    on_board: Callable[[str], None] | None = None,
) -> Iterator[str]:
    """Yield sentences to speak from streamed text; call on_action(kind, arg) for action lines.

    What's between [board] and [/board] is shown, never spoken: on_board(text) gets this reply's
    board so far each time a line is added, so it fills in live. The text is read only as fast
    as the sentences before it are spoken, so a part written just before Claude talks about it
    shows up just as Abdoh starts saying it. All the parts of one reply make one board."""
    allowed = set(allowed)
    board: list[str] | None = None  # the open part's lines, while on the board
    parts: list[str] = []  # this reply's finished parts
    shown = ""  # what on_board was last given
    buffer = ""

    def show() -> None:
        nonlocal shown
        current = "\n".join(board or []).strip("\n")
        text = "\n".join(p for p in (*parts, current) if p.strip())  # one board, written on
        if text == shown:
            return
        if on_board is None:
            if not shown:
                log.info("Claude wrote for the board, but there's no board here: not spoken")
        else:
            on_board(text)
        shown = text

    def close() -> None:
        nonlocal board
        part = "\n".join(board or []).strip("\n")
        board = None
        if part.strip():
            parts.append(part)
            log.info("On the board: %d lines", part.count("\n") + 1)
        show()

    def out(line: str) -> Iterator[str]:
        nonlocal board
        if board is None:
            at = line.lower().find(BOARD_START)
            if at < 0:
                yield from _line(line, on_action, allowed)
                return
            yield from _line(line[:at], on_action, allowed)  # words before it are spoken
            board, line = [], line[at + len(BOARD_START) :]
        end = line.lower().find(BOARD_END)
        if end < 0:
            board.append(line)
            show()
            return
        board.append(line[:end])
        close()
        yield from out(line[end + len(BOARD_END) :])  # words after it are spoken

    for chunk in chunks:
        buffer += chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            yield from out(line)
        # Speak finished sentences of an unfinished line, unless it may still become an action
        # line or a board marker ("[" is rare in speech: wait for the whole line).
        if buffer and board is None and "[" not in buffer and not _maybe_action(buffer):
            *done, buffer = _SENTENCE_END.split(buffer)
            for sentence in done:
                yield from _speech(sentence)
    if buffer.strip():
        yield from out(buffer)
    if board is not None:
        close()  # never closed: still shown, never spoken


def _line(line: str, on_action, allowed: set[str]) -> Iterator[str]:
    match = _ACTION.match(line.strip())
    if match:
        kind, arg = match.group(1).lower(), match.group(2).strip()
        if kind in allowed:
            log.info("Claude action %s: %s", kind, arg)
            on_action(kind, arg)
        else:
            log.warning("Ignoring action Claude isn't allowed to use: %s: %s", kind, arg)
        return
    for sentence in _SENTENCE_END.split(line):
        yield from _speech(sentence)


def _speech(text: str) -> Iterator[str]:
    cleaned = clean_for_speech(text)
    if cleaned:
        yield cleaned
