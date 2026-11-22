"""The board: what a role shows instead of saying (between [board] and [/board]), never spoken,
shown on the Act as page, and safe to show (board.js never turns Claude's text into HTML)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fakes import FakeTranscriber, FakeWakeWord
from test_router import FakeAct, FakeBrain

from abdoh.claude.reply import speakable
from abdoh.commands.registry import CommandRegistry
from abdoh.config import Config
from abdoh.daemon import Daemon
from abdoh.events import Bus
from abdoh.roles.acting import Acting
from abdoh.roles.model import parse_roles
from abdoh.router import Router
from abdoh.speech.tts import FakeSpeaker
from abdoh.ui.api import AppApi, UiState

BOARD_JS = Path(__file__).resolve().parents[1] / "src" / "abdoh" / "ui" / "web" / "board.js"


def run(chunks):
    shown = []
    spoken = list(speakable(iter(chunks), lambda kind, arg: None, on_board=shown.append))
    return spoken, shown


# ----- never spoken -----


def test_the_board_is_shown_and_not_said():
    spoken, shown = run([
        "Let's solve it together.\n",
        "[board]\n2x + 3 = 11\n2x = 8\nx = 4\n[/board]\n",
        "So x is four.",
    ])  # fmt: skip
    assert spoken == ["Let's solve it together.", "So x is four."]
    assert shown == ["2x + 3 = 11\n2x = 8\nx = 4"]


def test_markers_split_across_streamed_chunks():
    spoken, shown = run(["Here. [bo", "ard]\nprint('hi')\n[/bo", "ard] That prints hi."])
    assert spoken == ["Here.", "That prints hi."]
    assert shown == ["print('hi')"]


def test_a_board_that_never_closes_is_still_shown_not_said():
    spoken, shown = run(["Look at this.\n[board]\n```python\nx = 1\n```"])
    assert spoken == ["Look at this."]
    assert shown == ["```python\nx = 1\n```"]


def test_several_boards_in_one_reply():
    spoken, shown = run(["[board]\na\n[/board]\nThen.\n[BOARD]\nb\n[/BOARD]\n"])
    assert spoken == ["Then."] and shown == ["a", "b"]


def test_without_a_board_its_text_is_still_never_said():
    spoken = list(speakable(iter(["Ok.\n[board]\nsecret = 1\n[/board]\nDone."]), lambda k, a: None))
    assert spoken == ["Ok.", "Done."]


def test_an_empty_board_shows_nothing():
    spoken, shown = run(["[board]\n\n[/board]\nNothing there."])
    assert shown == [] and spoken == ["Nothing there."]


# ----- Claude knows about it, Abdoh shows it -----

TEACHER = {"name": "Math teacher", "instructions": "Explain step by step.", "board": True}


def test_claude_hears_about_the_board_only_for_a_role_that_uses_it():
    acting = Acting(lambda: parse_roles([TEACHER, {"name": "Chef", "instructions": "Cook."}]))
    acting.start("Math teacher")
    assert "[board]" in acting.state_text(4) and "never read aloud" in acting.state_text(4)
    acting.start("Chef")
    assert "[board]" not in acting.state_text(4)
    acting.start("a pirate")  # made up on the spot: may use the board
    assert "[board]" in acting.state_text(4)


def test_the_router_hands_the_board_to_abdoh(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text("[]", encoding="utf-8")
    router = Router(Config(app_dir=tmp_path), CommandRegistry(path), act=FakeAct())
    shown = []
    router.on_board = shown.append
    router.brain = FakeBrain(("First, the steps.\n[board]\nx = 4\n[/board]\nThat's it.",))
    assert " ".join(router.handle("solve 2x + 3 = 11")) == "First, the steps. That's it."
    assert shown == ["x = 4"]


def make_daemon(tmp_path):
    router = Router(Config(app_dir=tmp_path), CommandRegistry(tmp_path / "none.yaml"))
    bus = Bus()
    daemon = Daemon(
        Config(app_dir=tmp_path), router, FakeSpeaker(), None, FakeWakeWord(10_000),
        FakeTranscriber([]), bus=bus,
    )  # fmt: skip
    daemon.use_roles(Acting(lambda: parse_roles([TEACHER]), on_change=daemon._role_changed))
    return daemon, bus


def test_the_window_comes_up_on_the_act_as_page(tmp_path):
    daemon, bus = make_daemon(tmp_path)
    daemon.router.on_board("x = 4")
    assert bus.pending_events() == [("board", "x = 4"), ("show", None), ("page", "roles")]


def test_a_new_role_or_none_clears_the_board(tmp_path):
    daemon, bus = make_daemon(tmp_path)
    daemon.acting.start("Math teacher")
    assert ("board", None) in bus.pending_events()
    daemon.acting.stop()
    assert ("board", None) in bus.pending_events()


def test_the_page_keeps_the_board_until_cleared(tmp_path):
    state = UiState()
    for i in range(35):
        state.feed("board", f"item {i}")
    board = state.snapshot()["board"]
    assert len(board) == 30 and board[-1] == "item 34"  # the newest 30
    api = AppApi(Bus(), state, Config(app_dir=tmp_path))
    api.clear_board()
    assert state.snapshot()["board"] == []


# ----- board.js -----


def test_board_js_never_turns_text_into_html():
    source = BOARD_JS.read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("/*"))
    assert "innerHTML" not in code.replace("(never innerHTML)", "")
    assert "html:" not in code and "insertAdjacentHTML" not in code and "outerHTML" not in code


def parse(text: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js isn't installed")
    script = (
        f"const B = require({json.dumps(str(BOARD_JS))});"
        f"process.stdout.write(JSON.stringify(B.parse({json.dumps(text)})));"
    )
    out = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_board_markdown_blocks():
    blocks = parse(
        "## Steps\n1. Take 3: 2x = 8\n2. Halve: x = 4\n\n```python\nprint(x)\n```\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n- one\n- two\nline one\nline two"
    )
    assert [b["type"] for b in blocks] == ["heading", "list", "code", "table", "list", "para"]
    assert blocks[0]["level"] == 2 and blocks[1]["ordered"] is True
    assert blocks[2] == {"type": "code", "lang": "python", "text": "print(x)"}
    assert len(blocks[3]["rows"]) == 2  # the --- row isn't a row
    assert blocks[4]["ordered"] is False
    assert blocks[5]["spans"] == [{"t": "text", "text": "line one\nline two"}]  # steps keep lines


def test_board_inline_and_html_stays_text():
    [block] = parse("Use **x²** and `x**2`, *not* <script>alert(1)</script>")
    assert block["spans"] == [
        {"t": "text", "text": "Use "}, {"t": "b", "text": "x²"}, {"t": "text", "text": " and "},
        {"t": "code", "text": "x**2"}, {"t": "text", "text": ", "}, {"t": "i", "text": "not"},
        {"t": "text", "text": " <script>alert(1)</script>"},
    ]  # fmt: skip
