import re
import threading
from pathlib import Path

import pytest

from abdoh import __version__
from abdoh.config import load_config
from abdoh.events import Bus
from abdoh.ui.api import AppApi, UiState
from abdoh.ui.app import INDEX, WEB_DIR, WebWindow, webview2_available, windows_dark_mode

JS_FILES = sorted(WEB_DIR.glob("*.js"))


@pytest.fixture
def bus():
    return Bus()


@pytest.fixture
def api(app_dir, bus):
    opened = []
    api = AppApi(bus, UiState(), load_config(app_dir), open_url=opened.append)
    api.opened = opened  # for the tests only
    return api


def requests(bus):
    out = []
    while (message := bus.next_request(timeout=0)) is not None:
        out.append(message)
    return out


# ----- UiState -----


def test_state_remembers_and_queues_events():
    state = UiState()
    state.feed("status", "Listening")
    state.feed("history", "You: hi")
    assert state.drain() == [("status", "Listening"), ("history", "You: hi")]
    assert state.drain() == []
    snap = state.snapshot()
    assert snap["status"] == "Listening"
    assert snap["history"] == ["You: hi"]
    assert snap["voice"] is True


def test_snapshot_replaces_queued_events():
    state = UiState()
    state.feed("claude", "Pro subscription (Claude Code)")
    assert state.snapshot()["claude"] == "Pro subscription (Claude Code)"
    assert state.drain() == []  # already in the snapshot: not sent twice


def test_history_is_bounded():
    state = UiState()
    for i in range(UiState.HISTORY + 20):
        state.feed("history", f"Abdoh: {i}")
    history = state.snapshot()["history"]
    assert len(history) == UiState.HISTORY
    assert history[-1] == f"Abdoh: {UiState.HISTORY + 19}"


# ----- AppApi -----


def test_boot_has_version_settings_and_state(api, app_dir):
    (app_dir / ".env").write_text("ANTHROPIC_API_KEY=sk-secret\n")
    boot = api.boot()
    assert boot["version"] == __version__
    assert boot["settings"]["hotkey"] == "ctrl+alt+space"
    assert boot["settings"]["has_api_key"] is True
    assert "sk-secret" not in str(boot)
    assert boot["state"]["status"] == "Starting..."


def test_first_start_setup_shows_until_done(api):
    assert api.boot()["settings"]["setup_done"] is False  # a new install shows the setup
    assert api.save_settings({"setup_done": True})["ok"] is True
    assert api.boot()["settings"]["setup_done"] is True


def test_events_are_pairs(api):
    api._state.feed("status", "Speaking")
    assert api.events() == [["status", "Speaking"]]


def test_send_forwards_typed_text(api, bus):
    assert api.send("  what time is it  ") is True
    assert api.send("   ") is False
    assert api.send(None) is False
    assert requests(bus) == [("text", "what time is it")]


def test_buttons_become_requests(api, bus):
    api.talk()
    api.stop_speaking()
    api.set_paused(True)
    api.set_paused(False)
    api.set_voice(0)
    api.quit()
    assert requests(bus) == [
        ("listen", None),
        ("stop_speaking", None),
        ("pause", None),
        ("resume", None),
        ("voice", False),
        ("quit", None),
    ]


def test_only_web_links_open(api):
    assert api.open_link("https://claude.com") is True
    assert api.open_link("file:///C:/Windows/System32/cmd.exe") is False
    assert api.open_link("javascript:alert(1)") is False
    assert api.opened == ["https://claude.com"]


def test_hide_asks_the_window(api):
    hidden = []
    api._window = type("W", (), {"hide": lambda self: hidden.append(True)})()
    api.hide()
    assert hidden == [True]


def test_nothing_private_is_exposed_to_the_page(api):
    public = [n for n in vars(api) if not n.startswith("_") and n != "opened"]
    assert public == []  # pywebview exposes public attributes to JavaScript


# ----- commands -----


def news(name="Open news"):
    return {
        "name": name,
        "triggers": ["open the news"],
        "actions": [{"type": "open_url", "value": "https://news.google.com"}],
    }


def test_commands_and_templates(api):
    result = api.commands()
    assert result["ok"] is True
    assert "good_morning" in [c["name"] for c in result["commands"]]
    assert result["templates"] and all("description" in t for t in result["templates"])


def test_a_broken_commands_file_is_explained(api, app_dir):
    (app_dir / "commands.yaml").write_text("- name: [oops\n")
    result = api.commands()
    assert result["ok"] is False and "isn't valid" in result["error"]
    assert result["commands"] == [] and result["templates"]


def test_save_command_tells_the_daemon(api, bus):
    result = api.save_command(news())
    assert result == {"ok": True, "command": news()}
    assert requests(bus) == [("commands_changed", None)]
    assert news() in api.commands()["commands"]


def test_save_command_error_is_returned_not_raised(api, bus):
    result = api.save_command({**news(), "triggers": []})
    assert result["ok"] is False and "phrase" in result["error"]
    assert requests(bus) == []


def test_rename_and_delete_a_command(api, bus):
    api.save_command(news())
    assert api.save_command(news("News"), "Open news")["ok"] is True
    names = [c["name"] for c in api.commands()["commands"]]
    assert "News" in names and "Open news" not in names
    assert api.delete_command("News") == {"ok": True}
    assert api.delete_command("News")["ok"] is False
    assert requests(bus) == [("commands_changed", None)] * 3


def test_open_commands_file_asks_the_daemon(api, bus):
    api.open_commands_file()
    assert requests(bus) == [("edit_commands", None)]


# ----- settings -----


def test_save_settings_tells_the_daemon(api, bus):
    result = api.save_settings({"tts_rate": 210, "claude": {"allow_screen": False}})
    assert result["ok"] is True
    assert result["settings"]["tts_rate"] == 210
    assert result["settings"]["claude"]["allow_screen"] is False
    assert result["restart"] == []
    assert requests(bus) == [("settings_changed", None)]
    assert api.settings()["settings"]["tts_rate"] == 210


def test_bad_settings_are_explained_not_saved(api, bus):
    result = api.save_settings({"tts_rate": "fast"})
    assert result == {"ok": False, "error": "Voice speed must be a number."}
    assert requests(bus) == []


def test_restart_list_compares_with_what_abdoh_started_with(api):
    assert api.save_settings({"hotkey": "ctrl+shift+a"})["restart"] == ["hotkey"]
    # A later, unrelated change still reports the pending restart...
    assert api.save_settings({"tts_rate": 190})["restart"] == ["hotkey"]
    assert api.boot()["restart"] == ["hotkey"]
    # ...until the setting is back to what Abdoh is running with.
    assert api.save_settings({"hotkey": "ctrl+alt+space"})["restart"] == []


def test_microphones_voices_and_level(app_dir, bus):
    api = AppApi(
        bus,
        UiState(),
        load_config(app_dir),
        list_mics=lambda: [{"name": "USB Mic", "default": True}],
        list_voices=lambda: ["Zira"],
    )
    assert api.microphones() == {"devices": [{"name": "USB Mic", "default": True}], "current": ""}
    assert api.voices() == {"voices": ["Zira"], "current": ""}
    assert api.mic_level() is None  # the daemon isn't running yet
    api._attach(type("D", (), {"mic_level": lambda self: 4321})())
    assert api.mic_level() == 4321


def test_a_microphone_saved_cut_short_is_shown_by_its_full_name(app_dir, bus):
    cfg = load_config(app_dir)
    cfg.mic_device = "Microphone Array (Realtek(R) Au"  # what 0.8 saved
    mics = [
        {"name": "Headset (WH-1000XM4)", "default": True},
        {"name": "Microphone Array (Realtek(R) Audio)", "default": False},
    ]
    api = AppApi(bus, UiState(), cfg, list_mics=lambda: mics)
    api._config = lambda: cfg
    shown = api.microphones()
    assert shown["current"] == "Microphone Array (Realtek(R) Audio)"
    assert "using" not in shown


def test_a_chosen_microphone_that_isnt_connected_says_what_abdoh_uses(app_dir, bus):
    cfg = load_config(app_dir)
    cfg.mic_device = "Microphone (Lenovo FHD Webcam Audio)"
    mics = [{"name": "Headset (WH-1000XM4)", "default": True}]
    api = AppApi(bus, UiState(), cfg, list_mics=lambda: mics)
    api._config = lambda: cfg
    shown = api.microphones()
    assert shown["current"] == "Microphone (Lenovo FHD Webcam Audio)"  # the setting stays
    assert shown["using"] == "Headset (WH-1000XM4)"


def test_microphones_when_listing_fails(app_dir, bus):
    def broken():
        raise OSError("PortAudio not found")

    api = AppApi(bus, UiState(), load_config(app_dir), list_mics=broken)
    assert api.microphones()["devices"] == []


class FakeEndpoint:
    name = "Microphone Array"

    def __init__(self):
        self.level, self.mute = 28, True

    def volume(self):
        return self.level

    def set_volume(self, percent):
        self.level = percent

    def muted(self):
        return self.mute

    def set_muted(self, muted):
        self.mute = muted


def test_a_quiet_microphone_is_shown_and_fixed(app_dir, bus):
    endpoint, asked = FakeEndpoint(), []

    class Audio:
        def microphone(self, name):
            asked.append(name)
            return endpoint

    api = AppApi(bus, UiState(), load_config(app_dir), audio=Audio())
    assert api.mic_volume() == {"ok": True, "name": "Microphone Array", "volume": 28, "muted": True}
    api.save_settings({"mic_device": "USB Mic"})
    assert api.fix_mic_volume() == {
        "ok": True,
        "name": "Microphone Array",
        "volume": 90,
        "muted": False,
    }
    assert asked[-1] == "USB Mic"  # the microphone Abdoh listens with


def test_microphone_volume_when_windows_cant_tell(app_dir, bus):
    class Audio:
        def microphone(self, name):
            raise RuntimeError("no Core Audio here")

    api = AppApi(bus, UiState(), load_config(app_dir), audio=Audio())
    assert api.mic_volume() == {"ok": False}
    assert api.fix_mic_volume()["ok"] is False


def test_test_voice_asks_the_daemon(api, bus):
    api.test_voice()
    assert requests(bus) == [("say_sample", None)]


class FakeAutostart:
    def __init__(self, installed=False, fail=False):
        self.installed = installed
        self.fail = fail

    def is_installed(self):
        return self.installed

    def install(self):
        if self.fail:
            raise PermissionError("denied")
        self.installed = True
        return "Installed."

    def uninstall(self):
        self.installed = False
        return "Removed."


def test_start_at_sign_in(app_dir, bus):
    autostart = FakeAutostart()
    api = AppApi(bus, UiState(), load_config(app_dir), autostart=autostart)
    assert api.login_item() == {"ok": True, "on": False}
    assert api.set_login_item(True) == {"ok": True, "on": True, "message": "Installed."}
    assert api.login_item()["on"] is True
    assert api.set_login_item(False)["message"] == "Removed."
    failing = AppApi(bus, UiState(), load_config(app_dir), autostart=FakeAutostart(fail=True))
    result = failing.set_login_item(True)
    assert result["ok"] is False and "denied" in result["error"]


def test_open_folders_and_sound_settings(app_dir, bus):
    opened = []
    api = AppApi(bus, UiState(), load_config(app_dir), open_path=opened.append)
    assert api.open_folder("data") is True
    assert api.open_folder("logs") is True
    assert api.open_folder("C:/Windows") is False
    api.open_sound_settings()
    assert opened[0] == app_dir
    assert opened[1].name == ".abdoh"
    assert opened[2] == "ms-settings:sound"


def test_restart_and_folder_picking_use_the_window(api, bus):
    class Win:
        restart_requested = False

        def pick_folder(self):
            return "C:/Users/me/Music"

    api._window = Win()
    assert api.pick_folder() == "C:/Users/me/Music"
    api.restart()
    assert api._window.restart_requested is True
    assert requests(bus) == [("quit", None)]


# ----- the window -----


class FakeWebviewWindow:
    def __init__(self):
        self.calls = []

    def show(self):
        self.calls.append("show")

    def restore(self):
        self.calls.append("restore")

    def hide(self):
        self.calls.append("hide")

    def destroy(self):
        self.calls.append("destroy")


class FakeTray:
    def __init__(self):
        self.status = None
        self.voice = None

    def show_status(self, status):
        self.status = status

    def show_voice(self, on):
        self.voice = on


def window_without_gui(bus):
    win = WebWindow.__new__(WebWindow)  # no pywebview needed
    win.bus, win.tray, win.state = bus, FakeTray(), UiState()
    win.window = FakeWebviewWindow()
    win._quitting = threading.Event()
    return win


def test_route_sends_events_to_tray_window_and_page(bus):
    win = window_without_gui(bus)
    win.route("status", "Thinking...")
    win.route("voice", False)
    win.route("history", "Abdoh: hi")
    assert win.tray.status == "Thinking..."
    assert win.tray.voice is False
    assert [k for k, _ in win.state.drain()] == ["status", "voice", "history"]
    win.route("show", None)
    assert win.window.calls == ["show", "restore"]


def test_the_page_gets_the_status_even_if_the_tray_fails(bus):
    win = window_without_gui(bus)

    def broken(status):
        raise ValueError("string too long (185, maximum length 128)")

    win.tray.show_status = broken
    win.route("status", "Error: the speech recognition model couldn't be loaded")
    assert win.state.drain() == [
        ("status", "Error: the speech recognition model couldn't be loaded")
    ]


def test_closing_hides_unless_quitting(bus):
    win = window_without_gui(bus)
    assert win._on_closing() is False
    assert win.window.calls == ["hide"]
    win.route("quit", None)
    assert win.window.calls[-1] == "destroy"
    assert win._on_closing() is True


def test_webview2_detection():
    found = {("HKEY_CURRENT_USER", "pv"): "157.0.1.2"}

    def read(root, key, name):
        return found.get((root, name))

    if __import__("sys").platform == "win32":
        assert webview2_available(read) is True
        assert webview2_available(lambda *a: None) is False
        assert windows_dark_mode(lambda *a: 0) is True
        assert windows_dark_mode(lambda *a: 1) is False
    else:
        assert webview2_available(read) is True


# ----- the page and the Python side agree -----


def called_api_methods() -> set[str]:
    names = set()
    for path in JS_FILES:
        text = path.read_text(encoding="utf-8")
        names |= set(re.findall(r'call\((?:[^"()]*\?\s*)?"(\w+)"', text))
        names |= set(re.findall(r'call\([^"()]*\?\s*"\w+"\s*:\s*"(\w+)"', text))
        names |= set(re.findall(r"App\.api\.(\w+)\(", text))
        names |= set(re.findall(r'\bact\([^,()]+,\s*"(\w+)"', text))  # claude.js's helper
    return names


def test_every_method_the_page_calls_exists():
    called = called_api_methods()
    assert {"boot", "events", "send", "talk", "stop_speaking"} <= called
    missing = sorted(n for n in called if not callable(getattr(AppApi, n, None)))
    assert missing == []


def test_the_demo_has_every_method_the_page_calls():
    demo = (WEB_DIR / "bridge.js").read_text(encoding="utf-8")
    has = set(re.findall(r"\b(\w+): async", demo))
    assert sorted(called_api_methods() - has) == []


def test_every_file_the_page_loads_exists():
    html = INDEX.read_text(encoding="utf-8")
    for ref in re.findall(r'(?:src|href)="([^":#?]+)"', html):
        assert (WEB_DIR / ref).is_file(), ref
    assert Path(WEB_DIR / "app.css").is_file()


# ----- only today's conversation -----


def test_a_new_day_starts_with_an_empty_conversation():
    from datetime import date

    day = {"today": date(2026, 11, 17)}
    state = UiState(today=lambda: day["today"])
    state.feed("history", "You: what time is it")
    state.feed("history", "Abdoh: It's 11 PM.")
    state.drain()
    day["today"] = date(2026, 11, 18)  # midnight passed with the window open
    assert state.drain() == [("clear", None)]  # the page empties the chat
    assert state.snapshot()["history"] == []
    state.feed("history", "You: good morning")
    assert state.snapshot()["history"] == ["You: good morning"]
    assert state.drain() == []  # cleared once, not again


def test_a_page_opened_on_a_new_day_shows_nothing_old():
    from datetime import date

    day = {"today": date(2026, 11, 17)}
    state = UiState(today=lambda: day["today"])
    state.feed("history", "You: something from yesterday")
    day["today"] = date(2026, 11, 18)
    assert state.snapshot()["history"] == []


def test_the_page_can_clear_the_chat():
    script = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert "clear: clearHistory" in script


# ----- modes and screens -----


@pytest.fixture
def modes_api(app_dir, bus):
    from test_displays import FakeBackend

    from abdoh.displays import Displays

    class Audio:
        @staticmethod
        def outputs():
            from abdoh.winaudio import Output

            return [Output("a", "Speakers (Realtek(R) Audio)", True)]

    state = UiState()
    displays = Displays(app_dir / "displays.json", FakeBackend())
    return AppApi(bus, state, load_config(app_dir), audio=Audio(), displays=displays), state


def test_modes_for_the_page(modes_api):
    api, state = modes_api
    result = api.modes()
    assert result["ok"] and result["modes"] == [] and result["templates"]
    assert [d["number"] for d in result["displays"]] == [1, 2, 3]
    assert result["outputs"] == ["Speakers"] and "film" in result["icons"]
    saved = api.save_mode({"name": "Movie", "settings": {"displays": ["2"]}})
    assert saved["ok"] and saved["mode"]["settings"] == {"displays": ["2"]}
    assert [m["name"] for m in api.modes()["modes"]] == ["Movie"]
    assert api.save_mode({"name": "Bad", "settings": {"volume": 400}})["ok"] is False
    state.feed("mode", "Movie")
    assert api.modes()["current"] == "Movie"
    assert api.delete_mode("Movie") == {"ok": True}
    assert api.modes()["modes"] == []


def test_switching_goes_through_abdoh(modes_api, bus):
    api, _ = modes_api
    api.activate_mode("Movie")
    api.end_mode()
    assert requests(bus) == [("mode", "Movie"), ("mode", "")]


def test_naming_and_numbering_screens(modes_api):
    api, _ = modes_api
    ids = [d["id"] for d in api.displays()["displays"]]
    shown = api.rename_display(ids[1], "TV")["displays"]
    assert shown[1]["nickname"] == "TV" and shown[1]["label"] == "TV"
    shown = api.reorder_displays([ids[2], ids[0], ids[1]])["displays"]
    assert [d["id"] for d in shown] == [ids[2], ids[0], ids[1]]


def test_identify_shows_numbers_on_the_screens(modes_api):
    api, _ = modes_api
    shown = []
    api._window = type("W", (), {"identify": lambda self, displays: shown.append(displays)})()
    api.identify_displays()
    assert [d["number"] for d in shown[0]] == [1, 2, 3]


def test_the_voice_check_says_abdoh_is_still_starting(api):
    api._daemon = None
    assert api.voice_check()["starting"] is True


def test_the_demo_shows_this_version():
    from abdoh import __version__

    demo = (WEB_DIR / "bridge.js").read_text(encoding="utf-8")
    assert f'version: "{__version__}", platform' in demo  # the download page's screenshots
