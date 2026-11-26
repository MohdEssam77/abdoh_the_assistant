"""Codoh's own tools for ChatGPT chats: list, read, search, write, edit, run a command.

Everything happens inside the chosen project folder: a path outside it (with "..", an absolute
path elsewhere, or a link that leads out) is refused. Claude chats don't use these: Claude Code
has its own tools.
"""

import fnmatch
import os
import re
import subprocess
import sys
from pathlib import Path

from abdoh.claude.code import NO_WINDOW

# Folders nobody wants searched or listed.
SKIPPED = set(
    ".git node_modules .venv venv __pycache__ dist build .next .mypy_cache .pytest_cache "
    ".ruff_cache .idea .vs target .tox".split()
)
READ_LINES = 400  # lines of a file at a time
READ_MAX_BYTES = 2_000_000
SEARCH_MAX = 200
LIST_MAX = 400
OUTPUT_CHARS = 30_000
COMMAND_SECONDS = 120
COMMAND_MAX_SECONDS = 600
# What each tool does: reading just happens; changes and commands may ask first.
KIND = {
    "list_files": "read",
    "read_file": "read",
    "search": "read",
    "write_file": "edit",
    "edit_file": "edit",
    "run_command": "command",
}


class ToolError(Exception):
    """The tool couldn't do it; the message goes back to the model."""


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required}


_PATH = {"type": "string", "description": "A path relative to the project folder"}
SHELL = "PowerShell" if sys.platform == "win32" else "bash"
TOOLS = [
    {
        "type": "function",
        "name": "list_files",
        "description": "List a folder of the project, or the files matching a glob pattern "
        "such as **/*.py (common build and dependency folders are skipped).",
        "parameters": _schema(
            {
                "path": {**_PATH, "description": "The folder (default: the project folder)"},
                "pattern": {"type": "string", "description": "A glob pattern, e.g. src/**/*.ts"},
            },
            [],
        ),
    },
    {
        "type": "function",
        "name": "read_file",
        "description": f"Read a text file, with line numbers, {READ_LINES} lines at a time.",
        "parameters": _schema(
            {
                "path": _PATH,
                "offset": {"type": "integer", "description": "The first line (1 = the start)"},
                "limit": {"type": "integer", "description": "How many lines"},
            },
            ["path"],
        ),
    },
    {
        "type": "function",
        "name": "search",
        "description": "Search the project's files for a regular expression; returns "
        "path:line: text for each match.",
        "parameters": _schema(
            {
                "pattern": {"type": "string", "description": "A Python regular expression"},
                "path": {**_PATH, "description": "Where to search (default: everywhere)"},
                "glob": {"type": "string", "description": "Only files like this, e.g. *.py"},
            },
            ["pattern"],
        ),
    },
    {
        "type": "function",
        "name": "write_file",
        "description": "Create a file, or replace all of an existing file's content.",
        "parameters": _schema(
            {"path": _PATH, "content": {"type": "string", "description": "The whole file"}},
            ["path", "content"],
        ),
    },
    {
        "type": "function",
        "name": "edit_file",
        "description": "Replace exact text in a file. old_text must appear exactly once "
        "(include enough lines around it), unless replace_all is true.",
        "parameters": _schema(
            {
                "path": _PATH,
                "old_text": {"type": "string", "description": "The exact text to replace"},
                "new_text": {"type": "string", "description": "What replaces it"},
                "replace_all": {"type": "boolean", "description": "Replace every occurrence"},
            },
            ["path", "old_text", "new_text"],
        ),
    },
    {
        "type": "function",
        "name": "run_command",
        "description": f"Run a {SHELL} command in the project folder (tests, builds, git, "
        "package managers) and get its output and exit code.",
        "parameters": _schema(
            {
                "command": {"type": "string", "description": "The command line"},
                "timeout_seconds": {"type": "integer", "description": "At most 600"},
            },
            ["command"],
        ),
    },
]
READ_ONLY_TOOLS = [t for t in TOOLS if KIND[t["name"]] == "read"]


class Workspace:
    """The project folder, and the tools that work in it."""

    def __init__(self, folder: Path, run=subprocess.run):
        self.folder = Path(folder).resolve()
        self._run = run

    def resolve(self, path: str = ".") -> Path:
        """`path` inside the project folder, or ToolError."""
        raw = Path(str(path or ".").strip() or ".")
        target = raw if raw.is_absolute() else self.folder / raw
        try:
            target = target.resolve()
        except OSError as e:
            raise ToolError(f"Can't use the path {path}: {e}") from e
        if target != self.folder and not target.is_relative_to(self.folder):
            raise ToolError(f"{path} is outside the project folder; only {self.folder} is allowed.")
        return target

    def name(self, path: Path) -> str:
        return path.relative_to(self.folder).as_posix() or "."

    def call(self, tool: str, args: dict) -> str:
        """Run one tool. Raises ToolError."""
        handlers = {
            "list_files": self.list_files,
            "read_file": self.read_file,
            "search": self.search,
            "write_file": self.write_file,
            "edit_file": self.edit_file,
            "run_command": self.run_command,
        }
        if tool not in handlers:
            raise ToolError(f"There's no tool called {tool}.")
        try:
            return handlers[tool](**{k: v for k, v in (args or {}).items() if v is not None})
        except TypeError as e:
            raise ToolError(f"Wrong arguments for {tool}: {e}") from e

    # ----- reading -----

    def _walk(self, start: Path):
        for root, dirs, files in os.walk(start):
            dirs[:] = sorted(d for d in dirs if d not in SKIPPED and not d.startswith(".git"))
            for file in sorted(files):
                yield Path(root) / file

    def list_files(self, path: str = ".", pattern: str = "") -> str:
        where = self.resolve(path)
        if not where.exists():
            raise ToolError(f"{path} doesn't exist.")
        if pattern:
            found = [
                self.name(p)
                for p in self._walk(where)
                if fnmatch.fnmatch(p.relative_to(where).as_posix(), pattern)
                or fnmatch.fnmatch(p.name, pattern)
            ]
        elif where.is_dir():
            found = [
                self.name(p) + ("/" if p.is_dir() else "")
                for p in sorted(where.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
                if p.name not in SKIPPED
            ]
        else:
            found = [self.name(where)]
        more = f"\n... and {len(found) - LIST_MAX} more" if len(found) > LIST_MAX else ""
        return "\n".join(found[:LIST_MAX]) + more if found else "(nothing)"

    def _text(self, path: Path) -> str:
        if not path.is_file():
            raise ToolError(f"{self.name(path)} isn't a file.")
        if path.stat().st_size > READ_MAX_BYTES:
            raise ToolError(f"{self.name(path)} is too big to read ({path.stat().st_size} bytes).")
        data = path.read_bytes()
        if b"\0" in data[:8000]:
            raise ToolError(f"{self.name(path)} is a binary file.")
        return data.decode("utf-8", "replace")

    def read_file(self, path: str, offset: int = 1, limit: int = READ_LINES) -> str:
        target = self.resolve(path)
        lines = self._text(target).splitlines()
        start = max(1, int(offset or 1))
        count = max(1, min(int(limit or READ_LINES), 2000))
        shown = lines[start - 1 : start - 1 + count]
        body = "\n".join(f"{n:>5}\t{line}" for n, line in enumerate(shown, start))
        left = len(lines) - (start - 1 + len(shown))
        more = f"\n({left} more lines: read from line {start + len(shown)})" if left > 0 else ""
        return (body or "(empty)") + more

    def search(self, pattern: str, path: str = ".", glob: str = "") -> str:
        try:
            regex = re.compile(pattern)
        except re.error as e:
            raise ToolError(f"That isn't a valid regular expression: {e}") from e
        where = self.resolve(path)
        files = [where] if where.is_file() else self._walk(where)
        found = []
        for file in files:
            if glob and not fnmatch.fnmatch(file.name, glob):
                continue
            try:
                if file.stat().st_size > READ_MAX_BYTES:
                    continue
                data = file.read_bytes()
            except OSError:
                continue
            if b"\0" in data[:8000]:
                continue
            for number, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
                if regex.search(line):
                    found.append(f"{self.name(file)}:{number}: {line.strip()[:300]}")
                    if len(found) >= SEARCH_MAX:
                        return "\n".join(found) + f"\n(stopped at {SEARCH_MAX} matches)"
        return "\n".join(found) if found else "No matches."

    # ----- changing -----

    def current(self, path: str) -> str:
        """A file's text now ("" if it doesn't exist): for showing what a change does."""
        target = self.resolve(path)
        return self._text(target) if target.is_file() else ""

    def write_file(self, path: str, content: str) -> str:
        target = self.resolve(path)
        if target.is_dir():
            raise ToolError(f"{path} is a folder.")
        existed = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")
        lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        return f"{'Replaced' if existed else 'Created'} {self.name(target)} ({lines} lines)."

    def edit_file(self, path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
        target = self.resolve(path)
        text = self._text(target)
        if not old_text:
            raise ToolError("old_text is empty: use write_file to create a file.")
        found = text.count(old_text)
        if found == 0:
            raise ToolError(f"old_text wasn't found in {self.name(target)}: read it again.")
        if found > 1 and not replace_all:
            raise ToolError(
                f"old_text is in {self.name(target)} {found} times: add lines around it, or "
                "set replace_all."
            )
        changed = (
            text.replace(old_text, new_text) if replace_all else text.replace(old_text, new_text, 1)
        )
        target.write_text(changed, encoding="utf-8", newline="")
        times = f" ({found} places)" if replace_all and found > 1 else ""
        return f"Changed {self.name(target)}{times}."

    def run_command(self, command: str, timeout_seconds: int = COMMAND_SECONDS) -> str:
        if not str(command).strip():
            raise ToolError("The command is empty.")
        seconds = max(1, min(int(timeout_seconds or COMMAND_SECONDS), COMMAND_MAX_SECONDS))
        if sys.platform == "win32":
            args = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
        else:
            args = ["bash", "-lc", command]
        try:
            done = self._run(
                args,
                cwd=self.folder,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=seconds,
                creationflags=NO_WINDOW,
            )
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or "") if isinstance(e.stdout, str) else ""
            return f"{out[-OUTPUT_CHARS:]}\n(stopped after {seconds} seconds)"
        except OSError as e:
            raise ToolError(f"Couldn't run it: {e}") from e
        out = "\n".join(part for part in (done.stdout, done.stderr) if part and part.strip())
        if len(out) > OUTPUT_CHARS:
            out = "...\n" + out[-OUTPUT_CHARS:]
        return f"{out.rstrip()}\n(exit code {done.returncode})".strip()


def command_prefix(command: str) -> str:
    """What "allow for this chat" allows of a command: its program and first word ("npm test",
    "git status", "pytest")."""
    words = str(command).split()
    return (
        " ".join(words[:2])
        if len(words) > 1 and not words[1].startswith("-")
        else (words[0] if words else "")
    )
