"""Abdoh's log, read back: for Settings → Advanced → Log, and for Abdoh itself (ACTION logs).

The log keeps today's file and yesterday's (`abdoh.log` and `abdoh.log.2026-11-25`; see
config.setup_logging). Each entry is a line like

    2026-11-25 20:27:03,112 INFO abdoh.daemon: You: what's the weather

with any lines that follow it (a traceback) kept with it. Keys and tokens are hidden before an
entry leaves this module.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from abdoh.config import Config

_LINE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3} (DEBUG|INFO|WARNING|ERROR|CRITICAL) "
    r"([\w.]+): ?(.*)$"
)
PROBLEMS = ("WARNING", "ERROR", "CRITICAL")
READ_BYTES = 4_000_000  # of each file, from its end: plenty for a day
# Secrets that must never be shown or sent: API keys, bearer tokens, JWTs, OAuth codes.
_SECRETS = [
    re.compile(r"\bsk-(?:ant|or|proj)?-?[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)\b((?:access|refresh|id)_token|code|code_verifier|api_key)=[^&\s\"']+"),
]
HIDDEN = "[hidden]"
# Which part of Abdoh a logger belongs to, for people (first match wins).
_PARTS = (
    ("abdoh.codoh", "Codoh"),
    ("abdoh.claude", "Claude"),
    ("abdoh.watch", "Watching"),
    ("abdoh.audio.stt", "Speech"),
    ("abdoh.audio.gpu", "Speech"),
    ("abdoh.audio.wakeword", "Wake word"),
    ("abdoh.audio.oww", "Wake word"),
    ("abdoh.audio.voicecheck", "Wake word"),
    ("abdoh.audio", "Hearing"),
    ("abdoh.speech", "Voice"),
    ("abdoh.ui", "Window"),
    ("abdoh.lights", "Lamps"),
    ("abdoh.modes", "Modes"),
    ("abdoh.roles", "Act as"),
    ("abdoh.memory", "Memory"),
    ("abdoh.recall", "Memory"),
    ("abdoh.conversations", "Memory"),
    ("abdoh.commands", "Commands"),
    ("abdoh.router", "Requests"),
    ("abdoh.local_skills", "Requests"),
    ("abdoh.system_skills", "Requests"),
    ("abdoh.daemon", "Abdoh"),
    ("abdoh.models", "Models"),
    ("abdoh.updates", "Updates"),
    ("abdoh", "Abdoh"),
)


@dataclass
class Entry:
    time: datetime
    level: str
    logger: str
    text: str  # the line's message
    details: str = ""  # the lines after it (a traceback)

    @property
    def part(self) -> str:
        return part_of(self.logger)

    @property
    def problem(self) -> bool:
        return self.level in PROBLEMS

    def matches(self, words: list[str]) -> bool:
        hay = f"{self.text}\n{self.details}\n{self.logger}".lower()
        return any(word in hay for word in words)


def part_of(logger: str) -> str:
    for prefix, name in _PARTS:
        if logger == prefix or logger.startswith(prefix + "."):
            return name
    return logger.rsplit(".", 1)[-1] or "Abdoh"


def hide_secrets(text: str) -> str:
    for pattern in _SECRETS:
        text = pattern.sub(
            lambda m: f"{m.group(1)}={HIDDEN}" if m.lastindex else HIDDEN,
            text,
        )
    return text


def log_path(cfg: Config) -> Path:
    return cfg.resolve(cfg.log_file)


def log_files(path: Path) -> list[Path]:
    """Yesterday's file (and any older one left), then today's: oldest first."""
    path = Path(path)
    older = sorted(p for p in path.parent.glob(path.name + ".*") if p.is_file())
    return [*older, path] if path.is_file() else older


def _read_tail(path: Path, limit: int = READ_BYTES) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - limit))
            data = f.read()
    except OSError:
        return ""
    text = data.decode("utf-8", "replace")
    if size > limit:  # started mid-line: drop the broken first line
        text = text.split("\n", 1)[-1]
    return text


def parse(text: str) -> list[Entry]:
    entries: list[Entry] = []
    for line in text.splitlines():
        match = _LINE.match(line)
        if match:
            when, level, logger, message = match.groups()
            try:
                stamp = datetime.strptime(when, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            entries.append(Entry(stamp, level, logger, hide_secrets(message)))
        elif entries and line.strip():
            last = entries[-1]
            last.details = f"{last.details}\n{hide_secrets(line)}" if last.details else line
            last.details = hide_secrets(last.details)
    return entries


def read_entries(path: Path) -> list[Entry]:
    """Every entry of today's and yesterday's log, oldest first."""
    entries: list[Entry] = []
    for file in log_files(path):
        entries.extend(parse(_read_tail(file)))
    entries.sort(key=lambda e: e.time)  # stable: the order within a second stays
    return entries


def search_words(text: str) -> list[str]:
    """The words worth looking for in "why did you stop talking": 'stop', 'talking'."""
    words = re.findall(r"[a-z0-9']{3,}", (text or "").lower())
    return [w for w in words if w not in _STOPWORDS]


def pick(
    entries: list[Entry],
    since: datetime | None = None,
    until: datetime | None = None,
    problems: bool = False,
    search: str = "",
    limit: int = 300,
) -> list[Entry]:
    """The entries in a time span, optionally only problems or those with the search words;
    the latest `limit` of them, oldest first."""
    words = [w for w in (search or "").lower().split() if w]
    found = [
        e
        for e in entries
        if (since is None or e.time >= since)
        and (until is None or e.time <= until)
        and (not problems or e.problem)
        and (not words or all(e.matches([w]) for w in words))
    ]
    return found[-limit:] if limit else found


# ----- for Abdoh itself (ACTION logs) -----

FOR_CLAUDE_ENTRIES = 200
FOR_CLAUDE_CHARS = 24_000
_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10,
            "few": 3, "couple": 2, "fifteen": 15, "twenty": 20, "thirty": 30}  # fmt: skip
_SPAN = re.compile(
    r"(?:last|past)?\s*(\d+|an?|one|two|three|four|five|ten|few|couple(?: of)?|fifteen|twenty"
    r"|thirty)\s+(minute|min|hour|hr)s?"
)
_STOPWORDS = set(
    "the and you your why did what was were are for not that this with from have has had its "
    "just now any anything something did didn don doesn isn wasn there their about when then "
    "than them they she him her his how can could would should will check log logs look see "
    "tell happened happen wrong went going ago today yesterday minute minutes hour hours".split()
)


def span(when: str, now: datetime | None = None) -> tuple[datetime, datetime, str]:
    """(start, end, in words) for "just now", "the last 10 minutes", "an hour ago", "today",
    "this morning", "yesterday"; nothing: the last 30 minutes."""
    now = now or datetime.now()
    w = (when or "").lower().strip()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if "yesterday" in w:
        return midnight - timedelta(days=1), midnight, "yesterday"
    for name, start, end in (("morning", 5, 12), ("afternoon", 12, 18), ("evening", 17, 24)):
        if name in w:
            begin = midnight + timedelta(hours=start)
            return begin, min(now, midnight + timedelta(hours=end)), f"this {name}"
    if "today" in w or "whole day" in w:
        return midnight, now, "today"
    match = _SPAN.search(w)
    if match:
        count = match.group(1).replace(" of", "")
        number = int(count) if count.isdigit() else _NUMBERS.get(count, 1)
        unit = timedelta(hours=1) if match.group(2).startswith("h") else timedelta(minutes=1)
        number = max(1, min(number, 48 if unit == timedelta(hours=1) else 600))
        # "an hour ago" means around then: a little more than that, so it's in
        extra = 1.25 if "ago" in w else 1.0
        start = now - unit * number * extra
        what = f"the last {number} {'hour' if unit == timedelta(hours=1) else 'minute'}"
        return start, now, what + ("s" if number != 1 else "")
    if any(p in w for p in ("just now", "moment ago", "right now", "just", "second")):
        return now - timedelta(minutes=5), now, "the last 5 minutes"
    return now - timedelta(minutes=30), now, "the last 30 minutes"


def for_claude(entries: list[Entry], what: str = "") -> tuple[list[Entry], int]:
    """The entries worth sending (problems and the words asked about always; the rest as room
    allows, the latest kept), and how many were left out."""
    words = search_words(what)
    keep = set()
    for i, e in enumerate(entries):
        if e.problem or (words and e.matches(words)):
            keep.add(i)
    for i in range(len(entries) - 1, -1, -1):  # then the latest of the rest
        if len(keep) >= FOR_CLAUDE_ENTRIES:
            break
        keep.add(i)
    chosen = [entries[i] for i in sorted(keep)][-FOR_CLAUDE_ENTRIES:]
    return chosen, len(entries) - len(chosen)


def claude_line(e: Entry) -> str:
    details = ""
    if e.details:
        tail = [line.strip() for line in e.details.splitlines() if line.strip()][-3:]
        details = " | " + " / ".join(tail)
    return f"{e.time:%H:%M:%S} {e.level} {e.part}: {e.text}{details}"


def claude_text(entries: list[Entry]) -> str:
    """The entries as lines, oldest first, the oldest dropped past FOR_CLAUDE_CHARS."""
    lines = [claude_line(e)[:600] for e in entries]
    total, kept = 0, []
    for line in reversed(lines):
        total += len(line) + 1
        if total > FOR_CLAUDE_CHARS:
            break
        kept.append(line)
    return "\n".join(reversed(kept))


# ----- for the window -----


def for_page(e: Entry, today: datetime | None = None) -> dict:
    day = (today or datetime.now()).date()
    when = (
        "today"
        if e.time.date() == day
        else "yesterday"
        if e.time.date() == (day - timedelta(days=1))
        else f"{e.time:%b %d}"
    )
    return {
        "time": f"{e.time:%H:%M:%S}",
        "day": when,
        "level": e.level,
        "part": e.part,
        "text": e.text,
        "details": e.details,
    }


# ----- what Claude is sent (ACTION logs: what | when) -----

# How Abdoh is meant to work, so Claude can tell what in the log went wrong. (The Catalog,
# abdoh/catalog.py, adds the features the request is about.)
HOW_IT_WORKS = """- Waking: a wake word model listens for "Hey Abdoh"; a score under the \
sensitivity is ignored. With the voice check taught, only the user's voice wakes it. Paused ("stop \
listening"): only "start listening" counts, and Abdoh makes no sound.
- A request: the recording ends after a short pause; offline speech recognition writes it down. \
Heard speech but no words: the unclear sound. The user's own commands and the built-in skills \
(timers, volume, apps, music) run at once without Claude; everything else goes to Claude.
- Claude: Claude Code with the user's Claude account, an Anthropic key, OpenRouter or the \
ChatGPT plan. "Usage limit": the plan's limit; with the ChatGPT plan connected it answers until \
Claude's limit resets. "Claude Code failed": it crashed, wasn't signed in, or was updated.
- After a reply Abdoh listens a few more seconds without the wake word; in a lesson (a role \
with the board) or while watching the screen it keeps listening.
- Talking over a reply stops it (an echo canceller takes Abdoh's own voice out of the mic); a \
word or two from people nearby lets it carry on; "shut up" ends the conversation silently.
- Warnings like "Slow transcription" mean speech recognition took long; "Couldn't" lines say \
what failed and usually why."""

FOLLOW_UP = """Here is Abdoh's log for {span}{more}, oldest first: the time, how serious, \
which part of Abdoh, and what happened.
{lines}

How Abdoh is meant to work:
{works}

The user's request was: "{request}". From the log, explain in a few spoken sentences what \
happened and why, and what they can do about it if something went wrong. Say it plainly: don't \
read out log lines, exact times or file paths. If the log doesn't show it, say so. Don't ask to \
read the log again."""
EMPTY = """Abdoh's log has nothing for {span}. The user's request was: "{request}". Say so in \
one short sentence, and that you can look at a longer time if they say when it happened. Don't \
ask to read the log again."""


def follow_up(
    cfg: Config, arg: str, request: str, now: datetime | None = None, works: str = ""
) -> str:
    """The message that asks Claude again, with the log of the time asked about."""
    what, _, when = (arg or "").partition("|")
    start, end, words = span(when.strip(), now)
    entries = pick(read_entries(log_path(cfg)), since=start, until=end, limit=0)
    if not entries:
        return EMPTY.format(span=words, request=request)
    chosen, left = for_claude(entries, what.strip())
    more = f" ({left} more ordinary lines left out)" if left else ""
    return FOLLOW_UP.format(
        span=words,
        more=more,
        lines=claude_text(chosen),
        works=works or HOW_IT_WORKS,
        request=request,
    )
