"""What the app page can ask Abdoh for, and what it shows.

AppApi's public methods are called from JavaScript (window.pywebview.api.<name>). pywebview also
exposes public attributes, so everything else is kept in _underscore names. Methods return plain
data (dicts, lists, strings) and never raise to the page for expected problems.
"""

import logging
import sys
import threading
import webbrowser
from collections import deque
from collections.abc import Callable

from abdoh import __version__
from abdoh.commands.registry import CommandsFileError
from abdoh.commands.store import TEMPLATES, CommandsStore
from abdoh.config import Config, load_config
from abdoh.events import Bus
from abdoh.settings import settings_view

log = logging.getLogger(__name__)


class UiState:
    """What the page shows, kept in Python: a page that (re)loads late still shows it all."""

    HISTORY = 200

    def __init__(self):
        self._lock = threading.Lock()
        self._pending: list[tuple[str, object]] = []
        self._status = "Starting..."
        self._claude = ""
        self._wake = ""
        self._voice = True
        self._history: deque[str] = deque(maxlen=self.HISTORY)

    def feed(self, kind: str, value) -> None:
        """An event from the daemon (or the app): remember it and queue it for the page."""
        with self._lock:
            if kind == "status":
                self._status = value
            elif kind == "claude":
                self._claude = value
            elif kind == "wake":
                self._wake = value
            elif kind == "voice":
                self._voice = bool(value)
            elif kind == "history":
                self._history.append(value)
            self._pending.append((kind, value))

    def drain(self) -> list[tuple[str, object]]:
        with self._lock:
            pending, self._pending = self._pending, []
            return pending

    def snapshot(self) -> dict:
        """Everything so far. Queued events are dropped: the snapshot already has them."""
        with self._lock:
            self._pending.clear()
            return {
                "status": self._status,
                "claude": self._claude,
                "wake": self._wake,
                "voice": self._voice,
                "history": list(self._history),
            }


class AppApi:
    def __init__(
        self,
        bus: Bus,
        state: UiState,
        cfg: Config,
        window=None,
        open_url: Callable[[str], object] = webbrowser.open,
    ):
        self._bus = bus
        self._state = state
        self._cfg = cfg
        self._window = window  # WebWindow, for hide()
        self._open_url = open_url

    def _config(self) -> Config:
        """The settings as saved now (the file may have changed since Abdoh started)."""
        return load_config(self._cfg.app_dir)

    # ----- starting up and staying up to date -----

    def boot(self) -> dict:
        """Everything the page needs to draw itself."""
        return {
            "version": __version__,
            "platform": sys.platform,
            "settings": settings_view(self._config()),
            "state": self._state.snapshot(),
        }

    def events(self) -> list:
        """What happened since the last call, as [kind, value] pairs."""
        return [[kind, value] for kind, value in self._state.drain()]

    # ----- talking to Abdoh -----

    def send(self, text) -> bool:
        """A typed request."""
        text = str(text or "").strip()
        if not text:
            return False
        self._bus.request("text", text)
        return True

    def talk(self) -> None:
        """Listen for one request now (like the hotkey)."""
        self._bus.request("listen")

    def stop_speaking(self) -> None:
        self._bus.request("stop_speaking")

    def set_paused(self, paused) -> None:
        """Stop or start listening for the wake word."""
        self._bus.request("pause" if paused else "resume")

    def set_voice(self, on) -> None:
        self._bus.request("voice", bool(on))

    # ----- your commands -----

    def _store(self) -> CommandsStore:
        return CommandsStore(self._cfg.commands_path)

    def commands(self) -> dict:
        """Your commands and the templates. If the file has an error, says what it is."""
        try:
            items = self._store().load()
        except CommandsFileError as e:
            return {"ok": False, "error": str(e), "commands": [], "templates": TEMPLATES}
        return {"ok": True, "commands": items, "templates": TEMPLATES}

    def save_command(self, command, old_name=None) -> dict:
        """Add a command, or change the one called old_name."""
        try:
            saved = self._store().save(command, old_name or None)
        except CommandsFileError as e:
            return {"ok": False, "error": str(e)}
        self._bus.request("commands_changed")
        return {"ok": True, "command": saved}

    def delete_command(self, name) -> dict:
        try:
            self._store().delete(str(name))
        except CommandsFileError as e:
            return {"ok": False, "error": str(e)}
        self._bus.request("commands_changed")
        return {"ok": True}

    def open_commands_file(self) -> None:
        """Open commands.yaml in a text editor (e.g. to fix an error made by hand)."""
        self._bus.request("edit_commands")

    # ----- the window -----

    def hide(self) -> None:
        if self._window is not None:
            self._window.hide()

    def quit(self) -> None:
        self._bus.request("quit")

    def open_link(self, url) -> bool:
        """Open a web link in the browser (only http and https)."""
        url = str(url or "")
        if not url.lower().startswith(("https://", "http://")):
            return False
        self._open_url(url)
        return True
