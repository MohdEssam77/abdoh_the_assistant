"""Controlling the computer by voice, and the system actions (fakes; nothing on this PC changes)."""

import time

import pytest
import yaml
from test_displays import FakeBackend

from abdoh.commands.actions import (
    ActionError,
    parse_window,
    run_action,
    wait_seconds,
)
from abdoh.commands.registry import CommandsFileError, parse_commands
from abdoh.computer import display_at, find_output, short_output_name
from abdoh.displays import Displays
from abdoh.local_skills import LocalSkills
from abdoh.system import matches_window, newest_file, parse_keys
from abdoh.system_skills import NO_POWER, Question
from abdoh.winaudio import Output

SPEAKERS = Output("spk", "Speakers (Realtek(R) Audio)", True)
MONITOR = Output("mon", "C34H89x (NVIDIA High Definition Audio)", False)
HEADSET = Output("hs", "Headphones (WH-1000XM4)", False)


class FakeComputer:
    """Records what Xanthos did; the screens are the owner's three, faked."""

    def __init__(self, tmp_path):
        self.done = []
        self.displays = Displays(tmp_path / "displays.json", FakeBackend())
        self.outputs = [SPEAKERS, MONITOR]
        self.open = {"chrome", "spotify"}
        self.clip = "copied text"
        self.waiting_shutdown = False
        # what LocalSkills itself needs
        self.apps = type("Apps", (), {"find": staticmethod(lambda name: None)})()

    def screens(self, layout):
        self.done.append(("screens", layout))
        return self.displays.apply(layout)

    def screens_status(self):
        return self.displays.describe()

    def screen_in_front(self):
        return self.displays.all()[1]  # the HP 32f

    def power(self, what):
        self.done.append(("power", what))

    def audio_outputs(self):
        return self.outputs

    def set_audio_output(self, spoken):
        chosen = find_output(spoken, self.outputs)
        if chosen is None:
            raise ActionError("I can't tell which speakers you mean.")
        self.done.append(("output", chosen.id))
        return short_output_name(chosen.name)

    def set_dark_mode(self, on):
        self.done.append(("dark", on))

    def dark_mode(self):
        return True

    def set_power_mode(self, mode):
        self.done.append(("power_mode", mode))

    def shutdown(self, seconds, restart=False):
        self.done.append(("restart" if restart else "shutdown", seconds))
        self.waiting_shutdown = True

    def cancel_shutdown(self):
        waiting, self.waiting_shutdown = self.waiting_shutdown, False
        return waiting

    def is_open(self, app):
        return app in self.open

    def close_app(self, app):
        self.done.append(("close", app))

    def focus_app(self, app):
        self.done.append(("focus", app))

    def move_window(self, app, screen, how="maximized"):
        self.done.append(("move", app, screen, how))
        digits = "".join(c for c in screen if c.isdigit())
        return f"screen {digits or 2}"

    def open_folder(self, name):
        self.done.append(("folder", name))

    def open_newest(self, name):
        self.done.append(("newest", name))
        return "report.pdf"

    def clipboard(self):
        return self.clip

    def set_clipboard(self, text):
        self.clip = text

    def press_keys(self, keys):
        self.done.append(("keys", keys))

    def window(self, action):
        self.done.append(("window", action))


@pytest.fixture
def abdoh(tmp_path):
    computer = FakeComputer(tmp_path)
    said = ["The capital is Tokyo."]
    power = {"allowed": True}
    skills = LocalSkills(
        computer, last_reply=lambda: said[-1], allow_power=lambda: power["allowed"]
    )

    def say(text):
        return skills.handle(text, text)

    say.computer, say.power = computer, power
    return say


# ----- screens -----


@pytest.mark.parametrize(
    "request_, layout",
    [
        ("turn off monitor 3", "3 off"),
        ("turn off the laptop screen", "laptop off"),
        ("turn monitor 1 off", "1 off"),
        ("turn on screen 2", "2 on"),
        ("turn off the second monitor", "second off"),
        ("only screen 2", "only 2"),
        ("use only the laptop screen", "only laptop"),
        ("just the hp monitor", "only hp"),
        ("turn on all the monitors", "all"),
        ("all screens on", "all"),
        ("turn off the other screens", "only 2"),  # the window in front is on screen 2
    ],
)
def test_screens_by_voice(abdoh, request_, layout):
    abdoh(request_)
    assert abdoh.computer.done[-1] == ("screens", layout)


def test_screen_replies(abdoh):
    assert abdoh("turn off monitor 3") == "Screens 1 and 2 are on."
    assert abdoh("which screens are on") == "Screens 1 and 2 are on."
    assert abdoh("only screen 2") == "Only screen 2, HP 32f, is on."


def test_turning_off_the_screens_just_lets_them_sleep(abdoh):
    assert abdoh("turn off the screens") == ""
    assert abdoh.computer.done == [("power", "screens_off")]


def test_screens_that_dont_exist_are_left_to_claude(abdoh):
    assert abdoh("turn off the moon monitor") is None
    assert abdoh("turn off the lights") is None


# ----- speakers, theme, power mode -----


def test_switching_speakers(abdoh):
    assert abdoh("switch the sound to the monitor") == "Sound is coming out of C34H89x."
    assert abdoh("play the sound through the speakers") == "Sound is coming out of Speakers."
    assert abdoh("whats my audio output") == "The sound comes out of Speakers."
    assert abdoh("use the headphones") == "I can't tell which speakers you mean."
    abdoh.computer.outputs.append(HEADSET)
    assert abdoh("use the headphones") == "Sound is coming out of Headphones."


def test_dark_mode_and_power_mode(abdoh):
    assert abdoh("dark mode") == "Dark mode."
    assert abdoh("switch to light mode") == "Light mode."
    assert abdoh("turn off dark mode") == "Light mode."
    assert abdoh("best performance mode") == "Power mode: best performance."
    assert abdoh("battery saver") == "Power mode: best power efficiency."
    assert abdoh("switch to balanced power mode") == "Power mode: balanced."
    done = abdoh.computer.done
    assert [d for d in done if d[0] == "dark"] == [("dark", True), ("dark", False), ("dark", False)]


# ----- sleep and shutdown -----


def test_shutting_down_asks_first(abdoh):
    asked = abdoh("shut down the computer")
    assert asked == "Shut down the computer?" and isinstance(asked, Question)
    assert abdoh.computer.done == []
    assert abdoh("yes") == "Shutting down in 20 seconds. Say cancel the shutdown to stop it."
    assert abdoh.computer.done == [("shutdown", 20)]
    assert abdoh("cancel the shutdown") == "Okay, the shutdown is cancelled."
    assert abdoh("cancel the shutdown") == "No shutdown was waiting."


def test_no_means_no(abdoh):
    abdoh("restart the computer")
    assert abdoh("no") == "Okay, I won't."
    assert abdoh("yes") is None  # nothing is waiting any more
    assert abdoh.computer.done == []


def test_asking_something_else_forgets_the_question(abdoh):
    abdoh("go to sleep")
    abdoh("dark mode")
    assert abdoh("yes") is None
    assert ("power", "sleep") not in abdoh.computer.done


def test_a_question_runs_out(abdoh, monkeypatch):
    abdoh("go to sleep")
    real = time.time
    monkeypatch.setattr("time.time", lambda: real() + 120)
    assert abdoh("yes") is None


def test_a_shutdown_later_needs_no_yes(abdoh):
    assert abdoh("shut down in 30 minutes") == (
        "Shutting down in 30 minutes. Say cancel the shutdown to stop it."
    )
    assert abdoh.computer.done == [("shutdown", 1800)]


def test_power_can_be_turned_off(abdoh):
    abdoh.power["allowed"] = False
    assert abdoh("shut down the computer") == NO_POWER
    assert abdoh("go to sleep") == NO_POWER


def test_sleep_after_yes(abdoh):
    abdoh("put the computer to sleep")
    assert abdoh("go ahead") == ""
    assert abdoh.computer.done == [("power", "sleep")]


# ----- windows, folders, clipboard -----


def test_programs_and_windows(abdoh):
    assert abdoh("close spotify") == ""
    assert abdoh("switch to chrome") == ""
    assert abdoh("move chrome to screen 3") == "On screen 3."
    assert abdoh("move this to the other screen") == "On screen 2."
    assert abdoh("snap this window to the left") == ""
    assert abdoh.computer.done == [
        ("close", "spotify"),
        ("focus", "chrome"),
        ("move", "chrome", "screen 3", "maximized"),
        ("move", None, "other screen", "maximized"),
        ("move", None, "current", "left"),
    ]


def test_programs_that_arent_open_are_left_alone(abdoh):
    assert abdoh("close the door") is None
    assert abdoh("switch to plan b") is None


def test_folders(abdoh):
    assert abdoh("open my downloads folder") == ""
    assert abdoh("open my latest download") == "Opening report.pdf."
    assert abdoh("open the newest screenshot") == "Opening report.pdf."
    assert abdoh.computer.done == [
        ("folder", "downloads"), ("newest", "downloads"), ("newest", "screenshots")
    ]  # fmt: skip


def test_clipboard(abdoh):
    assert abdoh("read my clipboard") == "Your clipboard says: copied text"
    assert abdoh("copy that") == "Copied."
    assert abdoh.computer.clip == "The capital is Tokyo."
    abdoh.computer.clip = "word " * 200
    long = abdoh("what did i copy")
    assert long.endswith(", and more.") and len(long) < 360


# ----- the parsers -----


def test_key_combinations():
    assert parse_keys("ctrl+shift+esc") == [([0x11, 0x10], 0x1B)]
    assert parse_keys("win+d, alt+tab") == [([0x5B], ord("D")), ([0x12], 0x09)]
    assert parse_keys("f11") == [([], 0x7A)]
    assert parse_keys("win") == [([], 0x5B)]
    assert parse_keys("win+shift+s") == [([0x5B, 0x10], ord("S"))]
    for bad in ("", "hyper+x", "ctrl+banana"):
        with pytest.raises(ValueError):
            parse_keys(bad)


def test_window_names():
    assert matches_window("vscode", "Code", "main.py - abdoh - Visual Studio Code")
    assert matches_window("chrome", "chrome", "Inbox")
    assert matches_window("browser", "brave", "YouTube")
    assert matches_window("inbox", "chrome", "Inbox (3) - Gmail")
    assert not matches_window("it", "chrome", "Inbox")
    assert not matches_window("door", "chrome", "Inbox")


def test_speaker_names():
    outputs = [SPEAKERS, MONITOR, HEADSET]
    assert find_output("headphones", outputs) is HEADSET
    assert find_output("the speakers", outputs) is SPEAKERS
    assert find_output("the monitor", outputs) is MONITOR
    assert find_output("c34h89x", outputs) is MONITOR
    assert find_output("the fridge", outputs) is None
    assert short_output_name(SPEAKERS.name) == "Speakers"


def test_the_screen_a_window_is_on(tmp_path):
    displays = Displays(tmp_path / "d.json", FakeBackend()).all()
    assert display_at((-1800, 100, 800, 600), displays).number == 2
    assert display_at((100, 100, 800, 600), displays).number == 3
    assert display_at((-5000, 100, 800, 600), displays).number == 1  # off the left: nearest


def test_newest_file(tmp_path):
    import os

    for i, name in enumerate(["a.txt", "b.pdf", "c.crdownload"]):
        path = tmp_path / name
        path.write_text("x")
        os.utime(path, (1000 + i, 1000 + i))
    assert newest_file(tmp_path) == tmp_path / "b.pdf"  # unfinished downloads don't count
    assert newest_file(tmp_path / "missing") is None


def test_wait_and_window_values():
    assert wait_seconds("2 seconds") == 2 and wait_seconds("1.5") == 1.5
    with pytest.raises(ActionError):
        wait_seconds("5 minutes")
    assert parse_window("minimize") == "minimize"
    assert parse_window("Chrome to 2 left") == ("chrome", "2", "left")
    assert parse_window("this to the laptop") == (None, "the laptop", "maximized")
    with pytest.raises(ActionError):
        parse_window("sideways")


# ----- the actions in commands -----


def test_system_actions_run(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    computer = FakeComputer(tmp_path)
    for kind, value in [
        ("displays", "only 2"),
        ("audio_output", "monitor"),
        ("dark_mode", "off"),
        ("power_mode", "balanced"),
        ("power", "screens_off"),
        ("keys", "win+d"),
        ("wait", "1 second"),
        ("close_app", "spotify"),
        ("focus_app", "chrome"),
        ("window", "chrome to 3 right"),
        ("window", "minimize"),
    ]:
        run_action(kind, value, computer=computer)
    assert computer.done == [
        ("screens", "only 2"),
        ("output", "mon"),
        ("dark", False),
        ("power_mode", "balanced"),
        ("power", "screens_off"),
        ("keys", "win+d"),
        ("close", "spotify"),
        ("focus", "chrome"),
        ("move", "chrome", "3", "right"),
        ("window", "minimize"),
    ]


def test_dark_mode_can_toggle(tmp_path):
    computer = FakeComputer(tmp_path)
    run_action("dark_mode", "toggle", computer=computer)
    assert computer.done == [("dark", False)]  # it was dark


@pytest.mark.parametrize(
    "action, problem",
    [
        ("displays: sideways", "displays is like"),
        ("dark_mode: maybe", "dark_mode is on, off or toggle"),
        ("power_mode: turbo", "power_mode is"),
        ("power: shutdown", "power is sleep, lock or screens_off"),
        ("keys: ctrl+banana", "keys:"),
        ("wait: 5 minutes", "at most 60 seconds"),
        ("window: sideways", "window is like"),
        ("close_app: ''", "needs a text value"),
    ],
)
def test_the_commands_file_checks_system_actions(action, problem):
    text = f"- name: x\n  triggers: [x]\n  actions:\n    - {action}\n"
    with pytest.raises(CommandsFileError, match=problem):
        parse_commands(yaml.safe_load(text))


def test_good_system_actions_load():
    text = """- name: movie
  triggers: [movie time]
  actions:
    - displays: only 2
    - audio_output: C34H89x
    - dark_mode: on
    - power_mode: balanced
    - keys: win+d
    - wait: 2 seconds
    - window: Chrome to 2 maximized
"""
    (command,) = parse_commands(yaml.safe_load(text))
    assert [kind for kind, _ in command.actions][:3] == ["displays", "audio_output", "dark_mode"]


def test_keys_and_close_app_cant_use_slots():
    text = "- name: x\n  triggers: ['close {app}']\n  actions:\n    - close_app: '{app}'\n"
    with pytest.raises(CommandsFileError, match="can't use slots"):
        parse_commands(yaml.safe_load(text))


# ----- Claude and the clipboard; listening for the yes; brightness on every screen -----


def test_claude_gets_the_clipboard_only_when_you_mention_it(tmp_path):
    from test_router import FakeAct, FakeBrain

    from abdoh.commands.registry import CommandRegistry
    from abdoh.config import Config
    from abdoh.router import Router

    path = tmp_path / "commands.yaml"
    path.write_text("[]", encoding="utf-8")
    brain = FakeBrain()
    router = Router(Config(app_dir=tmp_path), CommandRegistry(path), brain=brain, act=FakeAct())
    router.computer = FakeComputer(tmp_path)
    list(router.handle("translate what i copied into french"))
    assert 'clipboard contains:\n"""\ncopied text\n"""' in brain.asked[-1][0]
    list(router.handle("what is the capital of japan"))
    assert "clipboard" not in brain.asked[-1][0]


def test_abdoh_listens_for_the_answer_to_its_question():
    from fakes import FakeMic, FakeTranscriber, FakeWakeWord

    from abdoh.config import Config
    from abdoh.daemon import Daemon
    from abdoh.speech.tts import FakeSpeaker

    class Router:
        brain = registry = None

        def add_builtin(self, *args):
            pass

        def builtin_name(self, text):
            return None

        def handle(self, text):
            return Question("Shut down the computer?") if "shut" in text else "Okay."

    daemon = Daemon(Config(follow_up_seconds=0), Router(), FakeSpeaker(),
                    lambda: FakeMic([]), FakeWakeWord(10**9), FakeTranscriber([]))  # fmt: skip
    daemon.handle_text("shut down", voice=True)
    assert daemon._awaiting_answer
    daemon._awaiting_answer = False
    daemon.handle_text("shut down")  # typed: answer by typing
    assert not daemon._awaiting_answer
    daemon.handle_text("hello", voice=True)
    assert not daemon._awaiting_answer


def test_brightness_on_every_screen_that_can(tmp_path):
    from abdoh.computer import Computer

    class Desk:
        def __init__(self, works=True):
            self.level, self.works = None, works

        def set_brightness(self, percent):
            if not self.works:
                raise ActionError("I can't change this screen's brightness.")
            self.level = percent
            return percent

    displays = Displays(tmp_path / "d.json", FakeBackend())
    desk = Desk()
    computer = Computer(desk=desk, displays=displays)
    assert computer.set_brightness(40) == 40
    assert desk.level == 40 and displays.backend.brightness_["path-wide"] == 40
    assert computer.set_brightness(70, screen="3") == 70
    assert desk.level == 40  # only screen 3
    no_wmi = Computer(desk=Desk(works=False), displays=displays)
    assert no_wmi.set_brightness(55) == 55  # a desktop PC: only the monitor that can
    with pytest.raises(ActionError):
        no_wmi.set_brightness(55, screen="2")  # the HP 32f can't


# ----- night light (the values captured from Windows 11 build 26200) -----

WINDOWS_START = "434201000a0201002a06b3d6b1d6062a2b0e054342010000000000"  # never switched yet
WINDOWS_ON = (
    "434201000a0201002a06b0b4f1d7062a2b0e15434201001000d00a02c614e1f0cae89bd3ddee0100000000"
)
WINDOWS_OFF = "434201000a0201002a0688b6f1d7062a2b0e1343420100d00a02c614eaedc8eba3d3ddee0100000000"


def test_night_light_is_read_from_windows_values():
    from abdoh.system import parse_night_light

    assert parse_night_light(bytes.fromhex(WINDOWS_START)) is False
    assert parse_night_light(bytes.fromhex(WINDOWS_ON.replace(" ", ""))) is True
    assert parse_night_light(bytes.fromhex(WINDOWS_OFF)) is False
    with pytest.raises(ValueError):
        parse_night_light(b"\x00" * 30)  # a layout Xanthos doesn't know: never written


def test_night_light_is_written_the_way_windows_writes_it():
    from abdoh.system import night_light_value, parse_night_light

    when = 1794923056  # 2026-11-17 13:44:16 UTC, the time in WINDOWS_ON
    on = night_light_value(bytes.fromhex(WINDOWS_START), True, when + 0.517744)
    expected = bytes.fromhex(WINDOWS_ON.replace(" ", ""))
    assert on[:15] == expected[:15]  # the same header and change time
    assert on[15:29] == expected[15:29] and len(on) == len(expected)  # the same "on since" block
    off = night_light_value(on, False, when + 60)
    assert parse_night_light(off) is False
    assert len(off) == len(bytes.fromhex(WINDOWS_OFF))  # off keeps "since when", like Windows
    assert night_light_value(off, False, when + 90) == off  # already off: unchanged


def test_night_light_by_voice(abdoh):
    done = []
    abdoh.computer.set_night_light = lambda on: done.append(on)
    assert abdoh("turn on night light") == "Night light on."
    assert abdoh("night light off") == "Night light off."
    assert done == [True, False]
