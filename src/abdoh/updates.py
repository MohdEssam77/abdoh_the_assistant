"""Is there a newer Abdoh? Asks GitHub for the latest release, at most once a day; and installs it
from the app ("Install now"): the installer downloads in the background (its size and SHA-256
checked against what GitHub says), then a small helper waits for Abdoh to close, installs it
quietly and starts the new Abdoh. No browser, nothing to click.

Nothing about you is sent: one anonymous request to GitHub's public releases API, and the
download of the installer.
"""

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

from abdoh import __version__

log = logging.getLogger(__name__)

REPO = "MohdEssam77/abdoh_the_assistant"
LATEST = "https://api.github.com/repos/{repo}/releases/latest"
ASSET = "Abdoh-Setup.exe"  # the installer's name in every release (stable download links)
STATE = Path.home() / ".abdoh" / "update.json"
DAY = 24 * 60 * 60


def version_tuple(text: str) -> tuple[int, ...]:
    """'v0.3.1' -> (0, 3, 1). Text without a version gives ()."""
    match = re.match(r"v?(\d+(?:\.\d+)*)", str(text).strip())
    return tuple(int(n) for n in match.group(1).split(".")) if match else ()


def is_newer(latest: str, current: str) -> bool:
    new, old = version_tuple(latest), version_tuple(current)
    size = max(len(new), len(old))
    return bool(new) and new + (0,) * (size - len(new)) > old + (0,) * (size - len(old))


def fetch_json(url: str, timeout: float = 10) -> dict:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Abdoh-update-check"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def latest_release(fetch=fetch_json, repo: str = REPO) -> dict | None:
    """The latest published release: {"version", "url", "download"}, or None if unknown."""
    try:
        data = fetch(LATEST.format(repo=repo))
    except Exception as e:  # offline, rate-limited, or no public release yet
        log.debug("Update check failed: %s", e)
        return None
    tag = str(data.get("tag_name") or "")
    if not version_tuple(tag) or data.get("draft") or data.get("prerelease"):
        return None
    page = str(data.get("html_url") or "")
    assets = data.get("assets") or []
    asset = next((a for a in assets if a.get("name") == ASSET), {})
    download = asset.get("browser_download_url") or ""
    found = {"version": tag.lstrip("v"), "url": page, "download": download or page}
    if download:  # what the downloaded installer must be
        found["size"] = int(asset.get("size") or 0)
        digest = str(asset.get("digest") or "")
        if digest.startswith("sha256:"):
            found["sha256"] = digest.split(":", 1)[1].lower()
    return found


def check_for_update(
    current: str = __version__,
    fetch=fetch_json,
    state_path: Path = STATE,
    now=time.time,
    force: bool = False,
) -> dict | None:
    """The newer release, if there is one. Asks GitHub at most once a day unless `force`."""
    state_path = Path(state_path)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    checked_at = state.get("checked_at")
    if force or not isinstance(checked_at, int | float) or now() - checked_at >= DAY:
        latest = latest_release(fetch)
        state = {"checked_at": now(), "latest": latest}
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state), encoding="utf-8")
        except OSError:
            log.debug("Couldn't remember the update check", exc_info=True)
    latest = state.get("latest")
    if isinstance(latest, dict) and is_newer(latest.get("version", ""), current):
        return latest
    return None


# ----- installing it from the app -----

FOLDER = Path(tempfile.gettempdir()) / "Abdoh-update"
CHUNK = 1 << 20
# Where the installer puts Abdoh (installer/abdoh.iss: {localappdata}\Programs\Abdoh).
INSTALLED = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Programs" / "Abdoh" / "Abdoh.exe"
)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
BREAKAWAY = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
FROM_SOURCE = "You're running Abdoh from its source code: update it with git pull."
NOT_AN_INSTALLER = "This release has no installer to download. Get it from the release page."
BROKEN = "The download didn't match what GitHub says it should be. Try again."
# The helper: wait for Abdoh to close, install quietly (the installer also closes Abdoh if it's
# still running, and keeps your choices: start at sign-in, the desktop shortcut), start it again.
HELPER = """@echo off
rem Abdoh's update: wait for Abdoh to close, install the new version quietly, start it again.
ping -n 4 127.0.0.1 >nul
start "" /wait "{setup}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /LOG="{log}"
if exist "{exe}" (start "" "{exe}" run --show) else (start "" "{fallback}" run --show)
"""


class UpdateError(RuntimeError):
    """The update couldn't be installed: the message is safe to show."""


def download(url: str, target: Path, size: int = 0, sha256: str = "",
             on_progress: Callable[[int], None] = lambda percent: None,
             opener=urllib.request.urlopen) -> Path:  # fmt: skip
    """Download the installer to `target` (a .part file first), checking its size and SHA-256
    when GitHub gave them. An installer already there and correct is kept."""
    target = Path(target)
    if target.is_file() and _matches(target, size, sha256):
        on_progress(100)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    done, shown = 0, -1
    request = urllib.request.Request(url, headers={"User-Agent": "Abdoh-update"})
    with opener(request, timeout=60) as response, open(part, "wb") as out:
        total = size or int(response.headers.get("Content-Length") or 0)
        while chunk := response.read(CHUNK):
            out.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            percent = int(done * 100 / total) if total else 0
            if percent != shown:
                shown = percent
                on_progress(min(percent, 99))
    if (size and done != size) or (sha256 and digest.hexdigest() != sha256.lower()):
        part.unlink(missing_ok=True)
        raise UpdateError(BROKEN)
    part.replace(target)
    on_progress(100)
    return target


def _matches(path: Path, size: int, sha256: str) -> bool:
    if size and path.stat().st_size != size:
        return False
    if not sha256:
        return bool(size)  # nothing to check it against: download it again
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest() == sha256.lower()


def helper_script(
    setup: Path, folder: Path, exe: Path = INSTALLED, fallback: Path | None = None
) -> Path:
    """The .cmd that installs `setup` once Abdoh has closed, then starts Abdoh again."""
    script = Path(folder) / "install-update.cmd"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        HELPER.format(
            setup=setup,
            log=Path(folder) / "install.log",
            exe=exe,
            fallback=fallback or Path(sys.executable),
        ),  # fmt: skip
        encoding="utf-8",
    )
    return script


def launch(script: Path, popen=subprocess.Popen) -> None:
    """Start the helper so it outlives Abdoh (no window; out of Abdoh's job if it may)."""
    args = ["cmd.exe", "/c", str(script)]
    quiet = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
             "stderr": subprocess.DEVNULL, "close_fds": True}  # fmt: skip
    try:
        popen(args, creationflags=NO_WINDOW | NEW_GROUP | BREAKAWAY, **quiet)
    except OSError:  # Abdoh's job doesn't allow breaking away: it still runs on its own
        popen(args, creationflags=NO_WINDOW | NEW_GROUP, **quiet)


class Updater:
    """One update at a time: download, check, hand over to the helper, then `on_ready` (Abdoh
    closes). `status` says how it's going, for the window."""

    def __init__(self, on_status: Callable[[dict], None] = lambda status: None,
                 on_ready: Callable[[], None] = lambda: None, folder: Path = FOLDER,
                 frozen: bool | None = None, fetch=download, start=launch) -> None:  # fmt: skip
        self.on_status = on_status
        self.on_ready = on_ready
        self.folder = Path(folder)
        self.frozen = getattr(sys, "frozen", False) if frozen is None else frozen
        self._fetch = fetch
        self._start = start
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.status: dict = {"state": "idle"}

    def _say(self, **status) -> None:
        self.status = status
        try:
            self.on_status(dict(status))
        except Exception:
            log.debug("Couldn't show the update's progress", exc_info=True)

    def install(self, release: dict) -> dict:
        """Start installing `release` (from check_for_update). Returns the status now."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return dict(self.status)
            if not self.frozen:
                return {"state": "failed", "error": FROM_SOURCE}
            download_url = str(release.get("download") or "")
            if not download_url.endswith(".exe"):
                return {"state": "failed", "error": NOT_AN_INSTALLER}
            self._say(state="downloading", version=release.get("version", ""), percent=0)
            self._thread = threading.Thread(
                target=self._run, args=(dict(release),), name="abdoh-update", daemon=True
            )
            self._thread.start()
            return dict(self.status)

    def _run(self, release: dict) -> None:
        version = str(release.get("version", ""))
        try:
            setup = self._fetch(
                release["download"],
                self.folder / f"Abdoh-Setup-{version}.exe",
                size=int(release.get("size") or 0),
                sha256=str(release.get("sha256") or ""),
                on_progress=lambda p: self._say(state="downloading", version=version, percent=p),
            )
            log.info("Downloaded Abdoh %s (%s): installing it after Abdoh closes", version, setup)
            self._start(helper_script(setup, self.folder))
        except UpdateError as e:
            log.warning("The update to %s failed: %s", version, e)
            self._say(state="failed", version=version, error=str(e))
            return
        except Exception as e:
            log.exception("The update to %s failed", version)
            self._say(
                state="failed", version=version, error=f"The update couldn't be downloaded ({e})."
            )
            return
        self._say(state="installing", version=version, percent=100)
        self.on_ready()
