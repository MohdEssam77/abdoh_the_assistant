from datetime import datetime

import pytest

from abdoh.commands.actions import ActionError, render, run_actions
from abdoh.commands.registry import Command


def test_render_placeholders():
    now = datetime(2026, 10, 8, 15, 5)
    assert render("It is {time}.", now) == "It is 3:05 PM."
    assert render("Today is {date}.", now) == "Today is Thursday, October 8."
    assert render("{time}", datetime(2026, 1, 1, 0, 30)) == "12:30 AM"
    assert render("braces {other} stay", now) == "braces {other} stay"


class Recorder:
    def __init__(self):
        self.calls = []

    def url(self, u):
        self.calls.append(("url", u))
        return True

    def app(self, a):
        self.calls.append(("app", a))

    def shell(self, c):
        self.calls.append(("run", c))


def run(command, allow_run=False):
    r = Recorder()
    spoken = run_actions(command, allow_run, r.url, r.app, r.shell)
    return spoken, r.calls


def test_actions_run_in_order():
    cmd = Command(
        "c",
        ["x"],
        [("say", "Hi at {time}"), ("open_url", "https://y.t"), ("open_app", "Code"), ("say", "ok")],
    )
    spoken, calls = run(cmd)
    assert spoken[0].startswith("Hi at ") and "{time}" not in spoken[0]
    assert spoken[1] == "ok"
    assert calls == [("url", "https://y.t"), ("app", "Code")]


def test_run_disabled_by_default():
    spoken, calls = run(Command("c", ["x"], [("run", "echo hi")]))
    assert calls == []
    assert "turned off" in spoken[0]


def test_run_when_allowed():
    spoken, calls = run(Command("c", ["x"], [("run", "echo hi")]), allow_run=True)
    assert calls == [("run", "echo hi")]
    assert spoken == []


def test_open_url_failure_raises():
    with pytest.raises(ActionError):
        run_actions(Command("c", ["x"], [("open_url", "u")]), open_url=lambda u: False)


def test_run_action_single():
    r = Recorder()
    from abdoh.commands.actions import run_action

    assert run_action("say", "hi", open_url=r.url) == "hi"
    assert run_action("open_url", "https://a.b", open_url=r.url) is None
    assert r.calls == [("url", "https://a.b")]
    with pytest.raises(ActionError):
        run_action("teleport", "mars")


class FakeComputer:
    def __init__(self):
        self.calls = []

    def open_url(self, url):
        self.calls.append(("url", url))

    def open_app(self, name):
        self.calls.append(("app", name))
        return name

    def media(self, key):
        self.calls.append(("media", key))

    def timer(self, text):
        self.calls.append(("timer", text))
        return f"Okay, {text} timer starting now."


def test_claude_can_only_open_web_links():
    from abdoh.commands.actions import claude_action

    computer = FakeComputer()
    claude_action("open_url", "https://www.python.org", computer)
    for bad in ("file:///C:/Windows/System32/cmd.exe", "ms-settings:", "javascript:alert(1)"):
        with pytest.raises(ActionError, match="web links"):
            claude_action("open_url", bad, computer)
    assert computer.calls == [("url", "https://www.python.org")]


def test_claude_apps_media_and_timers_go_through_the_computer():
    from abdoh.commands.actions import claude_action

    computer = FakeComputer()
    claude_action("open_app", "Spotify", computer)
    claude_action("media", "play_pause", computer)
    claude_action("timer", "5 minutes", computer)
    assert computer.calls == [("app", "Spotify"), ("media", "play_pause"), ("timer", "5 minutes")]


def test_claude_actions_outside_the_list_are_refused():
    from abdoh.commands.actions import claude_action

    with pytest.raises(ActionError):
        claude_action("run", "format c:", FakeComputer())
    with pytest.raises(ActionError):
        claude_action("open_url", "https://x.y", None)


def test_slots_are_filled_and_url_encoded_in_links():
    r = Recorder()
    cmd = Command(
        "yt",
        ["search youtube for {query}"],
        [
            ("open_url", "https://www.youtube.com/results?search_query={query}"),
            ("say", "Here's {query}."),
        ],
    )
    spoken = run_actions(cmd, False, r.url, r.app, r.shell, slots={"query": "lo-fi & jazz"})
    assert r.calls == [("url", "https://www.youtube.com/results?search_query=lo-fi+%26+jazz")]
    assert spoken == ["Here's lo-fi & jazz."]


def test_media_and_timer_actions():
    computer = FakeComputer()
    cmd = Command("focus", ["focus mode"], [("media", "play_pause"), ("timer", "25 minutes")])
    spoken = run_actions(cmd, computer=computer)
    assert computer.calls == [("media", "play_pause"), ("timer", "25 minutes")]
    assert spoken == ["Okay, 25 minutes timer starting now."]


def test_media_without_a_computer_is_reported():
    with pytest.raises(ActionError, match="isn't available"):
        run_actions(Command("m", ["x"], [("media", "mute")]))


def test_open_app_uses_the_computer_when_there_is_one():
    class Launcher(FakeComputer):
        def launch(self, target):
            self.calls.append(("launch", target))

    computer = Launcher()
    run_actions(Command("c", ["x"], [("open_app", "Spotify")]), computer=computer)
    assert computer.calls == [("launch", "Spotify")]
