"""Load, validate and hot-reload commands.yaml."""

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

ACTION_TYPES = ("say", "open_url", "open_app", "run")


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
        actions = []
        for action in actions_raw:
            if not isinstance(action, dict) or len(action) != 1:
                raise CommandsFileError(f"{where}: each action must have exactly one key.")
            ((kind, arg),) = action.items()
            if kind not in ACTION_TYPES:
                raise CommandsFileError(
                    f"{where}: unknown action '{kind}' (use one of {', '.join(ACTION_TYPES)})."
                )
            if not isinstance(arg, str | int | float) or not str(arg).strip():
                raise CommandsFileError(f"{where}: action '{kind}' needs a text value.")
            actions.append((kind, str(arg)))
        commands.append(Command(name.strip(), [t.strip() for t in triggers], actions))
    return commands


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
