"""Codoh's Claude chats: a fake Claude Code process (codoh/claude.py, codoh/cards.py)."""

import json
import queue
import time

from abdoh.codoh import cards
from abdoh.codoh.claude import MODELS, ClaudeChat, models_from


class FakeProcess:
    """Claude Code: what Codoh writes to it, and lines the test makes it print."""

    def __init__(self, args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.written = []
        self.lines = queue.Queue()
        self.code = None
        self.stdin = self
        self.stdout = self

    # stdin
    def write(self, text):
        self.written.append(json.loads(text))

    def flush(self):
        pass

    def close(self):
        pass

    # stdout
    def __iter__(self):
        while True:
            line = self.lines.get()
            if line is None:
                self.code = 1
                return
            yield line

    def say(self, event):
        self.lines.put(json.dumps(event) + "\n")

    def poll(self):
        return self.code

    def kill(self):
        self.lines.put(None)

    def wait(self, timeout=None):
        return self.code


class Started:
    def __init__(self):
        self.procs = []

    def __call__(self, args, **kwargs):
        proc = FakeProcess(args, **kwargs)
        self.procs.append(proc)
        return proc


def make(tmp_path, **kwargs):
    events = []
    popen = Started()
    chat = ClaudeChat(tmp_path / "claude.exe", tmp_path, events.append, popen=popen, **kwargs)
    return chat, events, popen


def wait_for(events, kind, count=1):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        found = [e for e in events if e["type"] == kind]
        if len(found) >= count:
            return found[count - 1]
        time.sleep(0.01)
    raise AssertionError(f"no {kind} event: {events}")


def test_it_starts_in_the_folder_as_plain_claude_code(tmp_path):
    chat, _, popen = make(tmp_path, model="sonnet", mode="auto_edit", effort="high")
    chat.send("explain this project")
    proc = popen.procs[0]
    assert proc.kwargs["cwd"] == tmp_path
    args = proc.args
    assert args[args.index("--permission-mode") + 1] == "acceptEdits"
    assert args[args.index("--model") + 1] == "sonnet"
    assert args[args.index("--effort") + 1] == "high"
    assert "--permission-prompt-tool" in args and "--resume" not in args
    assert "--system-prompt-file" not in args and "--safe-mode" not in args  # Claude Code's own
    assert "ANTHROPIC_API_KEY" not in proc.kwargs["env"]
    first, second = proc.written
    assert first["request"]["subtype"] == "initialize"
    assert second == {
        "type": "user",
        "message": {"role": "user", "content": "explain this project"},
    }
    chat.close()


def test_a_saved_chat_comes_back(tmp_path):
    chat, _, popen = make(tmp_path, session_id="abc-123")
    chat.send("go on")
    args = popen.procs[0].args
    assert args[args.index("--resume") + 1] == "abc-123"
    chat.close()


def test_a_reply_as_events(tmp_path):
    chat, events, popen = make(tmp_path)
    chat.send("fix the bug")
    proc = popen.procs[0]
    proc.say(
        {
            "type": "control_response",
            "response": {
                "subtype": "success",
                "request_id": "codoh-1",
                "response": {
                    "models": [
                        {"value": "opus", "displayName": "Opus 5.5", "description": "Complex"}
                    ],
                    "account": {"subscriptionType": "Claude Pro"},
                },
            },
        }
    )
    proc.say({"type": "system", "subtype": "init", "session_id": "s-1"})
    proc.say({"type": "stream_event", "event": {"type": "message_start", "message": {"id": "m1"}}})
    for word in ("Let me ", "look."):
        delta = {"type": "text_delta", "text": word}
        proc.say({"type": "stream_event", "event": {"type": "content_block_delta", "delta": delta}})
    proc.say(
        {
            "type": "assistant",
            "message": {
                "id": "m1",
                "content": [
                    {"type": "text", "text": "Let me look."},  # already streamed: not again
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Read",
                        "input": {"file_path": str(tmp_path / "app.py")},
                    },
                ],
            },
        }
    )
    proc.say(
        {
            "type": "user",
            "message": {
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "print(1)"}]
            },
            "tool_use_result": {"type": "text"},
        }
    )
    proc.say({"type": "result", "subtype": "success", "total_cost_usd": 0.01})
    done = wait_for(events, "done")
    assert done["ok"] and not done["error"] and not done["stopped"]
    kinds = [e["type"] for e in events]
    assert kinds == ["ready", "session", "text", "text", "tool", "tool_result", "done"]
    assert events[0]["models"][0] == {
        "id": "opus",
        "name": "Opus 5.5",
        "line": "Complex",
        "efforts": [],
    }
    assert events[0]["plan"] == "Claude Pro" and chat.session_id == "s-1"
    assert events[5] == {
        "type": "tool_result",
        "id": "t1",
        "ok": True,
        "output": "print(1)",
        "result": {"type": "text"},
    }
    assert not chat.busy
    chat.close()


def test_approvals_ask_codoh_and_wait(tmp_path):
    chat, events, popen = make(tmp_path)
    chat.send("delete the build folder")
    proc = popen.procs[0]
    suggestion = {"type": "setMode", "mode": "acceptEdits", "destination": "session"}
    proc.say(
        {
            "type": "control_request",
            "request_id": "r-9",
            "request": {
                "subtype": "can_use_tool",
                "tool_name": "Bash",
                "input": {"command": "rm -rf build"},
                "description": "Remove the build folder",
                "permission_suggestions": [suggestion],
                "tool_use_id": "t2",
            },
        }
    )
    ask = wait_for(events, "approval")
    assert ask["id"] == "r-9" and ask["tool"] == "Bash" and ask["suggestions"] == [suggestion]
    chat.answer("r-9", True, data={"command": "rm -rf build"}, rules=ask["suggestions"])
    allowed = proc.written[-1]["response"]
    assert allowed["request_id"] == "r-9"
    assert allowed["response"]["behavior"] == "allow"
    assert allowed["response"]["updatedPermissions"] == [suggestion]
    chat.answer("r-10", False)
    denied = proc.written[-1]["response"]["response"]
    assert denied == {"behavior": "deny", "message": "The user said no."}
    chat.close()


def test_stop_interrupts_and_the_chat_goes_on(tmp_path):
    chat, events, popen = make(tmp_path)
    chat.send("refactor everything")
    proc = popen.procs[0]
    chat.interrupt()
    assert proc.written[-1]["request"] == {"subtype": "interrupt"}
    proc.say({"type": "result", "subtype": "error_during_execution", "is_error": True})
    done = wait_for(events, "done")
    assert done["stopped"] and done["ok"] and done["error"] is None
    chat.send("now just the tests")
    assert len(popen.procs) == 1  # the same process
    chat.close()


def test_model_and_mode_change_mid_chat(tmp_path):
    chat, _, popen = make(tmp_path)
    chat.send("hi")
    proc = popen.procs[0]
    chat.set_model("haiku")
    chat.set_mode("plan")
    assert proc.written[-2]["request"] == {"subtype": "set_model", "model": "haiku"}
    assert proc.written[-1]["request"] == {"subtype": "set_permission_mode", "mode": "plan"}
    proc.say({"type": "result", "subtype": "success"})
    time.sleep(0.05)
    chat.set_effort("max")  # taken at start: the next message starts it again
    chat.send("again")
    assert len(popen.procs) == 2 and "--effort" in popen.procs[1].args
    chat.close()


def test_the_limit(tmp_path):
    chat, events, popen = make(tmp_path)
    chat.send("hi")
    proc = popen.procs[0]
    info = {"status": "rejected", "resetsAt": 1795665000}
    proc.say({"type": "rate_limit_event", "rate_limit_info": info})
    proc.say({"type": "result", "subtype": "error", "is_error": True, "result": "limit reached"})
    done = wait_for(events, "done")
    assert done["limit"] and done["resets_at"] == 1795665000
    assert done["error"].startswith("You've reached your Claude usage limit")
    chat.close()


def test_claude_code_dying_mid_reply(tmp_path):
    chat, events, popen = make(tmp_path)
    chat.send("hi")
    popen.procs[0].kill()
    done = wait_for(events, "done")
    assert not done["ok"] and done["error"] == "Claude Code stopped unexpectedly."


def test_models_from_initialize():
    init = {
        "models": [
            {"value": "fable", "displayName": "Fable 5.2", "supportedEffortLevels": ["low", "max"]},
            {},
        ]
    }
    assert models_from(init) == [
        {"id": "fable", "name": "Fable 5.2", "line": "", "efforts": ["low", "max"]}
    ]
    assert MODELS[0]["id"] == "default"


# ----- cards -----


def test_cards_for_claude_code_tools(tmp_path):
    read = cards.card("Read", {"file_path": str(tmp_path / "src" / "app.py")}, tmp_path)
    assert read["kind"] == "read" and read["title"] == "src/app.py" and read["status"] == "running"
    edit = cards.card(
        "Edit",
        {"file_path": str(tmp_path / "a.py"), "old_string": "x = 1", "new_string": "x = 2"},
        tmp_path,
    )
    assert "-x = 1" in edit["diff"] and "+x = 2" in edit["diff"]
    assert "@@ … @@" in edit["diff"]  # where in the file isn't known before it runs
    assert cards.counts(edit["diff"]) == (1, 1)
    command = cards.card("PowerShell", {"command": "npm test", "description": "Run the tests"})
    assert (command["kind"], command["title"], command["detail"]) == (
        "command",
        "npm test",
        "Run the tests",
    )
    todo = cards.card("TodoWrite", {"todos": [{"content": "Write tests", "status": "pending"}]})
    assert todo["kind"] == "todo" and json.loads(todo["detail"])[0]["text"] == "Write tests"
    assert cards.card("Mystery", {"a": 1})["kind"] == "other"


def test_finished_cards_take_claude_codes_patch():
    edit = cards.card("Edit", {"file_path": "a.py", "old_string": "a", "new_string": "b"})
    patch = [{"oldStart": 3, "oldLines": 1, "newStart": 3, "newLines": 1, "lines": ["-a", "+b"]}]
    cards.finish(edit, True, "ok", {"structuredPatch": patch})
    assert "@@ -3,1 +3,1 @@" in edit["diff"] and edit["status"] == "done"
    run = cards.card("Bash", {"command": "ls"})
    cards.finish(run, False, "", {"stdout": "a\nb", "stderr": "oops"})
    assert run["status"] == "failed" and run["output"] == "a\nb\noops"
    long = cards.card("Bash", {"command": "x"})
    cards.finish(long, True, "y" * (cards.OUTPUT_CHARS + 50))
    assert long["output"].startswith("…") and len(long["output"]) < cards.OUTPUT_CHARS + 10
