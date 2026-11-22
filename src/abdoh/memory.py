"""What Abdoh remembers about you (memory.yaml): facts about you, and lessons (what works on this
computer, learned when something failed and then worked).

Claude adds them (ACTION remember, ACTION lesson) and forgets them (ACTION forget); every new
Claude conversation gets them in its instructions; the Memory page shows and edits them. The
file stays on this computer. Every change is checked before it's written, and a file you broke
by hand is never overwritten: it's reported instead."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml
from rapidfuzz import fuzz

from abdoh.config import write_atomic

log = logging.getLogger(__name__)

KINDS = ("fact", "lesson")
MAX_ENTRIES = 60
MAX_CHARS = 4000  # all the entries together, so the instructions stay short
MAX_ENTRY_CHARS = 300
NEARLY_FULL = 300  # characters left at which Claude is told to merge or forget first
FORGET_MATCH = 85  # how close "forget ..." must be to an entry (0-100)

HEADER = """\
# What Abdoh remembers about you. It stays on this computer and goes to Claude with your
# requests. Edit it on the Memory page, or here by hand.
#
# - text: Their sister is called Lina.
#   kind: fact         # fact (about you) or lesson (what works on this computer)
#   added: 2026-11-23
"""

FULL = "My memory is full. Tell me something to forget first, then ask me again."
NOT_THERE = "I don't have that in my memory."


class MemoryChangeError(ValueError):
    """Abdoh can't remember or forget that; the message is safe to say and show."""


class MemoryFileError(MemoryChangeError):
    """memory.yaml can't be read (broken by hand): nothing is changed until it's fixed."""


@dataclass(frozen=True)
class Entry:
    text: str
    kind: str = "fact"
    added: str = ""  # YYYY-MM-DD

    def as_item(self) -> dict:
        return {"text": self.text, "kind": self.kind, "added": self.added}


def clean(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def _same(a: str, b: str) -> bool:
    return clean(a).rstrip(".").casefold() == clean(b).rstrip(".").casefold()


def parse(data) -> list[Entry]:
    """memory.yaml's content -> entries. Raises MemoryFileError if it isn't a list of entries."""
    if data is None:
        return []
    if not isinstance(data, list):
        raise MemoryFileError("Your memory file isn't a list of entries.")
    entries = []
    for i, item in enumerate(data, 1):
        if not isinstance(item, dict) or not clean(item.get("text", "")):
            raise MemoryFileError(f"Entry {i} in your memory file has no text.")
        kind = str(item.get("kind") or "fact")
        if kind not in KINDS:
            raise MemoryFileError(f"Entry {i} in your memory file: kind must be fact or lesson.")
        entries.append(Entry(clean(item["text"]), kind, str(item.get("added") or "")))
    return entries


def size(entries: list[Entry]) -> int:
    return sum(len(e.text) for e in entries)


def nearly_full(entries: list[Entry]) -> bool:
    return len(entries) >= MAX_ENTRIES or size(entries) > MAX_CHARS - NEARLY_FULL


class Memory:
    """Your memory file. `today()` gives the date new entries get."""

    def __init__(self, path: Path, today: Callable[[], date] = date.today):
        self.path = Path(path)
        self.today = today

    def load(self) -> list[Entry]:
        """The entries, oldest first. Raises MemoryFileError if the file is broken."""
        if not self.path.exists():
            return []
        try:
            data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as e:
            raise MemoryFileError(f"Your memory file can't be read: {e}") from e
        return parse(data)

    def entries(self) -> list[Entry]:
        """The entries, or none if the file is broken (for Claude's instructions)."""
        try:
            return self.load()
        except MemoryFileError as e:
            log.warning("%s", e)
            return []

    def add(self, text: str, kind: str = "fact") -> Entry:
        """Remember something new. The same thing again is kept once."""
        text = clean(text)
        if not text:
            raise MemoryChangeError("There's nothing to remember.")
        if kind not in KINDS:
            raise MemoryChangeError("A memory is a fact or a lesson.")
        if len(text) > MAX_ENTRY_CHARS:
            raise MemoryChangeError("That's too long to remember. Say it in one short sentence.")
        entries = self.load()
        same = next((e for e in entries if _same(e.text, text)), None)
        if same is not None:
            return same
        if len(entries) >= MAX_ENTRIES or size(entries) + len(text) > MAX_CHARS:
            raise MemoryChangeError(FULL)
        entry = Entry(text, kind, self.today().isoformat())
        self._write([*entries, entry])
        return entry

    def find(self, text: str, entries: list[Entry] | None = None) -> Entry | None:
        """The entry meant by `text`: the same words, or very nearly."""
        entries = self.load() if entries is None else entries
        exact = next((e for e in entries if _same(e.text, text)), None)
        if exact is not None or not clean(text):
            return exact
        scored = [(fuzz.ratio(clean(text).casefold(), e.text.casefold()), e) for e in entries]
        best = max(scored, default=(0, None), key=lambda pair: pair[0])
        return best[1] if best[0] >= FORGET_MATCH else None

    def forget(self, text: str) -> Entry:
        """Forget the entry meant by `text`. Raises MemoryChangeError if there's none."""
        entries = self.load()
        entry = self.find(text, entries)
        if entry is None:
            raise MemoryChangeError(NOT_THERE)
        self._write([e for e in entries if e is not entry])
        return entry

    def change(self, old_text: str, text: str, kind: str) -> Entry:
        """The Memory page changed an entry's words or kind (it keeps its place and date)."""
        text = clean(text)
        if not text:
            raise MemoryChangeError("A memory needs some words.")
        if kind not in KINDS or len(text) > MAX_ENTRY_CHARS:
            raise MemoryChangeError(
                "That's too long to remember." if kind in KINDS else "Pick fact or lesson."
            )
        entries = self.load()
        index = next((i for i, e in enumerate(entries) if _same(e.text, old_text)), None)
        if index is None:
            raise MemoryChangeError(NOT_THERE)
        if any(_same(e.text, text) for i, e in enumerate(entries) if i != index):
            raise MemoryChangeError("You already have that in your memory.")
        changed = Entry(text, kind, entries[index].added)
        entries[index] = changed
        if size(entries) > MAX_CHARS:
            raise MemoryChangeError(FULL)
        self._write(entries)
        return changed

    def _write(self, entries: list[Entry]) -> None:
        items = [e.as_item() for e in entries]
        body = yaml.safe_dump(items, sort_keys=False, allow_unicode=True, width=96)
        text = HEADER + "\n" + (body if items else "[]\n")
        parse(yaml.safe_load(text))  # what's written must read back
        write_atomic(self.path, text)


def for_claude(entries: list[Entry]) -> str:
    """The entries for Claude's instructions: what it knows about the user, then the lessons."""
    facts = [e.text for e in entries if e.kind == "fact"]
    lessons = [e.text for e in entries if e.kind == "lesson"]
    parts = []
    if facts:
        parts.append("What you know about the user:\n" + "\n".join(f"- {t}" for t in facts))
    if lessons:
        parts.append(
            "Lessons (what works on this computer):\n" + "\n".join(f"- {t}" for t in lessons)
        )
    return "\n".join(parts)
