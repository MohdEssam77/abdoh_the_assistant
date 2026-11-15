"""Tray icon wiring with a fake pystray (no real tray, no autostart changes)."""

import sys
import threading
import types

import pytest

from abdoh.events import Bus
from abdoh.ui.tray import BLUE, GRAY, GREEN, RED, icon_image, status_color


class FakeMenuItem:
    def __init__(self, text, action, checked=None, default=False):
        self.text, self.action, self.checked, self.default = text, action, checked, default

    def label(self):
        return self.text(self) if callable(self.text) else self.text


class FakeMenu:
    SEPARATOR = object()

    def __init__(self, *items):
        self.items = [i for i in items if i is not FakeMenu.SEPARATOR]


class FakeIcon:
    def __init__(self, name, icon, title, menu):
        self.icon, self.title, self.menu = icon, title, menu
        self.menu_updates = 0
        self.stopped = False

    def run(self):
        pass

    def stop(self):
        self.stopped = True

    def update_menu(self):
        self.menu_updates += 1


class FakeAutostart:
    def __init__(self, installed=False):
        self.installed = installed
        self.changed = threading.Event()

    def is_installed(self):
        return self.installed

    def install(self):
        self.installed = True
        self.changed.set()
        return "Installed."

    def uninstall(self):
        self.installed = False
        self.changed.set()
        return "Removed."


@pytest.fixture
def tray(monkeypatch):
    fake = types.SimpleNamespace(Icon=FakeIcon, Menu=FakeMenu, MenuItem=FakeMenuItem)
    monkeypatch.setitem(sys.modules, "pystray", fake)
    from abdoh.ui.tray import Tray

    bus = Bus()
    return Tray(bus, autostart=FakeAutostart())


def item(tray, label):
    return next(i for i in tray.icon.menu.items if i.label().startswith(label))


def test_status_colors():
    assert status_color("Listening") == GREEN
    assert status_color("Listening to you...") == GREEN
    assert status_color("Paused") == GRAY
    assert status_color("Thinking...") == BLUE
    assert status_color("Error: microphone not available") == RED


def test_icon_image():
    img = icon_image(GREEN)
    assert img.size == (64, 64) and img.mode == "RGBA"
    assert img.getpixel((32, 6))[:3] == GREEN  # the colored dot
    assert img.getpixel((0, 0))[3] == 0  # transparent corner


def test_menu_items_send_requests(tray):
    item(tray, "Show window").action()
    item(tray, "Stop speaking").action()
    item(tray, "Commands").action()
    item(tray, "Quit").action()
    assert tray.bus.pending_events() == [("show", None), ("show", None), ("page", "commands")]
    requests = []
    while (m := tray.bus.next_request(0)) is not None:
        requests.append(m)
    assert requests == [("stop_speaking", None), ("quit", None)]


def test_pause_and_voice_follow_the_daemon(tray):
    pause = item(tray, "Pause listening")
    pause.action()
    assert tray.bus.next_request(0) == ("pause", None)
    tray.show_status("Paused")
    assert pause.label() == "Resume listening"
    assert tray.icon.title == "Abdoh: Paused"
    pause.action()
    assert tray.bus.next_request(0) == ("resume", None)

    voice = item(tray, "Voice replies")
    assert voice.checked(voice) is True
    voice.action()
    assert tray.bus.next_request(0) == ("voice", False)
    tray.show_voice(False)
    assert voice.checked(voice) is False


def test_status_changes_the_icon(tray):
    tray.show_status("Thinking...")
    assert tray.icon.icon.getpixel((32, 6))[:3] == BLUE


def test_start_at_login_toggle(tray):
    login = item(tray, "Start at login")
    assert login.checked(login) is False
    login.action()
    assert tray._autostart.changed.wait(2)
    for _ in range(100):
        if tray.starts_at_login:
            break
        threading.Event().wait(0.01)
    assert login.checked(login) is True
    assert ("history", "Abdoh: Installed.") in tray.bus.pending_events()


def test_stop(tray):
    tray.stop()
    assert tray.icon.stopped
