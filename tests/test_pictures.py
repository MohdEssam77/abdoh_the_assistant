"""Pictures on the board: found on Wikimedia Commons or Openverse, or from a link. A fake network
(httpx.MockTransport): no internet."""

import json
import os
import time

import httpx
import pytest

from abdoh.pictures import (
    COMMONS,
    OPENVERSE,
    PictureError,
    Pictures,
    picture_lines,
)

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 2000
COMMONS_FOUND = {
    "query": {
        "pages": {
            "1": {
                "index": 1,
                "title": "File:Spaghetti carbonara.jpg",
                "imageinfo": [{
                    "mime": "image/jpeg",
                    "thumburl": "https://upload.wikimedia.org/thumb/carbonara.jpg",
                    "extmetadata": {
                        "Artist": {"value": '<a href="//commons.org/wiki/User:J">Javier S.</a>'},
                        "LicenseShortName": {"value": "CC BY-SA 4.0"},
                    },
                }],
            },
            "2": {"index": 2, "title": "File:Recipe.pdf",
                  "imageinfo": [{"mime": "application/pdf"}]},
        }
    }
}  # fmt: skip
OPENVERSE_FOUND = {
    "results": [{
        "url": "https://live.staticflickr.com/pizza.jpg", "creator": "joyosity", "license": "by",
        "license_version": "2.0", "source": "flickr", "title": "Margherita Pizza",
    }]
}  # fmt: skip


def network(commons=COMMONS_FOUND, openverse=OPENVERSE_FOUND, image=JPEG, mime="image/jpeg",
            status=200):  # fmt: skip
    asked = []

    def handle(request: httpx.Request):
        url = str(request.url)
        asked.append(url.split("?")[0])
        if url.startswith(COMMONS):
            return httpx.Response(200, json=commons)
        if url.startswith(OPENVERSE):
            return httpx.Response(status if status != 200 else 200, json=openverse)
        return httpx.Response(200, content=image, headers={"content-type": mime})

    client = httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True)
    return client, asked


def test_a_search_finds_a_picture_on_commons_with_its_credit(tmp_path):
    client, asked = network()
    picture = Pictures(tmp_path, client).find("spaghetti carbonara")
    assert picture.credit == "Photo: Javier S., CC BY-SA 4.0, Wikimedia Commons"
    assert picture.title == "Spaghetti carbonara" and picture.mime == "image/jpeg"
    assert picture.path.parent == tmp_path and picture.path.read_bytes() == JPEG
    assert picture.data_url().startswith("data:image/jpeg;base64,/9j/")
    assert asked == [COMMONS, "https://upload.wikimedia.org/thumb/carbonara.jpg"]  # no Openverse


def test_found_once_kept_after(tmp_path):
    client, asked = network()
    pictures = Pictures(tmp_path, client)
    pictures.find("spaghetti carbonara")
    asked.clear()
    pictures.find("spaghetti carbonara")
    assert asked == [COMMONS]  # searched, but the picture itself isn't downloaded again


def test_openverse_when_commons_has_nothing(tmp_path):
    client, asked = network(commons={"query": {"pages": {}}})
    picture = Pictures(tmp_path, client).find("margherita pizza")
    assert picture.credit == "Photo: joyosity, CC BY 2.0, flickr"
    assert asked[1].startswith(OPENVERSE)


def test_nothing_found(tmp_path):
    client, _ = network(commons={"query": {}}, openverse={"results": []})
    with pytest.raises(PictureError, match="couldn't find a picture of qwxzv"):
        Pictures(tmp_path, client).find("qwxzv")


def test_openverse_busy(tmp_path):
    client, _ = network(commons={}, status=429)
    with pytest.raises(PictureError, match="busy"):
        Pictures(tmp_path, client).find("pizza")


def test_a_link_claude_found(tmp_path):
    client, asked = network()
    picture = Pictures(tmp_path, client).find("https://example.org/photos/basil.jpg")
    assert picture.credit == "From example.org" and asked == [
        "https://example.org/photos/basil.jpg"
    ]
    with pytest.raises(PictureError, match="secure"):
        Pictures(tmp_path, client).find("http://example.org/basil.jpg")


@pytest.mark.parametrize(
    "size, mime, said",
    [(6, "text/html", "isn't a picture"), (2001, "image/png", "too big")],
    ids=["not a picture", "too big"],
)
def test_what_isnt_a_picture_or_is_too_big(tmp_path, monkeypatch, size, mime, said):
    monkeypatch.setattr("abdoh.pictures.MAX_BYTES", 2000)
    client, _ = network(image=b"x" * size, mime=mime)
    with pytest.raises(PictureError, match=said):
        Pictures(tmp_path, client).find("https://example.org/x")
    assert list(tmp_path.glob("*")) == []  # nothing kept


def test_old_pictures_go_after_a_week(tmp_path):
    old, new = tmp_path / "old.jpg", tmp_path / "new.jpg"
    old.write_bytes(JPEG)
    new.write_bytes(JPEG)
    week_ago = time.time() - 8 * 86400
    os.utime(old, (week_ago, week_ago))
    assert Pictures(tmp_path).clean() == 1
    assert not old.exists() and new.exists()


def test_a_long_wish_is_searched_shorter_too():
    """Claude asked for "authentic Roman spaghetti carbonara with guanciale and pecorino":
    nothing on Commons; "spaghetti carbonara guanciale" and shorter find it (2026-11-25)."""
    from abdoh.pictures import MAX_SEARCHES, searches

    tries = searches("authentic Roman spaghetti carbonara with guanciale and pecorino")
    assert tries[0] == "authentic Roman spaghetti carbonara with guanciale and pecorino"
    assert tries[1] == "Roman spaghetti carbonara guanciale pecorino"  # no filler words
    assert "spaghetti carbonara guanciale" in tries and len(tries) == MAX_SEARCHES
    assert searches("pizza") == ["pizza"]


def test_the_picture_lines_on_a_board():
    text = (
        "Here:\n[picture: spaghetti carbonara]\nand [picture: not alone] here\n"
        "  [Picture: https://x.org/a.png] "
    )
    assert picture_lines(text) == ["spaghetti carbonara", "https://x.org/a.png"]


def test_the_daemon_finds_them_while_the_board_fills(tmp_path):
    from abdoh.config import Config
    from abdoh.daemon import Daemon
    from abdoh.events import Bus
    from abdoh.ui.api import UiState

    class Found:
        def find(self, what):
            if what == "nothing":
                raise PictureError("I couldn't find a picture of nothing.")
            (tmp_path / "p.jpg").write_bytes(JPEG)
            from abdoh.pictures import Picture

            return Picture(tmp_path / "p.jpg", "image/jpeg", "Photo: X, CC BY 4.0", "P")

    daemon = Daemon.__new__(Daemon)
    daemon.bus, daemon.cfg = Bus(), Config(app_dir=tmp_path)
    daemon._pictures, daemon._pictures_asked = Found(), set()
    daemon._find_pictures("Look:\n[picture: carbonara]\n[picture: nothing]")
    daemon._find_pictures("Look:\n[picture: carbonara]\n[picture: nothing]\nMore")  # once each
    state = UiState()
    for _ in range(100):
        for kind, value in daemon.bus.pending_events():
            state.feed(kind, value)
        if len(state.snapshot()["pictures"]) == 2:
            break
        time.sleep(0.02)
    pictures = state.snapshot()["pictures"]
    assert pictures["carbonara"]["ok"] and pictures["carbonara"]["src"].startswith(
        "data:image/jpeg"
    )
    assert pictures["nothing"] == {"what": "nothing", "ok": False,
                                   "error": "I couldn't find a picture of nothing."}  # fmt: skip
    state.feed("board", None)  # a new role: a clean board, no pictures
    assert state.snapshot()["pictures"] == {}


def test_claude_hears_how_to_ask_for_a_picture():
    from abdoh.roles.acting import BOARD

    assert "[picture:" in BOARD and "real private people" in BOARD


def test_the_board_shows_a_picture_whole(tmp_path):
    from test_board import node_board, written

    blocks = node_board("done(B.parse('Look:\\n[picture: carbonara]\\nTasty'));")
    assert [b["type"] for b in blocks] == ["para", "picture", "para"]
    assert blocks[1]["what"] == "carbonara"
    assert "Look:\n[picture: carbonara]" in written("Look:\n[picture: carbonara]\nTasty")
    assert not any(s.endswith("[picture:") for s in written("Look:\n[picture: carbonara]"))
    json.dumps(blocks)
