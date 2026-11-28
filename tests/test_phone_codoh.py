"""Codoh from the phone (ABDOH_EPIC_11.md, story 151): its chats and a chat's items, trimmed for
a phone; sending, stopping, answering and new chats through the page's API; notices for the
phone's chats go to the phone, not out loud."""

from test_codoh_manager import World, items
from test_daemon import StubRouter, make_daemon
from test_phone import Recorder, call, make_app, make_hub, paired

from abdoh.events import Bus
from abdoh.phone.codoh import DIFF, NO_CODOH, NO_FOLDER, OUTPUT, chats, slim


def test_items_are_trimmed_for_a_phone():
    tool = {"id": "t", "kind": "tool", "rev": 4, "kind_of": "command", "title": "npm test",
            "output": "x" * 10_000 + "END", "diff": "y" * 20_000,
            "input": {"secret": 1}}  # fmt: skip
    got = slim(tool)
    assert got["output"].endswith("END") and len(got["output"]) == OUTPUT + 1
    assert len(got["diff"]) == DIFF + 1 and "input" not in got
    ask = {"id": "a", "kind": "approval", "tool": "Bash", "kind_of": "command",
           "title": "rm -rf build", "state": "waiting", "suggestions": [{"rule": "Bash(rm:*)"}],
           "input": {"command": "rm"}, "request_id": "r1"}  # fmt: skip
    got = slim(ask)
    assert got["suggestions"] is True and "input" not in got and "request_id" not in got
    question = {"id": "q", "kind": "approval", "tool": "AskUserQuestion", "state": "waiting",
                "input": {"questions": [{"question": "Which database?", "header": "DB",
                                         "multiSelect": False,
                                         "options": [{"label": "SQLite", "description": "simple"},
                                                     {"label": "Postgres"}]}]}}  # fmt: skip
    got = slim(question)
    assert got["questions"] == [{"question": "Which database?", "header": "DB", "multi": False,
                                 "options": [{"label": "SQLite", "about": "simple"},
                                             {"label": "Postgres", "about": ""}]}]  # fmt: skip


def test_running_chats_come_first():
    state = {
        "chats": [
            {"id": "a", "title": "Old", "folder": "C:/code/app", "updated": 1},
            {"id": "b", "title": "New", "folder": "C:/code/app", "updated": 9},
            {"id": "c", "title": "Busy", "folder": "C:/code/site", "updated": 2, "running": True},
        ],
        "folders": [{"path": "C:/code/app", "exists": True}, {"path": "C:/gone", "exists": False}],
    }
    found = chats(state)
    assert [c["id"] for c in found["chats"]] == ["c", "b", "a"]
    assert found["chats"][0]["where"] == "site"
    assert found["folders"] == [{"path": "C:/code/app", "name": "app"}]


def test_codoh_through_the_page(tmp_path):
    world = World(tmp_path)
    codoh = world.codoh
    bus, hub, phones, app = make_app_with(tmp_path, codoh)
    key = paired(app, phones)
    chat_id = world.chat()
    _, data = call(app, "GET", "/api/codoh", key=key)
    assert data["chats"][0]["id"] == chat_id and data["folders"][0]["path"] == str(world.folder)
    body = {"id": chat_id, "text": "Add tests"}
    _, data = call(app, "POST", "/api/codoh/send", key=key, body=body)
    assert data["ok"] and world.engines[0].sent == ["Add tests"]
    engine = world.engines[0]
    engine.on_event({"type": "tool", "id": "t1", "name": "Bash", "input": {"command": "npm test"}})
    engine.on_event({"type": "approval", "id": "r1", "tool": "Bash", "input": {"command": "npm i"}})
    _, data = call(app, "GET", f"/api/codoh/chat?id={chat_id}&since=0", key=key)
    ask = [i for i in data["items"] if i["kind"] == "approval"][0]
    assert data["running"] and ask["state"] == "waiting"
    assert codoh.viewing != chat_id  # the phone reading it isn't the window looking at it
    _, data = call(app, "POST", "/api/codoh/answer", key=key,
                   body={"id": chat_id, "item": ask["id"], "decision": "allow"})  # fmt: skip
    assert data["ok"] and engine.answers[0][:2] == ("r1", True)
    response, data = call(app, "POST", "/api/codoh/answer", key=key,
                          body={"id": chat_id, "item": ask["id"], "decision": "hack"})  # fmt: skip
    assert response.status == 400
    call(app, "POST", "/api/codoh/stop", key=key, body={"id": chat_id})
    assert engine.interrupted
    assert call(app, "GET", "/api/codoh")[0].status == 401  # only a paired phone


def make_app_with(tmp_path, codoh):
    bus, hub, phones, app = make_app(tmp_path)
    app.codoh = lambda: codoh
    return bus, hub, phones, app


def test_a_new_chat_from_the_phone(tmp_path):
    world = World(tmp_path)
    bus, hub, phones, app = make_app_with(tmp_path, world.codoh)
    key = paired(app, phones)
    _, data = call(app, "POST", "/api/codoh/new", key=key,
                   body={"folder": str(world.folder), "text": "Make a README"})  # fmt: skip
    assert data["ok"] and world.engines[0].sent == ["Make a README"]
    assert items(world.codoh, data["chat"], "user")[0]["text"] == "Make a README"
    _, data = call(app, "POST", "/api/codoh/new", key=key, body={"folder": str(tmp_path / "gone")})
    assert data == {"ok": False, "error": NO_FOLDER}


def test_without_codoh_the_phone_is_told(tmp_path):
    bus, hub, phones, app = make_app(tmp_path)
    response, data = call(app, "GET", "/api/codoh", key=paired(app, phones))
    assert response.status == 400 and data["error"] == NO_CODOH


def test_the_phones_chat_tells_the_phone_not_the_room(tmp_path):
    world = World(tmp_path)
    codoh = world.codoh
    said, phoned = [], []
    codoh.on_notice = lambda text, still=None: said.append(text)
    codoh.on_phone_notice = lambda chat, text: phoned.append((chat, text))
    chat_id = world.chat()
    codoh.send(chat_id, "Add a dark mode", by_phone=True)
    engine = world.engines[0]
    ask = {"type": "approval", "id": "r1", "tool": "Bash", "input": {"command": "npm test"}}
    engine.on_event(ask)
    engine.on_event({"type": "done", "seconds": 12})
    assert said == [] and len(phoned) == 2 and all(c == chat_id for c, _ in phoned)
    codoh.send(chat_id, "and a toggle")  # typed on the page: the page's again
    engine.on_event({"type": "done", "seconds": 3})
    assert len(phoned) == 2


def test_codoh_by_voice_from_the_phone_is_the_phones():
    from abdoh.codoh import voice

    sent = []

    class Fake:
        viewing = "c1"

        class store:  # noqa: N801 - the manager's store
            @staticmethod
            def load(chat_id):
                return {"id": chat_id}

        def send(self, chat, message, by_voice=False, by_phone=False):
            sent.append((chat, message, by_voice, by_phone))
            return {"ok": True}

    voice.act(Fake(), "send | run the tests", by_phone=True)
    voice.act(Fake(), "send | run the tests")
    assert sent == [("c1", "run the tests", False, True), ("c1", "run the tests", True, False)]


def test_abdoh_opens_codoh_on_the_phone_for_a_phone_request():
    bus = Bus(ui_attached=False)
    seen = Recorder(bus)
    daemon = make_daemon(StubRouter([]), bus=bus)
    daemon._phone_turn = True
    daemon._show_codoh("c1")
    assert seen.of("phone_codoh") == [{"chat": "c1", "open": True}] and seen.of("show") == []
    bus2, hub = make_hub()
    hub.ask("tell codoh to add tests", phone="p1")
    hub.take("phone_codoh", {"chat": "c1", "text": "Codoh is done."})
    event = hub.events(0, wait=0)["events"][-1]
    assert (event["type"], event["chat"], event["text"], event["for"]) == (
        "codoh", "c1", "Codoh is done.", "p1")  # fmt: skip
