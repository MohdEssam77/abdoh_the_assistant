"""A week of conversations: what you said to Abdoh and what it answered, one file a day
(`conversations/2026-11-25.jsonl` in Abdoh's folder), kept on this computer for
`conversation_days` (7) and then deleted. With memory or the Memory page's "Keep conversations"
switch off, nothing new is kept.

One line per exchange: the time, what you said (or typed), what Abdoh answered, the mode and
the role at the time, and what that answer put on the board. Not what Abdoh says by itself
(timers, reminders). Claude sees a part only when you ask about an earlier conversation.
"""

import json
import logging
import re
import threading
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

FOLDER = "conversations"
DAYS = 7
# Longest text kept per exchange: a request, an answer, a board (it may hold a drawing).
MAX_YOU, MAX_ABDOH, MAX_BOARD = 2_000, 8_000, 20_000
_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})\.jsonl$")
_LOCK = threading.Lock()  # the daemon writes, the window reads and deletes
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")  # fmt: skip


@dataclass
class Exchange:
    """One request and its answer."""

    at: datetime
    you: str
    abdoh: str
    typed: bool = False
    mode: str = ""
    role: str = ""
    board: str = ""

    def as_item(self) -> dict:
        """For the Memory page."""
        item = asdict(self)
        item["at"] = f"{self.at:%H:%M}"
        return item

    def line(self) -> str:
        data = {"at": self.at.isoformat(timespec="seconds"), "you": self.you, "abdoh": self.abdoh}
        more = {"typed": self.typed, "mode": self.mode, "role": self.role, "board": self.board}
        data.update({k: v for k, v in more.items() if v})  # only what there is
        return json.dumps(data, ensure_ascii=False)

    @classmethod
    def read(cls, line: str) -> "Exchange | None":
        try:
            data = json.loads(line)
            return cls(
                at=datetime.fromisoformat(data["at"]),
                you=str(data.get("you", "")),
                abdoh=str(data.get("abdoh", "")),
                typed=bool(data.get("typed", False)),
                mode=str(data.get("mode", "")),
                role=str(data.get("role", "")),
                board=str(data.get("board", "")),
            )
        except (ValueError, KeyError, TypeError):
            return None  # a broken line (cut off when the computer went off): skipped


def day_label(day: date, today: date) -> str:
    """Today, Yesterday, or "Monday 23 November" (in English, whatever Windows' language)."""
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    label = f"{WEEKDAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]}"
    return label if day.year == today.year else f"{label} {day.year}"


def _cut(text: str, limit: int) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class Conversations:
    """The conversations folder. `now` is for tests."""

    def __init__(self, folder: Path, days: int = DAYS, now=None):
        self.folder = Path(folder)
        self.days = max(1, int(days))
        self._now = now or (lambda: datetime.now())

    def _path(self, day: date) -> Path:
        return self.folder / f"{day:%Y-%m-%d}.jsonl"

    def _files(self) -> dict[date, Path]:
        found: dict[date, Path] = {}
        if not self.folder.is_dir():
            return found
        for path in self.folder.iterdir():
            match = _NAME.match(path.name)
            if match and path.is_file():
                try:
                    found[date.fromisoformat(match[1])] = path
                except ValueError:
                    continue
        return found

    def today(self) -> date:
        return self._now().date()

    def oldest_kept(self) -> date:
        """The first day still kept: exchanges from before it are deleted."""
        return self.today() - timedelta(days=self.days)

    def add(self, you: str, abdoh: str, typed: bool = False, mode: str = "", role: str = "",
            board: str = "") -> Exchange | None:  # fmt: skip
        """Keep one exchange (nothing when both sides are empty)."""
        you, abdoh = _cut(you, MAX_YOU), _cut(abdoh, MAX_ABDOH)
        if not you or not (abdoh or board):
            return None
        now = self._now()
        exchange = Exchange(now.replace(microsecond=0), you, abdoh, bool(typed), mode or "",
                            role or "", _cut(board, MAX_BOARD))  # fmt: skip
        with _LOCK:
            path = self._path(now.date())
            first_today = not path.exists()
            self.folder.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as f:
                f.write(exchange.line() + "\n")
        if first_today:  # a new day: the oldest one may go
            self.clean()
        return exchange

    def day(self, day: date) -> list[Exchange]:
        """One day's exchanges, oldest first."""
        path = self._path(day)
        with _LOCK:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except FileNotFoundError:
                return []
            except OSError:
                log.warning("Couldn't read %s", path, exc_info=True)
                return []
        return [e for e in (Exchange.read(line) for line in lines if line.strip()) if e]

    def days_kept(self) -> list[tuple[date, int]]:
        """Each day kept, newest first, with how many exchanges it has."""
        oldest = self.oldest_kept()
        days = sorted((d for d in self._files() if d >= oldest), reverse=True)
        return [(d, n) for d in days if (n := len(self.day(d)))]

    def exchanges(self, first: date | None = None, last: date | None = None) -> list[Exchange]:
        """Every exchange kept from `first` to `last` (both included), oldest first."""
        first = max(first or self.oldest_kept(), self.oldest_kept())
        last = last or self._now().date()
        found: list[Exchange] = []
        for day in sorted(d for d in self._files() if first <= d <= last):
            found += self.day(day)
        return found

    def delete_day(self, day: date) -> bool:
        with _LOCK:
            path = self._path(day)
            if not path.exists():
                return False
            path.unlink()
        log.info("Deleted the conversations of %s", day)
        return True

    def forget_all(self) -> int:
        """Delete every conversation kept. Returns how many days there were."""
        deleted = 0
        with _LOCK:
            for path in self._files().values():
                try:
                    path.unlink()
                    deleted += 1
                except OSError:
                    log.warning("Couldn't delete %s", path, exc_info=True)
        log.info("Forgot all conversations (%d days)", deleted)
        return deleted

    def clean(self) -> int:
        """Delete the days older than `days`. Returns how many went."""
        oldest = self.oldest_kept()
        deleted = 0
        with _LOCK:
            for day, path in self._files().items():
                if day < oldest:
                    try:
                        path.unlink()
                        deleted += 1
                    except OSError:
                        log.warning("Couldn't delete %s", path, exc_info=True)
        if deleted:
            log.info("Deleted conversations older than %d days (%d days)", self.days, deleted)
        return deleted
