"""Notes, reminders, sums, typing and the volume: the parts behind Abdoh's newer skills."""

import json
from datetime import datetime, timedelta

import pytest
import yaml

from abdoh.claude.reply import ACTION_HELP
from abdoh.commands.actions import ActionError, claude_action, percent, run_action
from abdoh.commands.registry import CommandsFileError, parse_commands
from abdoh.computer import Computer
from abdoh.config import CLAUDE_ACTIONS, load_config
from abdoh.desk import (
    KEYEVENTF_KEYUP,
    KEYEVENTF_UNICODE,
    VK_RETURN,
    Notes,
    Reminders,
    calculate,
    clock_text,
    key_events,
    parse_clock,
    save_screenshot,
)

NOW = datetime(2026, 11, 16, 14, 0)

# ----- notes -----


def test_notes_are_lines_in_a_file_you_can_read(tmp_path):
    notes = Notes(tmp_path / "data" / "notes.txt", now=lambda: NOW)
    notes.add("  buy   milk ")
    notes.add("call the bank")
    assert notes.path.read_text(encoding="utf-8") == (
        "- [2026-11-16 14:00] buy milk\n- [2026-11-16 14:00] call the bank\n"
    )
    assert notes.recent() == ["buy milk", "call the bank"]
    assert notes.recent(1) == ["call the bank"]


def test_notes_you_wrote_by_hand_are_read_too(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("first idea\n\n- second idea\n", encoding="utf-8")
    assert Notes(path).recent() == ["first idea", "second idea"]


def test_empty_notes(tmp_path):
    notes = Notes(tmp_path / "notes.txt")
    assert notes.recent() == []
    with pytest.raises(ActionError, match="What should I note"):
        notes.add("   ")


# ----- reminders -----


class FakeTimer:
    made: list = []

    def __init__(self, seconds, function, args=()):
        self.seconds, self.function, self.args = seconds, function, args
        self.cancelled = False
        FakeTimer.made.append(self)

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.function(*self.args)


@pytest.fixture
def reminders(tmp_path):
    FakeTimer.made.clear()
    said = []
    r = Reminders(tmp_path / "reminders.json", said.append, FakeTimer, now=lambda: NOW)
    r.said = said
    return r


def test_a_reminder_is_said_at_its_time_and_then_gone(reminders):
    reminders.add(NOW + timedelta(minutes=20), "call your mother")
    (timer,) = FakeTimer.made
    assert timer.seconds == 1200
    assert reminders.pending() == [(NOW + timedelta(minutes=20), "call your mother")]
    timer.fire()
    assert reminders.said == ["Reminder: call your mother."]
    assert reminders.pending() == [] and json.loads(reminders.path.read_text()) == []


def test_reminders_survive_a_restart(reminders):
    reminders.add(NOW + timedelta(hours=2), "leave for the gym")
    reminders.add(NOW + timedelta(minutes=5), "stretch")
    FakeTimer.made.clear()
    said = []
    later = NOW + timedelta(minutes=30)  # Abdoh was closed when "stretch" was due
    again = Reminders(reminders.path, said.append, FakeTimer, now=lambda: later)
    assert [text for _, text in again.pending()] == ["stretch", "leave for the gym"]
    seconds = sorted(t.seconds for t in FakeTimer.made)
    assert seconds == [1, 5400]  # the missed one right away, the other on time


def test_cancelling_reminders(reminders):
    reminders.add(NOW + timedelta(minutes=5), "stretch")
    assert reminders.cancel_all() == 1 and FakeTimer.made[0].cancelled
    assert reminders.pending() == [] and reminders.cancel_all() == 0


def test_a_damaged_reminders_file_is_ignored(tmp_path):
    path = tmp_path / "reminders.json"
    path.write_text("{not json")
    assert Reminders(path, print, FakeTimer).pending() == []


# ----- clock times -----


@pytest.mark.parametrize(
    "said, expected",
    [
        ("at 5:30 pm", NOW.replace(hour=17, minute=30)),
        ("at 5", NOW.replace(hour=17)),  # the next 5 o'clock
        ("at 1", NOW.replace(day=17, hour=1)),
        ("17:30", NOW.replace(hour=17, minute=30)),
        ("at 9 a.m.", NOW.replace(day=17, hour=9)),  # already past today
        ("tomorrow at 9", NOW.replace(day=17, hour=9)),
        ("noon", NOW.replace(day=17, hour=12)),
        ("at 5 30 PM", NOW.replace(hour=17, minute=30)),
    ],
)
def test_clock_times(said, expected):
    assert parse_clock(said, NOW) == expected


@pytest.mark.parametrize("said", ["soon", "at 25", "at 13 pm", "at 5:75", "later today"])
def test_things_that_are_not_times(said):
    assert parse_clock(said, NOW) is None


def test_saying_a_time():
    assert clock_text(NOW.replace(hour=17, minute=30), NOW) == "5:30 PM"
    assert clock_text(NOW.replace(day=17, hour=9), NOW) == "tomorrow at 9 AM"
    assert clock_text(NOW.replace(day=19, hour=0, minute=5), NOW) == "Thursday at 12:05 AM"


# ----- sums -----


@pytest.mark.parametrize(
    "said, answer",
    [
        ("What's 15% of 80?", "That's 12."),
        ("what is 12 times 12", "That's 144."),
        ("calculate 2 to the power of 10", "That's 1,024."),
        ("how much is 1,200 plus 300", "That's 1,500."),
        ("what is 100 divided by 7", "That's about 14.2857."),
        ("what's 9 squared", "That's 81."),
        ("what is 42", None),  # one number: not a sum
        ("what is 7 x 8", "That's 56."),
        ("what is 5 divided by 0", "You can't divide by zero."),
        ("what is 20 percent of 50", "That's 10."),
    ],
)
def test_sums(said, answer):
    assert calculate(said) == answer


@pytest.mark.parametrize(
    "said",
    [
        "what is the capital of japan",
        "what is 2 plus two",
        "what's 9 to the power of 999",  # too big to be useful
        "__import__('os').system('calc')",
        "what time is it",
    ],
)
def test_not_sums(said):
    assert calculate(said) is None


# ----- typing and screenshots -----


def test_typing_is_unicode_key_presses():
    down, up = KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
    assert key_events("hé") == [(0, ord("h"), down), (0, ord("h"), up)] + [
        (0, ord("é"), down),
        (0, ord("é"), up),
    ]
    assert key_events("\n") == [(VK_RETURN, 0, 0), (VK_RETURN, 0, KEYEVENTF_KEYUP)]
    assert len(key_events("😀")) == 4  # two UTF-16 halves, each pressed and released
    assert len(key_events("عبده")) == 8


def test_screenshots_are_saved_with_the_time(tmp_path):
    path = save_screenshot(tmp_path / "Screenshots", capture=lambda: b"PNG", now=NOW)
    assert path.name == "Abdoh 2026-11-16 14.00.00.png" and path.read_bytes() == b"PNG"

    def broken():
        raise OSError("no screen")

    with pytest.raises(ActionError, match="couldn't take a screenshot"):
        save_screenshot(tmp_path, capture=broken)


# ----- the computer -----


class Speaker:
    def __init__(self, level=40, mute=True):
        self.level, self.mute = level, mute

    def volume(self):
        return self.level

    def set_volume(self, percent):
        self.level = max(0, min(100, round(percent)))
        return self.level

    def muted(self):
        return self.mute

    def set_muted(self, muted):
        self.mute = muted


class Audio:
    def __init__(self, speaker=None):
        self.device = speaker

    def speaker(self):
        if self.device is None:
            raise RuntimeError("no Core Audio here")
        return self.device


def test_setting_the_volume_unmutes():
    speaker = Speaker(mute=True)
    computer = Computer(audio=Audio(speaker))
    assert computer.set_volume(75) == 75 and speaker.mute is False
    assert computer.volume() == 75
    speaker.mute = True
    assert computer.set_volume(0) == 0 and speaker.mute is True  # zero stays quiet


def test_mute_falls_back_to_the_mute_key():
    pressed = []
    computer = Computer(audio=Audio(None), press_key=pressed.append)
    computer.set_muted(True)
    assert pressed == ["mute"]
    with pytest.raises(ActionError, match="volume control"):
        computer.set_volume(50)


def test_claude_sets_reminders_in_plain_words(tmp_path):
    FakeTimer.made.clear()
    reminders = Reminders(tmp_path / "r.json", print, FakeTimer, now=lambda: NOW)
    computer = Computer(reminders=reminders, now=lambda: NOW)
    assert computer.remind("20 minutes | call your mother") == "in 20 minutes"
    assert computer.remind("17:30 | leave for the gym") == "at 5:30 PM"
    assert computer.remind("tomorrow at 9 | water the plants") == "tomorrow at 9 AM"
    assert reminders.pending() == [
        (NOW.replace(minute=20), "call your mother"),
        (NOW.replace(hour=17, minute=30), "leave for the gym"),
        (NOW.replace(day=17, hour=9), "water the plants"),
    ]
    for bad in ("20 minutes |", "whenever | nap", "nothing to split"):
        with pytest.raises(ActionError):
            computer.remind(bad)


def test_notes_and_reminders_need_setting_up():
    computer = Computer()
    with pytest.raises(ActionError, match="Notes aren't available"):
        computer.notes.add("x")
    with pytest.raises(ActionError, match="Reminders aren't available"):
        computer.reminders.pending()


class Desk:
    def __init__(self):
        self.calls = []

    def set_brightness(self, percent):
        self.calls.append(("brightness", percent))
        return percent

    def type_text(self, text):
        self.calls.append(("type", text))


# ----- actions: yours and Claude's -----


def test_percent():
    assert (percent("70"), percent("70%"), percent(" 35 percent ")) == (70, 70, 35)
    for bad in ("loud", "140", "-5"):
        with pytest.raises(ActionError):
            percent(bad)


def test_your_commands_can_set_the_volume_and_type(tmp_path):
    desk, speaker = Desk(), Speaker()
    computer = Computer(audio=Audio(speaker), desk=desk)
    assert run_action("volume", "30", computer=computer) is None and speaker.level == 30
    run_action("brightness", "70%", computer=computer)
    run_action("type", "Best regards, {name}", computer=computer, slots={"name": "Sam"})
    assert desk.calls == [("brightness", 70), ("type", "Best regards, Sam")]
    with pytest.raises(ActionError, match="isn't available here"):
        run_action("type", "hello")


def test_claude_can_use_the_new_actions_but_not_type(tmp_path):
    FakeTimer.made.clear()
    notes = Notes(tmp_path / "notes.txt", now=lambda: NOW)
    reminders = Reminders(tmp_path / "r.json", print, FakeTimer, now=lambda: NOW)
    speaker, desk = Speaker(), Desk()
    computer = Computer(
        audio=Audio(speaker), desk=desk, notes=notes, reminders=reminders, now=lambda: NOW
    )
    claude_action("volume", "55", computer)
    claude_action("brightness", "40", computer)
    claude_action("note", "the door code is 4471", computer)
    claude_action("remind", "10 minutes | check the oven", computer)
    assert speaker.level == 55 and desk.calls == [("brightness", 40)]
    assert notes.recent() == ["the door code is 4471"]
    assert reminders.pending() == [(NOW.replace(minute=10), "check the oven")]
    with pytest.raises(ActionError, match="can't do type"):
        claude_action("type", "rm -rf", computer)  # text from the web never reaches your keys
    assert "type" not in ACTION_HELP and "type" not in CLAUDE_ACTIONS


def test_command_files_check_the_new_actions():
    good = "- name: quiet\n  triggers: [quiet time]\n  actions:\n    - volume: 20\n    - type: hi\n"
    assert parse_commands(yaml.safe_load(good))[0].actions == [("volume", "20"), ("type", "hi")]
    bad = "- name: loud\n  triggers: [loud]\n  actions:\n    - volume: eleven\n"
    with pytest.raises(CommandsFileError, match="volume needs a number from 0 to 100"):
        parse_commands(yaml.safe_load(bad))


def test_old_settings_get_claudes_new_actions(app_dir):
    old = 'config_version: 2\nclaude:\n  actions: ["open_url", "timer"]\n'
    (app_dir / "config.yaml").write_text(old)
    cfg = load_config(app_dir)
    assert cfg.claude.actions == [
        "open_url", "timer", "volume", "brightness", "remind", "note", "app_volume"
    ]  # fmt: skip
    assert cfg.config_version == 4
    from_0_4 = 'config_version: 3\nclaude:\n  actions: ["open_url", "volume"]\n'
    (app_dir / "config.yaml").write_text(from_0_4)
    assert load_config(app_dir).claude.actions == ["open_url", "volume", "app_volume"]
    current = 'config_version: 4\nclaude:\n  actions: ["open_url"]\n'
    (app_dir / "config.yaml").write_text(current)
    assert load_config(app_dir).claude.actions == ["open_url"]  # your choice from then on
