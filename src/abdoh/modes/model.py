"""What a mode is, and reading modes.yaml.

A mode has settings (things with a state, put back when the mode ends: which screens are on,
volume, brightness, speakers, theme, power mode, and three of Abdoh's own switches) and actions
(things that just happen, like a command's: open an app, play music, say something).
"""

import re
from dataclasses import dataclass, field

from abdoh.commands.registry import CommandsFileError, parse_actions

# In the order they are applied (screens first: the rest may depend on them).
SETTINGS = (
    "displays",
    "audio_output",
    "volume",
    "brightness",
    "dark_mode",
    "power_mode",
    "night_light",
    "wake_word",
    "voice_replies",
    "follow_up",
    "role",
)
SWITCHES = ("dark_mode", "night_light", "wake_word", "voice_replies", "follow_up")  # on or off
PERCENTS = ("volume", "brightness")
POWER_MODES = ("best_performance", "balanced", "efficiency")
ICONS = ("sparkles", "film", "briefcase", "moon", "target", "presentation", "music", "game",
         "coffee", "book", "sun", "home")  # fmt: skip
RESERVED = ("normal",)  # "back to normal" ends a mode


DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_GROUPS = {"daily": DAYS, "every day": DAYS, "weekdays": DAYS[:5], "weekends": DAYS[5:]}
_SCHEDULE = re.compile(r"(?P<days>[a-z, ]+?)\s+(?P<hour>\d{1,2}):(?P<minute>\d{2})")


def parse_schedule(text: str) -> tuple[frozenset[int], int, int]:
    """'weekdays 09:00' -> ({0, 1, 2, 3, 4}, 9, 0) (Monday is 0). Raises ValueError."""
    found = _SCHEDULE.fullmatch(" ".join(text.lower().split()))
    if not found:
        raise ValueError(f"'{text}' isn't like 'weekdays 09:00'.")
    hour, minute = int(found["hour"]), int(found["minute"])
    if hour > 23 or minute > 59:
        raise ValueError(f"'{text}' has no such time.")
    words = found["days"].strip()
    if words in DAY_GROUPS:
        days = DAY_GROUPS[words]
    else:
        days = tuple(d.strip()[:3] for d in words.split(",") if d.strip())
        if not days or any(d not in DAYS for d in days):
            raise ValueError(f"'{text}': days are daily, weekdays, weekends, or mon,tue,...")
    return frozenset(DAYS.index(d) for d in days), hour, minute


class ModesFileError(ValueError):
    """modes.yaml (or a mode from the app) isn't valid; the message is safe to show."""


@dataclass(frozen=True)
class Mode:
    name: str
    icon: str = "sparkles"
    phrases: tuple[str, ...] = ()
    settings: dict = field(default_factory=dict)  # setting -> value, in SETTINGS order
    actions: tuple[tuple[str, str], ...] = ()
    exit_actions: tuple[tuple[str, str], ...] = ()
    schedule: tuple[str, ...] = ()


def parse_modes(data) -> list[Mode]:
    """Parsed YAML -> Modes. Raises ModesFileError."""
    if data is None:
        return []
    if not isinstance(data, list):
        raise ModesFileError("The modes file must be a list of modes.")
    modes, names = [], set()
    for i, item in enumerate(data, start=1):
        mode = parse_mode(item, f"mode #{i}")
        key = mode.name.lower()
        if key in names:
            raise ModesFileError(f"There are two modes called {mode.name}.")
        names.add(key)
        modes.append(mode)
    return modes


def parse_mode(item, where: str = "the mode") -> Mode:
    if not isinstance(item, dict):
        raise ModesFileError(f"{where} must be a mapping with a name, settings and actions.")
    name = str(item.get("name") or "").strip()
    if not name:
        raise ModesFileError(f"{where} needs a name.")
    if name.lower().removesuffix(" mode") in RESERVED:
        raise ModesFileError(f"A mode can't be called {name}.")
    where = f"mode '{name}'"
    unknown = set(item) - {"name", "icon", "phrases", "settings", "actions", "exit_actions",
                           "schedule"}  # fmt: skip
    if unknown:
        raise ModesFileError(f"{where}: unknown field '{sorted(unknown)[0]}'.")
    icon = str(item.get("icon") or "sparkles")
    if icon not in ICONS:
        raise ModesFileError(f"{where}: icon must be one of {', '.join(ICONS)}.")
    phrases = _strings(item.get("phrases"), f"{where}: phrases")
    settings = _settings(item.get("settings") or {}, where)
    try:
        actions = parse_actions(where, item.get("actions") or [])
        exit_actions = parse_actions(f"{where} (when it ends)", item.get("exit_actions") or [])
    except CommandsFileError as e:
        raise ModesFileError(str(e)) from e
    schedule = _strings(item.get("schedule"), f"{where}: schedule")
    for entry in schedule:
        try:
            parse_schedule(entry)
        except ValueError as e:
            raise ModesFileError(f"{where}: schedule {e}") from e
    if not settings and not actions:
        raise ModesFileError(f"{where}: add at least one setting or action.")
    return Mode(name, icon, phrases, settings, tuple(actions), tuple(exit_actions), schedule)


def _strings(value, what: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ModesFileError(f"{what} must be a list of words.")
    return tuple(v.strip() for v in value)


def _settings(raw, where: str) -> dict:
    if not isinstance(raw, dict):
        raise ModesFileError(f"{where}: settings must be names and values.")
    unknown = set(raw) - set(SETTINGS)
    if unknown:
        raise ModesFileError(
            f"{where}: unknown setting '{sorted(unknown)[0]}' (use {', '.join(SETTINGS)})."
        )
    settings = {}
    for key in SETTINGS:
        if key not in raw or raw[key] is None:
            continue
        value = raw[key]
        if key == "displays":
            value = _displays(value, where)
        elif key in PERCENTS:
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ModesFileError(f"{where}: {key} must be a number from 0 to 100.")
            if not 0 <= value <= 100:
                raise ModesFileError(f"{where}: {key} must be a number from 0 to 100.")
            value = round(value)
        elif key in SWITCHES:
            if not isinstance(value, bool):
                raise ModesFileError(f"{where}: {key} must be true or false.")
        elif key == "power_mode":
            if value not in POWER_MODES:
                raise ModesFileError(
                    f"{where}: power_mode must be one of {', '.join(POWER_MODES)}."
                )
        elif key == "audio_output":
            if not isinstance(value, str) or not value.strip():
                raise ModesFileError(f"{where}: audio_output needs the speakers' name.")
            value = value.strip()
        elif key == "role":
            if not isinstance(value, str) or not value.strip():
                raise ModesFileError(f"{where}: role needs a role's name (Act as).")
            value = value.strip()
        settings[key] = value
    return settings


def _displays(value, where: str) -> str | list[str]:
    """'all', or the screens to keep on: [2], ["laptop", 3], "1, 3"."""
    if isinstance(value, str) and value.strip().lower() == "all":
        return "all"
    if isinstance(value, int | str) and not isinstance(value, bool):
        value = [p for p in str(value).replace(" and ", ",").split(",") if p.strip()]
    if not isinstance(value, list) or not value:
        raise ModesFileError(f"{where}: displays is 'all' or a list of screens, like [2].")
    screens = []
    for screen in value:
        if isinstance(screen, bool) or not isinstance(screen, int | str) or not str(screen).strip():
            raise ModesFileError(f"{where}: displays is 'all' or a list of screens, like [2].")
        screens.append(str(screen).strip())
    return screens


def as_form(mode: Mode) -> dict:
    """A mode as the app's form data (and as a modes.yaml item, through store.to_item)."""
    return {
        "name": mode.name,
        "icon": mode.icon,
        "phrases": list(mode.phrases),
        "settings": dict(mode.settings),
        "actions": [{"type": k, "value": v} for k, v in mode.actions],
        "exit_actions": [{"type": k, "value": v} for k, v in mode.exit_actions],
        "schedule": list(mode.schedule),
    }
