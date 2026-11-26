"""The board as a PDF: the printable page, Edge (a fake one here), and "save the board"."""

import subprocess
import time
from datetime import datetime
from pathlib import Path

import pytest
from test_router import FakeBrain

from abdoh.board_pdf import BoardPdfError, file_name, page, save
from abdoh.events import Bus

WHEN = datetime(2026, 11, 25, 12, 3)
CARD = '<div class="board-item"><h3>DFA</h3><svg viewBox="0 0 10 10"><circle r="4"/></svg></div>'


@pytest.fixture(autouse=True)
def quick_waits(monkeypatch):
    """Edge's waits, short: a missing PDF is known in a moment here."""
    monkeypatch.setattr("abdoh.board_pdf.WAIT_SECONDS", 1.0)
    monkeypatch.setattr("abdoh.board_pdf.FAILED_WAIT_SECONDS", 0.05)
    monkeypatch.setattr("abdoh.board_pdf.POLL_SECONDS", 0.02)
    monkeypatch.setattr("abdoh.board_pdf.RETRY_SECONDS", 0)


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
        Path(target).write_bytes(b"%PDF-1.7 board\n%%EOF\n")


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
    long = "Theoretical computer science professor who explains clearly board"
    assert file_name(long, WHEN) == (  # cut at 60 letters: no space left before the date
        "Theoretical computer science professor who explains clearly 2026-11-25 12-03.pdf"
    )


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
    assert bus.next_request(timeout=0) == ("board_pdf_done", True)  # the watchdog stops
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


# ----- what went wrong is in the log, and Abdoh always hears back (the owner's three saves that
# left nothing, 2026-11-26) -----


class Done:
    def __init__(self, returncode=0, stderr=b""):
        self.returncode, self.stderr = returncode, stderr


def test_edge_gets_a_second_try(tmp_path, monkeypatch):
    monkeypatch.setattr("abdoh.board_pdf.RETRY_SECONDS", 0)
    tries = []

    def edge(args, **kwargs):
        tries.append(args)
        if len(tries) == 2:
            return FakeEdge()(args)
        return Done(1, b"[ERROR] something went wrong")

    pdf = save([CARD], "Board", tmp_path, edge=Path("msedge.exe"), run=edge, when=WHEN)
    assert pdf.exists() and len(tries) == 2
    profiles = [next(a for a in t if a.startswith("--user-data-dir=")) for t in tries]
    assert profiles[0] != profiles[1]  # a fresh profile each time


def test_what_edge_said_goes_to_the_log(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr("abdoh.board_pdf.RETRY_SECONDS", 0)
    edge = lambda args, **kwargs: Done(21, b"Fatal:\n  can't open the profile")  # noqa: E731
    with pytest.raises(BoardPdfError):
        save([CARD], "Board", tmp_path, edge=Path("msedge.exe"), run=edge, when=WHEN)
    said = [r.getMessage() for r in caplog.records if "made no PDF" in r.getMessage()]
    assert len(said) == 2 and "exit code 21" in said[0] and "can't open the profile" in said[0]


def make_api(tmp_path):
    from abdoh.config import Config
    from abdoh.ui.api import AppApi, UiState

    bus = Bus()
    return AppApi(bus, UiState(), Config(app_dir=tmp_path), open_path=lambda p: None), bus


def requests(bus):
    out = []
    while (request := bus.next_request(timeout=0)) is not None:
        out.append(request)
    return out


def test_when_edge_makes_nothing_abdoh_says_so_and_offers_the_print_dialog(tmp_path, monkeypatch):
    from abdoh.ui.api import PRINT_INSTEAD

    monkeypatch.setattr("abdoh.board_pdf.boards_folder", lambda documents=None: tmp_path)
    monkeypatch.setattr("abdoh.board_pdf.find_edge", lambda: Path("msedge.exe"))
    monkeypatch.setattr("abdoh.board_pdf.subprocess.run", lambda *a, **k: Done(1))
    monkeypatch.setattr("abdoh.board_pdf.RETRY_SECONDS", 0)
    api, bus = make_api(tmp_path)
    result = api.board_pdf([CARD], "Board", True)
    assert result["ok"] is False and result["print"] is True
    assert requests(bus) == [
        ("say", "The PDF couldn't be made." + PRINT_INSTEAD),
        ("board_pdf_done", False),
    ]


def test_an_unexpected_error_is_said_too(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr("abdoh.board_pdf.save", broken)
    api, bus = make_api(tmp_path)
    assert api.board_pdf([CARD], "Board", True)["ok"] is False
    said = requests(bus)
    assert said[0][0] == "say" and said[0][1].startswith("The PDF couldn't be made.")
    assert said[-1] == ("board_pdf_done", False)


def test_an_empty_board_is_said(tmp_path):
    api, bus = make_api(tmp_path)
    result = api.board_pdf([], "Board", True)
    assert result["ok"] is False and result["print"] is False
    assert requests(bus) == [("say", "The board is empty."), ("board_pdf_done", False)]


def test_the_page_failing_to_draw_the_board_is_said(tmp_path):
    api, bus = make_api(tmp_path)
    api.board_pdf_failed("TypeError: x is undefined", True)
    said = requests(bus)
    assert said[0] == ("say", "The board couldn't be saved: drawing it for the PDF failed.")
    assert said[-1] == ("board_pdf_done", False)


def watched_daemon(monkeypatch):
    from abdoh import daemon as module
    from abdoh.daemon import Daemon

    monkeypatch.setattr(module, "BOARD_PDF_SECONDS", 0.05)
    daemon = Daemon.__new__(Daemon)
    daemon.bus = Bus()
    daemon.bus.ui_attached = True
    said = []
    daemon._say_aside = said.append
    return daemon, said


def test_a_window_that_doesnt_answer_is_said(monkeypatch):
    import time

    from abdoh.daemon import BOARD_PDF_SILENT

    daemon, said = watched_daemon(monkeypatch)
    daemon._save_board()
    assert ("save_board", None) in daemon.bus.pending_events()
    time.sleep(0.2)
    assert said == [BOARD_PDF_SILENT]


def test_a_window_that_answers_stops_the_watchdog(monkeypatch):
    import time

    daemon, said = watched_daemon(monkeypatch)
    daemon._save_board()
    daemon.handle_request("board_pdf_done", True)
    time.sleep(0.2)
    assert said == []


def test_done_says_saving_the_board_in_words():
    from abdoh.daemon import _what_was_done

    assert _what_was_done([("board_pdf", "now")]) == "Done: saving the board as a PDF."
    assert _what_was_done([("open_app", "Spotify")]) == "Done: open app Spotify."


# ----- Edge returning before the PDF is written (the owner's Abdoh, 2026-11-27 00:31) -----


def test_edge_returning_early_is_waited_for(tmp_path, monkeypatch):
    """Edge handed the print off and returned at once; the PDF came a moment later."""
    import threading

    monkeypatch.setattr("abdoh.board_pdf.POLL_SECONDS", 0.02)
    tries = []

    def edge(args, **kwargs):
        tries.append(args)
        target = Path(next(a for a in args if a.startswith("--print-to-pdf="))[15:])
        page_file = Path(args[-1].replace("file:///", ""))

        def write():
            time.sleep(0.15)
            assert page_file.exists()  # the page is still there for Edge
            target.write_bytes(b"%PDF-1.7 half")  # being written...
            time.sleep(0.1)
            target.write_bytes(b"%PDF-1.7 board\n%%EOF\n")  # ...finished

        threading.Thread(target=write, daemon=True).start()
        return Done(0)

    pdf = save([CARD], "Board", tmp_path, edge=Path("msedge.exe"), run=edge, when=WHEN)
    assert pdf.read_bytes().endswith(b"%%EOF\n") and len(tries) == 1  # no second Edge


def test_a_half_written_pdf_isnt_finished(tmp_path):
    from abdoh.board_pdf import finished, wait_for

    pdf = tmp_path / "b.pdf"
    assert not finished(pdf)
    pdf.write_bytes(b"%PDF-1.7 half")
    assert not finished(pdf)
    clock = iter([0.0, 1.0, 2.0, 99.0]).__next__
    assert not wait_for(pdf, 5, sleep=lambda s: None, clock=clock)
    pdf.write_bytes(b"%PDF-1.7\n%%EOF")
    assert finished(pdf)


def test_edges_files_it_couldnt_let_go_of_are_tidied_later(tmp_path):
    import os

    from abdoh.board_pdf import _tidy_leftovers

    old, new, other = (tmp_path / n for n in ("abdoh-board-old", "abdoh-board-new", "keep-me"))
    for folder in (old, new, other):
        (folder / "edge-profile-1" / "Crashpad").mkdir(parents=True)
    os.utime(old, (0, 0))
    os.utime(other, (0, 0))
    _tidy_leftovers(tmp_path, now=10_000.0 + 3600 * 2)
    assert not old.exists() and new.exists() and other.exists()
