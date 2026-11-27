"""Connect Claude from the app: is Claude Code installed, signed in, and with which plan?

Abdoh never handles your Claude account. Signing in happens in your browser, on Anthropic's
sign-in page: Claude Code's own sign-in (`claude auth login`) runs in the background, without a
window, and opens it; Abdoh only asks Claude Code whether it's signed in (`claude auth status`).
An API key, if you use one, is your own and stays in Abdoh's settings folder on this computer.
"""

import logging
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

from abdoh.claude.brain import NOT_CONNECTED, BrainError, make_brain
from abdoh.claude.code import (
    NO_WINDOW,
    auth_status,
    child_env,
    find_claude_code,
    list_connectors,
)
from abdoh.config import Config, save_api_key

log = logging.getLogger(__name__)

INSTALL_URL = "https://claude.ai/install.ps1"  # Anthropic's official Windows installer
KEY_PREFIX = "sk-ant-"
SIGN_IN_MINUTES = 10  # then a sign-in nobody finished in the browser stops waiting
INSTALL_MINUTES = 15
_URL = re.compile(r"https://\S+")


class SetupError(RuntimeError):
    """Something in connecting Claude didn't work; the message is safe to show."""


def using(cfg: Config, exe: Path | None) -> str | None:
    """How Abdoh reaches Claude now: "code" (your account), "api" (your key), "openrouter"
    (your OpenRouter key), "chatgpt" (your ChatGPT plan), or None."""
    backend = cfg.claude.backend
    if backend in ("auto", "code") and exe:
        return "code"
    if backend in ("auto", "api") and cfg.has_api_key:
        return "api"
    if backend in ("auto", "openrouter") and cfg.has_openrouter_key:
        return "openrouter"
    from abdoh.claude.chatgpt import Account

    account = Account.of(cfg)
    if (backend == "chatgpt" and account.connected) or (backend == "auto" and account.plan_usage):
        return "chatgpt"
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
        summary = "No AI is connected: your commands and Abdoh's own skills still work."
    elif via == "code" and signed_in:
        kind = f"{plan.capitalize()} plan" if plan else "Claude account"
        if method != "claude.ai":
            kind = "Claude Console account"
        summary = f"Connected with your {kind}."
    elif via == "code":
        summary = "Claude Code is installed, but not signed in."
    elif via == "api":
        summary = "Connected with your API key."
    elif via == "openrouter":
        summary = (
            f"Connected through OpenRouter ({cfg.claude.openrouter_model or 'openrouter/auto'})."
        )
    elif via == "chatgpt":
        from abdoh.claude.chatgpt import Account

        if Account.of(cfg).plan_usage:
            model = cfg.claude.chatgpt_model
            summary = f"Using your ChatGPT plan{f' ({model})' if model else ''}."
        else:
            summary = "ChatGPT is connected, but Abdoh may not use your plan yet."
    else:
        summary = "Not connected."
    from abdoh.claude import chatgpt

    return {
        "installed": bool(exe),
        "signed_in": signed_in,
        "plan": plan,
        "method": method,
        "has_api_key": cfg.has_api_key,
        "has_openrouter_key": cfg.has_openrouter_key,
        "openrouter_model": cfg.claude.openrouter_model,
        "backend": cfg.claude.backend,
        "using": via,
        "connected": (via == "code" and signed_in)
        or via in ("api", "openrouter")
        or (via == "chatgpt" and chatgpt.connected(cfg)),
        "chatgpt": chatgpt.state(cfg),
        "summary": summary,
    }


CONNECTORS_URL = "https://claude.ai/settings/connectors"


def connectors(cfg: Config, find=find_claude_code, listing=list_connectors) -> dict:
    """The services connected to your Claude account and which ones Abdoh may use. Only
    with Claude Code (your account); takes a few seconds (Claude Code checks each one)."""
    exe = find(cfg.claude.code_path)
    if using(cfg, exe) != "code":
        return {"available": False, "reason": "Connectors need Claude Code (your Claude account)."}
    try:
        found = listing(exe)
    except BrainError as e:
        return {"available": False, "reason": str(e)}
    names = [c["name"] for c in found]
    allowed = cfg.claude.connectors
    missing = [{"name": n, "status": "not connected"} for n in allowed if n not in names]
    return {
        "available": True,
        "connectors": [{**c, "on": c["name"] in allowed} for c in found + missing],
        "url": CONNECTORS_URL,
    }


class Background:
    """A helper running without a window (Claude Code's sign-in, its installer). What it says
    goes to the log; the first link it prints is kept (the sign-in page, in case the browser
    didn't open); it's stopped after `minutes` if it's still waiting."""

    def __init__(self, what: str, args: list[str], popen, minutes: float, env=None, timer=None):
        self.what = what
        self.url = ""
        self._link = threading.Event()
        self.proc = popen(
            args,
            stdin=subprocess.PIPE,  # open (never written): Claude Code waits for the browser
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=NO_WINDOW,
        )
        threading.Thread(target=self._read, name=f"abdoh-{what}", daemon=True).start()
        self._stopper = (timer or threading.Timer)(minutes * 60, self.stop)
        self._stopper.daemon = True
        self._stopper.start()

    def _read(self) -> None:
        for line in self.proc.stdout or []:
            line = line.rstrip()
            found = _URL.search(line)
            if found and not self.url:
                self.url = found[0]
                self._link.set()
                continue  # the sign-in link isn't for the log
            if line:
                log.info("%s: %s", self.what, line)
        self._link.set()
        log.info("%s finished (%s)", self.what, self.proc.wait())

    def link(self, seconds: float) -> str:
        """The link it printed, waiting at most `seconds` for it ("" if none)."""
        self._link.wait(seconds)
        return self.url

    def stop(self) -> None:
        self._stopper.cancel()
        if self.proc.poll() is None:
            log.info("Stopped %s: nobody finished it", self.what)
            self.proc.kill()


_running: dict[str, Background] = {}  # one sign-in, one install at a time


def _start(what: str, *args, **kwargs) -> Background:
    old = _running.pop(what, None)
    if old is not None:
        old.stop()  # pressed again: the new one counts
    _running[what] = job = Background(what, *args, **kwargs)
    return job


def install_claude_code(popen=subprocess.Popen, platform: str = sys.platform, timer=None) -> None:
    """Run Anthropic's official installer in the background (the app shows when it's done)."""
    if platform != "win32":
        raise SetupError("Install Claude Code from code.claude.com/docs/en/setup, then come back.")
    script = f"irm {INSTALL_URL} | iex"
    try:
        _start(
            "Claude Code's installer",
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            popen,
            INSTALL_MINUTES,
            timer=timer,
        )
    except OSError as e:
        raise SetupError(f"Couldn't start the installer: {e}") from e


def sign_in(exe: Path, popen=subprocess.Popen, timer=None, wait: float = 5.0) -> str:
    """Start Claude Code's own sign-in in the background: it opens Anthropic's sign-in page in
    your browser and waits there. Returns that page's link, in case the browser didn't open."""
    try:
        job = _start(
            "Claude Code's sign-in",
            [str(exe), "auth", "login", "--claudeai"],
            popen,
            SIGN_IN_MINUTES,
            env=child_env(),  # with the account, not a key
            timer=timer,
        )
    except OSError as e:
        raise SetupError(f"Couldn't open Claude Code's sign-in: {e}") from e
    return job.link(wait)


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


def set_openrouter_key(cfg: Config, key: str) -> None:
    """Save your own OpenRouter key (or remove it with "") in Abdoh's .env file."""
    from abdoh.claude.openrouter import KEY_PREFIX as OPENROUTER_PREFIX
    from abdoh.config import OPENROUTER_KEY

    key = (key or "").strip()
    if key and not key.startswith(OPENROUTER_PREFIX):
        raise SetupError(
            f"That doesn't look like an OpenRouter key (they start with {OPENROUTER_PREFIX})."
        )
    save_api_key(cfg.env_path, key, OPENROUTER_KEY)
    if key:
        try:
            os.chmod(cfg.env_path, 0o600)
        except OSError:
            pass


def openrouter_models() -> dict:
    """The models on OpenRouter, for picking one in Settings."""
    from abdoh.claude.openrouter import models

    try:
        return {"ok": True, "models": models()}
    except BrainError as e:
        return {"ok": False, "error": str(e), "models": []}


def openrouter_pictures(cfg: Config) -> dict:
    """For the Claude card: the models that make pictures, the chosen one's price, and the
    credit left (when OpenRouter tells a normal key)."""
    from abdoh.claude import openrouter

    try:
        models = openrouter.image_models()
    except Exception as e:
        log.info("Couldn't list the picture models: %s", e)
        return {"ok": False, "error": "Couldn't get OpenRouter's picture models.", "models": []}
    chosen = cfg.claude.openrouter_image_model or openrouter.DEFAULT_IMAGE_MODEL
    try:
        left = openrouter.credit_left(cfg.openrouter_api_key) if cfg.openrouter_api_key else None
    except Exception:
        left = None
    return {
        "ok": True,
        "models": models,
        "chosen": chosen,
        "price": openrouter.picture_price(chosen),
        "credit": left,
    }


def picture_price(model: str) -> dict:
    from abdoh.claude import openrouter

    return {"price": openrouter.picture_price(str(model))}


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
