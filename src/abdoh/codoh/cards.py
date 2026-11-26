"""What Codoh shows for a tool the model used: one card, the same for both engines.

A card is a dict: {kind, title, detail, diff, output, ok, status}. `kind` says what the tool
did (read, search, list, edit, write, command, web, task, todo, other); `title` is the thing it
worked on (a file, a search, a command); `diff` is a unified diff for changes.
"""

import difflib
import json
from pathlib import Path

OUTPUT_CHARS = 20_000  # of a command's output or a tool's result, kept for the card
DIFF_LINES = 800

# Claude Code's tools, and Codoh's own (codoh/tools.py), by what they do.
KINDS = {
    "Read": "read",
    "read_file": "read",
    "Glob": "search",
    "Grep": "search",
    "search": "search",
    "LS": "list",
    "list_files": "list",
    "Edit": "edit",
    "MultiEdit": "edit",
    "edit_file": "edit",
    "NotebookEdit": "edit",
    "Write": "write",
    "write_file": "write",
    "Bash": "command",
    "PowerShell": "command",
    "run_command": "command",
    "WebSearch": "web",
    "WebFetch": "web",
    "Task": "task",
    "Agent": "task",
    "TodoWrite": "todo",
}
# Changes files or runs things: asks first in the "ask" mode.
CHANGES = ("edit", "write")


def kind_of(tool: str) -> str:
    return KINDS.get(tool, "other")


def relative(path: str, folder: Path | None) -> str:
    """A path as the user knows it: relative to the project folder when it's inside it."""
    if not path:
        return ""
    if folder is None:
        return str(path)
    try:
        return Path(path).resolve().relative_to(Path(folder).resolve()).as_posix()
    except (ValueError, OSError):
        return str(path)


def unified(old: str, new: str, name: str) -> str:
    lines = difflib.unified_diff(
        old.splitlines(), new.splitlines(), f"a/{name}", f"b/{name}", lineterm="", n=3
    )
    return "\n".join(list(lines)[:DIFF_LINES])


def from_patch(hunks: list, name: str) -> str:
    """Claude Code's structuredPatch ([{oldStart, oldLines, newStart, newLines, lines}]) as a
    unified diff."""
    out = [f"--- a/{name}", f"+++ b/{name}"]
    for h in hunks or []:
        try:
            out.append(f"@@ -{h['oldStart']},{h['oldLines']} +{h['newStart']},{h['newLines']} @@")
            out.extend(str(line) for line in h.get("lines", []))
        except (KeyError, TypeError):
            continue
    return "\n".join(out[:DIFF_LINES]) if len(out) > 2 else ""


def card(tool: str, data: dict, folder: Path | None = None) -> dict:
    """The card for a tool call, from its input (before it runs)."""
    data = data if isinstance(data, dict) else {}
    kind = kind_of(tool)
    path = data.get("file_path") or data.get("path") or data.get("notebook_path") or ""
    name = relative(str(path), folder)
    title, detail, diff = name, "", ""
    if kind == "read":
        start = data.get("offset")
        detail = f"from line {start}" if start else ""
    elif kind == "search":
        title = str(data.get("pattern") or data.get("query") or "")
        where = data.get("path") or data.get("glob") or ""
        detail = f"in {relative(str(where), folder)}" if where else ""
    elif kind == "list":
        title = name or "."
        detail = str(data.get("pattern") or "")
    elif kind == "edit":
        old = str(data.get("old_string", data.get("old_text", "")))
        new = str(data.get("new_string", data.get("new_text", "")))
        edits = data.get("edits")
        if isinstance(edits, list):  # MultiEdit
            parts = [
                unified(str(e.get("old_string", "")), str(e.get("new_string", "")), name)
                for e in edits
            ]
            diff = "\n".join(p for p in parts if p)
        else:
            diff = unified(old, new, name)
    elif kind == "write":
        diff = unified("", str(data.get("content", "")), name)
    elif kind == "command":
        title = str(data.get("command", ""))
        detail = str(data.get("description", ""))
    elif kind == "web":
        title = str(data.get("query") or data.get("url") or "")
    elif kind == "task":
        title = str(data.get("description") or data.get("prompt") or "")[:120]
    elif kind == "todo":
        todos = data.get("todos") if isinstance(data.get("todos"), list) else []
        title = f"{len(todos)} steps"
        detail = json.dumps(
            [{"text": t.get("content", ""), "status": t.get("status", "")} for t in todos]
        )
    else:
        title = tool
        detail = json.dumps(data)[:300] if data else ""
    return {
        "tool": tool,
        "kind": kind,
        "title": title,
        "detail": detail,
        "diff": diff,
        "output": "",
        "ok": True,
        "status": "running",
    }


def finish(item: dict, ok: bool, output: str = "", result=None, folder: Path | None = None):
    """The card once the tool ran: its output, and the real diff when Claude Code sent one."""
    item["ok"] = bool(ok)
    item["status"] = "done" if ok else "failed"
    text = output or ""
    if len(text) > OUTPUT_CHARS:
        text = "…\n" + text[-OUTPUT_CHARS:]
    item["output"] = text
    if isinstance(result, dict):
        name = item.get("title") or ""
        patch = result.get("structuredPatch")
        if patch:
            item["diff"] = from_patch(patch, name) or item.get("diff", "")
        elif result.get("type") == "create" and "content" in result:
            item["diff"] = unified("", str(result.get("content", "")), name)
        elif isinstance(result.get("stdout"), str) and item["kind"] == "command":
            parts = [result.get("stdout") or "", result.get("stderr") or ""]
            joined = "\n".join(p for p in parts if p.strip())
            if joined:
                item["output"] = joined[-OUTPUT_CHARS:]
    return item


def text_of(content) -> str:
    """A tool result's content (a string, or blocks with text) as text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(c.get("text", ""))
            for c in content
            if isinstance(c, dict) and c.get("type") == "text"
        )
    return ""


def counts(diff: str) -> tuple[int, int]:
    """(lines added, lines removed) in a unified diff."""
    added = removed = 0
    for line in (diff or "").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed
