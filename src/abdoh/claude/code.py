"""Claude through your Claude subscription: Claude Code in headless mode (`claude -p`).

Each request runs `claude -p` in an empty folder (~/.abdoh/claude) with Abdoh's own system
prompt, only the tools Abdoh allows, no plugins/MCP/CLAUDE.md (--safe-mode), your Claude Code
settings ignored (--restricted), nothing saved to your Claude Code history, and anything that
would need permission denied. With claude.allow_files, Claude can also read and change files in
your home folder (--add-dir) and run PowerShell commands; otherwise file access is limited to
that empty folder. The request goes in on stdin, never on the command line. API keys are removed
from its environment so the subscription (not an API account) pays for it.
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

from abdoh.claude.brain import Brain, BrainError, system_prompt
from abdoh.config import Config

log = logging.getLogger(__name__)

WORKDIR = Path.home() / ".abdoh" / "claude"
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

FAILED = "Claude couldn't answer that right now."
TOO_SLOW = "Claude took too long to answer."
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


def read_events(lines: Iterable[str]) -> Iterator[str]:
    """Yield reply text from Claude Code's `--output-format stream-json` lines.

    Uses the streamed text deltas (--include-partial-messages); a new line separates text from
    different messages (e.g. before and after a web search). Raises BrainError for errors and
    usage limits.
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
                    raise BrainError(error_message(str(event.get("result") or "")))
            elif not said and event.get("result"):
                yield str(event["result"])
            return
    if not said:
        raise BrainError(FAILED)


class ClaudeCodeBrain(Brain):
    name = "Claude Code"

    def __init__(
        self,
        cfg: Config,
        exe: Path,
        popen=subprocess.Popen,
        run=subprocess.run,
        workdir: Path = WORKDIR,
        home: Path | None = None,
        folders: dict[str, Path] | None = None,
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
        args = [
            str(self.exe),
            "-p",
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
            tools,
        ]
        if self.cfg.claude.allow_files:
            for folder in self.file_dirs():
                args += ["--add-dir", str(folder)]
        if self.cfg.claude.effort:
            args += ["--effort", self.cfg.claude.effort]
        if self.cfg.claude.code_model:
            args += ["--model", self.cfg.claude.code_model]
        return args

    def status(self) -> str:
        return describe_status(auth_status(self.exe, self._run))

    def stream(self, prompt: str, image_png: bytes | None = None) -> Iterator[str]:
        self.workdir.mkdir(parents=True, exist_ok=True)
        prompt_file = self.workdir / "system-prompt.txt"
        files = self.cfg.claude.allow_files
        system = system_prompt(
            self.cfg,
            web=self.cfg.claude.allow_web,
            home=self.home if files else None,
            folders=self.folders if files else None,
            only=self.only if files else None,
        )
        prompt_file.write_text(system, "utf-8")
        shot = self.workdir / SCREENSHOT
        if image_png:
            shot.write_bytes(image_png)
            prompt += (
                f"\n\nThe screenshot is the file {SCREENSHOT} in the current folder. "
                "Read it with the Read tool."
            )
        with tempfile.TemporaryFile() as stderr:
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
                log.error("Couldn't start Claude Code (%s): %s", self.exe, e)
                raise BrainError(START_FAILED) from e
            timed_out = threading.Event()

            def kill() -> None:
                timed_out.set()
                proc.kill()

            timer = threading.Timer(self.cfg.claude.timeout_seconds, kill)
            timer.start()
            try:
                try:
                    proc.stdin.write(prompt)
                    proc.stdin.close()
                except OSError:
                    log.debug("Claude Code closed its input early", exc_info=True)
                try:
                    yield from read_events(proc.stdout)
                except BrainError as e:
                    if timed_out.is_set():
                        raise BrainError(TOO_SLOW) from e
                    if str(e) == FAILED:
                        detail = self._stderr(proc, stderr)
                        log.error("Claude Code failed (exit %s): %s", proc.returncode, detail)
                        raise BrainError(error_message(detail)) from e
                    raise
                if timed_out.is_set():
                    raise BrainError(TOO_SLOW)
            finally:
                timer.cancel()
                if proc.poll() is None:
                    proc.kill()  # stopped early (e.g. "stop speaking")
                proc.wait()
                shot.unlink(missing_ok=True)

    @staticmethod
    def _stderr(proc, stderr) -> str:
        try:
            proc.wait(timeout=5)
            stderr.seek(0)
            return stderr.read().decode("utf-8", "replace").strip()[-500:]
        except Exception:
            return ""
