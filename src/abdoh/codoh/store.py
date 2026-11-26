"""Codoh's folders and chats, kept in <app_dir>/codoh/.

folders.json: the project folders opened lately, newest first. index.json: a short line for
each chat (for the chats list). chats/<id>.json: a whole chat: what the page shows (items),
which engine and model, Claude Code's session id, or the ChatGPT items to send again.
"""

import json
import logging
import time
import uuid
from pathlib import Path

from abdoh.config import write_atomic

log = logging.getLogger(__name__)

FOLDER = "codoh"
MAX_FOLDERS = 20
# What the chats list needs of each chat (the rest stays in its own file).
SUMMARY = ("id", "title", "folder", "engine", "model", "mode", "effort", "created", "updated")


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, ValueError):
        log.warning("Codoh: couldn't read %s", path, exc_info=True)
        return default


def _write(path: Path, data) -> None:
    write_atomic(path, json.dumps(data, ensure_ascii=False, indent=1))


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class CodohStore:
    def __init__(self, root: Path, clock=time.time):
        self.root = Path(root)
        self._clock = clock

    # ----- folders -----

    def folders(self) -> list[dict]:
        found = _read(self.root / "folders.json", [])
        return [f for f in found if isinstance(f, dict) and f.get("path")]

    def add_folder(self, path: Path) -> dict:
        path = Path(path)
        entry = {"path": str(path), "name": path.name or str(path), "opened": self._clock()}
        rest = [f for f in self.folders() if Path(f["path"]) != path]
        _write(self.root / "folders.json", [entry, *rest][:MAX_FOLDERS])
        return entry

    def forget_folder(self, path: str) -> None:
        rest = [f for f in self.folders() if Path(f["path"]) != Path(path)]
        _write(self.root / "folders.json", rest)

    # ----- chats -----

    def _chat_path(self, chat_id: str) -> Path:
        safe = "".join(c for c in str(chat_id) if c.isalnum() or c in "-_")
        return self.root / "chats" / f"{safe}.json"

    def chats(self) -> list[dict]:
        """Every chat's summary, the latest first."""
        index = _read(self.root / "index.json", {})
        found = [c for c in index.values() if isinstance(c, dict) and c.get("id")]
        return sorted(found, key=lambda c: c.get("updated", 0), reverse=True)

    def load(self, chat_id: str) -> dict | None:
        data = _read(self._chat_path(chat_id), None)
        return data if isinstance(data, dict) and data.get("id") == chat_id else None

    def save(self, chat: dict) -> None:
        chat["updated"] = chat.get("updated") or self._clock()
        _write(self._chat_path(chat["id"]), chat)
        index = _read(self.root / "index.json", {})
        index[chat["id"]] = {key: chat.get(key) for key in SUMMARY}
        _write(self.root / "index.json", index)

    def delete(self, chat_id: str) -> None:
        self._chat_path(chat_id).unlink(missing_ok=True)
        index = _read(self.root / "index.json", {})
        if index.pop(chat_id, None) is not None:
            _write(self.root / "index.json", index)
