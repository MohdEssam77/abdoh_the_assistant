"""The board: what a role shows instead of saying (between [board] and [/board]), never spoken,
shown on the Act as page, and safe to show (board.js never turns Claude's text into HTML)."""

import json
import shutil
import subprocess
import tomllib
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

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "abdoh" / "ui" / "web"
BOARD_JS = WEB / "board.js"


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
    assert shown == ["2x + 3 = 11", "2x + 3 = 11\n2x = 8", "2x + 3 = 11\n2x = 8\nx = 4"]  # live


def test_markers_split_across_streamed_chunks():
    spoken, shown = run(["Here. [bo", "ard]\nprint('hi')\n[/bo", "ard] That prints hi."])
    assert spoken == ["Here.", "That prints hi."]
    assert shown == ["print('hi')"]


def test_a_board_that_never_closes_is_still_shown_not_said():
    spoken, shown = run(["Look at this.\n[board]\n```python\nx = 1\n```"])
    assert spoken == ["Look at this."]
    assert shown[-1] == "```python\nx = 1\n```"


def test_the_parts_of_one_reply_make_one_board():
    spoken, shown = run(["[board]\na\n[/board]\nThen.\n[BOARD]\nb\n[/BOARD]\n"])
    assert spoken == ["Then."] and shown == ["a", "a\nb"]  # written on: a code block can go on


def test_the_board_fills_in_while_abdoh_talks():
    """Each part shows up right after the sentence before it is spoken, not when Claude's
    whole answer is done (the reply is read only as fast as it is spoken)."""
    happened = []
    chunks = [
        "Here's the formula.\n[board]\n",
        "x = (−b ± √(b² − 4ac)) / 2a\n",
        "[/board]\nFirst, find a, b and c.\n[board]\na = 1, b = −1, c = −13\n[/board]\n",
        "Then put them in.",
    ]
    board = lambda text: happened.append(("board", text))  # noqa: E731
    for sentence in speakable(iter(chunks), lambda kind, arg: None, on_board=board):
        happened.append(("say", sentence))
    formula = "x = (−b ± √(b² − 4ac)) / 2a"
    assert happened == [
        ("say", "Here's the formula."),
        ("board", formula),
        ("say", "First, find a, b and c."),
        ("board", formula + "\na = 1, b = −1, c = −13"),
        ("say", "Then put them in."),
    ]


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
    text = acting.state_text(4)
    assert "[board]" in text and "never read aloud" in text
    assert "a little at a time" in text and "LaTeX" in text  # written like on a whiteboard
    acting.start("Chef")
    assert "[board]" not in acting.state_text(4)
    acting.start("a pirate")  # made up on the spot: may use the board
    assert "[board]" in acting.state_text(4)


def test_the_router_hands_the_board_to_abdoh(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text("[]", encoding="utf-8")
    router = Router(Config(app_dir=tmp_path), CommandRegistry(path), act=FakeAct())
    shown = []
    router.on_board = lambda card, text: shown.append((card, text))
    router.brain = FakeBrain(("First, the steps.\n[board]\nx = 4\n[/board]\nThat's it.",))
    assert " ".join(router.handle("solve 2x + 3 = 11")) == "First, the steps. That's it."
    assert [text for _, text in shown] == ["x = 4"]


def test_each_answer_gets_its_own_card(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text("[]", encoding="utf-8")
    router = Router(Config(app_dir=tmp_path), CommandRegistry(path), act=FakeAct())
    shown = []
    router.on_board = lambda card, text: shown.append((card, text))
    router.brain = FakeBrain(("Ok.\n[board]\na\n[/board]\nAnd.\n[board]\nb\n[/board]\n",))
    list(router.handle("first question"))
    list(router.handle("second question"))
    (one, a), (same, ab), (two, a2), (also_two, ab2) = shown
    assert one == same and two == also_two and one != two
    assert (a, ab) == (a2, ab2) == ("a", "a\nb")


def make_daemon(tmp_path):
    router = Router(Config(app_dir=tmp_path), CommandRegistry(tmp_path / "none.yaml"))
    bus = Bus()
    daemon = Daemon(
        Config(app_dir=tmp_path), router, FakeSpeaker(), None, FakeWakeWord(10_000),
        FakeTranscriber([]), bus=bus,
    )  # fmt: skip
    daemon.use_roles(Acting(lambda: parse_roles([TEACHER]), on_change=daemon._role_changed))
    daemon._pause = lambda seconds: None  # no real waiting while the page writes
    return daemon, bus


def test_the_window_comes_up_on_the_act_as_page_once_per_card(tmp_path):
    daemon, bus = make_daemon(tmp_path)
    daemon.router.on_board(1, "x = 4")
    daemon.router.on_board(1, "x = 4\ny = 2")  # the same card grew: no new show
    daemon.router.on_board(2, "z")
    assert bus.pending_events() == [
        ("board", {"id": 1, "text": "x = 4"}), ("show", None), ("page", "roles"),
        ("board", {"id": 1, "text": "x = 4\ny = 2"}),
        ("board", {"id": 2, "text": "z"}), ("show", None), ("page", "roles"),
    ]  # fmt: skip


def test_abdoh_waits_while_the_page_writes_a_line(tmp_path):
    daemon, bus = make_daemon(tmp_path)
    waits = []
    daemon._pause = waits.append
    daemon.router.on_board(1, "x = 4")  # 5 characters
    daemon.router.on_board(1, "x = 4\ny = 2")  # 6 more
    daemon.router.on_board(1, "x = 4\ny = 2\n" + "z" * 1000)  # a long line: at most 3 s
    daemon.router.on_board(2, "a")  # a new card: from the start
    per = 1 / daemon.BOARD_CHARS_PER_SECOND
    assert waits == pytest.approx([5 * per, 6 * per, daemon.BOARD_WAIT_MAX, per])


def test_the_page_writes_as_fast_as_abdoh_waits():
    source = BOARD_JS.read_text(encoding="utf-8")
    assert f"CHARS_PER_SECOND = {Daemon.BOARD_CHARS_PER_SECOND};" in source


def test_a_new_role_or_none_clears_the_board(tmp_path):
    daemon, bus = make_daemon(tmp_path)
    daemon.acting.start("Math teacher")
    assert ("board", None) in bus.pending_events()
    daemon.acting.stop()
    assert ("board", None) in bus.pending_events()


def test_the_page_keeps_the_board_until_cleared(tmp_path):
    state = UiState()
    for i in range(35):
        state.feed("board", {"id": i, "text": f"item {i}"})
    state.feed("board", {"id": 34, "text": "item 34, grown"})  # the newest card grew
    board = state.snapshot()["board"]
    assert len(board) == 30 and board[0]["id"] == 5  # the newest 30
    assert board[-1] == {"id": 34, "text": "item 34, grown"} and board[-2]["id"] == 33
    api = AppApi(Bus(), state, Config(app_dir=tmp_path))
    api.clear_board()
    assert state.snapshot()["board"] == []


# ----- board.js -----


def test_board_js_never_turns_text_into_html():
    source = BOARD_JS.read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("/*"))
    assert "innerHTML" not in code.replace("(never innerHTML)", "")
    assert "html:" not in code and "insertAdjacentHTML" not in code and "outerHTML" not in code


def node_board(js: str):
    """Run js in Node with B = board.js; it calls done(value) with what to give back."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js isn't installed")
    script = (
        f"const B = require({json.dumps(str(BOARD_JS))});"
        "const done = (v) => process.stdout.write(JSON.stringify(v));" + js
    )
    out = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def parse(text: str):
    return node_board(f"done(B.parse({json.dumps(text)}));")


def written(text: str) -> list[str]:
    """The board's text as it's written out, step by step."""
    return node_board(
        f"const t = {json.dumps(text)}; done(B.stops(t).map((at) => t.slice(0, at)));"
    )


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


# ----- math (KaTeX) -----


def test_board_math():
    blocks = parse(
        "$$x = \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}$$\n"
        "So $a = 1$ and \\(b = -1\\); it costs $5 and $10.\n"
        "$$\n\\int_0^1 x\\,dx\n$$\n"
        "\\[ e^{i\\pi} + 1 = 0 \\]"
    )
    assert [b["type"] for b in blocks] == ["math", "para", "math", "math"]
    assert blocks[0]["text"] == "x = \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}"
    assert blocks[1]["spans"] == [
        {"t": "text", "text": "So "}, {"t": "math", "text": "a = 1"},
        {"t": "text", "text": " and "}, {"t": "math", "text": "b = -1"},
        {"t": "text", "text": "; it costs $5 and $10."},
    ]  # fmt: skip
    assert blocks[2]["text"] == "\\int_0^1 x\\,dx" and blocks[3]["text"] == "e^{i\\pi} + 1 = 0"


def test_math_in_code_stays_code():
    [block] = parse("```bash\necho $HOME $$\n```")
    assert block == {"type": "code", "lang": "bash", "text": "echo $HOME $$"}


# ----- written out like on a whiteboard -----


def test_the_board_is_written_word_by_word():
    assert written("## Binary search\nWe use **two pointers** here") == [
        "## Binary",  # never a lone "##"
        "## Binary search",
        "## Binary search\nWe",
        "## Binary search\nWe use",
        "## Binary search\nWe use **two pointers**",  # bold as one
        "## Binary search\nWe use **two pointers** here",
    ]


def test_code_is_written_word_by_word_with_its_indent():
    assert written("```python\nwhile low <= high:\n    mid = 1") == [
        "```python",
        "```python\nwhile",
        "```python\nwhile low",
        "```python\nwhile low <=",
        "```python\nwhile low <= high:",
        "```python\nwhile low <= high:\n    mid",
        "```python\nwhile low <= high:\n    mid =",
        "```python\nwhile low <= high:\n    mid = 1",
    ]


def test_a_formula_appears_whole():
    assert written("Here $\\frac{a}{b}$ goes") == [
        "Here",
        "Here $\\frac{a}{b}$",
        "Here $\\frac{a}{b}$ goes",
    ]
    assert written("$$x^2 + y^2$$\n| a | b |") == ["$$x^2 + y^2$$", "$$x^2 + y^2$$\n| a | b |"]
    # a formula of several lines: nothing of it until it's closed
    assert written("So\n$$\nx = 1") == ["So"]
    assert written("So\n$$\nx = 1\n$$") == ["So", "So\n$$\nx = 1\n$$"]


def test_the_typist_writes_on_where_it_was():
    drawn = node_board("""
        const drawn = [];
        const t = new B.Typist((text) => drawn.push(text), 1e6);
        t.set({ id: 1, text: "def f(x):" });
        setTimeout(() => {
          t.set({ id: 1, text: "def f(x):\\n    return x" });  // the same card grew
          setTimeout(() => {
            const before = drawn.length;
            t.set({ id: 2, text: "Next" });  // a new card: from the start
            setTimeout(() => done({ drawn, shown: t.shown({ id: 1, text: "old" }), before }), 50);
          }, 50);
        }, 50);
    """)
    assert drawn["drawn"] == [
        "def", "def f(x):", "def f(x):\n    return", "def f(x):\n    return x", "Next",
    ]  # fmt: skip
    assert drawn["shown"] == "old"  # an older card is shown whole


def test_katex_is_bundled_and_loaded_before_the_board():
    katex = WEB / "vendor" / "katex"
    assert (katex / "katex.min.js").stat().st_size > 100_000
    assert (katex / "katex.min.css").exists() and (katex / "LICENSE").exists()
    assert len(list((katex / "fonts").glob("*.woff2"))) == 20
    page = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'href="vendor/katex/katex.min.css"' in page
    assert page.index("vendor/katex/katex.min.js") < page.index('src="board.js"')


def test_katex_never_trusts_the_formula():
    source = BOARD_JS.read_text(encoding="utf-8")
    assert "trust: false" in source and "katex.render(" in source


def test_the_package_ships_every_page_file():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = project["tool"]["setuptools"]["package-data"]["abdoh.ui"]
    ui = WEB.parent
    shipped = {p for pattern in patterns for p in ui.glob(pattern) if p.is_file()}
    files = {p for p in WEB.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    assert files - shipped == set()
