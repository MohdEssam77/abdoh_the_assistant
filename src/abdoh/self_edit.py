"""Abdoh changes its own commands, modes and roles when you ask ("make a command called good
evening that locks the screen", "add Spotify to work mode", "undo that").

Claude writes ACTION save_item / delete_item / undo_change (claude.allow_self_edit). Each item
goes through the same checks as the app's pages (the stores' save_item), plus two of its own: an
app that isn't installed is named back, and `run:` steps need allow_run. Before every change the
file's text is kept, so the last changes since Abdoh started can be undone."""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from abdoh.commands.registry import CommandsFileError
from abdoh.config import Config, write_atomic
from abdoh.modes.model import ModesFileError
from abdoh.roles.model import RolesFileError

log = logging.getLogger(__name__)

KINDS = ("command", "mode", "role")
UNDO_STEPS = 10
# Actions whose value is an installed app (checked, so a misheard name is caught when saving).
APP_ACTIONS = ("open_app",)
_INSTRUCTIONS_SHOWN = 80  # characters of a role's instructions in Claude's list of your roles


class SelfEditError(ValueError):
    """The change wasn't made; the message is one short sentence that's safe to say."""


@dataclass
class _Change:
    kind: str
    name: str
    path: Path
    before: str | None  # the file's text before the change (None: there was no file)


def _store(cfg: Config, kind: str):
    if kind == "command":
        from abdoh.commands.store import CommandsStore

        return CommandsStore(cfg.commands_path)
    if kind == "mode":
        from abdoh.modes.store import ModesStore

        return ModesStore(cfg.app_dir / "modes.yaml")
    from abdoh.roles.store import RoleStore

    return RoleStore(cfg.app_dir / "roles.yaml")


def _split(arg: str) -> tuple[str, str]:
    """ "command | {...}" -> ("command", "{...}")."""
    kind, sep, rest = str(arg).partition("|")
    kind = kind.strip().lower()
    if not sep or kind not in KINDS:
        raise SelfEditError("I can only change commands, modes and roles.")
    return kind, rest.strip()


def _what(kind: str, name: str) -> str:
    return f"{name} mode" if kind == "mode" else f"the {kind} {name}"


def _said_as(kind: str, item: dict) -> str:
    """How to say an item's name: a command "remember that" saved (learned_chat_time) by the
    phrase that starts it (chat time)."""
    name = str(item.get("name", ""))
    triggers = item.get("triggers") or []
    if kind == "command" and name.startswith("learned_") and triggers:
        return str(triggers[0])
    return name


def _phrases(kind: str, item: dict) -> list[str]:
    """What you say to start it: a command's triggers, a mode's or role's phrases."""
    return [str(p) for p in item.get("triggers" if kind == "command" else "phrases") or []]


def _steps(item: dict) -> list[tuple[str, str]]:
    """A command's or mode's actions (and a mode's exit actions) as (kind, value)."""
    steps = []
    for key in ("actions", "exit_actions"):
        for action in item.get(key) or []:
            if isinstance(action, dict):
                steps += [(str(k), str(v)) for k, v in action.items()]
    return steps


def _looks_like_a_path(value: str) -> bool:
    return any(c in value for c in ":\\/") or value.lower().endswith(".exe")


class SelfEditor:
    """`find_app(name)` finds an installed app (or None); `on_change(kind)` is told after a
    change (the commands are reloaded, the app's pages refresh)."""

    def __init__(
        self,
        cfg: Config,
        find_app: Callable[[str], object] | None = None,
        on_change: Callable[[str], None] = lambda kind: None,
    ):
        self.cfg = cfg
        self.find_app = find_app
        self.on_change = on_change
        self._undo: list[_Change] = []

    # ----- save -----

    def save(self, arg: str) -> str:
        """ACTION save_item: <kind> | <JSON>. Returns what to say. Raises SelfEditError."""
        kind, text = _split(arg)
        try:
            item = json.loads(text)
        except ValueError as e:
            raise SelfEditError("I couldn't read that change, so nothing was saved.") from e
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            raise SelfEditError(f"The {kind} needs a name, so nothing was saved.")
        store = _store(self.cfg, kind)
        old = self._existing(store, kind, item["name"])
        if old is not None:  # fields left out stay as they were; so does its name ("work")
            item = {**old, **item, "name": old["name"]}
            if kind == "role" and _cut_short(item.get("instructions"), old.get("instructions")):
                item["instructions"] = old["instructions"]  # sent back as Claude saw it
        self._check(kind, item)
        said = _said_as(kind, item)
        self.change(kind, said, store.path, lambda: store.save_item(item))
        verb = "Changed" if old is not None else "Saved"
        log.info("%s %s %r: %s", verb, kind, item["name"], json.dumps(item, ensure_ascii=False))
        return f"{verb} {_what(kind, said)}."

    def _existing(self, store, kind: str, name: str) -> dict | None:
        try:
            items = store.items()
        except (CommandsFileError, ModesFileError, RolesFileError) as e:
            raise SelfEditError(f"Your {kind}s file has an error, so I left it alone.") from e
        from abdoh.commands.matcher import normalize

        wanted = " ".join(str(name).split()).lower()
        found = next((it for it in items if str(it.get("name", "")).lower() == wanted), None)
        if found is None:  # by what you say to start it ("chat time" is learned_chat_time)
            said = normalize(str(name))
            found = next(
                (it for it in items if said in {normalize(p) for p in _phrases(kind, it)}), None
            )
        return dict(found) if found is not None else None

    def _check(self, kind: str, item: dict) -> None:
        if kind == "role":
            return
        steps = _steps(item)
        if any(k == "run" for k, _ in steps) and not self.cfg.allow_run:
            raise SelfEditError(
                "Running programs is off in your permissions, so I didn't save the run step."
            )
        if self.find_app is None:
            return
        for k, value in steps:
            if k in APP_ACTIONS and value and not _looks_like_a_path(value):
                if self.find_app(value) is None:
                    raise SelfEditError(
                        f"I can't find an app called {value}, so nothing was saved."
                    )

    # ----- delete and undo -----

    def delete(self, arg: str) -> str:
        """ACTION delete_item: <kind> | <name>. Returns what to say. Raises SelfEditError."""
        kind, name = _split(arg)
        store = _store(self.cfg, kind)
        old = self._existing(store, kind, name)
        if old is None:
            raise SelfEditError(f"There's no {kind} called {name}.")
        said = _said_as(kind, old)
        self.change(kind, said, store.path, lambda: store.delete(old["name"]))
        log.info("Deleted %s %r", kind, old["name"])
        return f"Deleted {_what(kind, said)}."

    def undo(self, arg: str = "last") -> str:
        """ACTION undo_change: last. Puts the file back as it was before the last change."""
        if not self._undo:
            raise SelfEditError("There's no change of mine to undo.")
        change = self._undo.pop()
        if change.before is None:
            change.path.unlink(missing_ok=True)
        else:
            write_atomic(change.path, change.before)
        log.info("Undid the last change to %s %r", change.kind, change.name)
        self.on_change(change.kind)
        return f"Undone: {_what(change.kind, change.name)} is back as it was."

    def change(self, kind: str, name: str, path: Path, do: Callable[[], object]) -> None:
        """Run `do` (which changes the file at `path`), keeping the text before so it can be
        undone. Also used for "remember that" (the router's save_steps)."""
        path = Path(path)
        before = path.read_text(encoding="utf-8") if path.exists() else None
        try:
            do()
        except (CommandsFileError, ModesFileError, RolesFileError) as e:
            raise SelfEditError(_one_sentence(str(e))) from e
        self._undo = [*self._undo, _Change(kind, name, path, before)][-UNDO_STEPS:]
        self.on_change(kind)


def _cut_short(sent, full) -> bool:
    """Is `sent` the shortened instructions Claude was shown (current_items), not new ones?"""
    sent, full = str(sent or ""), str(full or "")
    return sent.endswith("…") and full.startswith(sent[:-1].rstrip()) and len(full) > len(sent)


def _one_sentence(text: str) -> str:
    text = " ".join(text.split())
    return text if text.endswith((".", "!", "?")) else text + "."


# ----- for Claude: the user's items, compact -----


def _compact(item: dict) -> str:
    return json.dumps(item, ensure_ascii=False, separators=(", ", ": "))


def current_items(cfg: Config) -> str:
    """The user's commands, modes and roles as one JSON line each (a role's instructions cut
    short), so Claude can change them. Files with errors are left out."""
    lines = []
    for kind in KINDS:
        try:
            items = _store(cfg, kind).items()
        except (CommandsFileError, ModesFileError, RolesFileError):
            lines.append(f"(The {kind}s file has an error: don't change {kind}s now.)")
            continue
        for item in items:
            item = dict(item)
            instructions = str(item.get("instructions") or "")
            if kind == "role" and len(instructions) > _INSTRUCTIONS_SHOWN:
                item["instructions"] = instructions[:_INSTRUCTIONS_SHOWN].rstrip() + "…"
            lines.append(f"{kind}: {_compact(item)}")
    return "\n".join(lines) or "(none yet)"
