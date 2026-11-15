"""The app window: Abdoh's HTML page (src/abdoh/ui/web) in a native window.

pywebview shows the page with Windows' built-in WebView2 (Edge). Like the old tkinter window it
only shows events and forwards requests; AppApi (abdoh.ui.api) is the page's only way in.
"""

import logging
import sys
import threading
from pathlib import Path

from abdoh.config import Config
from abdoh.events import Bus
from abdoh.ui.api import AppApi, UiState

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent / "web"
INDEX = WEB_DIR / "index.html"
STORAGE = Path.home() / ".abdoh" / "webview"  # the page's own small storage (e.g. the theme)
POLL_SECONDS = 0.1
WEBVIEW2_CLIENT = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def _registry_value(root: str, key: str, name: str):
    import winreg

    try:
        with winreg.OpenKey(getattr(winreg, root), key) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def webview2_available(read=_registry_value) -> bool:
    """Is Microsoft's WebView2 runtime installed (it ships with Windows 11 and recent 10)?"""
    if sys.platform != "win32":
        return True  # pywebview picks the platform's own web engine
    places = [
        ("HKEY_LOCAL_MACHINE", rf"SOFTWARE\WOW6432Node\{WEBVIEW2_CLIENT}"),
        ("HKEY_LOCAL_MACHINE", rf"SOFTWARE\{WEBVIEW2_CLIENT}"),
        ("HKEY_CURRENT_USER", rf"Software\{WEBVIEW2_CLIENT}"),
    ]
    return any(read(root, key, "pv") not in (None, "", "0.0.0.0") for root, key in places)


def windows_dark_mode(read=_registry_value) -> bool:
    if sys.platform != "win32":
        return False
    key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
    return read("HKEY_CURRENT_USER", key, "AppsUseLightTheme") == 0


class WebWindow:
    def __init__(self, bus: Bus, cfg: Config, start_hidden: bool = False, tray=None):
        import webview

        self.bus = bus
        self.tray = tray  # the tray icon also shows status and voice state
        self.state = UiState()
        self._webview = webview
        self._quitting = threading.Event()
        self.restart_requested = False  # the page's Restart button
        self.api = AppApi(bus, self.state, cfg, window=self)
        self.window = webview.create_window(
            "Abdoh",
            url=str(INDEX),
            js_api=self.api,
            width=1100,
            height=740,
            min_size=(760, 540),
            hidden=start_hidden,
            text_select=True,
            background_color="#0f1115" if windows_dark_mode() else "#f4f5f7",
        )
        self.window.events.closing += self._on_closing

    def _on_closing(self):
        """Closing the window only hides it; Abdoh keeps running in the tray."""
        if self._quitting.is_set():
            return True
        self.hide()
        return False

    def show(self) -> None:
        self.window.show()
        self.window.restore()

    def hide(self) -> None:
        self.window.hide()

    def pick_folder(self) -> str | None:
        """A folder chosen in Windows' folder picker, or None."""
        dialogs = getattr(self._webview, "FileDialog", None)
        kind = dialogs.FOLDER if dialogs else self._webview.FOLDER_DIALOG
        chosen = self.window.create_file_dialog(kind)
        return str(chosen[0]) if chosen else None

    def route(self, kind: str, value) -> None:
        """One event from the daemon: to the tray, the window, or the page."""
        if kind == "status" and self.tray:
            self.tray.show_status(value)
        elif kind == "voice" and self.tray:
            self.tray.show_voice(bool(value))
        if kind == "show":
            self.show()
        elif kind == "quit":
            self._quitting.set()
            self.window.destroy()
        else:
            self.state.feed(kind, value)

    def _pump(self) -> None:
        while not self._quitting.is_set():
            for kind, value in self.bus.pending_events():
                try:
                    self.route(kind, value)
                except Exception:
                    log.exception("Couldn't show event %r", kind)
            self._quitting.wait(POLL_SECONDS)

    def mainloop(self) -> None:
        STORAGE.mkdir(parents=True, exist_ok=True)
        gui = "edgechromium" if sys.platform == "win32" else None
        self._webview.start(self._pump, gui=gui, private_mode=False, storage_path=str(STORAGE))
        self._quitting.set()
