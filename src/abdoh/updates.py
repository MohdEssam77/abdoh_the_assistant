"""Is there a newer Abdoh? Asks GitHub for the latest release, at most once a day.

Nothing about you is sent: it's one anonymous request to GitHub's public releases API.
"""

import json
import logging
import re
import time
import urllib.request
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
    download = next((a.get("browser_download_url") for a in assets if a.get("name") == ASSET), "")
    return {"version": tag.lstrip("v"), "url": page, "download": download or page}


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
