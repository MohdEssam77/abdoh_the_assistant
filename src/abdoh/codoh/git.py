"""The project folder's git state for Codoh's header and Changes panel: the branch, what
changed, and each file's diff. Nothing is changed in the repository."""

import logging
import shutil
import subprocess
from pathlib import Path

from abdoh.claude.code import NO_WINDOW
from abdoh.codoh.cards import DIFF_LINES, counts, unified

log = logging.getLogger(__name__)

SECONDS = 8
MAX_FILES = 300


def _git(folder: Path, *args: str, run=subprocess.run) -> str | None:
    """git's output, or None when git isn't there, the folder isn't a repository, or it
    failed."""
    exe = shutil.which("git")
    if exe is None:
        return None
    try:
        done = run(
            [exe, "-C", str(folder), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=SECONDS,
            creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def info(folder: Path, git=_git) -> dict | None:
    """{branch, changed} for a repository, or None."""
    branch = git(folder, "branch", "--show-current")  # works before the first commit too
    if branch is None:
        return None
    if not branch.strip():  # a detached HEAD: its commit
        branch = git(folder, "rev-parse", "--short", "HEAD") or "detached"
    status = git(folder, "status", "--porcelain=v1") or ""
    changed = len([line for line in status.splitlines() if line.strip()])
    return {"branch": branch.strip() or "HEAD", "changed": changed}


_STATUS = {
    "M": "changed",
    "A": "added",
    "D": "deleted",
    "R": "renamed",
    "?": "new",
    "U": "conflict",
}


def changes(folder: Path, git=_git) -> list[dict] | None:
    """Each changed file: {path, state, added, removed}, or None outside a repository."""
    status = git(folder, "status", "--porcelain=v1", "-uall")
    if status is None:
        return None
    numbers: dict[str, tuple[int, int]] = {}
    for staged in (False, True):
        args = ["diff", "--numstat", *(["--cached"] if staged else [])]
        for line in (git(folder, *args) or "").splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                a, r = (int(x) if x.isdigit() else 0 for x in parts[:2])
                old = numbers.get(parts[2], (0, 0))
                numbers[parts[2]] = (old[0] + a, old[1] + r)
    found = []
    for line in status.splitlines()[:MAX_FILES]:
        if len(line) < 4:
            continue
        code, path = line[:2], line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        mark = (code.strip() or "M")[0]
        added, removed = numbers.get(path, (0, 0))
        if mark == "?":
            try:
                text = (Path(folder) / path).read_text(encoding="utf-8", errors="replace")
                added = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
            except OSError:
                added = 0
        found.append(
            {
                "path": path,
                "state": _STATUS.get(mark, "changed"),
                "added": added,
                "removed": removed,
            }
        )
    return found


def diff(folder: Path, path: str, git=_git) -> str:
    """One file's changes as a unified diff (a new file: all of it)."""
    from abdoh.codoh.tools import ToolError, Workspace

    try:
        target = Workspace(folder).resolve(path)
    except ToolError:
        return ""
    name = target.relative_to(Path(folder).resolve()).as_posix()
    text = (git(folder, "diff", "HEAD", "--", name) or "").strip()
    if not text:
        text = (git(folder, "diff", "--", name) or "").strip()
    if not text and target.is_file():  # untracked: all of it is new
        try:
            text = unified("", target.read_text(encoding="utf-8", errors="replace"), name)
        except OSError:
            text = ""
    lines = text.splitlines()
    return "\n".join(lines[:DIFF_LINES]) + ("\n…" if len(lines) > DIFF_LINES else "")


__all__ = ["changes", "counts", "diff", "info"]
