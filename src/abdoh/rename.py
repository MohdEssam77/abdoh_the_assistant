"""Abdoh became Xanthos, then Krekos: on the first start under the new name, the old folders
move over.

`%APPDATA%\\Xanthos` and `%APPDATA%\\Abdoh` (settings, commands, modes; only the built app keeps
them there) become `%APPDATA%\\Krekos`, and `~/.xanthos` and `~/.abdoh` (log, Claude's folder,
window storage) become `~/.krekos`. Xanthos's go first, as they are newer: Abdoh's only fill in
what's missing. Nothing happens once the old folders are gone. Runs before logging starts, so
it returns what it did for the log.
"""

import os
import shutil
import sys
from pathlib import Path


def move_folder(old: Path, new: Path) -> str:
    """Move `old` to `new`. If `new` already exists, what it lacks is moved into it (nothing is
    ever overwritten). Copies instead if something still holds a file open. Returns what
    happened ("" for nothing). Never raises."""
    if not old.is_dir():
        return ""
    if new.exists():
        return _merge(old, new)
    try:
        os.replace(old, new)
        return f"Moved {old} to {new}"
    except OSError:
        pass
    try:
        shutil.copytree(old, new)
        return f"Copied {old} to {new}"
    except OSError as e:
        return f"Couldn't bring over {old}: {e}"


def _merge(old: Path, new: Path) -> str:
    moved = 0
    for item in old.iterdir():
        if not (new / item.name).exists():
            try:
                os.replace(item, new / item.name)
                moved += 1
            except OSError:
                pass  # in use: it stays where it was
    try:
        old.rmdir()  # only if it's empty now
    except OSError:
        pass
    return f"Moved {moved} items from {old} to {new}" if moved else ""


def move_old_folders(
    home: Path | None = None, appdata: Path | None = None, frozen: bool | None = None
) -> list[str]:
    """Bring Xanthos's and Abdoh's folders over to Krekos's names. Returns log lines."""
    home = Path(home or Path.home())
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    moves = [(home / ".xanthos", home / ".krekos"), (home / ".abdoh", home / ".krekos")]
    if frozen and not os.environ.get("ABDOH_HOME"):
        appdata = Path(appdata or os.environ.get("APPDATA", home))
        moves += [
            (appdata / "Xanthos", appdata / "Krekos"),
            (appdata / "Abdoh", appdata / "Krekos"),
        ]
    return [done for old, new in moves if (done := move_folder(old, new))]
