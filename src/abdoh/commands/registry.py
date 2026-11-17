"""Load, validate and hot-reload commands.yaml."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

ACTION_TYPES = (
    "say",
    "open_url",
    "open_app",
    "play_youtube",
    "media",
    "timer",
    "volume",
    "brightness",
    "app_volume",
    "displays",
    "audio_output",
    "dark_mode",
    "power_mode",
    "power",
    "keys",
    "wait",
    "close_app",
    "focus_app",
    "window",
    "mode",
    "type",
    "run",
)
PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
BUILTIN_PLACEHOLDERS = {"time", "date"}


class CommandsFileError(ValueError):
    pass


@dataclass(frozen=True)
class Command:
    name: str
    triggers: list[str]
    actions: list[tuple[str, str]]  # (action type, argument)


def parse_commands(data) -> list[Command]:
    """Validate parsed YAML and turn it into Commands. Raises CommandsFileError."""
    if data is None:
        return []
    if not isinstance(data, list):
        raise CommandsFileError("The file must be a list of commands.")
    commands = []
    for i, item in enumerate(data, start=1):
        where = f"command #{i}"
        if not isinstance(item, dict):
            raise CommandsFileError(f"{where} must be a mapping with name, triggers, actions.")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise CommandsFileError(f"{where} needs a 'name'.")
        where = f"command '{name}'"
        triggers = item.get("triggers")
        if (
            not isinstance(triggers, list)
            or not triggers
            or not all(isinstance(t, str) and t.strip() for t in triggers)
        ):
            raise CommandsFileError(f"{where}: 'triggers' must be a non-empty list of phrases.")
        actions_raw = item.get("actions")
        if not isinstance(actions_raw, list) or not actions_raw:
            raise CommandsFileError(f"{where}: 'actions' must be a non-empty list.")
        actions = parse_actions(where, actions_raw, triggers)
        commands.append(Command(name.strip(), [t.strip() for t in triggers], actions))
    return commands


def parse_actions(where: str, raw, triggers=()) -> list[tuple[str, str]]:
    """A list of `- kind: value` items -> [(kind, value)], each checked (modes use this too).
    Raises CommandsFileError."""
    actions = []
    for action in raw:
        if not isinstance(action, dict) or len(action) != 1:
            raise CommandsFileError(f"{where}: each action must have exactly one key.")
        ((kind, arg),) = action.items()
        if kind not in ACTION_TYPES:
            raise CommandsFileError(
                f"{where}: unknown action '{kind}' (use one of {', '.join(ACTION_TYPES)})."
            )
        if isinstance(arg, bool):  # YAML reads `dark_mode: on` as true
            arg = "on" if arg else "off"
        if not isinstance(arg, str | int | float) or not str(arg).strip():
            raise CommandsFileError(f"{where}: action '{kind}' needs a text value.")
        actions.append((kind, str(arg)))
    if not triggers:  # a mode's actions: nothing fills {slots}
        for kind, arg in actions:
            if set(PLACEHOLDER.findall(arg)) - BUILTIN_PLACEHOLDERS:
                raise CommandsFileError(f"{where}: '{kind}' can't use {{slots}} here.")
    _check_slots(where, list(triggers), actions)
    return actions


def trigger_slots(trigger: str) -> list[str]:
    """'search youtube for {query}' -> ['query']."""
    return PLACEHOLDER.findall(trigger)


def _check_slots(where: str, triggers: list[str], actions: list[tuple[str, str]]) -> None:
    from abdoh.computer import MEDIA_KEYS, parse_duration  # here, to avoid an import cycle

    slot_sets = []
    for trigger in triggers:
        slots = trigger_slots(trigger)
        bad = [s for s in slots if not s.isidentifier()]
        if bad:
            raise CommandsFileError(f"{where}: slot names must be single words, not {{{bad[0]}}}.")
        if len(set(slots)) != len(slots):
            raise CommandsFileError(f"{where}: a trigger can't use the same slot twice.")
        slot_sets.append(set(slots))
    for kind, arg in actions:
        used = set(PLACEHOLDER.findall(arg)) - BUILTIN_PLACEHOLDERS
        if kind == "run" and used & set().union(*slot_sets):
            raise CommandsFileError(f"{where}: 'run' actions can't use slots (that's unsafe).")
        for slots in slot_sets:
            missing = (used & set().union(*slot_sets)) - slots
            if missing:
                name = sorted(missing)[0]
                raise CommandsFileError(f"{where}: every trigger needs {{{name}}}.")
        if kind == "media" and arg.strip().lower() not in MEDIA_KEYS:
            raise CommandsFileError(
                f"{where}: media must be one of {', '.join(MEDIA_KEYS)} (not '{arg}')."
            )
        if kind == "timer" and parse_duration(arg) is None:
            raise CommandsFileError(f"{where}: timer needs a duration like '5 minutes'.")
        if kind in ("volume", "brightness") and not _is_percent(arg):
            raise CommandsFileError(f"{where}: {kind} needs a number from 0 to 100.")
        problem = _system_problem(kind, arg)
        if problem:
            raise CommandsFileError(f"{where}: {problem}")
        if kind in ("keys", "close_app") and PLACEHOLDER.search(arg):
            raise CommandsFileError(f"{where}: '{kind}' actions can't use slots (that's unsafe).")
        if kind == "mode" and not arg.strip():
            raise CommandsFileError(f"{where}: mode needs a mode's name, or normal.")
        if kind == "app_volume":
            app, _, level = arg.replace("|", " ").strip().rpartition(" ")
            if not app.strip() or not _is_percent(level):
                raise CommandsFileError(
                    f"{where}: app_volume needs an app and a number, like 'browser 30'."
                )


_DISPLAYS = re.compile(r"all(?: on)?|only .+|.+ (?:on|off)", re.IGNORECASE)


def _system_problem(kind: str, arg: str) -> str | None:
    """What's wrong with a system action's value (only its form: the screens, speakers and
    programs it names may not be there right now)."""
    from abdoh.commands.actions import (
        ON_WORDS,
        WINDOW_WORDS,
        ActionError,
        parse_window,
        wait_seconds,
    )

    value = arg.strip().lower()
    if kind == "displays" and not _DISPLAYS.fullmatch(value):
        return "displays is like 'all', 'only 2', '1 off' or '3 on'."
    if kind == "dark_mode" and value not in (*ON_WORDS, "toggle"):
        return "dark_mode is on, off or toggle."
    if kind == "power_mode" and value not in ("best_performance", "balanced", "efficiency"):
        return "power_mode is best_performance, balanced or efficiency."
    if kind == "power" and value not in ("sleep", "lock", "screens_off"):
        return "power is sleep, lock or screens_off."
    if kind in ("audio_output", "close_app", "focus_app") and not value:
        return f"{kind} needs a name."
    if kind == "keys":
        from abdoh.system import parse_keys

        try:
            parse_keys(value)
        except ValueError as e:
            return f"keys: {e}"
    try:
        if kind == "wait":
            wait_seconds(value)
        if kind == "window" and value not in WINDOW_WORDS:
            parse_window(value)
    except ActionError as e:
        return str(e)
    return None


def _is_percent(arg: str) -> bool:
    text = arg.strip().rstrip("%").strip()
    return text.isdigit() and 0 <= int(text) <= 100


class CommandRegistry:
    """Holds the last valid commands; reloads when the file's mtime changes."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.commands: list[Command] = []
        self.error: str | None = None
        self._mtime: float | None = None
        self.refresh()

    def refresh(self, force: bool = False) -> str | None:
        """Reload if the file changed. Returns an error message if this reload failed."""
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            if self._mtime is not None or force:
                log.warning("Commands file not found: %s", self.path)
            self._mtime = None
            self.commands = []
            return None
        if not force and mtime == self._mtime:
            return None
        self._mtime = mtime
        try:
            data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
            self.commands = parse_commands(data)
        except (yaml.YAMLError, CommandsFileError) as e:
            self.error = str(e)
            log.error("Commands file has an error (keeping last valid version): %s", e)
            return self.error
        self.error = None
        log.info("Loaded %d commands from %s", len(self.commands), self.path)
        return None
