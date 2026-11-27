"""Abdoh from your phone (ABDOH_EPIC_10.md): paired phones, the hub, the page's API, and the
daemon answering the phone. No sockets: PhoneApp.handle is called directly."""

import json
import threading
from datetime import date

import pytest
from fakes import FakeTranscriber
from test_daemon import StubRouter, make_daemon

from abdoh.config import Config
from abdoh.events import Bus
from abdoh.phone.devices import (
    CODE_LETTERS,
    CODE_SECONDS,
    WRONG_CODES,
    Phones,
    clean_code,
    phone_name,
)
from abdoh.phone.hub import MAX_EVENTS, PhoneError, PhoneHub
from abdoh.phone.server import NOT_PAIRED, PhoneApp, PhoneService
from abdoh.system_skills import Question


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


# ----- paired phones -----


def test_a_code_pairs_one_phone_once(tmp_path):
    clock = Clock()
    phones = Phones(tmp_path / "phones.json", clock=clock)
    code = phones.new_code()
    key = phones.pair(code, "iPhone")
    assert key and len(key) > 30
    assert phones.pair(code, "Another") is None  # once
    assert phones.check(key)["name"] == "iPhone"
    assert key not in (tmp_path / "phones.json").read_text()  # only its hash is kept
    again = Phones(tmp_path / "phones.json", clock=clock)  # after a restart
    assert again.check(key)["name"] == "iPhone"
    assert again.list()[0].keys() == {"id", "name", "added", "seen"}


def test_a_code_stops_working_after_30_minutes(tmp_path):
    clock = Clock()
    phones = Phones(tmp_path / "phones.json", clock=clock)
    code = phones.new_code()
    clock.now += CODE_SECONDS - 5
    assert phones.code_left() == 5
    clock.now += 10
    assert phones.code_left() == 0
    assert phones.pair(code) is None


def test_wrong_codes_and_a_new_code(tmp_path):
    phones = Phones(tmp_path / "phones.json")
    old = phones.new_code()
    new = phones.new_code()
    assert phones.pair(old) is None  # the one before stops working
    for _ in range(WRONG_CODES - 1):
        assert phones.pair("guess") is None
    assert phones.pair(new) is None  # too many wrong codes: this one stopped working too
    assert phones.pair("anything") is None


def test_keys_that_dont_work(tmp_path):
    phones = Phones(tmp_path / "phones.json")
    key = phones.pair(phones.new_code())
    assert phones.check(None) is None
    assert phones.check("") is None
    assert phones.check(key + "x") is None
    assert phones.remove(phones.list()[0]["id"]) is True
    assert phones.check(key) is None
    assert phones.remove("nobody") is False


def test_a_broken_file_means_no_phones(tmp_path):
    path = tmp_path / "phones.json"
    path.write_text("{not json")
    assert Phones(path).list() == []
    path.write_text(json.dumps({"phones": [{"name": "no key"}, 3]}))
    assert Phones(path).list() == []


def test_codes_can_be_typed(tmp_path):
    phones = Phones(tmp_path / "phones.json")
    code = phones.new_code()
    assert len(code) == 9 and code[4] == "-"
    assert set(code.replace("-", "")) <= set(CODE_LETTERS)
    assert phones.pair(code.lower().replace("-", " ")) is not None  # as typed on the phone
    assert clean_code("k7mx2q9p") == "K7MX-2Q9P"
    assert clean_code("") == ""


def test_phone_names():
    assert phone_name("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)") == "iPhone"
    assert phone_name("Mozilla/5.0 (Linux; Android 15; Pixel 9)") == "Android phone"
    assert phone_name("") == "Phone"


# ----- the hub -----


def make_hub(**kw):
    bus = Bus(ui_attached=False)
    return bus, PhoneHub(bus, clock=kw.pop("clock", Clock()), **kw)


def test_events_after_a_number():
    bus, hub = make_hub()
    hub.take("history", "You: hi")
    hub.take("history", "Abdoh: Hello.")
    hub.take("status", "Ready")
    hub.take("windows", "ignored")
    got = hub.events(1, wait=0)
    assert [e["seq"] for e in got["events"]] == [2, 3]
    assert got["events"][0] == {"seq": 2, "type": "history", "line": "Abdoh: Hello."}
    assert hub.state()["history"] == ["You: hi", "Abdoh: Hello."]
    assert hub.state()["status"] == "Ready"


def test_the_page_waits_for_a_new_event():
    bus, hub = make_hub(clock=__import__("time").monotonic)
    found = []
    waiter = threading.Thread(target=lambda: found.append(hub.events(0, wait=5)))
    waiter.start()
    hub.take("status", "Thinking...")
    waiter.join(5)
    assert found and found[0]["events"][0]["text"] == "Thinking..."
    assert hub.events(1, wait=0)["events"] == []  # nothing new: back empty after the wait


def test_a_page_that_missed_events_starts_over():
    bus, hub = make_hub()
    for i in range(MAX_EVENTS + 5):
        hub.take("status", str(i))
    assert hub.events(1, wait=0)["reset"] is True  # its next events are gone
    assert hub.events(10_000, wait=0)["reset"] is True  # numbers from before a restart
    assert "reset" not in hub.events(MAX_EVENTS, wait=0)


def test_a_new_day_clears_the_conversation():
    day = [date(2026, 11, 27)]
    bus, hub = make_hub(today=lambda: day[0])
    hub.take("history", "You: hi")
    day[0] = date(2026, 11, 28)
    hub.take("history", "You: morning")
    assert hub.state()["history"] == ["You: morning"]
    assert [e["type"] for e in hub.events(1, wait=0)["events"]] == ["clear", "history"]


def test_the_ai_and_the_mode():
    bus, hub = make_hub()
    hub.take("claude", {"name": "ChatGPT", "label": "ChatGPT", "status": "your plan"})
    hub.take("claude", "API key")  # an older event: only the status
    hub.take("mode", "Movie")
    state = hub.state()
    assert state["ai"] == {"name": "Claude", "label": "Claude", "status": "API key"}
    assert state["mode"] == "Movie"


def test_asking_from_the_phone():
    bus, hub = make_hub()
    assert hub.ask("  what's   the time ") == "what's the time"
    assert bus.next_request(0) == ("phone", {"text": "what's the time"})
    with pytest.raises(PhoneError):
        hub.ask("   ")
    hub.stop()
    assert bus.next_request(0) == ("stop_speaking", None)


def test_talking_from_the_phone():
    heard = FakeTranscriber(["turn on the lamp", ""])
    bus, hub = make_hub(hear=heard.transcribe)
    assert hub.hear(b"\x00\x01" * 100) == "turn on the lamp"
    assert bus.next_request(0) == ("phone", {"text": "turn on the lamp"})
    assert hub.hear(b"\x00\x01" * 100) == ""  # nothing understood: nothing asked
    assert bus.next_request(0) is None
    _, deaf = make_hub()
    with pytest.raises(PhoneError):
        deaf.hear(b"\x00\x01")


def test_reply_sentences_with_and_without_audio():
    clock = Clock()
    made = []

    def voice(text):
        made.append(text)
        return b"RIFF" + text.encode()

    bus, hub = make_hub(voice=voice, clock=clock)
    hub.ask("hi", speak=False)
    hub.take("phone_say", "Hello there.")
    assert hub.events(0, wait=0)["events"][-1] == {
        "seq": 1, "type": "say", "text": "Hello there.", "audio": None}  # fmt: skip
    assert made == []  # not spoken: no audio made
    hub.ask("hi", speak=True)
    hub.take("phone_say", "Hello again.")
    audio = hub.events(1, wait=0)["events"][-1]["audio"]
    assert hub.audio(audio) == b"RIFFHello again."
    clock.now += 601
    assert hub.audio(audio) is None  # kept ten minutes


def test_a_voice_that_fails_sends_the_text_only():
    def voice(text):
        raise RuntimeError("no voice")

    bus, hub = make_hub(voice=voice)
    hub.ask("hi", speak=True)
    hub.take("phone_say", "Hello.")
    assert hub.events(0, wait=0)["events"][-1]["audio"] is None


def test_the_hub_listens_to_the_bus_in_order():
    bus, hub = make_hub(clock=__import__("time").monotonic)
    hub.start()
    try:
        bus.emit("phone_say", "One.")
        bus.emit("history", "Abdoh: One.")
        bus.emit("phone_aside", "One moment.")
        bus.emit("phone_question", "Shut down the computer?")
        got = []
        while len(got) < 4:
            got += hub.events(got[-1]["seq"] if got else 0, wait=2)["events"]
        assert [e["type"] for e in got] == ["say", "history", "aside", "question"]
    finally:
        hub.close()
    bus.emit("status", "after")  # no longer listening
    assert hub.events(4, wait=0)["events"] == []


# ----- the page's API -----


def make_app(tmp_path, **hub_kw):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>Abdoh</title>")
    (web / "phone.js").write_text("'use strict';")
    (web / "notes.txt").write_text("not served")
    bus, hub = make_hub(**hub_kw)
    phones = Phones(tmp_path / "phones.json")
    return bus, hub, phones, PhoneApp(hub, phones, web=web)


def call(app, method, path, key=None, body=b"", **headers):
    if key:
        headers["authorization"] = f"Bearer {key}"
    if isinstance(body, dict):
        body = json.dumps(body).encode()
    response = app.handle(method, path, headers, body)
    data = json.loads(response.body) if response.type.startswith("application/json") else None
    return response, data


def paired(app, phones):
    code = phones.new_code()
    response, data = call(app, "POST", "/api/pair", body={"code": code},
                          **{"user-agent": "Mozilla/5.0 (iPhone)"})  # fmt: skip
    assert response.status == 200
    return data["key"]


def test_the_page_itself(tmp_path):
    bus, hub, phones, app = make_app(tmp_path)
    response, _ = call(app, "GET", "/")
    assert response.status == 200 and response.type.startswith("text/html")
    assert call(app, "GET", "/phone.js")[0].type.startswith("text/javascript")
    for bad in ("/notes.txt", "/../phones.json", "/%2e%2e/phones.json", "/web/index.html",
                "/.hidden", "/nothing.js"):  # fmt: skip
        assert call(app, "GET", bad)[0].status == 404, bad
    assert call(app, "POST", "/")[0].status == 405


def test_pairing_through_the_page(tmp_path):
    bus, hub, phones, app = make_app(tmp_path)
    key = paired(app, phones)
    assert phones.list()[0]["name"] == "iPhone"
    response, data = call(app, "POST", "/api/pair", body={"code": "guess"})
    assert response.status == 403 and "Settings → Phone" in data["error"]
    assert call(app, "GET", "/api/pair")[0].status == 405
    assert call(app, "POST", "/api/pair", body=b"[1]")[0].status == 400
    response, data = call(app, "GET", "/api/state", key=key)
    assert response.status == 200 and data["phone"] == "iPhone"
    assert response.headers["Cache-Control"] == "no-store"


def test_everything_else_needs_a_paired_phone(tmp_path):
    bus, hub, phones, app = make_app(tmp_path)
    key = paired(app, phones)
    for method, path in (("GET", "/api/state"), ("GET", "/api/events?after=0"),
                         ("POST", "/api/text"), ("POST", "/api/voice"), ("POST", "/api/stop"),
                         ("POST", "/api/forget"), ("GET", "/api/audio/x")):  # fmt: skip
        for wrong in (None, "nope", key[:-1]):
            response, data = call(app, method, path, key=wrong, body={"text": "hi"})
            assert response.status == 401 and data["error"] == NOT_PAIRED, (method, path)
    assert bus.next_request(0) is None  # nothing reached Abdoh
    response, _ = call(app, "POST", "/api/forget", key=key)
    assert response.status == 200
    assert call(app, "GET", "/api/state", key=key)[0].status == 401  # unpaired


def test_asking_through_the_page(tmp_path):
    heard = FakeTranscriber(["play some jazz"])
    bus, hub, phones, app = make_app(tmp_path, hear=heard.transcribe)
    key = paired(app, phones)
    response, data = call(app, "POST", "/api/text", key=key, body={"text": "hi", "speak": True})
    assert data == {"ok": True, "text": "hi"}
    assert bus.next_request(0) == ("phone", {"text": "hi"})
    response, data = call(app, "POST", "/api/text", key=key, body={"text": " "})
    assert response.status == 400 and data["error"]
    response, data = call(app, "POST", "/api/voice?speak=1", key=key, body=b"\x00\x01" * 800)
    assert data == {"ok": True, "text": "play some jazz"}
    assert heard.calls == [b"\x00\x01" * 800]
    response, data = call(app, "POST", "/api/voice", key=key, body=b"\x00" * (60 * 32000 + 2))
    assert response.status == 400 and "minute" in data["error"]
    call(app, "POST", "/api/stop", key=key)
    assert [bus.next_request(0)[0] for _ in range(2)] == ["phone", "stop_speaking"]
    assert call(app, "GET", "/api/text", key=key)[0].status == 405
    assert call(app, "POST", "/api/nothing", key=key)[0].status == 404


def test_events_and_audio_through_the_page(tmp_path):
    bus, hub, phones, app = make_app(tmp_path, voice=lambda text: b"RIFF....WAVE")
    key = paired(app, phones)
    hub.ask("hi", speak=True)
    hub.take("phone_say", "Hello.")
    _, data = call(app, "GET", "/api/events?after=0", key=key)
    audio = data["events"][0]["audio"]
    response, _ = call(app, "GET", f"/api/audio/{audio}", key=key)
    assert response.status == 200 and response.type == "audio/wav"
    assert response.body == b"RIFF....WAVE"
    assert call(app, "GET", "/api/audio/gone", key=key)[0].status == 404
    _, data = call(app, "GET", "/api/events?after=junk", key=key)  # read as 0
    assert len(data["events"]) == 1


# ----- the daemon answering the phone -----


class Recorder:
    def __init__(self, bus):
        self.events = []
        bus.listen(lambda kind, value: self.events.append((kind, value)))

    def of(self, kind):
        return [v for k, v in self.events if k == kind]


def test_a_phone_request_is_answered_on_the_phone():
    bus = Bus(ui_attached=False)
    seen = Recorder(bus)
    daemon = make_daemon(StubRouter(["It's sunny."]), bus=bus)
    daemon.handle_request("phone", {"text": "weather?"})
    assert daemon.speaker.said == []  # nothing on the laptop's speakers
    assert seen.of("phone_say") == ["It's sunny."]
    assert "You (phone): weather?" in seen.of("history")
    assert "Abdoh: It's sunny." in seen.of("history")
    assert daemon._phone_turn is False  # the next request is the laptop's again


def test_a_streamed_reply_goes_to_the_phone_sentence_by_sentence():
    bus = Bus(ui_attached=False)
    seen = Recorder(bus)
    daemon = make_daemon(StubRouter([iter(["First.", "Second."])]), bus=bus)
    daemon.handle_request("phone", {"text": "tell me"})
    assert daemon.speaker.said == []
    assert seen.of("phone_say") == ["First.", "Second."]
    assert seen.of("history")[-1] == "Abdoh: First. Second."


def test_a_question_to_the_phone_gets_yes_and_no():
    bus = Bus(ui_attached=False)
    seen = Recorder(bus)
    daemon = make_daemon(StubRouter([Question("Shut down the computer?")]), bus=bus)
    daemon.handle_request("phone", {"text": "shut down"})
    assert seen.of("phone_question") == ["Shut down the computer?"]
    assert daemon._awaiting_answer is False  # the laptop doesn't listen for the answer


def test_fillers_go_to_the_phone():
    bus = Bus(ui_attached=False)
    seen = Recorder(bus)
    daemon = make_daemon(StubRouter([]), bus=bus)
    daemon._phone_turn = True
    daemon._say_aside("One moment.")
    daemon._activity("Searching the web")
    assert seen.of("phone_aside") == ["One moment."]
    assert daemon.speaker.said == []


def test_a_laptop_request_is_still_spoken_on_the_laptop():
    bus = Bus(ui_attached=False)
    seen = Recorder(bus)
    daemon = make_daemon(StubRouter(["Hi."]), bus=bus)
    daemon.handle_text("hello")
    assert daemon.speaker.said == ["Hi."]
    assert seen.of("phone_say") == []
    assert "You: hello" in seen.of("history")


def test_empty_phone_requests_are_ignored():
    daemon = make_daemon(StubRouter([]))
    daemon.handle_request("phone", {"text": "  "})
    daemon.handle_request("phone", None)


class FakeServer:
    started = []

    def __init__(self, app, port):
        self.port = port
        self.running = False

    def start(self):
        if self.port == 1:
            raise OSError("taken")
        self.running = True
        FakeServer.started.append(self)

    def stop(self):
        self.running = False


def test_the_phone_switch_starts_and_stops_the_page(tmp_path, monkeypatch):
    import abdoh.phone.server as server

    monkeypatch.setattr(server, "PhoneServer", FakeServer)
    bus = Bus(ui_attached=False)
    seen = Recorder(bus)
    cfg = Config(app_dir=tmp_path)
    daemon = make_daemon(StubRouter([]), cfg=cfg, bus=bus)
    daemon._phone_switch()
    assert daemon.phone is None  # off until you turn it on
    cfg.phone = True
    daemon._phone_switch()
    first = daemon.phone
    assert isinstance(first, PhoneService) and first.server.running
    daemon._phone_switch()
    assert daemon.phone is first  # already on
    cfg.phone_port = 47900
    daemon._phone_switch()
    assert not first.server.running and daemon.phone.port == 47900  # a new port: again
    cfg.phone_port = 1
    daemon._phone_switch()
    assert daemon.phone is None and "port 1 is taken" in seen.of("phone")[-1]["error"]
    cfg.phone_port = 47811
    daemon._phone_switch()
    daemon.stop()
    assert daemon.phone is None and not FakeServer.started[-1].running


def test_the_phone_hears_with_the_daemons_speech_recognition():
    daemon = make_daemon(StubRouter([]), transcriber=FakeTranscriber(["hello"]))
    assert daemon._phone_hear(b"\x00\x01") == "hello"
    assert daemon._phone_voice("Hi.") is None  # the fake voice can't make audio


# ----- the page's files -----


def test_the_phone_page_has_everything_it_names():
    import re

    from abdoh.phone.server import _NAME, TYPES, WEB_DIR

    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    named = re.findall(r'(?:src|href)="([^"#:]+)"', html)
    worker = (WEB_DIR / "sw.js").read_text(encoding="utf-8")
    page = json.loads(re.search(r"const PAGE = (\[.*?\]);", worker).group(1))
    manifest = json.loads((WEB_DIR / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert "start_url" not in manifest  # the app opens the link it was added from (its code)
    icons = [icon["src"] for icon in manifest["icons"]]
    for name in {*named, *page, *icons, "demo.js"} - {"./"}:
        path = WEB_DIR / name
        assert path.is_file(), name
        assert _NAME.fullmatch(name) and path.suffix in TYPES, name  # the server serves it


def test_a_phone_that_hangs_up_is_only_logged(caplog):
    import logging

    from abdoh.phone.server import _Server

    server = _Server.__new__(_Server)  # no socket
    with caplog.at_level(logging.DEBUG, logger="abdoh.phone.server"):
        try:
            raise ConnectionAbortedError("gone")
        except ConnectionAbortedError:
            server.handle_error(None, ("127.0.0.1", 1))
        try:
            raise ValueError("broken")
        except ValueError:
            server.handle_error(None, ("127.0.0.1", 1))
    levels = [(r.levelname, r.getMessage()) for r in caplog.records]
    assert levels[0][0] == "DEBUG" and "hung up" in levels[0][1]
    assert levels[1][0] == "ERROR"
