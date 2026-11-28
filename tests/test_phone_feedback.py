"""What the owner found trying the phone outside the house (story 156)."""

from test_claude_code import FakePopen, delta, make_brain, result, tool_start

from abdoh.events import Bus


def test_stop_stops_claude_in_the_middle_of_a_long_search(tmp_path):
    """Said over a reply while Claude searched the files: it waited for the search to end."""
    popen = FakePopen([tool_start("Glob"), delta("Found nothing called bubble."), result()],
                      [delta("Bubble sort swaps neighbours."), result()])  # fmt: skip
    brain = make_brain(tmp_path, popen)
    brain.on_activity = lambda text: brain.stop_now()  # "no, I meant the board", mid-search
    assert "".join(brain.stream("show me the bubble file")) == ""  # stopped: no error either
    assert len(popen.procs[0].stdin.interrupts) == 1
    assert "".join(brain.stream("explain bubble sort")) == "Bubble sort swaps neighbours."
    brain.stop_now()  # nothing being answered: nothing happens
    assert len(popen.procs[0].stdin.interrupts) == 1
    brain.close()


def test_the_daemon_stops_claude_when_it_stops():
    from test_daemon import StubRouter, make_daemon

    stopped = []
    router = StubRouter([])
    router.brain = type("Brain", (), {"stop_now": lambda self: stopped.append(True)})()
    daemon = make_daemon(router)
    daemon.stop_speaking()
    assert stopped == [True]


def test_events_only_for_the_phone_never_reach_the_window():
    """A picture's bytes went to the window, which couldn't take them (its events broke)."""
    bus = Bus()
    heard = []
    bus.listen(lambda kind, value: heard.append(kind))
    bus.emit("phone_image", {"data": b"JPEG"})
    bus.emit("history", "Abdoh: hi")
    assert bus.pending_events() == [("history", "Abdoh: hi")]
    assert heard == ["phone_image", "history"]  # the phone's hub still gets both


def test_a_photo_sent_alone_is_only_kept(tmp_path):
    """No words with it: it's for using later, so nothing is asked and nothing answered."""
    import io

    from test_phone import call, make_app, paired

    folder = tmp_path / "Downloads" / "From your phone"
    bus, hub, phones, app = make_app(tmp_path, uploads_to=lambda: folder)
    key = paired(app, phones)
    saved = hub.save("IMG_5632.png", io.BytesIO(b"PNG"), 3)
    seen = []
    bus.listen(lambda kind, value: seen.append((kind, value)))
    _, data = call(app, "POST", "/api/text", key=key, body={"text": "", "files": [saved["id"]]})
    assert data == {"ok": True, "text": "[sent IMG_5632.png]", "quiet": True}
    assert bus.next_request(0) is None  # Abdoh isn't asked anything
    me = phones.list()[0]["id"]
    assert ("history", "You (phone): [sent IMG_5632.png]") in seen  # here and on the laptop
    assert ("phone_note", {"text": "Saved on your computer, in Downloads › From your phone.",
                           "for": me}) in seen  # fmt: skip
    _, data = call(app, "POST", "/api/text", key=key, body={"text": "put it on the board"})
    assert data["quiet"] is False and data["text"] == "put it on the board"  # no "[sent" again
    asked = bus.next_request(0)[1]
    assert asked["files"] == [str(folder / "IMG_5632.png")]  # ... but Claude knows the photo
    call(app, "POST", "/api/text", key=key, body={"text": "and something else"})
    assert "files" not in bus.next_request(0)[1]  # only the next request


def test_a_file_from_the_phone_opens_on_the_laptop(tmp_path, monkeypatch):
    from test_board_pdf import make_api

    folder = tmp_path / "From your phone"
    folder.mkdir()
    (folder / "IMG_5632.png").write_bytes(b"PNG")
    monkeypatch.setattr("abdoh.phone.files.upload_folder", lambda cfg: folder)
    api, bus = make_api(tmp_path)
    opened = []
    api._open_path = opened.append
    assert api.open_phone_file("IMG_5632.png") == {"ok": True}
    assert opened == [str(folder / "IMG_5632.png")]
    assert api.open_phone_file(r"..\..\secret.txt")["ok"] is False  # only that folder's files
    assert api.open_phone_file("../secret.txt")["ok"] is False
    assert api.open_phone_file("gone.png")["ok"] is False
