"""Abdoh became Xanthos, then Krekos, and Abdoh again: on the first start as Abdoh, the folders
of the name it had last move back.

`%APPDATA%\\Krekos` (settings, commands, modes; only the built app keeps them there) becomes
`%APPDATA%\\Abdoh`, and `~/.krekos` (log, Claude's folder, window storage) becomes `~/.abdoh`;
Xanthos's fill in only what those lack. An Abdoh folder still there from before the renames is
older than all of that, so it is set aside first (`Abdoh-before-Krekos`), never mixed in.
`MARK` in the folder says it came back, so leftovers of the newer names that couldn't move
(something held them open) only fill in from then on. Runs before logging starts, so it
returns what it did for the log.
"""

import os
import shutil
import sys
from pathlib import Path

MARK = "came-back-from-krekos"
ASIDE = "-before-krekos"


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


def _set_aside(folder: Path) -> str:
    """Rename an Abdoh folder from before the renames out of the way. "" if it can't be."""
    aside = folder.with_name(folder.name + ASIDE)
    n = 2
    while aside.exists():
        aside = folder.with_name(f"{folder.name}{ASIDE}-{n}")
        n += 1
    try:
        os.replace(folder, aside)
    except OSError:
        return ""
    return f"Kept the older {folder} as {aside}"


def bring_back(sources: list[Path], target: Path) -> list[str]:
    """Move the newest of `sources` to `target` and let the others fill in. An older `target`
    (without MARK) is set aside first."""
    present = [s for s in sources if s.is_dir()]
    if not present:
        return []
    done = []
    if target.exists() and not (target / MARK).exists():
        aside = _set_aside(target)
        if aside:
            done.append(aside)
    done += [d for s in present if (d := move_folder(s, target))]
    try:
        target.mkdir(parents=True, exist_ok=True)
        (target / MARK).touch()
    except OSError:
        pass
    return done


def move_old_folders(
    home: Path | None = None, appdata: Path | None = None, frozen: bool | None = None
) -> list[str]:
    """Bring Krekos's (and Xanthos's) folders back to Abdoh's names. Returns log lines."""
    home = Path(home or Path.home())
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    done = bring_back([home / ".krekos", home / ".xanthos"], home / ".abdoh")
    if frozen and not os.environ.get("ABDOH_HOME"):
        appdata = Path(appdata or os.environ.get("APPDATA", home))
        done += bring_back([appdata / "Krekos", appdata / "Xanthos"], appdata / "Abdoh")
    return done
