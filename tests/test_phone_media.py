"""Pictures and files for the phone behind secret links (ABDOH_EPIC_11.md, story 148): the
store, the links, pictures of the screen after opening something and when asked."""

import io
import threading

import pytest
from PIL import Image
from test_daemon import StubRouter, make_daemon
from test_phone import Clock, Recorder, call, make_app, paired
from test_router import FakeAct, FakeBrain, text_of

from abdoh.claude.screen import ScreenCaptureError
from abdoh.commands.registry import CommandRegistry
from abdoh.config import Config
from abdoh.events import Bus
from abdoh.phone.media import MAX_PICTURES, MediaStore, file_kind, file_type, screen_picture
from abdoh.phone.server import _handler
from abdoh.router import Router


def jpeg(color=(200, 30, 30), size=(64, 40)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "JPEG")
    return out.getvalue()


# ----- the store -----


def test_pictures_and_files_behind_secret_links(tmp_path):
    clock = Clock()
    store = MediaStore(clock)
    key = store.add_picture(b"JPEG")
    assert len(key) == 32 and store.get(key).data == b"JPEG"
    cv = tmp_path / "CV.pdf"
    cv.write_bytes(b"%PDF-1.7")
    found = store.get(store.add_file(cv))
    assert (found.name, found.type, found.size) == ("CV.pdf", "application/pdf", 8)
    assert found.data is None and found.path == cv
    assert store.get("0" * 32) is None and store.get("") is None
    clock.now += 3601
    assert store.get(key) is None  # an hour at most


def test_only_the_newest_pictures_are_kept():
    store = MediaStore(Clock())
    keys = [store.add_picture(b"x") for _ in range(MAX_PICTURES + 5)]
    assert store.get(keys[0]) is None and store.get(keys[-1]) is not None
    with pytest.raises(ValueError):
        store.add_picture(b"")


def test_file_kinds():
    assert file_type("notes.txt") == "text/plain" and file_kind("text/plain") == "text"
    assert file_kind(file_type("photo.JPG")) == "image"
    assert file_kind(file_type("song.mp3")) == "audio"
    assert file_kind(file_type("report.pdf")) == "pdf"
    assert file_kind(file_type("archive.zip")) == "file"
    assert file_type("IMG_0001.HEIC") == "image/heic"


def test_a_picture_of_the_screen_for_the_phone():
    big = Image.new("RGB", (3200, 1800), (40, 90, 160))
    data = screen_picture(grab=lambda which: big)
    shot = Image.open(io.BytesIO(data))
    assert shot.format == "JPEG" and shot.size == (1600, 900)
    with pytest.raises(ScreenCaptureError, match="locked"):
        screen_picture(grab=lambda which: Image.new("RGB", (100, 100)))

    def broken(which):
        raise OSError("no screen")

    with pytest.raises(ScreenCaptureError):
        screen_picture(grab=broken)


# ----- the links -----


def test_a_picture_link_needs_no_key_but_its_secret(tmp_path):
    bus, hub, phones, app = make_app(tmp_path)
    key = hub.media.add_picture(b"JPEG")
    response, _ = call(app, "GET", f"/media/{key}")  # an <img> can't send the phone's key
    assert response.status == 200 and response.body == b"JPEG" and response.type == "image/jpeg"
    assert "sandbox" in response.headers["Content-Security-Policy"]
    assert call(app, "GET", f"/media/{'a' * 32}")[0].status == 404
    assert call(app, "GET", "/media/not-a-key")[0].status == 404
    assert call(app, "POST", f"/media/{key}")[0].status == 405


def test_files_are_sent_from_disk_in_pieces(tmp_path):
    bus, hub, phones, app = make_app(tmp_path)
    video = tmp_path / "clip.mp4"
    video.write_bytes(bytes(range(256)) * 4)
    key = hub.media.add_file(video)
    response, _ = call(app, "GET", f"/media/{key}")
    assert response.path == video and response.size == 1024 and response.body == b""
    assert response.headers["Content-Disposition"] == "inline; filename*=UTF-8''clip.mp4"
    response, _ = call(app, "GET", f"/media/{key}?download=1", range="bytes=1000-")
    assert response.status == 206 and (response.start, response.size) == (1000, 24)
    assert response.headers["Content-Range"] == "bytes 1000-1023/1024"
    assert response.headers["Content-Disposition"].startswith("attachment")
    response, _ = call(app, "GET", f"/media/{key}", range="bytes=-100")
    assert (response.start, response.size) == (924, 100)
    assert call(app, "GET", f"/media/{key}", range="bytes=5000-")[0].status == 416
    video.unlink()
    assert call(app, "GET", f"/media/{key}")[0].status == 404


def test_a_web_page_or_svg_is_only_downloaded(tmp_path):
    """Opened as a page of this site, a sent HTML or SVG file could read the phone's key."""
    bus, hub, phones, app = make_app(tmp_path)
    for name in ("page.html", "drawing.svg"):
        path = tmp_path / name
        path.write_text("<script>alert(1)</script>")
        response, _ = call(app, "GET", f"/media/{hub.media.add_file(path)}")
        assert response.type == "application/octet-stream"
        assert response.headers["Content-Disposition"].startswith("attachment")


def test_the_server_streams_the_file(tmp_path):
    bus, hub, phones, app = make_app(tmp_path)
    data = bytes(range(256)) * 2000
    path = tmp_path / "big.bin"
    path.write_bytes(data)
    response, _ = call(app, "GET", f"/media/{hub.media.add_file(path)}", range="bytes=10-")
    handler = _handler(app).__new__(_handler(app))
    handler.wfile = io.BytesIO()
    handler.request_version = "HTTP/1.1"
    handler.requestline = "GET / HTTP/1.1"
    handler.command = "GET"
    handler.client_address = ("127.0.0.1", 0)
    handler._send(response, "GET")
    sent = handler.wfile.getvalue()
    head, body = sent.split(b"\r\n\r\n", 1)
    assert b"206" in head.split(b"\r\n")[0] and f"Content-Length: {len(data) - 10}".encode() in head
    assert body == data[10:]


def test_see_the_screen(tmp_path):
    shots = [jpeg()]
    bus, hub, phones, app = make_app(tmp_path, screen=lambda: shots[0])
    key = paired(app, phones)
    response, data = call(app, "POST", "/api/screen", key=key)
    assert data["ok"] and call(app, "GET", f"/media/{data['id']}")[0].body == shots[0]
    assert call(app, "POST", "/api/screen")[0].status == 401  # only a paired phone asks

    def locked():
        raise ScreenCaptureError("The screen is off or locked, so its picture is all black.")

    (tmp_path / "2").mkdir()
    _, hub2, phones2, app2 = make_app(tmp_path / "2", screen=locked)
    response, data = call(app2, "POST", "/api/screen", key=paired(app2, phones2))
    assert response.status == 400 and "locked" in data["error"]


# ----- in the conversation -----


def test_a_picture_falls_where_it_was_sent(tmp_path):
    bus, hub, phones, app = make_app(tmp_path)
    hub.ask("open spotify", phone="p1")
    hub.take("history", "You (phone): open spotify")
    hub.take("history", "Abdoh: Done: open app Spotify.")
    hub.take("phone_image", {"data": b"JPEG", "caption": "Opened Spotify"})
    event = hub.events(2, wait=0)["events"][0]
    assert (event["type"], event["caption"], event["for"]) == ("image", "Opened Spotify", "p1")
    state = hub.state()
    assert state["first_line"] == 0 and state["media"][0]["line"] == 2
    hub.take("phone_image", {"data": b"", "caption": "nothing"})  # an empty picture: dropped


def test_after_opening_something_the_phone_gets_the_screen(monkeypatch):
    import abdoh.daemon as daemon_module

    monkeypatch.setattr(daemon_module, "PHONE_SHOT_SECONDS", 0.01)
    bus = Bus(ui_attached=False)
    seen = Recorder(bus)
    daemon = make_daemon(StubRouter([]), bus=bus)
    sent = threading.Event()
    daemon._grab_screen = lambda app="": (sent.set(), (b"JPEG", "", "follow"))[1]
    daemon._phone_turn = True
    daemon._did("open_app", "Spotify")
    daemon._did("media", "next")  # not an opening: no picture of its own
    assert sent.wait(2)
    _wait_for(lambda: seen.of("phone_image"))
    assert seen.of("phone_image") == [{"data": b"JPEG", "caption": "Opened Spotify"}]
    daemon._phone_turn = False
    daemon._did("open_app", "Spotify")  # at the laptop: nothing for the phone
    assert len(seen.of("phone_step")) == 2


def test_a_screen_that_cant_be_seen_is_said_on_the_phone():
    bus = Bus(ui_attached=False)
    seen = Recorder(bus)
    daemon = make_daemon(StubRouter([]), bus=bus)

    def locked(app=""):
        raise ScreenCaptureError("The screen is off or locked, so its picture is all black.")

    daemon._grab_screen = locked
    daemon._show_screen("they asked")
    _wait_for(lambda: seen.of("phone_note"))
    assert "locked" in seen.of("phone_note")[0]


def test_show_screen_is_only_for_the_phone(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text("[]", encoding="utf-8")
    router = Router(Config(app_dir=tmp_path), CommandRegistry(path), act=FakeAct())
    shown = []
    router.on_show_screen = shown.append
    router.brain = FakeBrain(["ACTION show_screen: they want to see it\n", "Here it is."])
    router.phone = True
    assert text_of(router.handle("show me my screen")) == "Here it is."
    assert shown == ["they want to see it"]
    router.phone = False
    router.brain = FakeBrain(["ACTION show_screen: no\n", "Sure."])
    text_of(router.handle("show me my screen"))
    assert shown == ["they want to see it"]  # at the laptop: not an action at all


def _wait_for(check, seconds=2.0):
    import time

    end = time.monotonic() + seconds
    while not check() and time.monotonic() < end:
        time.sleep(0.01)
    assert check()


def test_show_screen_after_opening_waits_for_what_was_opened(monkeypatch):
    import abdoh.daemon as daemon_module

    monkeypatch.setattr(daemon_module, "PHONE_SHOT_SECONDS", 0.2)
    bus = Bus(ui_attached=False)
    seen = Recorder(bus)
    daemon = make_daemon(StubRouter([]), bus=bus)
    daemon._grab_screen = lambda app="": (b"JPEG", "", "follow")
    daemon._phone_turn = True
    daemon._did("open_app", "Spotify")
    daemon._show_screen("they want to see it")  # the picture after opening covers it
    _wait_for(lambda: seen.of("phone_image"))
    import time

    time.sleep(0.3)
    pictures = seen.of("phone_image")
    assert len(pictures) == 1 and pictures[0]["caption"] == "Opened Spotify"
