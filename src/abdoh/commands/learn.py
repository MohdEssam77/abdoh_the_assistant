"""Save what Claude just did as a command in commands.yaml ("remember that").

The new command is appended to the end of the file as text, so your comments and formatting are
left alone. The combined file is validated first; nothing is written if it wouldn't load.
"""

import json
import re
from datetime import date
from pathlib import Path

import yaml

from abdoh.commands.registry import parse_commands

# A file holding no commands written as an empty list: the new one replaces it.
_EMPTY_LIST = re.compile(r"^\[\s*\]\s*(?:#.*)?$", re.M)


def command_name(trigger: str, taken: set[str]) -> str:
    """A new command is named by the phrase that starts it: 'chat time' (or 'chat time 2' if
    that name is taken). Commands saved before 0.12 are named 'learned_chat_time'."""
    phrase = " ".join(trigger.split())[:40].strip() or "command"
    used = {t.casefold() for t in taken}
    name, n = phrase, 2
    while name.casefold() in used:
        name, n = f"{phrase} {n}", n + 1
    return name


def command_text(name: str, trigger: str, actions: list[tuple[str, str]], said: str) -> str:
    lines = [
        f"# Learned on {date.today():%Y-%m-%d} from: {said}",
        f"- name: {json.dumps(name)}",
        f"  triggers: [{json.dumps(trigger)}]",
        "  actions:",
    ]
    lines += [f"    - {kind}: {json.dumps(arg)}" for kind, arg in actions]
    return "\n".join(lines) + "\n"


def append_command(
    path: Path, trigger: str, actions: list[tuple[str, str]], said: str, taken: set[str]
) -> str:
    """Append a command to the commands file and return its name. Raises ValueError if the
    file wouldn't be valid afterwards (it is then left untouched)."""
    path = Path(path)
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    current = _EMPTY_LIST.sub("", current)
    name = command_name(trigger, taken)
    if current and not current.endswith("\n"):
        current += "\n"
    blank_line = "\n" if current.strip() else ""
    text = command_text(name, trigger, actions, said.replace("\n", " "))
    updated = current + blank_line + text
    parse_commands(yaml.safe_load(updated))  # raises if the result wouldn't load
    path.write_text(updated, encoding="utf-8")
    return name
