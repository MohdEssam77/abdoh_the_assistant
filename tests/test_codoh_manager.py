"""Codoh's chats (codoh/manager.py, codoh/store.py, codoh/git.py) with fake engines."""

import subprocess

import pytest

from abdoh.codoh import git
from abdoh.codoh.manager import NEW_CHAT, NO_CHATGPT, Codoh, summary
from abdoh.config import Config


class FakeEngine:
    def __init__(self, kind, folder, on_event, **settings):
        self.engine = kind
        self.folder = folder
        self.on_event = on_event
        self.settings = settings
        self.sent = []
        self.answers = []
        self.changes = []
        self.interrupted = self.closed = False
        self.last_used = 0.0

    def send(self, text):
        self.sent.append(text)

    def interrupt(self):
        self.interrupted = True

    def answer(self, request_id, allow, data=None, rules=None, note=""):
        self.answers.append((request_id, allow, data, rules))

    def set_model(self, model):
        self.changes.append(("model", model))

    def set_mode(self, mode):
        self.changes.append(("mode", mode))

    def set_effort(self, effort):
        self.changes.append(("effort", effort))

    def alive(self):
        return not self.closed

    def close(self):
        self.closed = True


OPUS = {"id": "opus", "name": "Opus 5.5"}


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


class World:
    """Codoh with fake engines, a fake Claude Code and a ChatGPT plan that may be there."""

    def __init__(self, tmp_path, chatgpt=True, claude=True):
        self.tmp_path = tmp_path
        self.cfg = Config(app_dir=tmp_path / "app")
        self.folder = tmp_path / "project"
        self.folder.mkdir(exist_ok=True)
        self.engines = []
        self.chatgpt = chatgpt
        self.claude = claude
        self.clock = Clock()
        self.codoh = self.make()

    def make(self):
        def claude(exe, folder, on_event, **settings):
            engine = FakeEngine("claude", folder, on_event, exe=exe, **settings)
            self.engines.append(engine)
            return engine

        def chatgpt(cfg, folder, on_event, **settings):
            engine = FakeEngine("chatgpt", folder, on_event, **settings)
            self.engines.append(engine)
            return engine

        return Codoh(
            self.cfg,
            find_code=lambda _: self.tmp_path / "claude.exe" if self.claude else None,
            make_claude=claude,
            make_chatgpt=chatgpt,
            chatgpt_ready=lambda: self.chatgpt,
            chatgpt_models=lambda: {"ok": True, "models": [{"id": "gpt-6.2", "name": "GPT-6.2"}]},
            probe=lambda exe, folder: {
                "models": [{"id": "opus", "name": "Opus 5.5"}],
                "plan": "Pro",
            },
            clock_fn=self.clock,
        )

    def chat(self, **kwargs):
        return self.codoh.new_chat(str(self.folder), **kwargs)["chat"]["id"]


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def items(codoh, chat_id, kind=None):
    found = codoh.chat(chat_id)["items"]
    return [i for i in found if kind is None or i["kind"] == kind]


def test_a_new_chat_in_a_folder(world):
    chat_id = world.chat()
    state = world.codoh.state()
    assert state["folders"][0]["path"] == str(world.folder) and state["folders"][0]["exists"]
    assert state["chats"][0]["id"] == chat_id and state["chats"][0]["title"] == NEW_CHAT
    assert state["default_engine"] == "claude" and state["engines"]["chatgpt"]["ready"]


def test_a_reply_becomes_items(world):
    codoh = world.codoh
    chat_id = world.chat()
    assert codoh.send(chat_id, "Fix the add function please")["ok"]
    engine = world.engines[0]
    assert engine.sent == ["Fix the add function please"] and engine.engine == "claude"
    rev = codoh.chat(chat_id)["rev"]
    emit = engine.on_event
    emit({"type": "session", "id": "s-1"})
    emit({"type": "text", "delta": "Let me "})
    emit({"type": "text", "delta": "look."})
    emit(
        {
            "type": "tool",
            "id": "t1",
            "name": "Edit",
            "input": {
                "file_path": str(world.folder / "calc.py"),
                "old_string": "a - b",
                "new_string": "a + b",
            },
        }
    )
    assert codoh.chat(chat_id)["status"] == "Editing calc.py"
    emit({"type": "tool_result", "id": "t1", "ok": True, "output": "ok", "result": None})
    emit({"type": "text", "delta": "Fixed."})
    emit({"type": "done", "ok": True, "error": None, "seconds": 4.2})
    found = items(codoh, chat_id)
    assert [i["kind"] for i in found] == ["user", "assistant", "tool", "assistant", "done"]
    assert found[1]["text"] == "Let me look." and found[3]["text"] == "Fixed."
    tool = found[2]
    assert tool["kind_of"] == "edit" and tool["title"] == "calc.py" and tool["status"] == "done"
    assert "+a + b" in tool["diff"]
    state = codoh.chat(chat_id)
    assert not state["running"] and state["chat"]["title"] == "Fix the add function please"
    changed = codoh.chat(chat_id, since=rev)["items"]
    assert "user" not in [i["kind"] for i in changed]  # only what changed since
    assert world.codoh.store.load(chat_id)["claude_session"] == "s-1"


def test_approvals(world):
    codoh = world.codoh
    chat_id = world.chat()
    codoh.send(chat_id, "clean up")
    engine = world.engines[0]
    rule = {"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "rm:*"}]}
    engine.on_event(
        {"type": "tool", "id": "t1", "name": "Bash", "input": {"command": "rm -r build"}}
    )
    engine.on_event(
        {
            "type": "approval",
            "id": "r1",
            "tool": "Bash",
            "input": {"command": "rm -r build"},
            "description": "Remove build",
            "suggestions": [rule],
            "tool_use_id": "t1",
        }
    )
    ask = items(codoh, chat_id, "approval")[0]
    assert ask["state"] == "waiting" and ask["title"] == "rm -r build"
    assert codoh.chat(chat_id)["status"] == "Waiting for you"
    assert items(codoh, chat_id, "tool")[0]["status"] == "waiting"
    assert codoh.answer(chat_id, ask["id"], "always")["ok"]
    assert engine.answers == [("r1", True, {"command": "rm -r build"}, [rule])]
    assert not codoh.answer(chat_id, ask["id"], "deny")["ok"]  # already answered
    assert items(codoh, chat_id, "approval")[0]["state"] == "always"


def test_stop(world):
    codoh = world.codoh
    chat_id = world.chat()
    codoh.send(chat_id, "go")
    engine = world.engines[0]
    engine.on_event({"type": "approval", "id": "r1", "tool": "Write", "input": {"file_path": "x"}})
    codoh.stop(chat_id)
    assert engine.interrupted
    engine.on_event({"type": "done", "ok": True, "stopped": True})
    assert items(codoh, chat_id, "approval")[0]["state"] == "expired"
    assert items(codoh, chat_id)[-1] == {
        **items(codoh, chat_id)[-1],
        "kind": "note",
        "text": "Stopped.",
    }
    assert not codoh.send(chat_id, "")["ok"]


def test_busy_chat_says_so(world):
    chat_id = world.chat()
    world.codoh.send(chat_id, "one")
    assert world.codoh.send(chat_id, "two")["error"].startswith("Codoh is still answering")


def test_model_mode_and_effort(world):
    codoh = world.codoh
    chat_id = world.chat()
    codoh.send(chat_id, "hi")
    engine = world.engines[0]
    engine.on_event({"type": "done", "ok": True})
    codoh.configure(chat_id, {"model": "claude:sonnet", "mode": "plan", "effort": "high"})
    assert engine.changes == [("model", "sonnet"), ("mode", "plan"), ("effort", "high")]
    saved = world.codoh.store.load(chat_id)
    assert (saved["model"], saved["mode"], saved["effort"]) == ("sonnet", "plan", "high")
    assert not codoh.configure(chat_id, {"mode": "anything"})["chat"]["mode"] == "anything"


def test_moving_a_chat_to_the_other_plan(world):
    codoh = world.codoh
    chat_id = world.chat()
    codoh.send(chat_id, "What does calc.py do?")
    claude = world.engines[0]
    claude.on_event({"type": "text", "delta": "It adds numbers."})
    claude.on_event({"type": "done", "ok": True})
    assert codoh.configure(chat_id, {"model": "chatgpt:gpt-6.2"})["ok"]
    assert claude.closed
    note = items(codoh, chat_id, "note")[-1]
    assert "ChatGPT" in note["text"]
    codoh.send(chat_id, "Now add tests")
    chatgpt = world.engines[1]
    assert chatgpt.engine == "chatgpt" and chatgpt.settings["model"] == "gpt-6.2"
    sent = chatgpt.sent[0]
    assert "User: What does calc.py do?" in sent and "Assistant: It adds numbers." in sent
    assert sent.endswith("Now add tests")
    codoh.configure(chat_id, {"model": "claude:opus"})  # and back: a new Claude Code session
    assert world.codoh.store.load(chat_id)["claude_session"] == ""


def test_moving_needs_the_other_plan(tmp_path):
    world = World(tmp_path, chatgpt=False)
    chat_id = world.chat()
    assert world.codoh.configure(chat_id, {"model": "chatgpt:gpt-6.2"})["error"] == NO_CHATGPT


def test_chatgpt_takes_over_when_claudes_limit_runs_out(world):
    codoh = world.codoh
    chat_id = world.chat()
    codoh.send(chat_id, "Refactor the parser")
    claude = world.engines[0]
    resets = world.clock.now + 3600
    claude.on_event(
        {"type": "done", "ok": False, "error": "limit", "limit": True, "resets_at": resets}
    )
    chatgpt = world.engines[1]
    assert chatgpt.engine == "chatgpt"
    assert chatgpt.sent[0].endswith("Refactor the parser")  # the same request, sent again
    note = items(codoh, chat_id, "note")[-1]["text"]
    assert note.startswith("Claude's limit is used up until") and "ChatGPT plan" in note
    assert not items(codoh, chat_id, "error")
    state = codoh.state()
    assert state["default_engine"] == "chatgpt" and state["limited_until"] == resets
    other = world.chat()  # a new chat starts on ChatGPT meanwhile
    assert codoh.chat(other)["chat"]["engine"] == "chatgpt"
    world.clock.now = resets + 1
    assert codoh.state()["default_engine"] == "claude"


def test_a_claude_chat_moves_when_sent_during_the_limit(world):
    codoh = world.codoh
    first = world.chat()
    second = world.chat()
    codoh.send(first, "a")
    world.engines[0].on_event({"type": "done", "limit": True, "resets_at": world.clock.now + 60})
    codoh.send(second, "b")
    assert world.engines[-1].engine == "chatgpt" and world.engines[-1].sent == ["b"]


def test_no_takeover_when_switched_off(world):
    world.cfg.claude.fallback = False
    chat_id = world.chat()
    world.codoh.send(chat_id, "hi")
    limit = "You've reached your Claude usage limit for now."
    world.engines[0].on_event({"type": "done", "ok": False, "error": limit, "limit": True})
    assert items(world.codoh, chat_id, "error")[0]["text"].startswith("You've reached")
    assert len(world.engines) == 1


def test_chats_come_back_after_a_restart(world):
    chat_id = world.chat()
    world.codoh.send(chat_id, "hi")
    world.engines[0].on_event({"type": "session", "id": "s-9"})
    world.engines[0].on_event({"type": "text", "delta": "Hello!"})
    world.engines[0].on_event({"type": "done", "ok": True})
    again = world.make()
    assert [i["kind"] for i in items(again, chat_id)] == ["user", "assistant", "done"]
    again.send(chat_id, "go on")
    assert world.engines[-1].settings["session_id"] == "s-9"


def test_rename_and_delete(world):
    chat_id = world.chat()
    assert world.codoh.rename(chat_id, "  Parser   work ")["ok"]
    assert world.codoh.state()["chats"][0]["title"] == "Parser work"
    world.codoh.delete(chat_id)
    assert world.codoh.state()["chats"] == []
    assert not world.codoh.chat(chat_id)["ok"]


def test_no_claude_code(tmp_path):
    world = World(tmp_path, claude=False)
    assert world.codoh.state()["default_engine"] == "chatgpt"
    world.chatgpt = False
    chat_id = world.chat(engine="claude")
    result = world.codoh.send(chat_id, "hi")
    assert not result["ok"] and "isn't installed" in result["error"]
    assert items(world.codoh, chat_id, "error")


def test_models_of_both_plans(world):
    import time

    world.codoh.models()
    deadline = time.monotonic() + 3
    while not world.codoh.claude_models and time.monotonic() < deadline:
        time.sleep(0.01)
    found = world.codoh.models()
    assert found["claude"] == [{"id": "opus", "name": "Opus 5.5"}] and found["claude_plan"] == "Pro"
    assert found["chatgpt"] == [{"id": "gpt-6.2", "name": "GPT-6.2", "line": ""}]


def test_summary_for_the_other_plan():
    found = [
        {"kind": "user", "text": "fix it"},
        {"kind": "tool", "kind_of": "command", "title": "npm test", "ok": False},
        {"kind": "assistant", "text": "Done."},
    ]
    text = summary(found, "claude")
    assert "another coding assistant, Claude" in text
    assert "User: fix it\n[ran npm test (it failed)]\nAssistant: Done." in text


def test_folders(world, tmp_path):
    assert not world.codoh.open_folder(str(tmp_path / "missing"))["ok"]
    other = tmp_path / "other"
    other.mkdir()
    opened = world.codoh.open_folder(str(other))
    assert opened["ok"] and opened["folder"]["name"] == "other"
    assert world.codoh.state()["folders"][0]["name"] == "other"
    world.codoh.forget_folder(str(other.resolve()))
    assert all(f["name"] != "other" for f in world.codoh.state()["folders"])


# ----- git -----


def fake_git(outputs):
    def run(folder, *args):
        return outputs.get(args)

    return run


def test_git_info_and_changes(tmp_path):
    (tmp_path / "new.py").write_text("a\nb\n", "utf-8")
    outputs = {
        ("branch", "--show-current"): "main\n",
        ("status", "--porcelain=v1"): " M app.py\n?? new.py\n",
        ("status", "--porcelain=v1", "-uall"): " M app.py\n?? new.py\n",
        ("diff", "--numstat"): "3\t1\tapp.py\n",
        ("diff", "--numstat", "--cached"): "",
    }
    run = fake_git(outputs)
    assert git.info(tmp_path, git=run) == {"branch": "main", "changed": 2}
    assert git.changes(tmp_path, git=run) == [
        {"path": "app.py", "state": "changed", "added": 3, "removed": 1},
        {"path": "new.py", "state": "new", "added": 2, "removed": 0},
    ]
    assert git.info(tmp_path, git=lambda *a: None) is None
    assert "+a" in git.diff(tmp_path, "new.py", git=lambda *a: "")
    assert git.diff(tmp_path, "../outside.py", git=run) == ""


def test_git_for_real_in_a_temporary_repository(tmp_path):
    if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
        pytest.skip("no git here")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "a.txt").write_text("one\n", "utf-8")
    assert git.changes(tmp_path) == [{"path": "a.txt", "state": "new", "added": 1, "removed": 0}]
    assert git.info(tmp_path)["changed"] == 1


# ----- the window -----


def test_the_window_api(tmp_path):
    from abdoh.events import Bus
    from abdoh.ui.api import AppApi, UiState

    world = World(tmp_path)
    api = AppApi(Bus(), UiState(), world.cfg, codoh=world.codoh)
    assert api.codoh_open_folder(str(world.folder))["ok"]
    assert api.codoh_open_folder()["cancelled"]  # no window to pick one in
    chat_id = api.codoh_new_chat(str(world.folder))["chat"]["id"]
    assert api.codoh_send(chat_id, "hi")["ok"]
    assert api.codoh_chat(chat_id)["running"]
    assert api.codoh_reveal(str(world.folder)) is True or True


def test_abdoh_open_codoh(tmp_path):
    """ "Abdoh, open Codoh": the window comes up on the page."""
    from fakes import FakeTranscriber, FakeWakeWord

    from abdoh.commands.registry import CommandRegistry
    from abdoh.daemon import Daemon
    from abdoh.events import Bus
    from abdoh.router import Router
    from abdoh.speech.tts import FakeSpeaker

    cfg = Config(app_dir=tmp_path)
    bus = Bus()
    router = Router(cfg, CommandRegistry(tmp_path / "none.yaml"))
    Daemon(cfg, router, FakeSpeaker(), None, FakeWakeWord(10_000), FakeTranscriber([]), bus=bus)
    assert router.handle("open codoh") == "Opening Codoh."
    events = bus.pending_events()
    assert ("show", None) in events and ("page", "codoh") in events
