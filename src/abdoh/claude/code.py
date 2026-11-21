"""Claude through your Claude subscription: Claude Code in headless mode (`claude -p`).

One `claude -p` process is kept open per conversation (requests go in on its stdin, one JSON line
each), so answers start sooner and Claude remembers what was said. It runs in an empty folder
(~/.krekos/claude) with Krekos's own system
prompt, only the tools Krekos allows, no plugins/MCP/CLAUDE.md (--safe-mode), your Claude Code
settings ignored (--restricted), nothing saved to your Claude Code history, and anything that
would need permission denied.

Connectors (claude.connectors): the services you connected at claude.ai (Gmail, Google
Calendar, ...) only load without --safe-mode and --strict-mcp-config. With connectors on, those
two are left out; --restricted still keeps your settings, hooks, plugins and CLAUDE.md out, and
only the tools of the connectors you allowed are permitted (a server-wide rule such as
mcp__claude_ai_Gmail); anything else needs permission, which is denied. Checked with Claude Code
2.1.327: the connectors are ready a few seconds after the process starts (warm_up), and a
connector that isn't allowed is refused.

With claude.allow_files, Claude can also read and change files in your home folder (--add-dir)
and run PowerShell commands; otherwise file access is limited to that empty folder. Requests go
in on stdin, never on the command line. API keys are removed from its environment so the
subscription (not an API account) pays for it.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path

from abdoh.about import about
from abdoh.claude.brain import Brain, BrainError, stamp, system_prompt
from abdoh.config import Config

log = logging.getLogger(__name__)

WORKDIR = Path.home() / ".krekos" / "claude"
SCREENSHOT = "screenshot.png"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flash when run by pythonw
# Tools for working with your files (claude.allow_files), on top of Read.
FILE_TOOLS = ["Write", "Edit", "Glob", "Grep", "PowerShell" if sys.platform == "win32" else "Bash"]
# Your main folders, and their names in Windows' "User Shell Folders" registry key (they can
# live elsewhere than your home folder, e.g. in OneDrive).
_KNOWN_FOLDERS = {
    "Desktop": "Desktop",
    "Documents": "Personal",
    "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "Pictures": "My Pictures",
}
# Credentials that would make Claude Code bill an API account instead of your subscription,
# and the marker Claude Code sets for its own child processes.
_STRIPPED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE")

# What to show (and say) while Claude uses a tool.
TOOL_ACTIVITY = {
    "WebSearch": "Searching the web",
    "WebFetch": "Reading a web page",
    "Read": "Looking at a file",
    "Glob": "Looking through your files",
    "Grep": "Looking through your files",
    "Write": "Writing a file",
    "Edit": "Changing a file",
    "PowerShell": "Running a command",
    "Bash": "Running a command",
}

FAILED = "Claude couldn't answer that right now."
TOO_SLOW = "Claude took too long to answer."
# After an interrupt, Claude Code confirms within a few hundredths of a second. If it hasn't
# after this long, it is stopped and a fresh one is started.
INTERRUPT_SECONDS = 3.0
NOT_SIGNED_IN = (
    "Claude Code isn't signed in. Open Claude Code and sign in with your Claude account."
)
LIMIT = "You've reached your Claude usage limit for now."
START_FAILED = "I couldn't start Claude Code."


def _exe_name() -> str:
    return "claude.exe" if sys.platform == "win32" else "claude"


def _version(dirname: str) -> tuple[int, ...]:
    """'anthropic.claude-code-2.1.325-win32-x64' -> (2, 1, 325)."""
    m = re.search(r"claude-code-(\d+(?:\.\d+)*)", dirname)
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def editor_binaries(home: Path) -> list[Path]:
    """Claude Code binaries bundled with the VS Code (or similar) extension, newest first."""
    found = []
    for editor in (".vscode", ".vscode-insiders", ".cursor", ".windsurf"):
        for ext in (home / editor / "extensions").glob("anthropic.claude-code-*"):
            exe = ext / "resources" / "native-binary" / _exe_name()
            if exe.is_file():
                found.append((_version(ext.name), exe))
    return [exe for _, exe in sorted(found, reverse=True)]


def connector_rule(name: str) -> str:
    """The permission rule for all of a claude.ai connector's tools: "Google Calendar" ->
    "mcp__claude_ai_Google_Calendar"."""
    return "mcp__" + re.sub(r"[^A-Za-z0-9_-]", "_", f"claude.ai {name}")


_MCP_LINE = re.compile(r"^claude\.ai (?P<name>.+?): \S+ - (?P<status>.+)$")


def list_connectors(exe: Path, run=subprocess.run, workdir: Path = WORKDIR) -> list[dict]:
    """The services connected to your Claude account (claude.ai → Settings → Connectors), as
    Claude Code sees them: [{"name": "Gmail", "status": "connected" | "sign in" | "failed"}].
    Raises BrainError if Claude Code couldn't tell."""
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        result = run(
            [str(exe), "mcp", "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            cwd=workdir,
            env=child_env(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise BrainError(f"Couldn't ask Claude Code about your connectors ({e}).") from e
    found = []
    for line in (result.stdout or "").splitlines():
        match = _MCP_LINE.match(line.strip())
        if not match:
            continue
        status = match["status"].lower()
        if "connected" in status and "fail" not in status:
            state = "connected"
        elif "auth" in status or "sign" in status:
            state = "sign in"
        else:
            state = "failed"
        found.append({"name": match["name"], "status": state})
    return found


def find_claude_code(configured: str = "", home: Path | None = None, which=shutil.which):
    """Path to Claude Code: config, PATH, ~/.local/bin, then an editor extension's copy."""
    home = home or Path.home()
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return path
        log.warning("claude.code_path not found: %s", path)
        return None
    on_path = which("claude")
    if on_path:
        return Path(on_path)
    local = home / ".local" / "bin" / _exe_name()
    if local.is_file():
        return local
    bundled = editor_binaries(home)
    return bundled[0] if bundled else None


def child_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _STRIPPED_ENV}


def _shell_folder(name: str) -> str | None:
    """Where Windows keeps one of your folders (from the registry), or None."""
    if sys.platform != "win32":
        return None
    import winreg

    key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            value, _ = winreg.QueryValueEx(k, name)
    except OSError:
        return None
    return os.path.expandvars(value) if isinstance(value, str) and value else None


def user_folders(home: Path | None = None, lookup=_shell_folder) -> dict[str, Path]:
    """Your Desktop, Documents, Downloads and Pictures folders, wherever they really are."""
    home = home or Path.home()
    return {name: Path(lookup(key) or home / name) for name, key in _KNOWN_FOLDERS.items()}


def auth_status(exe: Path, run=subprocess.run) -> dict | None:
    """`claude auth status` as a dict (loggedIn, authMethod, subscriptionType, ...)."""
    try:
        out = run(
            [str(exe), "auth", "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            env=child_env(),
            creationflags=NO_WINDOW,
        ).stdout
        start = out.find("{")
        return json.JSONDecoder().raw_decode(out[start:])[0] if start >= 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        log.warning("Couldn't check Claude Code's sign-in", exc_info=True)
        return None


def describe_status(info: dict | None) -> str:
    if not info:
        return "Claude Code (couldn't check sign-in)"
    if not info.get("loggedIn"):
        return "Claude Code (not signed in)"
    if info.get("authMethod") == "claude.ai":
        plan = info.get("subscriptionType") or info.get("planTier") or "Claude"
        return f"{plan.capitalize()} subscription (Claude Code)"
    return "Claude Code"


def _clock(epoch_seconds) -> str:
    t = datetime.fromtimestamp(float(epoch_seconds))
    minutes = f":{t.minute:02d}" if t.minute else ""
    return f"{t.hour % 12 or 12}{minutes} {'AM' if t.hour < 12 else 'PM'}"


def limit_message(resets_at=None) -> str:
    try:
        return f"{LIMIT} It resets at {_clock(resets_at)}." if resets_at else LIMIT
    except (TypeError, ValueError, OverflowError, OSError):
        return LIMIT


def error_message(detail: str) -> str:
    """A speakable message for an error Claude Code reported."""
    d = detail.lower()
    if any(w in d for w in ("login", "log in", "sign in", "logged in", "authenticat", "api key")):
        return NOT_SIGNED_IN
    if "limit" in d:
        return LIMIT
    return FAILED


def read_events(lines: Iterable[str], on_tool=None) -> Iterator[str]:
    """Yield one reply's text from Claude Code's `--output-format stream-json` lines, up to its
    "result" line (the lines after it belong to the next reply).

    Uses the streamed text deltas (--include-partial-messages); a new line separates text from
    different messages (e.g. before and after a web search). `on_tool(name)` is called when
    Claude starts using a tool. Raises BrainError for errors and usage limits.
    """
    said = False
    new_message = False
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind == "stream_event":
            inner = event.get("event") or {}
            delta = inner.get("delta") or {}
            if inner.get("type") == "message_start" and said:
                new_message = True
            elif inner.get("type") == "content_block_start":
                block = inner.get("content_block") or {}
                if block.get("type") in ("tool_use", "server_tool_use"):
                    if said:
                        yield "\n"  # what Claude said before the tool is complete: speak it now
                    if on_tool:
                        on_tool(str(block.get("name") or ""))
            elif inner.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                text = delta.get("text") or ""
                if text:
                    if new_message:
                        text, new_message = "\n" + text, False
                    said = True
                    yield text
        elif kind == "rate_limit_event":
            info = event.get("rate_limit_info") or {}
            if info.get("status") == "rejected":
                raise BrainError(limit_message(info.get("resetsAt")))
        elif kind == "result":
            if event.get("is_error") or event.get("subtype", "success") != "success":
                if not said:
                    log.warning("Claude Code reported an error: %s", str(event)[:300])
                    raise BrainError(error_message(str(event.get("result") or "")))
            elif not said and event.get("result"):
                yield str(event["result"])
            return
    if not said:
        raise BrainError(FAILED)


def activity(tool: str) -> str:
    """A few words for what Claude is doing with this tool."""
    return TOOL_ACTIVITY.get(tool, "Working on it")


class _Session:
    """One running Claude Code process: a conversation that stays open."""

    def __init__(self, proc, stderr):
        self.proc = proc
        self.stderr = stderr  # a temporary file with what it printed about errors
        self.turns = 0
        self.busy = False

    def alive(self) -> bool:
        return self.proc.poll() is None

    def error_text(self) -> str:
        try:
            self.proc.wait(timeout=5)
            self.stderr.seek(0)
            return self.stderr.read().decode("utf-8", "replace").strip()[-500:]
        except Exception:
            return ""

    def close(self) -> None:
        try:
            if self.proc.poll() is None:
                self.proc.kill()
            self.proc.wait(timeout=5)
        except Exception:
            log.debug("Couldn't stop Claude Code cleanly", exc_info=True)
        for stream in (self.proc.stdin, self.proc.stdout, self.stderr):
            try:
                if stream is not None:
                    stream.close()
            except Exception:  # noqa: S110 - already gone
                pass


class ClaudeCodeBrain(Brain):
    """Claude through Claude Code, kept open between requests.

    One `claude -p --input-format stream-json` process serves a whole conversation: each request
    is one line on its stdin. Starting it costs about a second, so it's started ahead of time
    (`warm_up`), and Claude remembers what was said. A fresh one replaces it after MAX_TURNS
    requests, after IDLE_SECONDS without any, or on an error. A reply that is stopped early (you
    started talking) is interrupted, and the conversation goes on.
    """

    name = "Claude Code"
    remembers = True
    MAX_TURNS = 40
    IDLE_SECONDS = 600.0

    def __init__(
        self,
        cfg: Config,
        exe: Path,
        popen=subprocess.Popen,
        run=subprocess.run,
        workdir: Path = WORKDIR,
        home: Path | None = None,
        folders: dict[str, Path] | None = None,
        timer=threading.Timer,
        keep_warm: bool = True,
    ):
        self.cfg = cfg
        self.exe = Path(exe)
        self.workdir = Path(workdir)
        self.home = Path(home or Path.home())
        if folders is None:
            folders = user_folders(self.home) if cfg.claude.allow_files else {}
        self.folders = folders
        # claude.folders: Claude may only work in these (empty: anywhere in your home folder).
        self.only = [Path(f).expanduser() for f in cfg.claude.folders if str(f).strip()]
        self._popen = popen
        self._run = run
        self._timer = timer
        self._keep_warm = keep_warm  # start a fresh process whenever one is retired
        self._session: _Session | None = None
        self._lock = threading.RLock()  # guards _session
        self._idle = None  # the timer that retires a session nobody talks to
        self._closed = False
        self._interrupts = 0  # numbers the interrupt requests
        self._started_with: tuple | None = None  # see same_setup

    def tools(self) -> list[str]:
        tools = ["Read"]
        if self.cfg.claude.allow_files:
            tools += FILE_TOOLS
        if self.cfg.claude.allow_web:
            tools += ["WebSearch", "WebFetch"]
        return tools

    def file_dirs(self) -> list[Path]:
        """Where Claude may work with files: the folders you chose in Permissions, or else your
        home folder plus your main folders that live outside it."""
        if self.only:
            return list(dict.fromkeys(self.only))
        dirs = [self.home]
        for folder in self.folders.values():
            if not folder.is_relative_to(self.home) and folder not in dirs:
                dirs.append(folder)
        return dirs

    def command(self, prompt_file: Path) -> list[str]:
        tools = ",".join(self.tools())
        connectors = [connector_rule(name) for name in self.cfg.claude.connectors]
        allowed = ",".join([*self.tools(), *connectors])
        args = [
            str(self.exe),
            "-p",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--safe-mode",
            "--restricted",
            "--no-session-persistence",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--permission-prompts",
            "none",
            "--system-prompt-file",
            str(prompt_file),
            "--tools",
            tools,
            "--allowedTools",
            allowed,
        ]
        if connectors:  # they only load without these two (see the module's docstring)
            args = [a for a in args if a not in ("--safe-mode", "--strict-mcp-config")]
        if self.cfg.claude.allow_files:
            for folder in self.file_dirs():
                args += ["--add-dir", str(folder)]
        if self.cfg.claude.effort:
            args += ["--effort", self.cfg.claude.effort]
        if self.cfg.claude.code_model:
            args += ["--model", self.cfg.claude.code_model]
        return args

    def instructions(self) -> str:
        files = self.cfg.claude.allow_files
        return system_prompt(
            self.cfg,
            connectors=self.cfg.claude.connectors,
            about=about(self.cfg, "code"),
            web=self.cfg.claude.allow_web,
            home=self.home if files else None,
            folders=self.folders if files else None,
            only=self.only if files else None,
            stamped=True,
        )

    def _setup(self) -> tuple:
        """Everything a running Claude Code process was started with."""
        return (
            self.command(Path("prompt")),
            self.instructions(),
            self.cfg.claude.timeout_seconds,
        )

    def same_setup(self, other) -> bool:
        """True if the conversation that's open was started exactly the way `other` (a brain
        made from the settings as they are now) would start one."""
        return (
            isinstance(other, ClaudeCodeBrain)
            and self._started_with is not None
            and self._started_with == other._setup()
        )

    def status(self) -> str:
        return describe_status(auth_status(self.exe, self._run))

    # ----- the process -----

    def _start(self) -> _Session:
        self.workdir.mkdir(parents=True, exist_ok=True)
        prompt_file = self.workdir / "system-prompt.txt"
        prompt_file.write_text(self.instructions(), "utf-8")
        stderr = tempfile.TemporaryFile()
        try:
            proc = self._popen(
                self.command(prompt_file),
                cwd=self.workdir,
                env=child_env(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=NO_WINDOW,
            )
        except OSError as e:
            stderr.close()
            log.error("Couldn't start Claude Code (%s): %s", self.exe, e)
            raise BrainError(START_FAILED) from e
        log.debug("Claude Code started")
        self._started_with = self._setup()
        return _Session(proc, stderr)

    def _take_session(self) -> _Session:
        """The open conversation, or a new one. Marks it busy."""
        with self._lock:
            session = self._session
            if session is not None and not (session.alive() and session.turns < self.MAX_TURNS):
                self._retire(session)
                session = None
            if session is None:
                session = self._session = self._start()
            session.busy = True
            if self._idle is not None:
                self._idle.cancel()
                self._idle = None
            return session

    def _retire(self, session: _Session) -> None:
        with self._lock:
            if self._session is session:
                self._session = None
        session.close()

    def _rest(self, session: _Session) -> None:
        """A reply finished: keep the conversation, and retire it if nobody comes back."""
        with self._lock:
            session.busy = False
            session.turns += 1
            if self._closed:
                return self._retire(session)
            self._idle = self._timer(self.IDLE_SECONDS, self._went_quiet, args=(session,))
            self._idle.daemon = True
            self._idle.start()

    def _went_quiet(self, session: _Session) -> None:
        with self._lock:
            if self._session is not session or session.busy or self._closed:
                return
            log.debug("Claude Code conversation closed after a quiet while")
            self._retire(session)
        if self._keep_warm:
            self.warm_up()  # a fresh, empty one, ready for the next question

    def warm_up(self) -> None:
        """Start Claude Code now, in the background, so the next question doesn't wait for it."""

        def start() -> None:
            with self._lock:
                if self._closed or self._session is not None:
                    return
                try:
                    self._session = self._start()
                except BrainError:
                    pass  # reported when a question is asked

        threading.Thread(target=start, name="abdoh-claude-warm", daemon=True).start()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self._idle is not None:
                self._idle.cancel()
            session, self._session = self._session, None
        if session is not None:
            session.close()

    # ----- asking -----

    def _send(self, session: _Session, prompt: str) -> None:
        content = stamp(prompt, state=self.state_now())
        message = {"type": "user", "message": {"role": "user", "content": content}}
        session.proc.stdin.write(json.dumps(message) + "\n")
        session.proc.stdin.flush()

    def stream(self, prompt: str, image_png: bytes | None = None) -> Iterator[str]:
        shot = self.workdir / SCREENSHOT
        if image_png:
            self.workdir.mkdir(parents=True, exist_ok=True)
            shot.write_bytes(image_png)
            prompt += (
                f"\n\nThe screenshot is the file {SCREENSHOT} in the current folder. "
                "Read it with the Read tool."
            )
        said = False
        try:
            for attempt in (1, 2):
                try:
                    for chunk in self._ask(prompt):
                        said = True
                        yield chunk
                    return
                except BrainError as e:
                    # Now and then Claude Code returns nothing at all; a fresh process usually
                    # answers. Anything else (not signed in, a limit, too slow) is final.
                    if said or attempt == 2 or str(e) != FAILED or self._closed:
                        raise
                    log.info("Claude Code gave no answer; asking once more")
        finally:
            shot.unlink(missing_ok=True)

    def _ask(self, prompt: str) -> Iterator[str]:
        """One try at a reply, in the open conversation (or a new one)."""
        session = self._take_session()
        try:
            self._send(session, prompt)
        except (OSError, ValueError):  # it died while waiting: one fresh try
            log.info("Claude Code had stopped; starting it again")
            self._retire(session)
            session = self._take_session()
            try:
                self._send(session, prompt)
            except (OSError, ValueError) as e:
                detail = session.error_text()
                self._retire(session)
                log.error("Claude Code isn't taking requests: %s", detail or e)
                raise BrainError(error_message(detail)) from e
        timed_out = threading.Event()

        def kill() -> None:
            timed_out.set()
            session.proc.kill()

        timer = self._timer(self.cfg.claude.timeout_seconds, kill)
        timer.daemon = True
        timer.start()
        finished = stopped = False
        try:
            try:
                yield from read_events(session.proc.stdout, self._on_tool)
            except GeneratorExit:
                stopped = True  # you interrupted: nobody wants the rest
                raise
            except BrainError as e:
                if timed_out.is_set():
                    raise BrainError(TOO_SLOW) from e
                if str(e) == FAILED:
                    detail = session.error_text()
                    log.error("Claude Code failed (exit %s): %s", session.proc.returncode, detail)
                    message = error_message(detail)
                    raise BrainError(message) from e
                raise
            if timed_out.is_set():
                raise BrainError(TOO_SLOW)
            finished = True
        finally:
            timer.cancel()
            if finished or (stopped and self._interrupt(session)):
                self._rest(session)
            else:  # an error, or it didn't stop when asked: start over next time
                self._retire(session)
                if self._keep_warm and not self._closed:
                    self.warm_up()

    def _interrupt(self, session: _Session) -> bool:
        """Ask Claude Code to stop the reply it is writing; the conversation stays open, and
        Claude remembers what it had said. False if it didn't confirm in time (it is killed)."""
        self._interrupts += 1
        request_id = f"abdoh-{self._interrupts}"
        request = {"type": "control_request", "request_id": request_id}
        request["request"] = {"subtype": "interrupt"}
        timer = self._timer(INTERRUPT_SECONDS, session.proc.kill)
        timer.daemon = True
        timer.start()
        try:
            session.proc.stdin.write(json.dumps(request) + "\n")
            session.proc.stdin.flush()
            # It confirms the request, and ends the reply with a "result" line. If the reply
            # had just ended by itself, that result came first and nothing more follows.
            confirmed = ended = False
            for line in session.proc.stdout:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "result":
                    ended = True
                elif event.get("type") == "control_response":
                    response = event.get("response") or {}
                    if response.get("request_id") != request_id:
                        continue
                    if response.get("subtype") != "success":
                        return False
                    confirmed = True
                if confirmed and ended:
                    return session.alive()
            return False
        except (OSError, ValueError):
            return False
        finally:
            timer.cancel()

    def _on_tool(self, tool: str) -> None:
        log.info("Claude is using %s", tool)
        notify = self.on_activity
        if notify:
            try:
                notify(activity(tool))
            except Exception:
                log.debug("Couldn't report Claude's activity", exc_info=True)
