import pytest

from abdoh.commands.actions import ActionError
from abdoh.local_skills import LocalSkills


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


class FakeComputer:
    def __init__(self):
        self.calls = []
        self.apps = FakeApps()
        self.timers = FakeTimers()

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
        ("mute", "mute"),
        ("unmute the sound", "mute"),
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
