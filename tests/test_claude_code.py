"""Claude Code backend with a fake `claude` process (no Claude Code, no network)."""

import json
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
    def __init__(self):
        self.text = ""
        self.closed = False

    def write(self, text):
        self.text += text

    def close(self):
        self.closed = True


class FakeProc:
    def __init__(self, lines, returncode=0, hang=False):
        self.stdin = FakeStdin()
        self._lines = lines
        self._returncode = returncode
        self._hang = hang
        self.killed = threading.Event()
        self.returncode = None

    @property
    def stdout(self):
        yield from (line + "\n" for line in self._lines)
        if self._hang:
            self.killed.wait(5)  # like a stuck process: no more output until killed

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = -9 if self.killed.is_set() else self._returncode
        return self.returncode

    def kill(self):
        self.killed.set()


class FakePopen:
    def __init__(self, lines=(), returncode=0, stderr=b"", hang=False, error=None):
        self.lines = list(lines)
        self.returncode = returncode
        self.stderr = stderr
        self.hang = hang
        self.error = error
        self.calls = []
        self.procs = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        kwargs["stderr"].write(self.stderr)
        proc = FakeProc(self.lines, self.returncode, self.hang)
        self.procs.append(proc)
        return proc


HOME = Path("C:/Users/me")
FOLDERS = {"Desktop": HOME / "OneDrive" / "Desktop", "Downloads": HOME / "Downloads"}


def make_brain(tmp_path, popen, folders=FOLDERS, **claude):
    cfg = Config(app_dir=tmp_path, claude=ClaudeConfig(**claude))
    return ClaudeCodeBrain(
        cfg, Path("claude.exe"), popen=popen, workdir=tmp_path / "work", home=HOME, folders=folders
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
    brain = make_brain(tmp_path, FakePopen(), effort="low", code_model="sonnet")
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
    assert popen.procs[0].stdin.text == "Put my screenshots in a folder."


def test_system_prompt_without_file_access(tmp_path):
    popen = FakePopen([INIT, delta("Hi."), result("Hi.")])
    "".join(make_brain(tmp_path, popen, allow_files=False).stream("hello"))
    args, _ = popen.calls[0]
    text = Path(args[args.index("--system-prompt-file") + 1]).read_text(encoding="utf-8")
    assert "You cannot run commands" in text and str(HOME) not in text


def test_stream_sends_the_request_on_stdin(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    popen = FakePopen([INIT, delta("Tokyo."), result("Tokyo.")])
    brain = make_brain(tmp_path, popen)
    assert "".join(brain.stream("What's the capital of Japan?")) == "Tokyo."
    args, kwargs = popen.calls[0]
    assert "What's the capital of Japan?" not in " ".join(args)
    assert popen.procs[0].stdin.text == "What's the capital of Japan?"
    assert popen.procs[0].stdin.closed
    assert "ANTHROPIC_API_KEY" not in kwargs["env"]
    assert kwargs["cwd"] == tmp_path / "work"
    prompt_file = Path(args[args.index("--system-prompt-file") + 1])
    assert "You are Abdoh" in prompt_file.read_text(encoding="utf-8")


def test_screenshot_is_given_as_a_file_and_removed(tmp_path):
    seen = {}

    class Popen(FakePopen):
        def __call__(self, args, **kwargs):
            seen["exists"] = (tmp_path / "work" / SCREENSHOT).read_bytes()
            return super().__call__(args, **kwargs)

    popen = Popen([delta("It shows a cat."), result()])
    brain = make_brain(tmp_path, popen)
    assert "".join(brain.stream("Summarize", image_png=b"PNG")) == "It shows a cat."
    assert seen["exists"] == b"PNG"
    assert SCREENSHOT in popen.procs[0].stdin.text
    assert not (tmp_path / "work" / SCREENSHOT).exists()


def test_not_signed_in_from_stderr(tmp_path):
    popen = FakePopen([], returncode=1, stderr=b"Error: not logged in. Run claude /login")
    with pytest.raises(BrainError, match="isn't signed in"):
        list(make_brain(tmp_path, popen).stream("hi"))


def test_cannot_start(tmp_path):
    with pytest.raises(BrainError, match=START_FAILED):
        list(make_brain(tmp_path, FakePopen(error=OSError("no such file"))).stream("hi"))


def test_timeout_kills_the_process(tmp_path):
    popen = FakePopen([INIT], hang=True)
    brain = make_brain(tmp_path, popen, timeout_seconds=0.05)
    with pytest.raises(BrainError, match=TOO_SLOW):
        list(brain.stream("a long question"))
    assert popen.procs[0].killed.is_set()


def test_stopping_early_kills_the_process(tmp_path):
    popen = FakePopen([delta("One. "), delta("Two. "), result()])
    stream = make_brain(tmp_path, popen).stream("count")
    assert next(stream) == "One. "
    stream.close()
    assert popen.procs[0].killed.is_set()
