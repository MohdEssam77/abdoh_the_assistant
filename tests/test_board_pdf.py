"""The board as a PDF: the printable page, Edge (a fake one here), and "save the board"."""

import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from test_router import FakeBrain

from abdoh.board_pdf import BoardPdfError, file_name, page, save
from abdoh.events import Bus

WHEN = datetime(2026, 11, 25, 12, 3)
CARD = '<div class="board-item"><h3>DFA</h3><svg viewBox="0 0 10 10"><circle r="4"/></svg></div>'


class FakeEdge:
    """Writes a PDF where Edge was told to, like Edge does."""

    def __init__(self, works=True):
        self.args = None
        self.works = works

    def __call__(self, args, **kwargs):
        self.args = args
        if not self.works:
            raise subprocess.TimeoutExpired(args, 60)
        target = next(a for a in args if a.startswith("--print-to-pdf="))[len("--print-to-pdf=") :]
        Path(target).write_bytes(b"%PDF-1.7 board")


def test_the_printable_page():
    html = page([CARD], "Chef <board>", WHEN)
    assert html.startswith("<!doctype html>") and "katex.min.css" in html
    assert "<h1>Chef &lt;board&gt;</h1>" in html and "25 November 2026, 12:03" in html
    assert CARD in html and "@page" in html


def test_nothing_that_could_run_gets_into_it():
    sneaky = (
        '<div onclick="steal()"><script>alert(1)</script><img src="x" onerror="x()">'
        '<a href="javascript:alert(2)">a</a><iframe src="https://x"></iframe></div>'
    )
    html = page([sneaky], "Board", WHEN)
    for bad in ("<script", "onclick", "onerror", "javascript:", "<iframe"):
        assert bad not in html.lower()


def test_a_file_name_windows_takes():
    assert (
        file_name("Chef: carbonara / pasta?", WHEN) == "Chef carbonara  pasta 2026-11-25 12-03.pdf"
    )
    assert file_name("...", WHEN) == "Board 2026-11-25 12-03.pdf"


def test_edge_prints_it_in_the_background_with_its_own_profile(tmp_path):
    edge = FakeEdge()
    pdf = save([CARD], "Chef board", tmp_path, edge=Path("msedge.exe"), run=edge, when=WHEN)
    assert pdf == tmp_path / "Chef board 2026-11-25 12-03.pdf" and pdf.read_bytes().startswith(
        b"%PDF"
    )
    assert "--headless" in edge.args and "--no-pdf-header-footer" in edge.args
    assert any(a.startswith("--user-data-dir=") for a in edge.args)  # never the user's Edge
    assert edge.args[-1].startswith("file:///")


@pytest.mark.parametrize(
    "cards, edge, run, said",
    [
        ([], Path("msedge.exe"), FakeEdge(), "empty"),
        ([CARD], None, FakeEdge(), "Edge isn't on this computer"),
        ([CARD], Path("msedge.exe"), FakeEdge(works=False), "couldn't be made"),
        ([CARD], Path("msedge.exe"), lambda args, **k: None, "couldn't be made"),  # no file
    ],
    ids=["empty", "no edge", "edge fails", "no pdf"],
)
def test_when_there_is_no_pdf(tmp_path, monkeypatch, cards, edge, run, said):
    monkeypatch.setattr("abdoh.board_pdf.find_edge", lambda: None)
    with pytest.raises(BoardPdfError, match=said):
        save(cards, "Board", tmp_path, edge=edge, run=run)


def test_the_app_saves_it_and_says_where_when_asked_by_voice(tmp_path, monkeypatch):
    from abdoh.config import Config
    from abdoh.ui.api import AppApi, UiState

    monkeypatch.setattr("abdoh.board_pdf.boards_folder", lambda documents=None: tmp_path)
    monkeypatch.setattr("abdoh.board_pdf.find_edge", lambda: Path("msedge.exe"))
    monkeypatch.setattr("abdoh.board_pdf.subprocess.run", FakeEdge())
    bus = Bus()
    opened = []
    api = AppApi(bus, UiState(), Config(app_dir=tmp_path), open_path=opened.append)
    result = api.board_pdf([CARD], "Chef board", True)
    assert result["ok"] and Path(result["path"]).exists() and opened == [result["path"]]
    assert bus.next_request(timeout=0) == (
        "say",
        "The board is saved as a PDF in your Documents, Abdoh, Boards.",
    )
    monkeypatch.setattr("abdoh.board_pdf.find_edge", lambda: None)
    no_edge = api.board_pdf([CARD], "Chef board", False)
    assert no_edge["ok"] is False and no_edge["print"] is True  # the print dialog instead


def test_claude_saves_the_board_only_while_a_role_is_on(tmp_path):
    from test_roles import make_acting

    from abdoh.commands.registry import CommandRegistry
    from abdoh.config import Config
    from abdoh.router import Router

    path = tmp_path / "commands.yaml"
    path.write_text("[]", encoding="utf-8")
    router = Router(Config(app_dir=tmp_path), CommandRegistry(path))
    router.acting, _ = make_acting()
    asked = []
    router.on_board_pdf = lambda: asked.append(True)
    router.brain = FakeBrain(("ACTION board_pdf: now\n", "Saving it."))
    " ".join(router.handle("save the board"))
    assert asked == []  # no role: not an action Claude has
    router.acting.start("German teacher")
    router.brain = FakeBrain(("ACTION board_pdf: now\n", "Saving it."))
    " ".join(router.handle("save the board"))
    assert asked == [True]


def test_the_daemon_says_what_the_window_asks():
    from abdoh.daemon import Daemon

    daemon = Daemon.__new__(Daemon)
    said = []
    daemon._say_aside = said.append
    daemon.handle_request("say", "The board is saved.")
    assert said == ["The board is saved."]
