"""Everything Abdoh does to the computer itself: media keys, lock screen, timers, opening apps
and YouTube videos.

Kept in one place so tests can replace it with a fake. Windows-first: media keys, lock screen and
the installed-app list are Windows features; elsewhere they say so politely.
"""

import json
import logging
import re
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz

from abdoh import youtube
from abdoh.commands.actions import ActionError, open_app
from abdoh.commands.matcher import normalize

log = logging.getLogger(__name__)

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# ----- media keys -----

# Windows virtual-key codes, and how many presses (volume moves 2% per press).
MEDIA_KEYS: dict[str, tuple[int, int]] = {
    "play_pause": (0xB3, 1),
    "next": (0xB0, 1),
    "previous": (0xB1, 1),
    "volume_up": (0xAF, 5),
    "volume_down": (0xAE, 5),
    "mute": (0xAD, 1),
}


def press_media_key(name: str) -> None:
    if name not in MEDIA_KEYS:
        raise ActionError(f"I don't know the media key {name}.")
    if sys.platform != "win32":
        raise ActionError("Media keys only work on Windows for now.")
    import ctypes

    code, presses = MEDIA_KEYS[name]
    for _ in range(presses):
        ctypes.windll.user32.keybd_event(code, 0, 0, 0)
        ctypes.windll.user32.keybd_event(code, 0, 2, 0)  # key up


def lock_screen() -> None:
    if sys.platform != "win32":
        raise ActionError("Locking the screen only works on Windows for now.")
    import ctypes

    if not ctypes.windll.user32.LockWorkStation():
        raise ActionError("I couldn't lock the computer.")


# ----- timers -----

_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "ninety": 90,
}  # fmt: skip
_UNITS = {"second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600}
_UNIT_NAMES = {"sec": "second", "min": "minute", "hr": "hour"}
_PART = re.compile(r"(\d+(?:\.\d+)?|[a-z]+(?: [a-z]+)?) (second|sec|minute|min|hour|hr)s?\b")


def _number(text: str) -> float | None:
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)
    total = 0
    for word in text.split():
        if word not in _NUMBERS:
            return None
        total += _NUMBERS[word]
    return float(total)


def parse_duration(text: str) -> tuple[float, str] | None:
    """'5 minutes' -> (300, '5 minute'); 'an hour and a half' -> (5400, '1 and a half hour')."""
    text = " ".join(re.sub(r"[^\w\s.]|(?<!\d)\.|\.(?!\d)", " ", text.lower()).split())
    text = text.replace("half an hour", "30 minutes").replace("a half", "half")
    seconds, labels = 0.0, []
    for amount, unit in _PART.findall(text):
        number = _number(amount.removeprefix("and ").strip())
        if number is None:
            words = amount.split()  # "for five" -> "five"
            number = _number(words[-1]) if words else None
        if number is None:
            continue
        seconds += number * _UNITS[unit]
        labels.append(f"{number:g} {_UNIT_NAMES.get(unit, unit)}")
    if "and half" in text and labels:  # "an hour and a half"
        unit = labels[-1].split()[-1]
        seconds += _UNITS[unit] / 2
        labels[-1] = f"{labels[-1].split()[0]} and a half {unit}"
    if seconds <= 0:
        return None
    return seconds, " ".join(labels)


class Timers:
    """Countdown timers; when one finishes, announce() is called with what to say."""

    def __init__(self, announce: Callable[[str], None], start_timer=threading.Timer):
        self._announce = announce
        self._start_timer = start_timer
        self._running: list = []
        self._lock = threading.Lock()

    def start(self, duration_text: str) -> str:
        parsed = parse_duration(duration_text)
        if parsed is None:
            raise ActionError("I didn't catch how long the timer should be.")
        seconds, label = parsed
        timer = self._start_timer(seconds, self._finished, args=(label,))
        timer.daemon = True
        with self._lock:
            self._running.append(timer)
        timer.start()
        log.info("Timer set: %s (%.0f s)", label, seconds)
        return f"Okay, {label} timer starting now."

    def _finished(self, label: str) -> None:
        with self._lock:
            me = threading.current_thread()
            self._running = [t for t in self._running if t is not me]
        self._announce(f"Your {label} timer is done.")

    def cancel_all(self) -> str:
        with self._lock:
            running, self._running = self._running, []
        for timer in running:
            timer.cancel()
        return "Timer cancelled." if running else "There's no timer running."


# ----- installed apps -----


@dataclass(frozen=True)
class App:
    name: str
    app_id: str

    @property
    def key(self) -> str:
        return normalize(self.name)


_FILLER = {"the", "app", "application", "program", "my", "a", "please"}
_JUNK = ("uninstall", "readme", "release notes", "documentation", "help", "website", "license")
_ALIASES = {"vs code": "visual studio code", "vscode": "visual studio code"}


def load_start_apps() -> list[App]:
    """Every app in the Windows Start menu, including Store apps (Get-StartApps)."""
    if sys.platform != "win32":
        return []
    out = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json -Compress"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        creationflags=NO_WINDOW,
    ).stdout.strip()
    data = json.loads(out) if out else []
    if isinstance(data, dict):
        data = [data]
    return [App(d["Name"], d["AppID"]) for d in data if d.get("Name") and d.get("AppID")]


def _launch(app: App) -> None:
    # The Start menu's own way to start an app, for desktop and Store apps alike.
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app.app_id}"], creationflags=NO_WINDOW)


class AppIndex:
    """Finds an installed app by spoken name. Loaded once, refreshed when a name isn't found."""

    REFRESH_SECONDS = 600

    def __init__(self, loader: Callable[[], list[App]] = load_start_apps, launch=_launch):
        self._loader = loader
        self._launch = launch
        self._apps: list[App] | None = None
        self._loaded_at = 0.0
        self._lock = threading.Lock()

    def load(self) -> None:
        try:
            apps = [a for a in self._loader() if not any(j in a.key for j in _JUNK)]
        except Exception:
            log.warning("Couldn't list installed apps", exc_info=True)
            apps = []
        with self._lock:
            self._apps, self._loaded_at = apps, time.monotonic()
        log.info("Found %d installed apps", len(apps))

    def load_in_background(self) -> None:
        threading.Thread(target=self.load, name="abdoh-apps", daemon=True).start()

    def find(self, spoken: str) -> App | None:
        found = self._find(spoken)
        stale = time.monotonic() - self._loaded_at > self.REFRESH_SECONDS
        if found is None and (self._apps is None or stale):
            self.load()  # maybe it was installed since
            found = self._find(spoken)
        return found

    def _find(self, spoken: str) -> App | None:
        apps = self._apps or []
        query = " ".join(w for w in normalize(spoken).split() if w not in _FILLER)
        query = _ALIASES.get(query, query)
        if not query or not apps:
            return None
        for app in apps:
            if app.key == query:
                return app
        words = set(query.split())
        containing = [a for a in apps if words <= set(a.key.split())]
        if containing:
            return min(containing, key=lambda a: len(a.name))  # "chrome" -> "Google Chrome"
        best = max(apps, key=lambda a: fuzz.ratio(query, a.key))
        return best if fuzz.ratio(query, best.key) >= 85 else None

    def open(self, spoken: str) -> str:
        """Open the app that best matches the spoken name; returns its real name."""
        app = self.find(spoken)
        if app is None:
            raise ActionError(f"I couldn't find an app called {spoken}.")
        log.info("Opening %s (%s)", app.name, app.app_id)
        try:
            self._launch(app)
        except OSError as e:
            raise ActionError(f"I couldn't open {app.name}.") from e
        return app.name


# ----- all together -----


class Computer:
    def __init__(
        self,
        timers: Timers | None = None,
        apps: AppIndex | None = None,
        press_key: Callable[[str], None] = press_media_key,
        lock: Callable[[], None] = lock_screen,
        open_url: Callable[[str], object] = webbrowser.open,
        start_app: Callable[[str], None] = open_app,
        find_video: Callable[[str], str | None] = youtube.find_video,
    ):
        self.timers = timers or Timers(announce=lambda text: log.info(text))
        self.apps = apps or AppIndex()
        self._press_key = press_key
        self._lock = lock
        self._open_url = open_url
        self._start_app = start_app
        self._find_video = find_video

    def open_url(self, url: str) -> None:
        if not self._open_url(url):
            raise ActionError("I couldn't open that link.")

    def play_youtube(self, query: str) -> str:
        """Start the top YouTube video for a search. If none is found (or YouTube can't be
        reached), open the results page instead and say so. Returns what to say ("" = nothing)."""
        query = query.strip()
        if not query:
            raise ActionError("What should I play?")
        video = self._find_video(query)
        if video:
            log.info("Playing YouTube video %s for %r", video, query)
            self.open_url(youtube.watch_url(video))
            return ""
        self.open_url(youtube.search_url(query))
        return "Here are the YouTube results."

    def open_app(self, name: str) -> str:
        """For Claude: only apps from the installed-app list."""
        return self.apps.open(name)

    def launch(self, target: str) -> None:
        """For your own commands: an installed app by name (Store apps too), or a path or
        anything else Windows can start."""
        if not Path(target).expanduser().exists() and self.apps.find(target):
            self.apps.open(target)
        else:
            self._start_app(target)

    def media(self, key: str) -> None:
        self._press_key(key.strip().lower())

    def lock(self) -> None:
        self._lock()

    def timer(self, duration_text: str) -> str:
        return self.timers.start(duration_text)
