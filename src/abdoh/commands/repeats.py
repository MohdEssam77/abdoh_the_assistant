"""What Claude did for you that took several actions, so that when you ask for the same again
(in a later conversation too) it offers once to save it as a command.

Kept in repeats.json in Abdoh's data folder while memory is on: each different set of steps,
the words you used last time, and how often you asked. Claude is told about the ones you asked
for once (see brain.SAVE_STEPS); after the second time they're never offered again, whether
you said yes (then it's a command) or no."""

import json
import logging
from datetime import date
from pathlib import Path

from abdoh.config import write_atomic

log = logging.getLogger(__name__)

FILE = "repeats.json"
MIN_STEPS = 2  # a single action is quick to ask for: never worth a command of its own
KEEP = 40  # the most recent different things
SHOWN = 10  # how many Claude is told about
_REQUEST_CHARS = 120

Steps = list[tuple[str, str]]


def _load(path: Path) -> list[dict]:
    try:
        entries = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        log.warning("Couldn't read %s (%s): starting it again", path, e)
        return []
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def _steps(entry: dict) -> Steps:
    return [(str(k), str(v)) for k, v in entry.get("steps") or []]


def same(a: Steps, b: Steps) -> bool:
    """The same things done, in any order ("volume 75, then WhatsApp" is "WhatsApp, volume 75")."""

    def key(steps: Steps) -> list[tuple[str, str]]:
        return sorted((str(k).casefold(), str(v).strip().casefold()) for k, v in steps)

    return key(a) == key(b)


def is_saved(steps: Steps, saved: list[Steps]) -> bool:
    """Is there a command that does just these steps?"""
    return any(same(steps, command) for command in saved)


def record(path: Path, request: str, steps: Steps, today: date | None = None) -> int:
    """Note that `steps` were done for `request` (only when there are several). Returns how
    many times they have been asked for now (0: not noted)."""
    if len(steps) < MIN_STEPS:
        return 0
    steps = [(str(k), str(v)) for k, v in steps]
    entries = _load(path)
    old = next((e for e in entries if same(_steps(e), steps)), None)
    if old is not None:
        entries.remove(old)
    times = int(old.get("times", 1)) + 1 if old else 1
    entries.append(
        {
            "request": " ".join(request.split())[:_REQUEST_CHARS],
            "steps": [list(s) for s in steps],
            "times": times,
            "last": (today or date.today()).isoformat(),
        }
    )
    try:
        write_atomic(Path(path), json.dumps(entries[-KEEP:], ensure_ascii=False, indent=1))
    except OSError as e:
        log.warning("Couldn't save %s: %s", path, e)
    return times


def command_steps(item: dict) -> Steps:
    """A commands.yaml item's actions as (kind, value)."""
    return [
        (str(k), str(v))
        for action in item.get("actions") or []
        if isinstance(action, dict)
        for k, v in action.items()
    ]


def for_claude(path: Path, saved: list[Steps]) -> str:
    """The things asked for once so far that aren't commands, newest first, one per line."""
    lines = []
    for entry in reversed(_load(path)):
        steps = _steps(entry)
        if entry.get("times") != 1 or len(steps) < MIN_STEPS or is_saved(steps, saved):
            continue
        did = "; ".join(f"{k}: {v}" for k, v in steps)
        lines.append(f'- "{entry.get("request", "")}" ({did})')
        if len(lines) == SHOWN:
            break
    return "\n".join(lines)
