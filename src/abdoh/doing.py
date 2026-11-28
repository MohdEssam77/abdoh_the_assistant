"""What Abdoh is doing, in a few words: Claude's tools and Abdoh's own actions.

The phone shows these as a live list while Abdoh works on its request (ABDOH_EPIC_11.md, 2.2):
"Searching the web: weather in Berlin", "Reading CV.pdf", "Opened Spotify".
"""

import re
from pathlib import PurePath
from urllib.parse import urlparse

LONG = 70  # a step's details are cut to about this many characters


def _cut(text: str, size: int = LONG) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= size else text[: size - 1].rstrip() + "…"


def _name(path: str) -> str:
    """A file's name, as the user knows it ("CV.pdf"), from a full path."""
    path = str(path or "").strip().strip('"')
    return PurePath(path.replace("\\", "/")).name or path


def _site(url: str) -> str:
    host = urlparse(str(url or "")).netloc or str(url or "")
    return host[4:] if host.startswith("www.") else host


def tool_step(tool: str, data: dict | None) -> str:
    """Claude started using a tool: "Searching the web: <query>", "Reading CV.pdf"."""
    data = data if isinstance(data, dict) else {}
    if tool in ("WebSearch", "web_search"):
        query = data.get("query") or ""
        return f"Searching the web: {_cut(query)}" if query else "Searching the web"
    if tool == "WebFetch":
        return f"Reading {_site(data.get('url', ''))}" if data.get("url") else "Reading a web page"
    if tool == "Read":
        return f"Reading {_cut(_name(data.get('file_path', '')))}".strip()
    if tool == "Glob":
        pattern = _name(data.get("pattern", "")) or data.get("pattern", "")
        return f"Looking for {_cut(pattern)}" if pattern else "Looking through your files"
    if tool == "Grep":
        pattern = data.get("pattern", "")
        return f"Searching files for “{_cut(pattern, 40)}”" if pattern else "Searching your files"
    if tool in ("PowerShell", "Bash"):
        command = data.get("description") or data.get("command") or ""
        return f"Running: {_cut(command)}" if command else "Running a command"
    if tool == "Write":
        return f"Writing {_cut(_name(data.get('file_path', '')))}".strip()
    if tool in ("Edit", "MultiEdit"):
        return f"Changing {_cut(_name(data.get('file_path', '')))}".strip()
    if tool in ("Task", "Agent"):
        return (
            f"Working on: {_cut(data.get('description', ''))}"
            if data.get("description")
            else ("Working on a part")
        )
    if tool == "TodoWrite":
        return "Planning the steps"
    if tool.startswith("mcp__"):  # a claude.ai connector: mcp__claude_ai_Gmail__search
        parts = [p for p in tool.split("__")[1:] if p]
        app = parts[0].replace("claude_ai_", "").replace("_", " ") if parts else "a connector"
        what = parts[1].replace("_", " ") if len(parts) > 1 else "working"
        return f"{app}: {what}"
    words = re.sub(r"(?<!^)(?=[A-Z])", " ", tool).replace("_", " ").strip().lower()
    return f"Using {words}" if words else "Working on it"


# Abdoh's actions (claude/reply.py ACTION_HELP and the router's own), as done.
ACTIONS = {
    "open_app": "Opened {arg}",
    "play_youtube": "Playing on YouTube: {arg}",
    "media": "Music: {media}",
    "timer": "Timer set: {arg}",
    "volume": "Volume: {arg}%",
    "brightness": "Brightness: {arg}%",
    "app_volume": "Volume of {arg}",
    "remind": "Reminder: {arg}",
    "note": "Note added: {arg}",
    "mode": "Mode: {arg}",
    "displays": "Screens: {arg}",
    "audio_output": "Sound to: {arg}",
    "dark_mode": "Dark theme: {arg}",
    "lamp": "Lamp: {arg}",
    "window": "Window: {arg}",
    "power": "Computer: {arg}",
    "codoh": "Codoh: {arg}",
    "role": "Role: {arg}",
    "board_pdf": "Saving the board as a PDF",
    "remember": "Remembered: {arg}",
    "lesson": "Learned: {arg}",
    "forget": "Forgot: {arg}",
    "save_item": "Saved: {arg}",
    "delete_item": "Deleted: {arg}",
    "undo_change": "Undid: {arg}",
    "save_steps": "Saved as a command: {arg}",
    "watch": "Watching your screen: {arg}",
    "listen": "Listening without the wake word: {arg}",
    "send_file": "Sent you {name}",
    "show_screen": "Showed you the screen",
}
MEDIA = {"play_pause": "play or pause", "next": "next", "previous": "previous",
         "volume_up": "louder", "volume_down": "quieter", "mute": "mute"}  # fmt: skip


def action_step(kind: str, arg: str) -> str:
    """One of Abdoh's actions, done: "Opened Spotify", "Lamp: desk | warm white"."""
    arg = " ".join(str(arg or "").split())
    if kind == "open_url":
        return f"Opened {_cut(_site(arg) or arg)}"
    if kind == "setting":
        from abdoh.self_settings import describe_arg

        return _cut(describe_arg(arg), 90)
    if kind == "codoh":
        from abdoh.codoh.voice import done_words

        parts = [p.strip() for p in arg.split("|")]
        verb = parts[0].lower()
        if verb in ("new", "create") and len(parts) > 1:
            told = f": {parts[2]}" if len(parts) > 2 and parts[2] else ""
            return _cut(f"New Codoh chat in {_name(parts[1])}{told}", 90)
        if verb in ("send", "answer") and len(parts) > 1:
            return _cut(f"Told Codoh: {parts[1]}", 90)
        said = done_words(arg)
        return _cut(said[:1].upper() + said[1:], 90)
    form = ACTIONS.get(kind)
    if form is None:
        return _cut(f"{kind.replace('_', ' ').capitalize()}: {arg}" if arg else kind)
    return _cut(form.format(arg=arg, media=MEDIA.get(arg, arg), name=_name(arg)), 90)
