"""Claude Code backend with a fake `claude` process (no Claude Code, no network)."""

import json
import subprocess
import threading
from pathlib import Path

import pytest

from abdoh.claude.brain import BrainError
from abdoh.claude.code import (
    FAILED,
    FILE_TOOLS,
    LIMIT,
    NOT_SIGNED_IN,
    SCREENSHOT,
    START_FAILED,
    TOO_SLOW,
    ClaudeCodeBrain,
    activity,
    auth_status,
    describe_status,
    editor_binaries,
    error_message,
    find_claude_code,
    limit_message,
    read_events,
    user_folders,
)
from abdoh.config import ClaudeConfig, Config


def delta(text):
    event = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}
    return json.dumps({"type": "stream_event", "event": event})


def message_start():
    return json.dumps({"type": "stream_event", "event": {"type": "message_start"}})


def result(text="", is_error=False, subtype="success"):
    return json.dumps({"type": "result", "subtype": subtype, "is_error": is_error, "result": text})


def rate_limit(status, resets_at=None):
    info = {"status": status, "resetsAt": resets_at}
    return json.dumps({"type": "rate_limit_event", "rate_limit_info": info})


INIT = json.dumps({"type": "system", "subtype": "init", "tools": []})


class FakeStdin:
    def __init__(self, broken=False):
        self.lines = []
        self.closed = False
        self.broken = broken

    def write(self, text):
        if self.broken:
            raise OSError("pipe closed")
        self.lines.append(text)

    def flush(self):
        pass

    def close(self):
        self.closed = True

    @property
    def prompts(self):
        """What was asked, without the date and time stamp in front."""
        return [
            json.loads(line)["message"]["content"].split("\n", 1)[1]
            for line in self.lines
            if json.loads(line)["type"] == "user"
        ]

    @property
    def interrupts(self):
        return [json.loads(line) for line in self.lines if '"control_request"' in line]


class FakeProc:
    """A `claude -p --input-format stream-json` process: `replies` is one list of output lines
    per request; they're only produced once that request has been written to stdin."""

    def __init__(self, replies, returncode=0, hang=False, dead=False, deaf=False):
        self.stdin = FakeStdin(broken=dead)
        self._replies = replies
        self._returncode = returncode
        self._hang = hang
        self._deaf = deaf  # ignores interrupts
        self.killed = threading.Event()
        self.returncode = returncode if dead else None
        self.stdout = self._output()

    def _output(self):
        answered = 0
        for reply in self._replies:
            for line in reply:
                asked = self.stdin.interrupts
                if len(asked) > answered and not self._deaf:
                    # Like Claude Code: confirm, end this reply, drop the rest of it.
                    answered = len(asked)
                    response = {"subtype": "success", "request_id": asked[-1]["request_id"]}
                    yield json.dumps({"type": "control_response", "response": response}) + "\n"
                    yield result(is_error=True, subtype="error_during_execution") + "\n"
                    break
                yield line + "\n"
        if self._hang or self._deaf:
            self.killed.wait(5)  # like a stuck process: no more output until killed

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = -9 if self.killed.is_set() else self._returncode
        return self.returncode

    def kill(self):
        self.killed.set()
        self.returncode = -9


class FakePopen:
    def __init__(
        self,
        *replies,
        returncode=0,
        stderr=b"",
        hang=False,
        error=None,
        dead_first=False,
        deaf=False,
    ):
        self.replies = [list(r) for r in replies]
        self.returncode = returncode
        self.stderr = stderr
        self.hang = hang
        self.error = error
        self.dead_first = dead_first
        self.deaf = deaf
        self.calls = []
        self.procs = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        kwargs["stderr"].write(self.stderr)
        dead = self.dead_first and not self.procs
        proc = FakeProc(self.replies, self.returncode, self.hang, dead, self.deaf)
        self.procs.append(proc)
        return proc


class FakeTimer:
    """threading.Timer that only runs when a test says so."""

    made: list = []

    def __init__(self, seconds, function, args=()):
        self.seconds, self.function, self.args = seconds, function, args
        self.cancelled = False
        self.daemon = False
        FakeTimer.made.append(self)

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.function(*self.args)


HOME = Path("C:/Users/me")
FOLDERS = {"Desktop": HOME / "OneDrive" / "Desktop", "Downloads": HOME / "Downloads"}


def make_brain(tmp_path, popen, folders=FOLDERS, timer=threading.Timer, keep_warm=False, **claude):
    cfg = Config(app_dir=tmp_path, claude=ClaudeConfig(**claude))
    return ClaudeCodeBrain(
        cfg,
        Path("claude.exe"),
        popen=popen,
        workdir=tmp_path / "work",
        home=HOME,
        folders=folders,
        timer=timer,
        keep_warm=keep_warm,
    )


# ----- finding Claude Code -----


def test_configured_path_wins(tmp_path):
    exe = tmp_path / "my-claude.exe"
    exe.write_text("")
    assert find_claude_code(str(exe), home=tmp_path, which=lambda n: "/usr/bin/claude") == exe
    assert find_claude_code(str(tmp_path / "missing.exe"), home=tmp_path) is None


def test_path_then_local_bin(tmp_path):
    assert find_claude_code(home=tmp_path, which=lambda n: "C:/bin/claude.exe") == Path(
        "C:/bin/claude.exe"
    )
    local = tmp_path / ".local" / "bin"
    local.mkdir(parents=True)
    exe_name = "claude.exe" if __import__("sys").platform == "win32" else "claude"
    (local / exe_name).write_text("")
    assert find_claude_code(home=tmp_path, which=lambda n: None) == local / exe_name


def test_newest_editor_binary(tmp_path):
    exe_name = "claude.exe" if __import__("sys").platform == "win32" else "claude"
    for version in ("2.1.9", "2.1.325", "2.1.40"):
        d = tmp_path / ".vscode" / "extensions" / f"anthropic.claude-code-{version}-win32-x64"
        (d / "resources" / "native-binary").mkdir(parents=True)
        (d / "resources" / "native-binary" / exe_name).write_text("")
    found = editor_binaries(tmp_path)
    assert [p.parents[2].name.split("-")[2] for p in found] == ["2.1.325", "2.1.40", "2.1.9"]
    assert find_claude_code(home=tmp_path, which=lambda n: None) == found[0]


def test_nothing_found(tmp_path):
    assert find_claude_code(home=tmp_path, which=lambda n: None) is None


# ----- sign-in status -----


class FakeRun:
    def __init__(self, stdout="", error=None):
        self.stdout = stdout
        self.error = error
        self.args = None

    def __call__(self, args, **kwargs):
        self.args = args
        if self.error:
            raise self.error
        return type("Done", (), {"stdout": self.stdout})()


def test_auth_status_parses_json_with_extra_text():
    run = FakeRun('{"loggedIn": true, "authMethod": "claude.ai", "subscriptionType": "pro"}\nok')
    info = auth_status(Path("claude.exe"), run)
    assert info["subscriptionType"] == "pro"
    assert run.args[1:] == ["auth", "status"]


def test_auth_status_failure_is_none():
    assert auth_status(Path("claude.exe"), FakeRun(error=OSError("missing"))) is None
    assert auth_status(Path("claude.exe"), FakeRun("not json")) is None


def test_describe_status():
    pro = {"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "pro"}
    assert describe_status(pro) == "Pro subscription (Claude Code)"
    assert describe_status({"loggedIn": False}) == "Claude Code (not signed in)"
    assert describe_status({"loggedIn": True, "authMethod": "api_key"}) == "Claude Code"
    assert "couldn't check" in describe_status(None)


# ----- reading the event stream -----


def test_read_events_yields_text_deltas():
    lines = [INIT, delta("Tokyo "), delta("is the capital."), result("Tokyo is the capital.")]
    assert "".join(read_events(lines)) == "Tokyo is the capital."


def test_new_message_starts_on_a_new_line():
    lines = [
        message_start(),
        delta("Let me check."),
        message_start(),
        delta("It's sunny."),
        result(),
    ]
    assert "".join(read_events(lines)) == "Let me check.\nIt's sunny."


def test_result_text_is_used_when_nothing_streamed():
    assert "".join(read_events([INIT, result("Hello.")])) == "Hello."


def test_result_error_is_spoken_safely():
    with pytest.raises(BrainError, match="isn't signed in"):
        list(read_events([result("Invalid API key · Please run /login", is_error=True)]))


def test_usage_limit():
    with pytest.raises(BrainError, match="usage limit"):
        list(read_events([rate_limit("rejected", 1794704400), result("", is_error=True)]))
    assert list(read_events([rate_limit("allowed"), delta("Hi."), result()])) == ["Hi."]


def test_no_output_at_all_fails():
    with pytest.raises(BrainError, match=FAILED):
        list(read_events(["garbage", "{not json"]))


def test_messages():
    assert error_message("Please log in again") == NOT_SIGNED_IN
    assert error_message("Claude AI usage limit reached") == LIMIT
    assert error_message("boom") == FAILED
    assert limit_message(None) == LIMIT
    assert "It resets at" in limit_message(1794704400)


# ----- running claude -p -----


def test_command_flags(tmp_path):
    brain = make_brain(tmp_path, FakePopen(), effort="low", code_model="sonnet", connectors=[])
    args = brain.command(tmp_path / "prompt.txt")
    for flag in (
        "-p",
        "--safe-mode",
        "--restricted",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--include-partial-messages",
    ):
        assert flag in args
    assert args[args.index("--output-format") + 1] == "stream-json"
    assert args[args.index("--input-format") + 1] == "stream-json"  # stays open for more
    assert args[args.index("--permission-prompts") + 1] == "none"
    tools = ",".join(["Read", *FILE_TOOLS, "WebSearch", "WebFetch"])
    assert args[args.index("--tools") + 1] == tools
    assert args[args.index("--allowedTools") + 1] == tools
    assert args[args.index("--add-dir") + 1] == str(HOME)  # your files, not just the empty folder
    assert args.count("--add-dir") == 1  # the OneDrive Desktop is inside your home folder
    assert args[args.index("--model") + 1] == "sonnet"
    assert args[args.index("--effort") + 1] == "low"
    assert "--bare" not in args  # it would ignore the subscription login


def test_file_tools_include_a_shell():
    assert {"Write", "Edit", "Glob", "Grep"} <= set(FILE_TOOLS)
    assert "PowerShell" in FILE_TOOLS or "Bash" in FILE_TOOLS


def test_no_web_tools_when_disabled(tmp_path):
    brain = make_brain(tmp_path, FakePopen(), allow_web=False, effort="")
    args = brain.command(tmp_path / "p.txt")
    assert args[args.index("--tools") + 1] == ",".join(["Read", *FILE_TOOLS])
    assert "--effort" not in args and "--model" not in args


def test_no_file_access_when_disabled(tmp_path):
    brain = make_brain(tmp_path, FakePopen(), allow_files=False, allow_web=False)
    args = brain.command(tmp_path / "p.txt")
    assert args[args.index("--tools") + 1] == "Read"  # screenshots only
    assert "--add-dir" not in args
    assert "--restricted" in args  # file tools stay inside the empty working folder


def test_folders_outside_home_are_added(tmp_path):
    folders = {**FOLDERS, "Documents": Path("D:/Documents")}
    args = make_brain(tmp_path, FakePopen(), folders=folders).command(tmp_path / "p.txt")
    added = [args[i + 1] for i, a in enumerate(args) if a == "--add-dir"]
    assert added == [str(HOME), str(Path("D:/Documents"))]


def test_user_folders_follow_windows_settings():
    moved = {"Desktop": r"C:\Users\me\OneDrive\Desktop"}  # e.g. OneDrive backs up the Desktop
    folders = user_folders(HOME, lookup=moved.get)
    assert folders["Desktop"] == Path(r"C:\Users\me\OneDrive\Desktop")
    assert folders["Downloads"] == HOME / "Downloads"  # not moved
    assert list(folders) == ["Desktop", "Documents", "Downloads", "Pictures"]


def test_system_prompt_names_your_folders(tmp_path):
    popen = FakePopen([INIT, delta("Done."), result("Done.")])
    brain = make_brain(tmp_path, popen)
    "".join(brain.stream("Put my screenshots in a folder."))
    args, _ = popen.calls[0]
    text = Path(args[args.index("--system-prompt-file") + 1]).read_text(encoding="utf-8")
    assert str(HOME) in text and str(FOLDERS["Desktop"]) in text
    assert "ask whether to go ahead" in text
    assert "You cannot run commands" not in text
    assert "date and time in square brackets" in text and "Today is" not in text
    assert popen.procs[0].stdin.prompts == ["Put my screenshots in a folder."]
    brain.close()


def test_system_prompt_without_file_access(tmp_path):
    popen = FakePopen([INIT, delta("Hi."), result("Hi.")])
    brain = make_brain(tmp_path, popen, allow_files=False)
    "".join(brain.stream("hello"))
    args, _ = popen.calls[0]
    text = Path(args[args.index("--system-prompt-file") + 1]).read_text(encoding="utf-8")
    assert "You cannot run commands" in text and str(HOME) not in text
    brain.close()


def test_stream_sends_the_request_on_stdin(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    popen = FakePopen([INIT, delta("Tokyo."), result("Tokyo.")])
    brain = make_brain(tmp_path, popen)
    assert "".join(brain.stream("What's the capital of Japan?")) == "Tokyo."
    args, kwargs = popen.calls[0]
    assert "What's the capital of Japan?" not in " ".join(args)
    sent = json.loads(popen.procs[0].stdin.lines[0])
    assert sent["type"] == "user" and sent["message"]["role"] == "user"
    stamp, prompt = sent["message"]["content"].split("\n", 1)
    assert prompt == "What's the capital of Japan?"
    assert stamp.startswith("[") and stamp.endswith(("AM]", "PM]"))  # the time, every time
    assert "ANTHROPIC_API_KEY" not in kwargs["env"]
    assert kwargs["cwd"] == tmp_path / "work"
    prompt_file = Path(args[args.index("--system-prompt-file") + 1])
    assert "You are Krekos" in prompt_file.read_text(encoding="utf-8")
    brain.close()


# ----- one conversation, kept open -----


def turn(text):
    return [delta(text), result(text)]


def test_the_same_process_answers_the_next_question(tmp_path):
    popen = FakePopen([INIT, *turn("Tokyo.")], turn("About 14 million."))
    brain = make_brain(tmp_path, popen)
    assert "".join(brain.stream("What's the capital of Japan?")) == "Tokyo."
    assert "".join(brain.stream("How many people live there?")) == "About 14 million."
    assert len(popen.procs) == 1  # Claude remembers: it's the same conversation
    proc = popen.procs[0]
    assert proc.stdin.prompts == ["What's the capital of Japan?", "How many people live there?"]
    assert not proc.stdin.closed and not proc.killed.is_set()
    assert brain.remembers is True
    brain.close()
    assert proc.killed.is_set()


def test_a_long_conversation_starts_over(tmp_path):
    popen = FakePopen(turn("One."), turn("Two."))
    brain = make_brain(tmp_path, popen)
    brain.MAX_TURNS = 1
    assert "".join(brain.stream("first")) == "One."
    assert "".join(brain.stream("second")) == "One."  # a new process, from the top
    assert len(popen.procs) == 2 and popen.procs[0].killed.is_set()
    brain.close()


def test_a_quiet_conversation_is_closed_and_a_fresh_one_made_ready(tmp_path):
    FakeTimer.made.clear()
    popen = FakePopen(turn("Hi."))
    brain = make_brain(tmp_path, popen, timer=FakeTimer, keep_warm=True)
    "".join(brain.stream("hello"))
    idle = FakeTimer.made[-1]
    assert idle.seconds == brain.IDLE_SECONDS
    idle.fire()
    assert popen.procs[0].killed.is_set()
    wait_for(lambda: len(popen.procs) == 2)  # warmed up again, with nothing remembered
    brain.close()


def test_asking_again_cancels_the_quiet_timer(tmp_path):
    FakeTimer.made.clear()
    popen = FakePopen(turn("Hi."), turn("Yes."))
    brain = make_brain(tmp_path, popen, timer=FakeTimer)
    "".join(brain.stream("hello"))
    idle = FakeTimer.made[-1]
    "".join(brain.stream("still there?"))
    assert idle.cancelled and len(popen.procs) == 1
    brain.close()


def wait_for(condition, seconds=3.0):
    import time

    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert condition()


def test_warm_up_starts_claude_before_the_first_question(tmp_path):
    popen = FakePopen(turn("Hi."))
    brain = make_brain(tmp_path, popen)
    brain.warm_up()
    wait_for(lambda: len(popen.procs) == 1)
    assert popen.procs[0].stdin.lines == []  # started, nothing asked yet
    assert "".join(brain.stream("hello")) == "Hi."
    assert len(popen.procs) == 1  # the warm one answered
    brain.close()


def test_a_process_that_died_is_replaced(tmp_path):
    popen = FakePopen(turn("Hi."), dead_first=True)
    brain = make_brain(tmp_path, popen)
    brain.warm_up()
    wait_for(lambda: len(popen.procs) == 1)
    assert "".join(brain.stream("hello")) == "Hi."
    assert len(popen.procs) == 2
    brain.close()


def test_same_setup_keeps_the_conversation_only_if_nothing_changed(tmp_path):
    popen = FakePopen(turn("Hi."))
    brain = make_brain(tmp_path, popen)
    assert not brain.same_setup(make_brain(tmp_path, popen))  # nothing open yet to keep
    "".join(brain.stream("hello"))
    assert brain.same_setup(make_brain(tmp_path, popen))
    assert not brain.same_setup(make_brain(tmp_path, popen, allow_web=False))
    assert not brain.same_setup(make_brain(tmp_path, popen, instructions="Call me Mo."))
    assert not brain.same_setup(make_brain(tmp_path, popen, code_model="haiku"))
    brain.close()


def test_tools_are_reported_as_activity(tmp_path):
    tool = json.dumps(
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "content_block": {"type": "tool_use", "name": "WebSearch"},
            },
        }
    )
    popen = FakePopen([delta("Let me check. "), tool, message_start(), delta("Sunny."), result()])
    brain = make_brain(tmp_path, popen)
    seen = []
    brain.on_activity = seen.append
    stream = brain.stream("weather?")
    assert [next(stream), next(stream)] == ["Let me check. ", "\n"]
    assert seen == []  # the line before the search can be spoken before the search starts
    assert "".join(stream) == "\nSunny."
    assert seen == ["Searching the web"]
    assert activity("SomethingNew") == "Working on it"
    brain.close()


def test_screenshot_is_given_as_a_file_and_removed(tmp_path):
    popen = FakePopen([delta("It shows a cat."), result()])
    brain = make_brain(tmp_path, popen)
    stream = brain.stream("Summarize", image_png=b"PNG")
    assert next(stream) == "It shows a cat."
    assert (tmp_path / "work" / SCREENSHOT).read_bytes() == b"PNG"  # there while Claude works
    assert list(stream) == []
    assert SCREENSHOT in popen.procs[0].stdin.prompts[0]
    assert not (tmp_path / "work" / SCREENSHOT).exists()
    brain.close()


def test_not_signed_in_from_stderr(tmp_path):
    popen = FakePopen(returncode=1, stderr=b"Error: not logged in. Run claude /login")
    brain = make_brain(tmp_path, popen)
    with pytest.raises(BrainError, match="isn't signed in"):
        list(brain.stream("hi"))
    assert brain._session is None  # not kept for the next question


def test_cannot_start(tmp_path):
    with pytest.raises(BrainError, match=START_FAILED):
        list(make_brain(tmp_path, FakePopen(error=OSError("no such file"))).stream("hi"))


def test_timeout_kills_the_process(tmp_path):
    popen = FakePopen([INIT], hang=True)
    brain = make_brain(tmp_path, popen, timeout_seconds=0.05)
    with pytest.raises(BrainError, match=TOO_SLOW):
        list(brain.stream("a long question"))
    assert popen.procs[0].killed.is_set()


def test_stopping_early_interrupts_claude_and_keeps_the_conversation(tmp_path):
    popen = FakePopen(
        [INIT, delta("One. "), delta("Two. "), delta("Three. "), result()],
        [delta("Okay, a short one."), result()],
    )
    brain = make_brain(tmp_path, popen, keep_warm=True)
    stream = brain.stream("count")
    assert next(stream) == "One. "
    stream.close()  # you started talking
    proc = popen.procs[0]
    assert [i["request"] for i in proc.stdin.interrupts] == [{"subtype": "interrupt"}]
    assert not proc.killed.is_set()
    assert "".join(brain.stream("shorter please")) == "Okay, a short one."
    assert len(popen.procs) == 1  # the same conversation: Claude knows what it was saying
    assert proc.stdin.prompts == ["count", "shorter please"]
    brain.close()


def test_a_claude_that_ignores_the_interrupt_is_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr("abdoh.claude.code.INTERRUPT_SECONDS", 0.05)
    popen = FakePopen([delta("One. "), delta("Two. "), result()], deaf=True)
    brain = make_brain(tmp_path, popen, keep_warm=True)
    stream = brain.stream("count")
    assert next(stream) == "One. "
    stream.close()
    assert popen.procs[0].killed.is_set()
    wait_for(lambda: len(popen.procs) == 2)  # a fresh one is made ready
    brain.close()


def test_an_interrupt_just_as_the_reply_ended(tmp_path):
    """The result was already on its way: Claude Code only confirms, and nothing more comes."""
    brain = make_brain(tmp_path, FakePopen([delta("Hi.")]))
    session = brain._take_session()
    response = {"subtype": "success", "request_id": "abdoh-1"}
    session.proc.stdout = iter(
        [result() + "\n", json.dumps({"type": "control_response", "response": response}) + "\n"]
    )
    assert brain._interrupt(session) is True
    brain.close()


def test_closed_brain_keeps_nothing_open(tmp_path):
    popen = FakePopen(turn("Hi."))
    brain = make_brain(tmp_path, popen, keep_warm=True)
    brain.close()
    brain.warm_up()
    assert popen.procs == []


def test_an_empty_answer_is_asked_once_more(tmp_path):
    class Flaky(FakePopen):
        def __call__(self, args, **kwargs):
            self.replies = [[result("", is_error=True)]] if not self.procs else [turn("Tokyo.")]
            return super().__call__(args, **kwargs)

    popen = Flaky()
    brain = make_brain(tmp_path, popen)
    assert "".join(brain.stream("capital of japan?")) == "Tokyo."
    assert len(popen.procs) == 2  # a fresh process answered
    brain.close()


def test_two_empty_answers_are_an_error(tmp_path):
    popen = FakePopen([result("", is_error=True)])
    brain = make_brain(tmp_path, popen)
    with pytest.raises(BrainError, match=FAILED):
        list(brain.stream("hello"))
    assert len(popen.procs) == 2


def test_real_errors_are_not_retried(tmp_path):
    popen = FakePopen([rate_limit("rejected")])
    brain = make_brain(tmp_path, popen)
    with pytest.raises(BrainError, match=LIMIT):
        list(brain.stream("hello"))
    assert len(popen.procs) == 1


# ----- your claude.ai connectors (Gmail, Google Calendar, ...) -----


def test_connectors_load_and_only_yours_are_allowed(tmp_path):
    from abdoh.claude.code import connector_rule

    brain = make_brain(tmp_path, FakePopen(), connectors=["Gmail", "Google Calendar"])
    args = brain.command(tmp_path / "prompt.txt")
    assert "--safe-mode" not in args and "--strict-mcp-config" not in args  # else none load
    assert "--restricted" in args  # your settings, hooks, plugins and CLAUDE.md stay out
    allowed = args[args.index("--allowedTools") + 1].split(",")
    assert allowed[-2:] == ["mcp__claude_ai_Gmail", "mcp__claude_ai_Google_Calendar"]
    assert "mcp__" not in args[args.index("--tools") + 1]  # only built-in tools there
    assert connector_rule("Google Drive") == "mcp__claude_ai_Google_Drive"
    assert "Gmail, Google Calendar" in brain.instructions()


def test_changing_the_connectors_starts_a_new_conversation(tmp_path):
    one = make_brain(tmp_path, FakePopen(), connectors=["Gmail"])
    one._started_with = one._setup()
    assert one.same_setup(make_brain(tmp_path, FakePopen(), connectors=["Gmail"]))
    assert not one.same_setup(make_brain(tmp_path, FakePopen(), connectors=[]))


def test_listing_your_connectors(tmp_path):
    from abdoh.claude.code import list_connectors

    out = "\n".join(
        [
            "Checking MCP server health…",
            "",
            "claude.ai Gmail: https://gmailmcp.googleapis.com/mcp/v1 - ✔ Connected",
            "claude.ai Google Calendar: https://calendarmcp.googleapis.com/mcp/v1 - ! Needs auth",
            "claude.ai Notion: https://mcp.notion.com/mcp - ✗ Failed to connect",
            "my-server: node server.js - ✔ Connected",
        ]
    )
    seen = {}

    def run(args, **kw):
        seen["args"] = args
        return subprocess.CompletedProcess(args, 0, out, "")

    found = list_connectors(Path("claude.exe"), run, tmp_path)
    assert seen["args"][1:] == ["mcp", "list"]
    assert found == [
        {"name": "Gmail", "status": "connected"},
        {"name": "Google Calendar", "status": "sign in"},
        {"name": "Notion", "status": "failed"},
    ]
