from datetime import datetime
from pathlib import Path

import pytest

from abdoh.commands.actions import ActionError
from abdoh.local_skills import HELP, LocalSkills, parse_reminder, spoken_number

NOW = datetime(2026, 11, 16, 14, 0)  # a Monday afternoon


class FakeApps:
    def __init__(self, known=("Calculator",)):
        self.known = {k.lower(): k for k in known}

    def find(self, spoken):
        return self.known.get(spoken.replace("the ", ""))


class FakeTimers:
    def __init__(self):
        self.cancelled = 0

    def cancel_all(self):
        self.cancelled += 1
        return "Timer cancelled."


class FakeNotes:
    def __init__(self):
        self.lines = []

    def add(self, text):
        self.lines.append(text)

    def recent(self, count=5):
        return self.lines[-count:]


class FakeReminders:
    def __init__(self):
        self.items = []

    def add(self, when, text):
        self.items.append((when, text))

    def pending(self):
        return sorted(self.items)

    def cancel_all(self):
        count, self.items = len(self.items), []
        return count


class FakeComputer:
    def __init__(self):
        self.calls = []
        self.apps = FakeApps()
        self.timers = FakeTimers()
        self.notes = FakeNotes()
        self.reminders = FakeReminders()
        self.level = 40  # volume
        self.light = 50  # brightness
        self.power = (79, True)

    def now(self):
        return NOW

    def volume(self):
        return self.level

    def set_volume(self, percent):
        self.level = percent
        self.calls.append(("volume", percent))
        return percent

    def set_muted(self, muted):
        self.calls.append(("muted", muted))

    def brightness(self):
        return self.light

    def set_brightness(self, percent):
        self.light = percent
        self.calls.append(("brightness", percent))
        return percent

    def battery(self):
        return self.power

    def type_text(self, text):
        self.calls.append(("type", text))

    def window(self, action):
        self.calls.append(("window", action))

    def screenshot(self):
        self.calls.append(("screenshot",))
        return Path("C:/Users/me/Pictures/Screenshots/Krekos 2026-11-16 14.00.00.png")

    def open_notes(self):
        self.calls.append(("open_notes",))

    def media(self, key):
        self.calls.append(("media", key))

    def lock(self):
        self.calls.append(("lock",))

    def timer(self, text):
        self.calls.append(("timer", text))
        return "Okay, 5 minute timer starting now."

    def open_app(self, name):
        self.calls.append(("open", name))
        return self.apps.find(name)


@pytest.fixture
def skills():
    return LocalSkills(FakeComputer())


@pytest.mark.parametrize(
    "request_text, key",
    [
        ("volume up", "volume_up"),
        ("turn the volume up", "volume_up"),
        ("can you turn it down", "volume_down"),
        ("pause", "play_pause"),
        ("pause the music", "play_pause"),
        ("resume the song please", "play_pause"),
        ("stop the music", "play_pause"),
        ("next song", "next"),
        ("skip this song", "next"),
        ("previous track", "previous"),
        ("go back a song", "previous"),
    ],
)
def test_media_keys(skills, request_text, key):
    assert skills.handle(request_text) == ""  # done quietly
    assert skills.computer.calls == [("media", key)]


def test_timer(skills):
    assert skills.handle("set a timer for 5 minutes") == "Okay, 5 minute timer starting now."
    assert skills.computer.calls == [("timer", "set a timer for 5 minutes")]


def test_cancel_timer(skills):
    assert skills.handle("cancel the timer") == "Timer cancelled."
    assert skills.computer.timers.cancelled == 1


def test_timer_without_a_duration_is_not_mine(skills):
    assert skills.handle("how long is left on my timer") is None


def test_lock(skills):
    assert skills.handle("lock my computer") == ""
    assert skills.computer.calls == [("lock",)]


def test_open_an_installed_app(skills):
    assert skills.handle("open the calculator") == "Opening Calculator."


def test_unknown_app_falls_through_to_claude(skills):
    assert skills.handle("open youtube") is None
    assert skills.computer.calls == []


@pytest.mark.parametrize(
    "request_text",
    ["play some jazz on spotify", "whats the weather", "stop the music now", "turn up the heat"],
)
def test_other_requests_are_not_mine(skills, request_text):
    assert skills.handle(request_text) is None


@pytest.mark.parametrize(
    "request_text", ["thanks", "thank you", "no thanks", "thats all", "never mind", "stop", "bye"]
)
def test_ending_the_conversation_needs_no_answer(skills, request_text):
    assert skills.handle(request_text) == ""  # handled, nothing to say, nothing sent to Claude
    assert skills.computer.calls == []


def test_errors_are_spoken(skills):
    def broken(key):
        raise ActionError("Media keys only work on Windows for now.")

    skills.computer.media = broken
    assert skills.handle("next song") == "Media keys only work on Windows for now."


# ----- volume, exactly -----


@pytest.mark.parametrize(
    "request_text, level",
    [
        ("set the volume to 75", 75),
        ("volume 30", 30),
        ("let the volume to 75 percent", 75),  # what Whisper once made of "set the volume"
        ("increase the volume to seventy", 70),
        ("turn the volume down to twenty five percent", 25),
        ("just decrease it to 50", None),  # no "volume": Claude knows what "it" is
        ("max volume", 100),
        ("volume to 300", None),
    ],
)
def test_exact_volume(skills, request_text, level):
    reply = skills.handle(request_text)
    if level is None:
        assert reply is None and skills.computer.calls == []
    else:
        assert reply == f"Volume at {level} percent."
        assert skills.computer.calls == [("volume", level)]


def test_mute_and_unmute_are_not_a_toggle(skills):
    assert skills.handle("mute") == "" and skills.handle("mute the laptop") == ""
    assert skills.handle("unmute") == "" and skills.handle("turn the sound back on") == ""
    assert skills.computer.calls == [("muted", True), ("muted", True), ("muted", False)] + [
        ("muted", False)
    ]


def test_asking_for_the_volume(skills):
    assert skills.handle("whats the volume") == "The volume is at 40 percent."


def test_spoken_numbers():
    assert spoken_number("75") == 75 and spoken_number("seventy five") == 75
    assert spoken_number("ten") == 10 and spoken_number("the method") is None


# ----- screen and battery -----


def test_brightness(skills):
    assert skills.handle("set the brightness to 80 percent") == "Brightness at 80 percent."
    assert skills.handle("brighter") == "" and skills.computer.light == 100
    assert skills.handle("dim the screen") == "" and skills.computer.light == 80
    assert skills.handle("lower the brightness") == "" and skills.computer.light == 60


def test_battery(skills):
    assert skills.handle("how much battery do i have") == (
        "The battery is at 79 percent and charging."
    )
    skills.computer.power = (15, False)
    assert skills.handle("whats my battery level") == "The battery is at 15 percent."
    skills.computer.power = None
    assert skills.handle("battery") == "This computer doesn't have a battery."


def test_screenshot(skills):
    assert skills.handle("take a screenshot") == "Saved a screenshot in your Screenshots folder."
    assert skills.computer.calls == [("screenshot",)]


@pytest.mark.parametrize(
    "request_text, action",
    [
        ("minimize this window", "minimize"),
        ("maximise the window", "maximize"),
        ("close this window", "close"),
        ("show the desktop", "desktop"),
        ("switch window", "switch"),
    ],
)
def test_window_controls(skills, request_text, action):
    assert skills.handle(request_text) == ""
    assert skills.computer.calls == [("window", action)]


# ----- time, reminders -----


def test_time_and_date(skills):
    assert skills.handle("what time is it") == "It's 2 PM."
    assert skills.handle("whats the date") == "It's Monday, November 16."


@pytest.mark.parametrize(
    "said, when, what, spoken",
    [
        (
            "to call my mother in 20 minutes",
            NOW.replace(minute=20),
            "call my mother",
            "in 20 minutes",
        ),
        ("in an hour to stretch", NOW.replace(hour=15), "stretch", "in 1 hour"),
        (
            "at 5:30 PM to leave for the gym.",
            NOW.replace(hour=17, minute=30),
            "leave for the gym",
            "at 5:30 PM",
        ),
        (
            "to check in with Bob in 5 minutes",
            NOW.replace(minute=5),
            "check in with Bob",
            "in 5 minutes",
        ),
        (
            "to take out the bins tomorrow at 8",
            NOW.replace(day=17, hour=8),
            "take out the bins",
            "tomorrow at 8 AM",
        ),
        (
            "that the oven is on in ten minutes",
            NOW.replace(minute=10),
            "the oven is on",
            "in 10 minutes",
        ),
    ],
)
def test_reminders_are_understood(said, when, what, spoken):
    assert parse_reminder(said, NOW) == (when, what, spoken)


def test_a_reminder_without_a_time_is_for_claude(skills):
    assert parse_reminder("to be nice", NOW) is None
    assert skills.handle("remind me to be nice", "Remind me to be nice.") is None


def test_setting_listing_and_cancelling_reminders(skills):
    reply = skills.handle(
        "remind me to call my mother in 20 minutes", "Remind me to call my mother in 20 minutes."
    )
    assert reply == "Okay, I'll remind you to call your mother in 20 minutes."
    assert skills.computer.reminders.items == [(NOW.replace(minute=20), "call your mother")]
    assert skills.handle("what are my reminders") == "You have 1: call your mother, at 2:20 PM."
    assert skills.handle("cancel my reminders") == "Your reminders are cancelled."
    assert skills.handle("do i have any reminders") == "You have no reminders."


# ----- notes, typing, sums -----


def test_notes_keep_your_own_words(skills):
    said = "Take a note: the Wi-Fi password is Blue-42!"
    assert skills.handle("take a note the wifi password is blue42", said) == "Noted."
    assert skills.computer.notes.lines == ["the Wi-Fi password is Blue-42!"]
    assert skills.handle("read my notes") == "Your latest notes: the Wi-Fi password is Blue-42!."
    assert skills.handle("open my notes") == "" and skills.computer.calls == [("open_notes",)]


def test_no_notes_yet(skills):
    assert skills.handle("what are my notes") == "You have no notes."


def test_typing_what_you_dictate(skills):
    assert skills.handle("type best regards sam", "Type: Best regards, Sam.") == ""
    assert skills.computer.calls == [("type", "Best regards, Sam.")]


def test_quick_maths(skills):
    assert skills.handle("whats 15 of 80", "What's 15% of 80?") == "That's 12."
    assert skills.handle("what is 12 times 12") == "That's 144."
    assert skills.handle("what is the capital of japan") is None


# ----- talking -----


def test_repeat_that():
    said = ["It's sunny in Cairo."]
    skills = LocalSkills(FakeComputer(), last_reply=lambda: said[-1])
    assert skills.handle("repeat that") == "It's sunny in Cairo."
    assert skills.handle("say that again please") == "It's sunny in Cairo."
    assert LocalSkills(FakeComputer()).handle("pardon") == "I haven't said anything yet."


def test_what_can_you_do(skills):
    assert skills.handle("what can you do") == HELP


# ----- what you say while Krekos is talking -----


def test_what_an_interruption_means():
    from abdoh.local_skills import interruption_kind

    cases = {
        "nothing": ["", "Um.", "uh, hmm", "mm hmm", "Er..."],
        "backchannel": ["Okay.", "Yeah, right.", "I see", "Go on", "Got it", "Alright", "wow"],
        "stop": [
            "Wait.",
            "Hold on a second",
            "Thanks!",
            "Stop.",
            "Be quiet please",
            "Enough",
            "That's enough",
            "no",
            "never mind",
            "shh",
        ],  # fmt: skip
        "request": [
            "What about tomorrow?",
            "Okay, and what about Paris?",
            "stop the music",
            "wait what did you say about the capital",
            "open notepad",
        ],  # fmt: skip
    }
    for kind, texts in cases.items():
        for text in texts:
            assert interruption_kind(text) == kind, text
