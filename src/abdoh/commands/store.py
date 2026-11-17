"""Add, change and delete commands from the app. Every change is checked before it's written,
so a mistake in the app can never break commands.yaml."""

import json
from pathlib import Path

import yaml

from abdoh.commands.registry import Command, CommandsFileError, parse_commands
from abdoh.config import write_atomic

HEADER = """\
# Your commands: edit them in the Abdoh app (Commands), or here by hand.
# Each command: one or more trigger phrases, and one or more actions run in order.
# The wake word ("Abdoh" / "Hey Abdoh") is stripped before matching, so don't include it.
# A trigger can have {slots}: "search youtube for {query}" catches whatever you say there.
#
# Actions:
#   say: <text>            speak text ({time}, {date} and your {slots} are replaced)
#   open_url: <url>        open in the default browser ({slots} are URL-encoded)
#   open_app: <name/path>  open an application
#   play_youtube: <words>  play the top YouTube video for those words
#   media: <key>           play_pause, next, previous, volume_up, volume_down or mute
#   timer: <duration>      e.g. "25 minutes"; Abdoh tells you when it's done
#   volume: <0-100>        set the speakers to exactly that volume
#   app_volume: <app> <0-100>  one app in the volume mixer ("browser 30", "Spotify 0")
#   brightness: <0-100>    every screen's brightness that can be changed
#   type: <text>           type the text into the app in front ({slots} are replaced)
#   displays: <layout>     screens on and off: "all", "only 2", "1 off", "3 on"
#   audio_output: <name>   send the sound to these speakers ("headphones", "C34H89x")
#   dark_mode: on|off|toggle
#   power_mode: best_performance|balanced|efficiency
#   night_light: on|off
#   power: sleep|lock|screens_off
#   keys: <keys>           press keys: "ctrl+shift+esc", "win+d, alt+tab", "f11"
#   wait: <time>           wait before the next action (up to 60 seconds)
#   close_app: <program>   close a program's windows ("Spotify")
#   focus_app: <program>   bring a program to the front
#   window: <program> to <screen> [maximized|left|right], or minimize, maximize, ...
#   run: <shell command>   run a command (only if allow_run: true in config.yaml; no {slots})
"""

# Ready-made commands to start from (the Commands page shows them as a gallery).
TEMPLATES: list[dict] = [
    {
        "name": "Good morning",
        "description": "Says good morning with the time and date, then opens the news.",
        "triggers": ["good morning"],
        "actions": [
            {"type": "say", "value": "Good morning! It's {time} on {date}."},
            {"type": "open_url", "value": "https://news.google.com"},
        ],
    },
    {
        "name": "Focus time",
        "description": "A 25-minute focus timer with calm music.",
        "triggers": ["focus time", "start focus mode"],
        "actions": [
            {"type": "timer", "value": "25 minutes"},
            {"type": "play_youtube", "value": "lofi hip hop radio"},
        ],
    },
    {
        "name": "Take a break",
        "description": "A 5-minute break timer.",
        "triggers": ["take a break", "break time"],
        "actions": [
            {"type": "timer", "value": "5 minutes"},
            {"type": "say", "value": "Enjoy your break."},
        ],
    },
    {
        "name": "Start my work day",
        "description": "Opens your email and your calendar.",
        "triggers": ["start my work day", "start my day"],
        "actions": [
            {"type": "open_url", "value": "https://mail.google.com"},
            {"type": "open_url", "value": "https://calendar.google.com"},
        ],
    },
    {
        "name": "Google search",
        "description": "Searches Google for whatever you say.",
        "triggers": ["google {query}", "search google for {query}"],
        "actions": [{"type": "open_url", "value": "https://www.google.com/search?q={query}"}],
    },
    {
        "name": "Weather",
        "description": "Shows the weather forecast.",
        "triggers": ["what's the weather", "show me the weather"],
        "actions": [{"type": "open_url", "value": "https://www.google.com/search?q=weather"}],
    },
    {
        "name": "Directions",
        "description": "Directions to a place on Google Maps.",
        "triggers": ["directions to {place}", "take me to {place}"],
        "actions": [
            {
                "type": "open_url",
                "value": "https://www.google.com/maps/dir/?api=1&destination={place}",
            }
        ],
    },
    {
        "name": "Wikipedia",
        "description": "Looks something up on Wikipedia.",
        "triggers": ["wikipedia {topic}", "look up {topic}"],
        "actions": [
            {"type": "open_url", "value": "https://en.wikipedia.org/w/index.php?search={topic}"}
        ],
    },
    {
        "name": "WhatsApp",
        "description": "Opens WhatsApp in your browser.",
        "triggers": ["open whatsapp"],
        "actions": [{"type": "open_url", "value": "https://web.whatsapp.com"}],
    },
    {
        "name": "Play some music",
        "description": "Plays a music mix on YouTube.",
        "triggers": ["play some music", "play music"],
        "actions": [{"type": "play_youtube", "value": "chill music mix"}],
    },
]


def as_dict(command: Command) -> dict:
    """A command as the app's form data."""
    return {
        "name": command.name,
        "triggers": list(command.triggers),
        "actions": [{"type": kind, "value": value} for kind, value in command.actions],
    }


def _item(command: Command) -> dict:
    """A command as a commands.yaml item."""
    return {
        "name": command.name,
        "triggers": list(command.triggers),
        "actions": [{kind: value} for kind, value in command.actions],
    }


def _from_form(command) -> dict:
    """The app's form data -> a commands.yaml item. Raises CommandsFileError."""
    if not isinstance(command, dict):
        raise CommandsFileError("A command needs a name, trigger phrases and actions.")
    name = str(command.get("name") or "").strip()
    triggers = [str(t).strip() for t in command.get("triggers") or [] if str(t).strip()]
    actions = []
    for action in command.get("actions") or []:
        if not isinstance(action, dict):
            raise CommandsFileError("Each action needs a type and a value.")
        kind = str(action.get("type") or "").strip()
        value = "" if action.get("value") is None else str(action.get("value")).strip()
        if kind or value:  # skip rows left empty in the form
            actions.append({kind: value})
    if not name:
        raise CommandsFileError("Give the command a name.")
    if not triggers:
        raise CommandsFileError("Add at least one phrase that triggers the command.")
    if not actions:
        raise CommandsFileError("Add at least one action.")
    return {"name": name, "triggers": list(dict.fromkeys(triggers)), "actions": actions}


def dump(items: list[dict]) -> str:
    """commands.yaml text: the help header, then one block per command."""

    def q(text: str) -> str:
        return json.dumps(text, ensure_ascii=False)  # a valid YAML double-quoted string

    lines = [HEADER]
    for item in items:
        lines.append(f"- name: {q(item['name'])}")
        lines.append(f"  triggers: [{', '.join(q(t) for t in item['triggers'])}]")
        lines.append("  actions:")
        for action in item["actions"]:
            ((kind, value),) = action.items()
            lines.append(f"    - {kind}: {q(value)}")
        lines.append("")
    return "\n".join(lines)


class CommandsStore:
    """Your commands file, for the app. All methods raise CommandsFileError with a message
    that's safe to show (e.g. the file has an error you made by hand)."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _commands(self) -> list[Command]:
        if not self.path.exists():
            return []
        try:
            data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise CommandsFileError(f"Your commands file isn't valid: {e}") from e
        return parse_commands(data)

    def load(self) -> list[dict]:
        return [as_dict(c) for c in self._commands()]

    def save(self, command: dict, old_name: str | None = None) -> dict:
        """Add a command, or replace the one called `old_name`. Returns it as saved."""
        items = [_item(c) for c in self._commands()]
        item = _from_form(command)
        index = None
        if old_name is not None:
            index = next((i for i, it in enumerate(items) if it["name"] == old_name), None)
            if index is None:
                raise CommandsFileError(f"There's no command called '{old_name}'.")
        name = item["name"].lower()
        if any(it["name"].lower() == name for i, it in enumerate(items) if i != index):
            raise CommandsFileError(f"You already have a command called '{item['name']}'.")
        (saved,) = parse_commands([item])  # its own errors first, with a clear message
        if index is None:
            items.append(item)
        else:
            items[index] = item
        self._write(items)
        return as_dict(saved)

    def delete(self, name: str) -> None:
        items = [_item(c) for c in self._commands()]
        kept = [it for it in items if it["name"] != name]
        if len(kept) == len(items):
            raise CommandsFileError(f"There's no command called '{name}'.")
        self._write(kept)

    def _write(self, items: list[dict]) -> None:
        text = dump(items)
        if [_item(c) for c in parse_commands(yaml.safe_load(text))] != items:
            raise CommandsFileError("Couldn't write the commands file safely.")
        write_atomic(self.path, text)
