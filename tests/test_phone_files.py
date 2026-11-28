"""Files between the computer and the phone, and the clipboard (ABDOH_EPIC_11.md, story 149)."""

import io

import pytest
from test_daemon import StubRouter, make_daemon
from test_phone import Recorder, call, make_app, make_hub, paired
from test_router import FakeAct, FakeBrain, text_of

from abdoh.commands.registry import CommandRegistry
from abdoh.config import Config
from abdoh.events import Bus
from abdoh.phone.files import (
    ABDOHS_OWN,
    FOLDER,
    NOT_A_FILE,
    NOT_ALLOWED,
    NOT_FOUND,
    FileProblem,
    clean_name,
    file_to_send,
    free_path,
    save_upload,
    upload_folder,
)
from abdoh.router import FROM_PHONE, Router


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    (home / "Documents").mkdir(parents=True)
    (home / "Downloads").mkdir()
    (home / "Documents" / "CV.pdf").write_bytes(b"%PDF")
    return home


def config(tmp_path, **claude):
    cfg = Config(app_dir=tmp_path / "home" / "AppData" / "Abdoh")
    for name, value in claude.items():
        setattr(cfg.claude, name, value)
    return cfg


def folders(home):
    return {"Documents": home / "Documents", "Downloads": home / "Downloads"}


# ----- to the phone: only files from where Claude may work -----


def test_a_file_in_the_home_folder_goes(tmp_path, home):
    cv = home / "Documents" / "CV.pdf"
    assert file_to_send(f'"{cv}"', config(tmp_path), home, folders(home)) == cv.resolve()


@pytest.mark.parametrize(
    ("what", "problem"),
    [
        ("", NOT_FOUND),
        ("CV.pdf", NOT_FOUND),  # not a full path
        ("{home}/Documents/missing.pdf", NOT_FOUND),
        ("{home}/Documents", NOT_A_FILE),
        ("{outside}", NOT_ALLOWED),
        ("{app}/phones.json", ABDOHS_OWN),  # keys, paired phones
    ],
)
def test_what_never_goes(tmp_path, home, what, problem):
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("x")
    app = tmp_path / "home" / "AppData" / "Abdoh"
    app.mkdir(parents=True)
    (app / "phones.json").write_text("{}")
    path = what.format(home=home, outside=outside, app=app)
    with pytest.raises(FileProblem) as found:
        file_to_send(path, config(tmp_path), home, folders(home))
    assert str(found.value) == problem


def test_only_the_chosen_folders_when_there_are_some(tmp_path, home):
    cv = home / "Documents" / "CV.pdf"
    chosen = config(tmp_path, folders=[str(home / "Downloads")])
    with pytest.raises(FileProblem, match="folders I may use"):
        file_to_send(str(cv), chosen, home, folders(home))
    with pytest.raises(FileProblem, match="folders I may use"):
        file_to_send(str(cv), config(tmp_path, allow_files=False), home, folders(home))


# ----- from the phone -----


def test_files_from_the_phone_go_to_downloads(tmp_path, home):
    assert upload_folder(config(tmp_path), home, folders(home)) == home / "Downloads" / FOLDER
    chosen = config(tmp_path, folders=[str(home / "Documents")])
    assert upload_folder(chosen, home, folders(home)) == home / "Documents" / FOLDER


def test_names_from_the_phone_are_cleaned():
    assert clean_name("../../Windows/system32/evil.dll") == "evil.dll"
    assert clean_name(r"..\..\x.txt") == "x.txt"
    assert clean_name('a<b>:c"d|e?.jpg') == "a b c d e .jpg"
    assert clean_name("CON.txt") == "_CON.txt"
    assert clean_name("") == clean_name("...") == "file"
    long = clean_name("x" * 300 + ".jpeg")
    assert len(long) <= 100 and long.endswith(".jpeg")


def test_a_saved_file_never_overwrites(tmp_path):
    folder = tmp_path / "in"
    first = save_upload(folder, "photo.jpg", io.BytesIO(b"one"), 3)
    second = save_upload(folder, "photo.jpg", io.BytesIO(b"two"), 3)
    assert (first.name, second.name) == ("photo.jpg", "photo (2).jpg")
    assert first.read_bytes() == b"one" and second.read_bytes() == b"two"
    assert free_path(folder, "photo.jpg").name == "photo (3).jpg"


def test_a_file_too_big_empty_or_cut_short_isnt_saved(tmp_path):
    folder = tmp_path / "in"
    with pytest.raises(FileProblem, match="too big"):
        save_upload(folder, "x.bin", io.BytesIO(b"12345"), 5, limit=4)
    with pytest.raises(FileProblem, match="empty"):
        save_upload(folder, "x.bin", io.BytesIO(b""), 0)
    with pytest.raises(FileProblem, match="whole"):
        save_upload(folder, "x.bin", io.BytesIO(b"12"), 5)
    assert not folder.exists() or list(folder.iterdir()) == []  # no half files left


def test_a_file_sent_from_the_phone_goes_with_the_next_request(tmp_path):
    bus, hub = make_hub(uploads_to=lambda: tmp_path / "in")
    saved = hub.save("homework.jpg", io.BytesIO(b"JPEG"), 4)
    assert (saved["name"], saved["size"], saved["kind"]) == ("homework.jpg", 4, "image")
    text = hub.ask("explain this on the board", phone="p1", files=[saved["id"]])
    assert text == "explain this on the board [sent homework.jpg]"
    kind, request = bus.next_request(0)
    assert request["files"] == [str(tmp_path / "in" / "homework.jpg")]
    assert hub.ask("and again", files=[saved["id"]]) == "and again"  # each file goes once
    photo = hub.save("photo.jpg", io.BytesIO(b"JPEG"), 4)
    assert hub.ask("", files=[photo["id"]]) == "[sent photo.jpg]"  # a file alone is a request


def test_uploading_through_the_page(tmp_path):
    bus, hub, phones, app = make_app(tmp_path, uploads_to=lambda: tmp_path / "in")
    key = paired(app, phones)
    reader = io.BytesIO(b"%PDF-1.7")
    headers = {"authorization": f"Bearer {key}"}
    response = app.upload(headers, "/api/upload?name=Notes%20week%202.pdf", reader, 8)
    data = __import__("json").loads(response.body)
    assert response.status == 200 and data["name"] == "Notes week 2.pdf" and data["kind"] == "pdf"
    unread = io.BytesIO(b"secret")
    assert app.upload({}, "/api/upload?name=x", unread, 6).status == 401
    assert unread.tell() == 0  # nothing read from a phone that isn't paired
    too_big = app.upload(headers, "/api/upload?name=x", io.BytesIO(b""), 200 * 1024**2)
    assert too_big.status == 400 and "too big" in __import__("json").loads(too_big.body)["error"]


def test_the_clipboard_both_ways(tmp_path):
    board = ["Meeting at 3"]
    bus, hub, phones, app = make_app(
        tmp_path, clipboard=lambda: board[0], set_clipboard=lambda text: board.__setitem__(0, text)
    )
    key = paired(app, phones)
    assert call(app, "GET", "/api/clipboard", key=key)[1] == {"ok": True, "text": "Meeting at 3"}
    call(app, "POST", "/api/clipboard", key=key, body={"text": "from the phone"})
    assert board == ["from the phone"]
    assert call(app, "GET", "/api/clipboard")[0].status == 401


# ----- Claude sends a file -----


def router_for(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text("[]", encoding="utf-8")
    return Router(Config(app_dir=tmp_path), CommandRegistry(path), act=FakeAct())


def test_claude_sends_a_file_to_the_phone_only(tmp_path):
    router = router_for(tmp_path)
    sent = []
    router.on_send_file = lambda path: sent.append(path) or ""
    router.brain = FakeBrain(["ACTION send_file: C:/Users/me/CV.pdf\n", "Sent it."])
    router.phone = True
    assert text_of(router.handle("send me my cv")) == "Sent it."
    assert sent == ["C:/Users/me/CV.pdf"]
    router.phone = False
    router.brain = FakeBrain(["ACTION send_file: C:/Users/me/CV.pdf\n", "Sure."])
    text_of(router.handle("send me my cv"))
    assert sent == ["C:/Users/me/CV.pdf"]  # at the laptop: no such action


def test_a_file_that_cant_go_is_said(tmp_path):
    router = router_for(tmp_path)
    router.on_send_file = lambda path: NOT_ALLOWED
    router.brain = FakeBrain(["ACTION send_file: D:/secret.txt\n", "Here you go."])
    router.phone = True
    assert NOT_ALLOWED in text_of(router.handle("send me the secret"))


def test_claude_is_told_where_the_phones_file_is(tmp_path):
    photo = tmp_path / "homework.jpg"
    photo.write_bytes(b"x" * 3000)
    router = router_for(tmp_path)
    router.brain = FakeBrain(["It's a math problem."])
    router.phone, router.phone_files = True, [str(photo)]
    text_of(router.handle("explain this [sent homework.jpg]"))
    prompt = router.brain.asked[0][0]
    assert prompt.startswith(FROM_PHONE) and f"{photo} (image, 2 KB)" in prompt


def test_the_daemon_sends_a_checked_file(tmp_path, monkeypatch):
    bus = Bus(ui_attached=False)
    seen = Recorder(bus)
    daemon = make_daemon(StubRouter([]), bus=bus)
    cv = tmp_path / "CV.pdf"
    cv.write_bytes(b"%PDF")
    import abdoh.phone.files as files

    monkeypatch.setattr(files, "roots", lambda cfg, home=None, folders=None: [tmp_path])
    assert daemon._send_file(str(cv)) == ""
    assert seen.of("phone_file") == [{"path": str(cv.resolve())}]
    assert daemon._send_file(str(tmp_path / "nope.pdf")) == NOT_FOUND


def test_the_phone_gets_a_card_for_the_file(tmp_path):
    bus, hub = make_hub()
    cv = tmp_path / "CV.pdf"
    cv.write_bytes(b"%PDF-1.7")
    hub.ask("send me my cv", phone="p1")
    hub.take("phone_file", {"path": str(cv)})
    event = hub.events(0, wait=0)["events"][-1]
    assert {k: event[k] for k in ("type", "name", "size", "kind", "for")} == {
        "type": "file", "name": "CV.pdf", "size": 8, "kind": "pdf", "for": "p1"}  # fmt: skip
    assert hub.media.get(event["id"]).path == cv
    hub.take("phone_file", {"path": str(tmp_path / "gone.pdf")})  # gone meanwhile: nothing
    assert len(hub.events(0, wait=0)["events"]) == 1


def test_files_are_kept_where_claude_handles_requests(tmp_path):
    """The daemon gives the phone's files to the router for that request only."""
    bus = Bus(ui_attached=False)
    seen_files = []

    class Seeing(StubRouter):
        phone_files: list = []

        def handle(self, text, **kw):
            seen_files.append(list(self.phone_files))
            return super().handle(text, **kw)

    router = Seeing(["Got it.", "Hi."])
    daemon = make_daemon(router, bus=bus)
    daemon.handle_request("phone", {"text": "look [sent a.jpg]", "files": ["C:/in/a.jpg"]})
    daemon.handle_text("hello")
    assert seen_files == [["C:/in/a.jpg"], []]


def test_a_file_goes_with_a_voice_message_too(tmp_path):
    """A photo, then "what's in this?" said instead of typed: the photo goes with it."""
    from fakes import FakeTranscriber

    heard = FakeTranscriber(["what's in this photo"])
    bus, hub, phones, app = make_app(tmp_path, hear=heard.transcribe, uploads_to=lambda: tmp_path)
    key = paired(app, phones)
    saved = hub.save("photo.jpg", io.BytesIO(b"JPEG"), 4)
    path = f"/api/voice?speak=1&files={saved['id']}"
    _, data = call(app, "POST", path, key=key, body=b"\x00\x01" * 800)
    assert data["text"] == "what's in this photo [sent photo.jpg]"
    assert bus.next_request(0)[1]["files"] == [str(tmp_path / "photo.jpg")]


def test_a_refused_upload_is_read_to_the_end_so_the_phone_hears_why(tmp_path):
    """Answered before its file was read, the phone saw a cut connection, not "not paired"."""
    from email.message import Message

    from abdoh.phone.server import _handler

    bus, hub, phones, app = make_app(tmp_path, uploads_to=lambda: tmp_path / "in")
    handler = _handler(app).__new__(_handler(app))
    body = b"x" * 300_000
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.headers = Message()
    handler.path = "/api/upload?name=x.bin"
    handler.request_version = "HTTP/1.1"
    handler.requestline = "POST /api/upload HTTP/1.1"
    handler.command = "POST"
    handler.client_address = ("127.0.0.1", 0)
    handler._upload(len(body))
    assert handler.wfile.getvalue().split(b"\r\n")[0].endswith(b"401 Unauthorized")
    assert handler.rfile.tell() == len(body) and handler.close_connection
