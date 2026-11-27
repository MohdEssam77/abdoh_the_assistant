"""What Abdoh is doing, live on the phone (ABDOH_EPIC_11.md, story 147): Claude's steps and
Abdoh's actions in a few words, reported for phone requests only, and Claude told when a
request comes from the phone."""

import json

from fakes import FakeTranscriber  # noqa: F401 - the shared fakes load first
from test_claude_code import FakePopen, delta, make_brain, result
from test_daemon import StubRouter, make_daemon
from test_router import FakeAct, FakeBrain, text_of

from abdoh.claude.brain import system_prompt
from abdoh.claude.code import read_events
from abdoh.commands.registry import CommandRegistry
from abdoh.config import Config
from abdoh.doing import action_step, tool_step
from abdoh.events import Bus
from abdoh.phone.hub import PhoneHub
from abdoh.router import FROM_PHONE, Router


def test_claudes_tools_in_a_few_words():
    searched = "Searching the web: weather in Berlin"
    assert tool_step("WebSearch", {"query": "weather in Berlin"}) == searched
    assert tool_step("WebFetch", {"url": "https://www.bbc.co.uk/weather"}) == "Reading bbc.co.uk"
    assert tool_step("Read", {"file_path": r"C:\Users\me\Documents\CV.pdf"}) == "Reading CV.pdf"
    assert tool_step("Glob", {"pattern": "**/*CV*.pdf"}) == "Looking for *CV*.pdf"
    assert tool_step("Grep", {"pattern": "invoice"}) == "Searching files for “invoice”"
    ran = tool_step("PowerShell", {"command": "Get-ChildItem", "description": "List the files"})
    assert ran == "Running: List the files"
    assert tool_step("Bash", {}) == "Running a command"
    assert tool_step("Edit", {"file_path": "/home/me/notes.md"}) == "Changing notes.md"
    assert tool_step("mcp__claude_ai_Gmail__search_threads", {}) == "Gmail: search threads"
    assert tool_step("NotebookEdit", None) == "Using notebook edit"
    long = tool_step("WebSearch", {"query": "x" * 200})
    assert len(long) < 100 and long.endswith("…")


def test_abdohs_actions_in_a_few_words():
    assert action_step("open_app", "Spotify") == "Opened Spotify"
    assert action_step("open_url", "https://www.python.org/downloads") == "Opened python.org"
    assert action_step("media", "next") == "Music: next"
    assert action_step("lamp", "desk | warm white") == "Lamp: desk | warm white"
    assert action_step("codoh", "new | C:/code/portfolio | add a dark mode") == (
        "New Codoh chat in portfolio: add a dark mode"
    )
    assert action_step("codoh", "send | run the tests too") == "Told Codoh: run the tests too"
    assert action_step("codoh", "stop") == "Stopped Codoh"
    assert action_step("send_file", r"C:\Users\me\CV.pdf") == "Sent you CV.pdf"
    assert action_step("something_new", "x") == "Something new: x"


def test_claude_codes_stream_gives_each_tools_details():
    tool = {"type": "tool_use", "id": "t1", "name": "WebSearch", "input": {"query": "jazz"}}
    lines = [
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text"}, tool]}}),
        json.dumps({"type": "result", "subtype": "success", "result": "Found it."}),
    ]
    steps = []
    assert "".join(read_events(lines, on_step=lambda n, d: steps.append((n, d)))) == "Found it."
    assert steps == [("WebSearch", {"query": "jazz"})]


def test_the_screenshot_abdoh_handed_over_isnt_a_step(tmp_path):
    def read(path):
        block = {"type": "tool_use", "name": "Read", "input": {"file_path": path}}
        return json.dumps({"type": "assistant", "message": {"content": [block]}})

    shot = str(tmp_path / "work" / "screenshot.png")
    popen = FakePopen([read(shot), read(r"C:\Users\me\notes.txt"), delta("Here."), result()])
    brain = make_brain(tmp_path, popen)
    seen = []
    brain.on_step = seen.append
    assert "".join(brain.stream("what's on screen?", image_png=b"PNG")) == "Here."
    assert seen == ["Reading notes.txt"]
    brain.close()


def test_the_router_reports_each_action_and_tags_phone_requests(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text("[]", encoding="utf-8")
    router = Router(Config(app_dir=tmp_path), CommandRegistry(path), act=FakeAct())
    router.brain = FakeBrain(["ACTION open_app: Spotify\n", "Opening Spotify."])
    did = []
    router.on_action = lambda kind, arg: did.append((kind, arg))
    router.phone = True
    assert text_of(router.handle("open spotify")) == "Opening Spotify."
    assert did == [("open_app", "Spotify")]
    assert router.brain.asked[0][0].startswith(FROM_PHONE)
    router.phone = False
    router.brain = FakeBrain(["Sure."])
    text_of(router.handle("hello there"))
    assert not router.brain.asked[0][0].startswith(FROM_PHONE)


def test_claude_is_told_about_the_phone():
    prompt = system_prompt(Config())
    assert "(From the phone)" in prompt and "[board]" in prompt


class StepRouter(StubRouter):
    """Claude's answer that does an action and takes a step."""

    def __init__(self, daemon_ref):
        super().__init__([iter(["Opened it."])])
        self.daemon_ref = daemon_ref
        self.on_action = lambda kind, arg: None
        self.phone = False

    def handle(self, text, **kw):
        self.daemon_ref[0]._step("Searching the web: jazz")
        self.on_action("open_app", "Spotify")
        return super().handle(text, **kw)


def test_steps_go_to_the_phone_for_its_requests_only():
    bus = Bus(ui_attached=False)
    seen = []
    bus.listen(lambda kind, value: seen.append((kind, value)))
    ref = []
    router = StepRouter(ref)
    daemon = make_daemon(router, bus=bus)
    ref.append(daemon)
    daemon.handle_request("phone", {"text": "play some jazz"})
    steps = [v for k, v in seen if k == "phone_step"]
    assert steps == ["Searching the web: jazz", "Opened Spotify"]
    assert router.phone is False  # back to the laptop's after the request
    seen.clear()
    router.replies = [iter(["Opened it."])]
    daemon.handle_text("play some jazz")  # at the laptop: no steps for the phone
    assert [v for k, v in seen if k == "phone_step"] == []


def test_the_hub_sends_steps_to_the_phone_that_asked():
    bus = Bus(ui_attached=False)
    hub = PhoneHub(bus)
    hub.ask("open spotify", phone="p1")
    hub.take("phone_step", "Opened Spotify")
    assert hub.events(0, wait=0)["events"][-1] == {
        "seq": 1, "type": "step", "text": "Opened Spotify", "for": "p1"}  # fmt: skip


def test_the_board_doesnt_bring_the_laptops_window_up_for_the_phone():
    bus = Bus(ui_attached=False)
    seen = []
    bus.listen(lambda kind, value: seen.append(kind))
    daemon = make_daemon(StubRouter([]), bus=bus)
    daemon._pause = lambda seconds: None
    daemon._phone_turn = True
    daemon._on_board(1, "## Merge sort")
    assert "board" in seen and "show" not in seen and "page" not in seen
    daemon._phone_turn = False
    daemon._on_board(2, "## Quick sort")
    assert "show" in seen
