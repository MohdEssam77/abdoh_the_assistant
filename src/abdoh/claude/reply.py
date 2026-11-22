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

log = logging.getLogger(__name__)

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
    "lamp": "ACTION lamp: <a lamp's name, or all> | <on, off, 40%, red, warm white, blue 30%>   "
    "(the user's smart lamps)",
    "window": "ACTION window: <app> to <screen> [maximized, left, right or keep]   (moves an "
    "open app's window to one of the user's screens, by number or name, e.g. WhatsApp to 1 "
    "maximized or Chrome to the laptop left; this to <screen> moves the window in front), or "
    "ACTION window: <minimize, maximize, restore, desktop or switch>   (the window in front)",
}

# Not one of the user's switchable actions: Claude asks to see the screen (claude.allow_screen).
LOOK = "look"
# Said after a reply, but meant for someone else in the room: Claude stays quiet.
IGNORE = "ignore"
# Yes or no to the question Abdoh just asked (a mode that needs screens that aren't there).
ANSWER = "answer"
# Start a role ("act as my German teacher"), or end it (off). Not one of the switchable actions.
ROLE = "role"

_ACTION = re.compile(r"^ACTION\s+([A-Za-z_]+)\s*:\s*(.+)$")
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
) -> Iterator[str]:
    """Yield sentences to speak from streamed text; call on_action(kind, arg) for action lines."""
    allowed = set(allowed)
    buffer = ""
    for chunk in chunks:
        buffer += chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            yield from _line(line, on_action, allowed)
        if buffer and not _maybe_action(buffer):
            *done, buffer = _SENTENCE_END.split(buffer)
            for sentence in done:
                yield from _speech(sentence)
    if buffer.strip():
        yield from _line(buffer, on_action, allowed)


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
