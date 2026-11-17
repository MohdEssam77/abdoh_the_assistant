"""The system tray icon: Abdoh's status at a glance and a small menu.

Like the window, it only shows state and forwards requests on the bus; no logic here. pystray
runs its own loop on a background thread (fine on Windows).
"""

import logging
import threading

from PIL import Image, ImageDraw

from abdoh.events import Bus

log = logging.getLogger(__name__)

GREEN, GRAY, BLUE, RED = (46, 160, 67), (128, 128, 128), (40, 110, 220), (210, 50, 50)
TITLE_MAX = 127  # Windows' limit for a tray icon's tooltip (128 with the terminating zero)


def status_color(status: str) -> tuple[int, int, int]:
    if status.startswith("Error"):
        return RED
    if status in ("Listening", "Listening to you..."):
        return GREEN
    if status in ("Thinking...", "Speaking"):
        return BLUE
    return GRAY  # paused, starting


def icon_image(color: tuple[int, int, int], size: int = 64) -> Image.Image:
    """A colored dot with a white ring: readable at 16 px."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((2, 2, size - 3, size - 3), fill=color + (255,))
    ring = size // 4
    draw.ellipse(
        (ring, ring, size - ring - 1, size - ring - 1), outline=(255, 255, 255, 255), width=5
    )
    return img


class Tray:
    def __init__(self, bus: Bus, autostart=None, list_modes=None):
        import pystray

        if autostart is None:
            from abdoh import autostart
        self.bus = bus
        self._autostart = autostart
        self.status = "Starting..."
        self.paused = False
        self.voice_on = True
        self.starts_at_login = False
        self.mode = ""  # the mode that is on
        self._list_modes = list_modes or (lambda: [])
        self._item = pystray.MenuItem
        item, menu = pystray.MenuItem, pystray.Menu
        self.icon = pystray.Icon(
            "abdoh",
            icon_image(status_color(self.status)),
            "Abdoh",
            menu(
                item("Show window", lambda: bus.emit("show"), default=True),
                item(lambda i: "Resume listening" if self.paused else "Pause listening",
                     self.toggle_pause),
                item("Stop speaking", lambda: bus.request("stop_speaking")),
                item("Voice replies", self.toggle_voice, checked=lambda i: self.voice_on),
                item("Modes", menu(self.mode_items)),
                item("Commands", self.open_commands),
                item("Start at login", self.toggle_login, checked=lambda i: self.starts_at_login),
                menu.SEPARATOR,
                item("Quit Abdoh", lambda: bus.request("quit")),
            ),
        )  # fmt: skip

    def start(self) -> None:
        threading.Thread(target=self.icon.run, name="abdoh-tray", daemon=True).start()
        threading.Thread(target=self._check_login, name="abdoh-autostart", daemon=True).start()

    def stop(self) -> None:
        self.icon.stop()

    # ----- menu actions (send requests) -----

    def mode_items(self) -> list:
        """The Modes submenu: each of your modes (a check on the one that's on), and back to
        normal. Built each time the menu opens, so it follows modes.yaml."""
        try:
            names = list(self._list_modes())
        except Exception:
            log.debug("Couldn't list the modes", exc_info=True)
            names = []
        item = self._item
        items = [
            item(name, self._mode_action(name), checked=self._mode_checked(name)) for name in names
        ]
        if not items:
            items.append(item("No modes yet: make one in the window", self.open_modes))
        items.append(item("Back to normal", lambda: self.bus.request("mode", ""),
                          enabled=lambda i: bool(self.mode)))  # fmt: skip
        return items

    def _mode_action(self, name: str):
        return lambda: self.bus.request("mode", name)

    def _mode_checked(self, name: str):
        return lambda i: self.mode.lower() == name.lower()

    def open_modes(self) -> None:
        self.bus.emit("show")
        self.bus.emit("page", "modes")

    def open_commands(self) -> None:
        """Show the window's Commands page (the simple window opens the file instead)."""
        self.bus.emit("show")
        self.bus.emit("page", "commands")

    def toggle_pause(self) -> None:
        self.bus.request("resume" if self.paused else "pause")

    def toggle_voice(self) -> None:
        self.bus.request("voice", not self.voice_on)

    def toggle_login(self) -> None:
        wanted = not self.starts_at_login
        threading.Thread(target=self._set_login, args=(wanted,), daemon=True).start()

    def _set_login(self, wanted: bool) -> None:
        try:
            message = self._autostart.install() if wanted else self._autostart.uninstall()
            self.starts_at_login = wanted
            self.bus.emit("history", f"Abdoh: {message}")
        except Exception as e:
            log.exception("Couldn't change start at login")
            self.bus.emit("history", f"Abdoh: Couldn't change start at login: {e}")
        self.icon.update_menu()

    def _check_login(self) -> None:
        try:
            self.starts_at_login = self._autostart.is_installed()
            self.icon.update_menu()
        except Exception:
            log.debug("Couldn't check start at login", exc_info=True)

    # ----- events from the daemon (forwarded by the window) -----

    def show_status(self, status: str) -> None:
        self.status = status
        if status in ("Listening", "Paused"):
            self.paused = status == "Paused"
        self.icon.icon = icon_image(status_color(status))
        self._title()

    def show_mode(self, name: str) -> None:
        self.mode = name or ""
        self._title()
        self.icon.update_menu()

    def _title(self) -> None:
        title = f"Abdoh: {self.status}" + (f" ({self.mode} mode)" if self.mode else "")
        self.icon.title = title if len(title) <= TITLE_MAX else title[: TITLE_MAX - 1] + "…"

    def show_voice(self, on: bool) -> None:
        self.voice_on = on
        self.icon.update_menu()
