"""The board as a PDF on the phone (ABDOH_EPIC_11.md, story 154): the phone's Save as PDF, or
asking in any words; the computer makes it the way its window does and sends it as a file."""

import time
from pathlib import Path

import pytest
from test_board_pdf import CARD, make_api, requests, watched_daemon
from test_phone import Recorder, call, make_app, make_hub, paired
from test_router import FakeAct, FakeBrain, text_of

from abdoh.commands.registry import CommandRegistry
from abdoh.config import Config
from abdoh.daemon import BOARD_PDF_SILENT_PHONE
from abdoh.router import Router


def test_save_as_pdf_on_the_phone(tmp_path):
    bus, hub, phones, app = make_app(tmp_path)
    key = paired(app, phones)
    response, data = call(app, "POST", "/api/board_pdf", key=key)
    assert response.status == 400 and data["error"] == "There's nothing on the board yet."
    hub.take("board", {"id": 1, "text": "## Merge sort"})
    _, data = call(app, "POST", "/api/board_pdf", key=key)
    assert data == {"ok": True}
    assert bus.next_request(0) == ("phone_board_pdf", {"phone": phones.list()[0]["id"]})
    assert call(app, "POST", "/api/board_pdf")[0].status == 401


def test_the_pdf_goes_to_the_phone_that_asked(monkeypatch, tmp_path):
    daemon, said = watched_daemon(monkeypatch)
    seen = Recorder(daemon.bus)
    daemon.handle_request("phone_board_pdf", {"phone": "p1"})
    assert ("save_board", {"phone": True}) in daemon.bus.pending_events()
    pdf = tmp_path / "Board.pdf"
    daemon.handle_request("board_pdf_done", {"ok": True, "path": str(pdf)})
    time.sleep(0.1)  # the watchdog is stopped: nothing said on the laptop
    assert seen.of("phone_file") == [{"path": str(pdf), "for": "p1"}] and said == []


def test_why_it_couldnt_be_made_goes_to_the_phone(monkeypatch):
    daemon, said = watched_daemon(monkeypatch)
    seen = Recorder(daemon.bus)
    daemon._phone_turn = True  # asked in words, from the phone ("send me the board as a PDF")
    daemon._save_board()
    daemon.handle_request("board_pdf_done", {"ok": False, "error": "The board is empty."})
    assert seen.of("phone_note") == [{"text": "The board is empty.", "for": ""}]
    daemon._phone_turn = False
    daemon.handle_request("phone_board_pdf", {"phone": "p1"})
    time.sleep(0.2)  # the window never answers
    assert seen.of("phone_note")[-1] == {"text": BOARD_PDF_SILENT_PHONE, "for": "p1"}
    assert said == []  # nothing out loud on the laptop


def test_the_laptops_own_pdf_is_as_before(monkeypatch):
    daemon, said = watched_daemon(monkeypatch)
    seen = Recorder(daemon.bus)
    daemon._save_board()
    assert ("save_board", None) in daemon.bus.pending_events()
    daemon.handle_request("board_pdf_done", True)
    assert seen.of("phone_file") == [] and seen.of("phone_note") == []


def test_the_window_makes_it_for_the_phone_without_opening_it_here(tmp_path, monkeypatch):
    from abdoh.board_pdf import BoardPdfError

    def save(cards, title):
        if not cards:
            raise BoardPdfError("The board is empty.")
        return tmp_path / "Board.pdf"

    opened = []
    monkeypatch.setattr("abdoh.board_pdf.save", save)
    api, bus = make_api(tmp_path)
    api._open_path = opened.append
    result = api.board_pdf([CARD], "Board", False, True)
    assert result["ok"] and opened == []  # not opened on the laptop
    assert requests(bus) == [("board_pdf_done", {"ok": True, "path": str(tmp_path / "Board.pdf")})]
    result = api.board_pdf([], "Board", False, True)  # empty: why, for the phone, not said here
    assert requests(bus) == [("board_pdf_done", {"ok": False, "error": "The board is empty."})]
    assert result["print"] is False
    api.board_pdf_failed("TypeError", False, True)
    assert requests(bus)[-1][1]["ok"] is False


def test_asking_in_any_words_from_the_phone_works_without_a_role(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text("[]", encoding="utf-8")
    router = Router(Config(app_dir=tmp_path), CommandRegistry(path), act=FakeAct())
    asked = []
    router.on_board_pdf = lambda: asked.append(True)
    router.brain = FakeBrain(["ACTION board_pdf: now\n", "Making it a PDF for you."])
    router.phone = True
    text_of(router.handle("can I keep this explanation?"))
    assert asked == [True]
    router.phone = False
    router.brain = FakeBrain(["ACTION board_pdf: now\n", "Sure."])
    text_of(router.handle("can I keep this explanation?"))
    assert asked == [True]  # at the laptop without a role: as before, not an action


def test_a_file_and_a_note_can_say_which_phone():
    bus, hub = make_hub()
    hub.ask("hi", phone="p2")
    hub.take("phone_note", {"text": "The board is empty.", "for": "p1"})
    hub.take("phone_note", "A plain line")
    events = hub.events(0, wait=0)["events"]
    notes = [(e["text"], e["for"]) for e in events]
    assert notes == [("The board is empty.", "p1"), ("A plain line", "p2")]


def test_claude_is_told_it_can_send_the_board():
    from abdoh.claude.brain import system_prompt

    assert "ACTION board_pdf: now" in system_prompt(Config())


@pytest.fixture(autouse=True)
def _no_real_windows(monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: Path("C:/Users/test"))
