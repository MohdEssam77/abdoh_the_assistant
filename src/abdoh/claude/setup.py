"""Connect Claude from the app: is Claude Code installed, signed in, and with which plan?

Abdoh never handles your Claude account. Signing in happens in Claude Code's own window and in
your browser, on Anthropic's sign-in page (`claude auth login`); Abdoh only asks Claude Code
whether it's signed in (`claude auth status`). An API key, if you use one, is your own and stays
in Abdoh's settings folder on this computer.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

from abdoh.claude.brain import NOT_CONNECTED, BrainError, make_brain
from abdoh.claude.code import NO_WINDOW, auth_status, child_env, find_claude_code
from abdoh.config import Config, save_api_key

log = logging.getLogger(__name__)

INSTALL_URL = "https://claude.ai/install.ps1"  # Anthropic's official Windows installer
NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
KEY_PREFIX = "sk-ant-"


class SetupError(RuntimeError):
    """Something in connecting Claude didn't work; the message is safe to show."""


def using(cfg: Config, exe: Path | None) -> str | None:
    """How Abdoh reaches Claude now: "code" (your account), "api" (your key), or None."""
    backend = cfg.claude.backend
    if backend in ("auto", "code") and exe:
        return "code"
    if backend in ("auto", "api") and cfg.has_api_key:
        return "api"
    return None


def claude_state(cfg: Config, find=find_claude_code, status=auth_status) -> dict:
    """Everything the app shows about the Claude connection (no secrets)."""
    exe = find(cfg.claude.code_path)
    info = (status(exe) or {}) if exe else {}
    signed_in = bool(info.get("loggedIn"))
    plan = info.get("subscriptionType") or info.get("planTier") or ""
    method = info.get("authMethod") or ""
    via = using(cfg, exe)
    if cfg.claude.backend == "off":
        summary = "Claude is turned off."
    elif via == "code" and signed_in:
        kind = f"{plan.capitalize()} plan" if plan else "Claude account"
        if method != "claude.ai":
            kind = "Claude Console account"
        summary = f"Connected with your {kind}."
    elif via == "code":
        summary = "Claude Code is installed, but not signed in."
    elif via == "api":
        summary = "Connected with your API key."
    else:
        summary = "Not connected."
    return {
        "installed": bool(exe),
        "signed_in": signed_in,
        "plan": plan,
        "method": method,
        "has_api_key": cfg.has_api_key,
        "backend": cfg.claude.backend,
        "using": via,
        "connected": (via == "code" and signed_in) or via == "api",
        "summary": summary,
    }


def install_claude_code(popen=subprocess.Popen, platform: str = sys.platform) -> None:
    """Run Anthropic's official installer in a window you can watch."""
    if platform != "win32":
        raise SetupError("Install Claude Code from code.claude.com/docs/en/setup, then come back.")
    script = (
        "Write-Host 'Installing Claude Code from Anthropic...'; Write-Host '';"
        f"irm {INSTALL_URL} | iex; Write-Host '';"
        "Write-Host 'Done. Close this window and go back to Abdoh to sign in.'"
    )
    try:
        popen(
            ["powershell.exe", "-NoProfile", "-NoExit", "-Command", script],
            creationflags=NEW_CONSOLE,
        )
    except OSError as e:
        raise SetupError(f"Couldn't start the installer: {e}") from e


def sign_in(exe: Path, popen=subprocess.Popen) -> None:
    """Open Claude Code's own sign-in (it continues in your browser) in a window you can see."""
    script = (
        "& $env:ABDOH_CLAUDE auth login; Write-Host '';"
        "Write-Host 'Signed in? Close this window and go back to Abdoh.'"
    )
    env = {**child_env(), "ABDOH_CLAUDE": str(exe)}  # the path goes in safely, never parsed
    try:
        popen(
            ["powershell.exe", "-NoProfile", "-NoExit", "-Command", script],
            env=env,
            creationflags=NEW_CONSOLE,
        )
    except OSError as e:
        raise SetupError(f"Couldn't open Claude Code's sign-in: {e}") from e


def sign_out(exe: Path, run=subprocess.run) -> None:
    try:
        run(
            [str(exe), "auth", "logout"],
            capture_output=True,
            timeout=30,
            env=child_env(),
            creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise SetupError(f"Couldn't sign out: {e}") from e


def set_api_key(cfg: Config, key: str) -> None:
    """Save your own Anthropic API key (or remove it with "") in Abdoh's .env file."""
    key = (key or "").strip()
    if key and not key.startswith(KEY_PREFIX):
        raise SetupError(
            f"That doesn't look like an Anthropic API key (they start with {KEY_PREFIX})."
        )
    save_api_key(cfg.env_path, key)
    if key:
        try:
            os.chmod(cfg.env_path, 0o600)  # only you (has little effect on Windows)
        except OSError:
            pass


def check_connection(cfg: Config, make=make_brain) -> dict:
    """Ask Claude for one word. Uses a tiny bit of your plan or key."""
    brain = make(cfg)
    if brain is None:
        return {"ok": False, "error": NOT_CONNECTED}
    try:
        reply = "".join(brain.stream("Reply with just the word OK.")).strip()
    except BrainError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        log.exception("Claude test failed")
        return {"ok": False, "error": f"Claude couldn't answer: {e}"}
    finally:
        brain.close()
    return {"ok": True, "reply": reply[:200], "via": brain.name}
