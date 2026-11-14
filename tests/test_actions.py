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


def test_claude_can_only_open_web_links():
    from abdoh.commands.actions import claude_action

    r = Recorder()
    claude_action("open_url", "https://www.python.org", open_url=r.url)
    assert r.calls == [("url", "https://www.python.org")]
    for bad in ("file:///C:/Windows/System32/cmd.exe", "ms-settings:", "javascript:alert(1)"):
        with pytest.raises(ActionError, match="web links"):
            claude_action("open_url", bad, open_url=r.url)
    assert len(r.calls) == 1


def test_claude_actions_outside_the_list_are_refused():
    from abdoh.commands.actions import claude_action

    with pytest.raises(ActionError):
        claude_action("run", "format c:")


@pytest.mark.parametrize(
    "name",
    [r"C:\Windows\System32\cmd.exe", "calc.exe", r"..\evil", "a/b", "x & y", "run.bat", ""],
)
def test_installed_app_names_cannot_be_paths_or_commands(name):
    from abdoh.commands.actions import open_installed_app

    with pytest.raises(ActionError):
        open_installed_app(name)
