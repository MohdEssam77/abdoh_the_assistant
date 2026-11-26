"""Codoh's ChatGPT chats (codoh/chatgpt.py) and its tools (codoh/tools.py), with a fake
Responses API and a fake shell."""

import json
import subprocess
import time
from types import SimpleNamespace

import pytest

from abdoh.codoh.chatgpt import OFF, ChatGPTChat, clean, instructions, trimmed
from abdoh.codoh.tools import READ_ONLY_TOOLS, TOOLS, ToolError, Workspace, command_prefix
from abdoh.config import Config

# ----- the tools -----


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "project"
    (folder / "src").mkdir(parents=True)
    (folder / "src" / "app.py").write_text("def add(a, b):\n    return a - b\n", "utf-8")
    (folder / "README.md").write_text("# Demo\n", "utf-8")
    (folder / "node_modules").mkdir()
    (folder / "node_modules" / "x.js").write_text("return a - b", "utf-8")
    (tmp_path / "secret.txt").write_text("keys", "utf-8")
    return folder


def test_only_inside_the_project_folder(project, tmp_path):
    ws = Workspace(project)
    for outside in ("../secret.txt", str(tmp_path / "secret.txt"), "src/../../secret.txt"):
        with pytest.raises(ToolError, match="outside the project folder"):
            ws.read_file(outside)
    assert ws.resolve("src/app.py") == (project / "src" / "app.py").resolve()


def test_a_link_out_of_the_folder_is_refused(project, tmp_path):
    link = project / "out"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("making links needs more rights here")
    with pytest.raises(ToolError, match="outside"):
        Workspace(project).read_file("out/secret.txt")


def test_list_read_and_search(project):
    ws = Workspace(project)
    assert ws.list_files() == "src/\nREADME.md"  # folders first; node_modules skipped
    assert ws.list_files(pattern="*.py") == "src/app.py"
    assert ws.read_file("src/app.py") == "    1\tdef add(a, b):\n    2\t    return a - b"
    assert ws.read_file("src/app.py", offset=2) == "    2\t    return a - b"
    assert "more lines" in ws.read_file("src/app.py", limit=1)
    assert ws.search(r"a - b") == "src/app.py:2: return a - b"  # not in node_modules
    assert ws.search("nothing here") == "No matches."
    with pytest.raises(ToolError, match="regular expression"):
        ws.search("(")


def test_write_and_edit(project):
    ws = Workspace(project)
    assert ws.write_file("docs/notes.md", "hi\n") == "Created docs/notes.md (1 lines)."
    assert (project / "docs" / "notes.md").read_text("utf-8") == "hi\n"
    assert ws.edit_file("src/app.py", "a - b", "a + b") == "Changed src/app.py."
    assert "a + b" in (project / "src" / "app.py").read_text("utf-8")
    with pytest.raises(ToolError, match="wasn't found"):
        ws.edit_file("src/app.py", "a * b", "x")
    (project / "twice.py").write_text("x\nx\n", "utf-8")
    with pytest.raises(ToolError, match="2 times"):
        ws.edit_file("twice.py", "x", "y")
    assert ws.edit_file("twice.py", "x", "y", replace_all=True) == "Changed twice.py (2 places)."


def test_run_a_command_in_the_folder(project):
    seen = {}

    def run(args, **kwargs):
        seen.update(args=args, **kwargs)
        return SimpleNamespace(stdout="3 passed\n", stderr="", returncode=0)

    out = Workspace(project, run=run).run_command("pytest -q", timeout_seconds=5000)
    assert out == "3 passed\n(exit code 0)"
    assert seen["cwd"] == project.resolve() and seen["timeout"] == 600
    assert "pytest -q" in seen["args"]

    def slow(args, **kwargs):
        raise subprocess.TimeoutExpired(args, 1, output="half")

    assert "(stopped after 1 seconds)" in Workspace(project, run=slow).run_command("x", 1)


def test_command_prefixes():
    assert command_prefix("npm test -- --watch") == "npm test"
    assert command_prefix("pytest -q") == "pytest"
    assert command_prefix("git status") == "git status"


def test_tool_lists():
    names = {t["name"] for t in TOOLS}
    assert names == {"list_files", "read_file", "search", "write_file", "edit_file", "run_command"}
    assert {t["name"] for t in READ_ONLY_TOOLS} == {"list_files", "read_file", "search"}


# ----- the chat -----


class FakeResponse:
    def __init__(self, status, events=(), body=None):
        self.status_code = status
        self.events = list(events)
        self.body = body or {}
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b""

    def json(self):
        return self.body

    @property
    def text(self):
        return json.dumps(self.body)

    def iter_lines(self):
        for event in self.events:
            if self.closed:
                return
            if event == "WAIT":
                time.sleep(0.3)
                continue
            yield "data: " + json.dumps(event)

    def close(self):
        self.closed = True


class FakeHTTP:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.bodies = []

    def stream(self, method, url, json=None, headers=None):
        self.bodies.append(json)
        return self.responses.pop(0)


class FakeSession:
    def __init__(self):
        self.account = SimpleNamespace(plan_usage=True)

    def access_token(self, force=False):
        return "token"

    def models(self):
        return [{"id": "gpt-6.2", "name": "GPT-6.2"}]


def answer(text):
    """A streamed answer with only text."""
    message = {"type": "message", "content": [{"type": "output_text", "text": text}]}
    return FakeResponse(
        200,
        [
            {"type": "response.output_text.delta", "delta": text},
            {"type": "response.completed", "response": {"output": [message]}},
        ],
    )


def calls(*items):
    """A streamed answer that calls tools: (name, arguments) pairs."""
    output = [
        {"type": "function_call", "call_id": f"c{i}", "name": name, "arguments": json.dumps(args)}
        for i, (name, args) in enumerate(items)
    ]
    output.insert(0, {"type": "reasoning", "id": "r1", "summary": [], "encrypted_content": "enc"})
    return FakeResponse(200, [{"type": "response.completed", "response": {"output": output}}])


def make_chat(project, *responses, mode="ask", run=None):
    events = []
    http = FakeHTTP(*responses)
    chat = ChatGPTChat(
        Config(app_dir=project.parent),
        project,
        events.append,
        mode=mode,
        session=FakeSession(),
        http=http,
        run=run or subprocess.run,
    )
    return chat, events, http


def wait_done(events, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        done = [e for e in events if e["type"] == "done"]
        if done:
            return done[0]
        time.sleep(0.01)
    raise AssertionError(f"not done: {events}")


def wait_for(events, kind):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        found = [e for e in events if e["type"] == kind]
        if found:
            return found[0]
        time.sleep(0.01)
    raise AssertionError(f"no {kind}: {events}")


def test_a_plain_answer(project):
    chat, events, http = make_chat(project, answer("It adds numbers."))
    chat.send("what does app.py do?")
    done = wait_done(events)
    assert done["ok"] and [e["delta"] for e in events if e["type"] == "text"] == [
        "It adds numbers."
    ]
    body = http.bodies[0]
    assert body["model"] == "gpt-6.2" and body["store"] is False and body["stream"] is True
    assert body["include"] == ["reasoning.encrypted_content"]
    assert str(project) in body["instructions"] and "Abdoh" not in body["instructions"]
    assert body["input"][0]["content"][0]["text"] == "what does app.py do?"
    assert chat.items[-1]["role"] == "assistant"


def test_tools_run_and_their_output_goes_back(project):
    chat, events, http = make_chat(
        project, calls(("read_file", {"path": "src/app.py"})), answer("It subtracts: a bug.")
    )
    chat.send("is add right?")
    assert wait_done(events)["ok"]
    tool = wait_for(events, "tool")
    assert tool["name"] == "read_file" and tool["input"] == {"path": "src/app.py"}
    result = wait_for(events, "tool_result")
    assert result["ok"] and "return a - b" in result["output"]
    second = http.bodies[1]["input"]
    kinds = [i.get("type") for i in second]
    assert kinds == ["message", "reasoning", "function_call", "function_call_output"]
    assert second[1]["encrypted_content"] == "enc"
    assert "return a - b" in second[3]["output"]
    assert not [e for e in events if e["type"] == "approval"]  # reading just happens


def test_a_change_asks_first(project):
    edit = ("edit_file", {"path": "src/app.py", "old_text": "a - b", "new_text": "a + b"})
    chat, events, http = make_chat(project, calls(edit), answer("Fixed."))
    chat.send("fix it")
    ask = wait_for(events, "approval")
    assert ask["tool"] == "edit_file" and ask["suggestions"][0]["kind"] == "edits"
    assert "a - b" in (project / "src" / "app.py").read_text("utf-8")  # not yet
    chat.answer(ask["id"], True)
    assert wait_done(events)["ok"]
    assert "a + b" in (project / "src" / "app.py").read_text("utf-8")
    result = wait_for(events, "tool_result")
    assert "+    return a + b" in result["result"]["diff"]


def test_no_means_no(project):
    edit = ("edit_file", {"path": "src/app.py", "old_text": "a - b", "new_text": "a + b"})
    chat, events, http = make_chat(project, calls(edit), answer("Okay, I won't."))
    chat.send("fix it")
    chat.answer(wait_for(events, "approval")["id"], False)
    wait_done(events)
    assert "a - b" in (project / "src" / "app.py").read_text("utf-8")
    assert "said no" in http.bodies[1]["input"][-1]["output"]


def test_allow_for_this_chat(project):
    one = ("edit_file", {"path": "src/app.py", "old_text": "a - b", "new_text": "a + b"})
    two = ("write_file", {"path": "NOTES.md", "content": "done\n"})
    chat, events, _ = make_chat(project, calls(one), calls(two), answer("Done."))
    chat.send("fix it and take notes")
    ask = wait_for(events, "approval")
    chat.answer(ask["id"], True, rules=ask["suggestions"])
    wait_done(events)
    assert len([e for e in events if e["type"] == "approval"]) == 1
    assert (project / "NOTES.md").read_text("utf-8") == "done\n"


def test_modes(project):
    run_calls = []

    def run(args, **kwargs):
        run_calls.append(args)
        return SimpleNamespace(stdout="ok", stderr="", returncode=1)

    edit = ("write_file", {"path": "x.txt", "content": "x"})
    command = ("run_command", {"command": "npm test"})
    chat, events, _ = make_chat(
        project, calls(edit, command), answer("ok"), mode="auto_edit", run=run
    )
    chat.send("go")
    ask = wait_for(events, "approval")
    assert ask["tool"] == "run_command"  # changes just happen; commands ask
    chat.answer(ask["id"], True)
    wait_done(events)
    failed = [e for e in events if e["type"] == "tool_result"][-1]
    assert not failed["ok"]  # exit code 1

    chat, events, _ = make_chat(project, calls(command), answer("ok"), mode="full", run=run)
    chat.send("go")
    wait_done(events)
    assert not [e for e in events if e["type"] == "approval"]


def test_plan_mode_changes_nothing(project):
    write = ("write_file", {"path": "x.txt", "content": "x"})
    chat, events, http = make_chat(project, calls(write), answer("1. Fix add"), mode="plan")
    chat.send("plan the fix")
    wait_done(events)
    assert not (project / "x.txt").exists()
    assert {t["name"] for t in http.bodies[0]["tools"]} == {"list_files", "read_file", "search"}
    assert "plan mode" in http.bodies[0]["instructions"]


def test_stop_while_it_asks(project):
    edit = ("write_file", {"path": "x.txt", "content": "x"})
    chat, events, _ = make_chat(project, calls(edit))
    chat.send("go")
    wait_for(events, "approval")
    chat.interrupt()
    done = wait_done(events)
    assert done["stopped"] and done["error"] is None and not (project / "x.txt").exists()


def test_errors_are_said(project):
    limited = FakeResponse(429, body={"error": {"code": "rate_limit_exceeded", "message": "x"}})
    chat, events, _ = make_chat(project, limited)
    chat.send("hi")
    done = wait_done(events)
    assert not done["ok"] and done["error"]


def test_not_connected(project):
    chat, events, _ = make_chat(project)
    chat.account = SimpleNamespace(plan_usage=False)
    chat.send("hi")
    assert wait_done(events)["error"] == OFF


def test_a_model_without_reasoning_is_asked_again(project):
    refused = FakeResponse(400, body={"error": {"message": "reasoning isn't supported"}})
    chat, events, http = make_chat(project, refused, answer("ok"))
    chat.send("hi")
    assert wait_done(events)["ok"]
    assert "include" not in http.bodies[1]


def test_items_kept_and_trimmed():
    assert clean(
        {"type": "message", "id": "m", "content": [{"type": "output_text", "text": "a"}]}
    ) == {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "a"}],
    }
    assert clean({"type": "reasoning", "summary": []}) is None  # nothing to send back
    user = {"type": "message", "role": "user", "content": []}
    other = {"type": "function_call_output", "call_id": "c", "output": "x"}
    items = [user, other, other, user, other]
    assert trimmed(items, keep=3) == [user, other]
    assert "plan mode" in instructions(__import__("pathlib").Path("x"), "plan")
