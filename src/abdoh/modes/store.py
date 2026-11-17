"""modes.yaml: read it, and add, change or delete modes from the app. Every change is checked
before it's written, so a mistake in the app can never break the file."""

from pathlib import Path

import yaml

from abdoh.config import write_atomic
from abdoh.modes.model import Mode, ModesFileError, as_form, parse_mode, parse_modes

HEADER = """\
# Your modes: make them in the Abdoh app (Modes), or here by hand.
# Say "<name> mode" to switch one on, and "back to normal" to undo what it changed.
#
# - name: Movie
#   icon: film                  # sparkles, film, briefcase, moon, target, presentation, music,
#                               # game, coffee, book, sun or home
#   phrases: ["movie night"]    # more ways to switch it on ("<name> mode" always works)
#   settings:                   # each is put back when the mode ends
#     displays: [2]             # these screens on, the others off ("all" for every screen)
#     brightness: 70            # 0-100, every screen that can
#     volume: 60                # 0-100
#     audio_output: "C34H89x"   # speakers, by name
#     dark_mode: true
#     power_mode: balanced      # best_performance, balanced or efficiency
#     wake_word: false          # false: Abdoh doesn't listen for its name in this mode
#     voice_replies: true
#     follow_up: false          # keep listening after a reply
#   actions:                    # run in order when the mode starts (the same as commands)
#     - say: "Enjoy the movie."
#   exit_actions:               # run when the mode ends
#     - media: play_pause
"""

# Ready-made modes to start from. They never set screens: those differ on every computer.
TEMPLATES: list[dict] = [
    {
        "name": "Movie",
        "icon": "film",
        "description": "Quieter, dark theme. Add which screens to keep on.",
        "settings": {"volume": 60, "dark_mode": True},
        "actions": [{"type": "say", "value": "Enjoy the movie."}],
    },
    {
        "name": "Work",
        "icon": "briefcase",
        "description": "Full speed, every screen on, your work app open.",
        "settings": {"displays": "all", "power_mode": "best_performance", "brightness": 100},
        "actions": [{"type": "open_app", "value": "Visual Studio Code"}],
    },
    {
        "name": "Night",
        "icon": "moon",
        "description": "Dim screens, low volume, dark theme.",
        "settings": {"brightness": 30, "volume": 30, "dark_mode": True},
        "actions": [],
    },
    {
        "name": "Focus",
        "icon": "target",
        "description": "A 25-minute timer, and Abdoh stops listening for more after replies.",
        "settings": {"follow_up": False},
        "actions": [
            {"type": "timer", "value": "25 minutes"},
            {"type": "say", "value": "Focus time. I'll tell you when it's up."},
        ],
    },
    {
        "name": "Presentation",
        "icon": "presentation",
        "description": "Light theme, full brightness, and Abdoh stays quiet.",
        "settings": {"dark_mode": False, "brightness": 100, "voice_replies": False},
        "actions": [],
    },
]


def to_item(form) -> dict:
    """The app's form data -> a modes.yaml item. Raises ModesFileError."""
    if not isinstance(form, dict):
        raise ModesFileError("A mode needs a name and some settings or actions.")
    item: dict = {"name": str(form.get("name") or "").strip()}
    if form.get("icon"):
        item["icon"] = str(form["icon"])
    phrases = [str(p).strip() for p in form.get("phrases") or [] if str(p).strip()]
    if phrases:
        item["phrases"] = list(dict.fromkeys(phrases))
    settings = {k: v for k, v in (form.get("settings") or {}).items() if v is not None}
    if settings:
        item["settings"] = settings
    for key in ("actions", "exit_actions"):
        rows = []
        for action in form.get(key) or []:
            if not isinstance(action, dict):
                raise ModesFileError("Each action needs a type and a value.")
            kind = str(action.get("type") or "").strip()
            value = "" if action.get("value") is None else str(action.get("value")).strip()
            if kind or value:
                rows.append({kind: value})
        if rows:
            item[key] = rows
    schedule = [str(s).strip() for s in form.get("schedule") or [] if str(s).strip()]
    if schedule:
        item["schedule"] = schedule
    parse_mode(item)  # raises ModesFileError with a readable message
    return item


def dump(items: list[dict]) -> str:
    body = yaml.safe_dump(items, sort_keys=False, allow_unicode=True, default_flow_style=None)
    return HEADER + "\n" + (body if items else "[]\n")


class ModesStore:
    """Your modes file. All methods raise ModesFileError with a message that's safe to show."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _items(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise ModesFileError(f"Your modes file isn't valid: {e}") from e
        parse_modes(data)
        return data or []

    def load(self) -> list[Mode]:
        if not self.path.exists():
            return []
        try:
            data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise ModesFileError(f"Your modes file isn't valid: {e}") from e
        return parse_modes(data)

    def forms(self) -> list[dict]:
        return [as_form(mode) for mode in self.load()]

    def save(self, form, old_name: str | None = None) -> Mode:
        """Add a mode, or replace the one called `old_name`. Returns the saved mode."""
        item = to_item(form)
        items = self._items()
        old = (old_name or item["name"]).lower()
        index = next((i for i, it in enumerate(items) if it["name"].lower() == old), None)
        clash = next(
            (i for i, it in enumerate(items) if it["name"].lower() == item["name"].lower()), None
        )
        if clash is not None and clash != index:
            raise ModesFileError(f"You already have a mode called {items[clash]['name']}.")
        if index is None:
            items.append(item)
        else:
            items[index] = item
        self._write(items)
        return parse_mode(item)

    def delete(self, name: str) -> None:
        items = [it for it in self._items() if it["name"].lower() != name.lower()]
        self._write(items)

    def _write(self, items: list[dict]) -> None:
        text = dump(items)
        parse_modes(yaml.safe_load(text))  # what's written must read back
        write_atomic(self.path, text)
