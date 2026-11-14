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


def command_name(trigger: str, taken: set[str]) -> str:
    """'open the python website' -> 'learned_open_the_python_website' (unique)."""
    slug = re.sub(r"[^a-z0-9]+", "_", trigger.lower()).strip("_")[:40] or "command"
    name, n = f"learned_{slug}", 2
    while name in taken:
        name, n = f"learned_{slug}_{n}", n + 1
    return name


def command_text(name: str, trigger: str, actions: list[tuple[str, str]], said: str) -> str:
    lines = [
        f"# Learned on {date.today():%Y-%m-%d} from: {said}",
        f"- name: {name}",
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
    name = command_name(trigger, taken)
    if current and not current.endswith("\n"):
        current += "\n"
    blank_line = "\n" if current.strip() else ""
    text = command_text(name, trigger, actions, said.replace("\n", " "))
    updated = current + blank_line + text
    parse_commands(yaml.safe_load(updated))  # raises if the result wouldn't load
    path.write_text(updated, encoding="utf-8")
    return name
