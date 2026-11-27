"""Tailscale: how the phone reaches Abdoh (ABDOH_EPIC_10.md, 3.3).

Tailscale puts your phone and this computer in one private network (a "tailnet").
`tailscale serve` shares the phone page (on 127.0.0.1 only) in that network over HTTPS, at
https://<this computer>.<tailnet>.ts.net: only your own devices can reach it, nothing is open to
the internet. With --bg it stays shared, also after a restart, until it's turned off.

Every command runs without a window and with a time limit. `tailscale status --json` is said
to change between versions: only a few fields are read, and missing ones are fine.
"""

import json
import logging
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

DOWNLOAD = "https://tailscale.com/download"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
TIMEOUT = 10.0
SHARE_SECONDS = 15.0
_LINK = re.compile(r"https://login\.tailscale\.com/\S+")
NOT_RUNNING = "Tailscale isn't running. Open Tailscale and sign in."
TOO_SLOW = "Tailscale didn't answer. Open Tailscale, check it's on, and try again."


def find(which=shutil.which, is_file=Path.is_file) -> str | None:
    """tailscale.exe: on PATH, or where its installer puts it."""
    found = which("tailscale")
    if found:
        return found
    places = (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"), r"C:\Program Files")
    for base in places:
        if base:
            path = Path(base) / "Tailscale" / "tailscale.exe"
            if is_file(path):
                return str(path)
    return None


def _run(args: list[str], timeout: float = TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL,
    )  # fmt: skip


def _proxies(data) -> list[str]:
    """Every "Proxy" target in `tailscale serve status --json`, wherever it is."""
    found = []
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "Proxy" and isinstance(value, str):
                found.append(value)
            else:
                found += _proxies(value)
    elif isinstance(data, list):
        for value in data:
            found += _proxies(value)
    return found


class Tailscale:
    def __init__(self, exe: str | None = None, run=_run, popen=subprocess.Popen, find=find,
                 clock=time.monotonic):  # fmt: skip
        self._exe = exe
        self._run = run
        self._popen = popen
        self._find = find
        self._clock = clock

    def exe(self) -> str | None:
        if self._exe is None:
            self._exe = self._find()
        return self._exe

    def state(self, port: int) -> dict:
        """What the Settings card shows: {installed, running, signed_in, address, https,
        shared, error}."""
        state = {"installed": False, "running": False, "signed_in": False, "address": "",
                 "https": False, "shared": False, "error": ""}  # fmt: skip
        exe = self.exe()
        if exe is None:
            return state
        state["installed"] = True
        try:
            done = self._run([exe, "status", "--json"])
            data = json.loads(done.stdout or "{}")
        except subprocess.TimeoutExpired:
            return {**state, "error": TOO_SLOW}
        except (OSError, ValueError):
            log.info("Couldn't read Tailscale's status", exc_info=True)
            return {**state, "error": NOT_RUNNING}
        if not isinstance(data, dict):
            return {**state, "error": NOT_RUNNING}
        backend = str(data.get("BackendState") or "")
        me = data.get("Self") if isinstance(data.get("Self"), dict) else {}
        name = str(me.get("DNSName") or "").rstrip(".")
        state.update(
            running=backend == "Running",
            signed_in=backend in ("Running", "Stopped", "Starting"),
            address=f"https://{name}" if name and backend == "Running" else "",
            https=bool(data.get("CertDomains")),
        )
        if state["running"]:
            state["shared"] = self.shared(port)
        elif backend == "Stopped":
            state["error"] = "Tailscale is off. Turn it on in the Tailscale app."
        elif not state["signed_in"]:
            state["error"] = NOT_RUNNING
        return state

    def shared(self, port: int) -> bool:
        """Is the phone page shared in the tailnet (tailscale serve to 127.0.0.1:<port>)?"""
        exe = self.exe()
        if exe is None:
            return False
        try:
            done = self._run([exe, "serve", "status", "--json"])
            data = json.loads(done.stdout or "{}")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            log.info("Couldn't read what Tailscale shares", exc_info=True)
            return False
        targets = (f"127.0.0.1:{port}", f"localhost:{port}")
        return any(proxy.rstrip("/").endswith(targets) for proxy in _proxies(data))

    def share(self, port: int, wait: float = SHARE_SECONDS) -> dict:
        """Share the phone page in the tailnet. {"ok": True}, or {"ok": False, "link": ...}
        when HTTPS must be allowed for the tailnet first (Tailscale's page for it; the command
        is stopped), or {"ok": False, "error": ...}."""
        exe = self.exe()
        if exe is None:
            return {"ok": False, "error": "Tailscale isn't installed."}
        args = [exe, "serve", "--bg", "--https=443", f"http://127.0.0.1:{port}"]
        try:
            proc = self._popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
            )  # fmt: skip
        except OSError as e:
            log.warning("Couldn't run tailscale serve: %s", e)
            return {"ok": False, "error": NOT_RUNNING}
        lines: queue.Queue = queue.Queue()

        def read() -> None:
            try:
                for line in proc.stdout:
                    lines.put(line)
            finally:
                lines.put(None)

        threading.Thread(target=read, name="abdoh-tailscale", daemon=True).start()
        said: list[str] = []
        deadline = self._clock() + wait
        while True:
            try:
                line = lines.get(timeout=max(0.0, deadline - self._clock()))
            except queue.Empty:
                proc.kill()
                log.warning("tailscale serve took too long: %s", " ".join(said)[-300:])
                return {"ok": False, "error": TOO_SLOW}
            if line is None:
                break
            said.append(line.strip())
            link = _LINK.search(line)
            if link:  # HTTPS isn't allowed yet: it waits for you to allow it there
                proc.kill()
                log.info("Tailscale asks to allow HTTPS for the tailnet first")
                return {"ok": False, "link": link.group(0).rstrip(".,)")}
        code = proc.wait(timeout=5)
        if code == 0:
            log.info("The phone page is shared in your Tailscale network")
            return {"ok": True}
        message = next((s for s in reversed(said) if s), "") or NOT_RUNNING
        log.warning("tailscale serve failed (%s): %s", code, message)
        return {"ok": False, "error": f"Tailscale said: {message}"}

    def unshare(self) -> bool:
        """Stop sharing the phone page (only Abdoh's: other things you share stay)."""
        exe = self.exe()
        if exe is None:
            return False
        try:
            done = self._run([exe, "serve", "--https=443", "off"])
        except (OSError, subprocess.TimeoutExpired):
            log.info("Couldn't stop sharing the phone page", exc_info=True)
            return False
        return done.returncode == 0
