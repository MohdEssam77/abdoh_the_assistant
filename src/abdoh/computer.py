"""Everything Abdoh does to the computer itself: media keys, lock screen, timers, opening apps
and YouTube videos.

Kept in one place so tests can replace it with a fake. Windows-first: media keys, lock screen and
the installed-app list are Windows features; elsewhere they say so politely.
"""

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
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
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
    "ninety": 90, "hundred": 100,
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
        audio=None,
        desk=None,
        notes=None,
        reminders=None,
        pictures: Path | None = None,
        now: Callable[[], datetime] = datetime.now,
        system=None,
        displays=None,
    ):
        self.timers = timers or Timers(announce=lambda text: log.info(text))
        self.apps = apps or AppIndex()
        self._audio = audio  # abdoh.winaudio, or a fake: speaker() gives the volume control
        self._desk = desk  # abdoh.desk, or a fake: brightness, battery, typing, windows
        self._notes = notes
        self._reminders = reminders
        self._pictures = pictures  # where screenshots go
        self._system = system  # abdoh.system, or a fake: theme, power, keys, windows, folders
        self.displays = displays  # abdoh.displays.Displays, or None (no monitor control)
        self.now = now
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

    # ----- volume -----

    def _speaker(self):
        if self._audio is None:
            from abdoh import winaudio

            self._audio = winaudio
        try:
            return self._audio.speaker()
        except Exception as e:
            log.warning("Volume control isn't available: %s", e)
            raise ActionError("I can't reach the volume control here.") from e

    def volume(self) -> int:
        return self._speaker().volume()

    def set_volume(self, percent: float) -> int:
        """Set the speakers to exactly this volume (unmuting them if it's above zero)."""
        speaker = self._speaker()
        level = speaker.set_volume(percent)
        if level > 0 and speaker.muted():
            speaker.set_muted(False)
        return level

    def muted(self) -> bool:
        return self._speaker().muted()

    def set_muted(self, muted: bool) -> None:
        try:
            self._speaker().set_muted(muted)
        except ActionError:
            self._press_key("mute")  # the mute key at least toggles it

    # ----- each app's volume (the volume mixer) -----

    def _mixer(self):
        if self._audio is None:
            from abdoh import winaudio

            self._audio = winaudio
        return self._audio

    def find_app_audio(self, name: str) -> list:
        """The mixer's sessions for an app you named ("the browser", "Spotify"); [] if none.
        Abdoh's own sound never counts."""
        return find_sessions(name, self._mixer().app_sessions())

    def _app_sessions(self, name: str) -> list:
        found = self.find_app_audio(name)
        if not found:
            raise ActionError(f"I can't find {name.strip()} in the volume mixer.")
        return found

    def app_volume(self, name: str) -> tuple[str, int]:
        """(the app's name, its volume 0 to 100)."""
        found = self._app_sessions(name)
        return app_label(found[0]), max(s.volume for s in found)

    def set_app_volume(self, name: str, percent: float) -> str:
        """Set an app's volume (0 to 100, unmuting it). Returns the app's name."""
        found = self._app_sessions(name)
        level = max(0, min(100, round(percent)))
        for session in found:
            self._mixer().set_session_volume(session.id, level, muted=False if level else None)
        return app_label(found[0])

    def change_app_volume(self, name: str, step: int) -> tuple[str, int]:
        """Turn an app up (step > 0) or down. Returns (its name, the new volume)."""
        label, now = self.app_volume(name)
        level = max(0, min(100, now + step))
        self.set_app_volume(name, level)
        return label, level

    def mute_app(self, name: str, muted: bool) -> str:
        found = self._app_sessions(name)
        for session in found:
            self._mixer().set_session_volume(session.id, muted=muted)
        return app_label(found[0])

    def playing_apps(self) -> list[str]:
        """The apps making sound right now (not Abdoh itself, not Windows' system sounds)."""
        own = os.getpid()
        names = []
        for session in self._mixer().app_sessions():
            if session.playing and session.pid not in (0, own):
                label = app_label(session)
                if label not in names:
                    names.append(label)
        return names

    # ----- screen, battery, keyboard, windows -----

    def _on_desk(self):
        if self._desk is None:
            from abdoh import desk

            self._desk = desk
        return self._desk

    def brightness(self) -> int:
        """The laptop screen's brightness, or the first monitor that can tell."""
        try:
            return self._on_desk().get_brightness()
        except ActionError:
            for display in self._external_screens():
                level = self.displays.brightness(display)
                if level is not None:
                    return level
            raise

    def set_brightness(self, percent: float, screen: str | None = None) -> int:
        """Every screen that's on and can change it (the laptop's own, and monitors that
        support DDC/CI), or just the one you named."""
        level = max(0, min(100, round(percent)))
        targets = self._screens_named(screen) if screen else None
        done = False
        problem = None
        if targets is None or any(d.internal for d in targets):
            try:
                level = self._on_desk().set_brightness(level)
                done = True
            except ActionError as e:
                problem = e
        for display in self._external_screens(targets):
            done = self.displays.set_brightness(display, level) or done
        if not done:
            raise problem or ActionError("That screen's brightness can't be changed from here.")
        return level

    def screen_brightness(self) -> dict:
        """Each screen's brightness that can be read: {"laptop" or monitor id: percent}."""
        levels = {}
        try:
            levels["laptop"] = self._on_desk().get_brightness()
        except ActionError:
            pass
        for display in self._external_screens():
            level = self.displays.brightness(display)
            if level is not None:
                levels[display.id] = level
        return levels

    def restore_brightness(self, levels: dict) -> None:
        """Put each screen back to the brightness `screen_brightness()` read."""
        if "laptop" in levels:
            try:
                self._on_desk().set_brightness(levels["laptop"])
            except ActionError:
                pass
        for display in self._external_screens():
            if display.id in levels:
                self.displays.set_brightness(display, levels[display.id])

    def restore_audio_output(self, output_id: str) -> None:
        if any(o.id == output_id for o in self.audio_outputs()):
            self._mixer().set_default_output(output_id)

    def _external_screens(self, among=None) -> list:
        if self.displays is None:
            return []
        displays = among if among is not None else self.displays.all()
        return [d for d in displays if d.active and not d.internal]

    def _screens_named(self, spoken: str) -> list:
        if self.displays is None:
            raise ActionError("I can't control the screens here.")
        found = self.displays.find(spoken)
        if not found:
            raise ActionError(f"I don't know which screen '{spoken.strip()}' is.")
        return found

    # ----- monitors on and off -----

    def screens(self, layout: str) -> str:
        """'all', 'only 2', '1 off', '3 on'. Returns which screens are on, to say."""
        if self.displays is None:
            raise ActionError("I can't control the screens here.")
        return self.displays.apply(layout)

    def screens_status(self) -> str:
        if self.displays is None:
            raise ActionError("I can't control the screens here.")
        return self.displays.describe()

    # ----- Windows settings, keys, windows, folders, clipboard -----

    def _on_system(self):
        if self._system is None:
            from abdoh import system

            self._system = system
        return self._system

    def audio_outputs(self) -> list:
        return self._mixer().outputs()

    def set_audio_output(self, spoken: str) -> str:
        """Send the sound to the speakers you named. Returns their name."""
        outputs = self.audio_outputs()
        chosen = find_output(spoken, outputs)
        if chosen is None:
            names = ", ".join(short_output_name(o.name) for o in outputs) or "none"
            raise ActionError(f"I can't tell which speakers you mean. You have: {names}.")
        if not chosen.default:
            self._mixer().set_default_output(chosen.id)
        return short_output_name(chosen.name)

    def dark_mode(self) -> bool:
        return self._on_system().dark_mode()

    def set_dark_mode(self, on: bool) -> None:
        self._on_system().set_dark_mode(on)

    def night_light(self) -> bool:
        return self._on_system().night_light()

    def set_night_light(self, on: bool) -> None:
        self._on_system().set_night_light(on)

    def power_mode(self) -> str:
        return self._on_system().power_mode()

    def set_power_mode(self, name: str) -> None:
        self._on_system().set_power_mode(name)

    def power(self, what: str) -> None:
        """'sleep', 'lock' or 'screens_off'."""
        what = what.strip().lower().replace(" ", "_")
        if what == "sleep":
            self._on_system().sleep()
        elif what == "lock":
            self.lock()
        elif what in ("screens_off", "screen_off", "monitors_off"):
            self._on_system().screens_off()
        else:
            raise ActionError("Power is one of sleep, lock or screens_off.")

    def shutdown(self, seconds: int, restart: bool = False) -> None:
        self._on_system().shutdown(seconds, restart)

    def cancel_shutdown(self) -> bool:
        return self._on_system().cancel_shutdown()

    def press_keys(self, keys: str) -> None:
        self._on_system().press_keys(keys)

    def close_app(self, name: str) -> int:
        count = self._on_system().close_app(name)
        if not count:
            raise ActionError(f"{name.strip().capitalize()} isn't open.")
        return count

    def focus_app(self, name: str) -> str:
        return self._on_system().focus_app(name)

    def is_open(self, name: str) -> bool:
        return bool(self._on_system().app_windows(name))

    def move_window(self, app: str | None, screen: str, how: str = "maximized") -> str:
        """Put a program's window (Abdoh's too), or the one in front, on a screen. Returns the
        screen."""
        system = self._on_system()
        if app:
            windows = system.app_windows(app, own=True)
            if not windows:
                raise ActionError(f"{app.strip().capitalize()} isn't open.")
            handle = windows[0][0]
        else:
            handle = system.front_window_handle()
            if handle is None:
                raise ActionError("There's no window in front.")
        if self.displays is None:
            raise ActionError("I can't control the screens here.")
        on = [d for d in self.displays.all() if d.active and d.rect]
        current = display_at(system.window_rect(handle), on)
        spoken = screen.lower().strip()
        if spoken in ("current", "this", "this screen", "same screen"):
            target = current
        elif spoken in ("other", "next", "other screen", "next screen", "another screen"):
            if len(on) < 2:
                raise ActionError("Only one screen is on.")
            target = on[(on.index(current) + 1) % len(on)] if current in on else on[0]
        else:
            named = [d for d in self._screens_named(screen) if d.active]
            if not named:
                raise ActionError("That screen is off.")
            target = named[0]
        system.move_window(handle, target.rect, how)
        return self.displays.numbers([target])

    def screen_in_front(self):
        """The screen with the window you're working in (the primary one if none)."""
        if self.displays is None:
            raise ActionError("I can't control the screens here.")
        from abdoh.claude.screen import front_window

        on = [d for d in self.displays.all() if d.active and d.rect]
        if not on:
            raise ActionError("I can't see any screens.")
        window = front_window()
        if window.rect is None:
            return next((d for d in on if d.primary), on[0])
        left, top, right, bottom = window.rect
        return display_at((left, top, right - left, bottom - top), on)

    def open_folder(self, name: str) -> None:
        system = self._on_system()
        system.open_path(system.folder(name))

    def open_newest(self, name: str) -> str:
        """Open the newest file in a folder ("downloads"). Returns its name."""
        system = self._on_system()
        newest = system.newest_file(system.folder(name))
        if newest is None:
            raise ActionError(f"Your {name} folder is empty.")
        system.open_path(newest)
        return newest.name

    def clipboard(self) -> str:
        return self._on_system().get_clipboard()

    def set_clipboard(self, text: str) -> None:
        self._on_system().set_clipboard(text)

    def battery(self) -> tuple[int, bool] | None:
        return self._on_desk().battery()

    def type_text(self, text: str) -> None:
        """Type into whatever app is in front."""
        self._on_desk().type_text(text)

    def window(self, action: str) -> None:
        self._on_desk().window(action)

    def screenshot(self) -> Path:
        folder = self._pictures or Path.home() / "Pictures" / "Screenshots"
        return self._on_desk().save_screenshot(folder)

    # ----- notes and reminders -----

    @property
    def notes(self):
        if self._notes is None:
            raise ActionError("Notes aren't available here.")
        return self._notes

    @property
    def reminders(self):
        if self._reminders is None:
            raise ActionError("Reminders aren't available here.")
        return self._reminders

    def open_notes(self) -> None:
        from abdoh.commands.actions import open_in_editor

        path = self.notes.path
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        open_in_editor(path)

    def remind(self, when_and_what: str) -> str:
        """For Claude: "20 minutes | call mom" or "17:30 | leave". Returns how to say when."""
        from abdoh.local_skills import parse_reminder

        when_text, _, what = when_and_what.partition("|")
        when_text, what = when_text.strip().lower(), what.strip()
        if not what:
            raise ActionError("What should I remind you of?")
        if not when_text.startswith(("in ", "at ", "tomorrow", "tonight")):
            when_text = ("in " if parse_duration(when_text) else "at ") + when_text
        parsed = parse_reminder(f"{when_text}, to {what}", self.now())
        if parsed is None:
            raise ActionError("I didn't catch when to remind you.")
        when, what, said = parsed
        self.reminders.add(when, what)
        return said


# ----- naming the apps in the volume mixer -----

BROWSERS = ("chrome", "msedge", "brave", "firefox", "opera", "vivaldi", "arc", "browser")
# What you might call an app -> the programs it means.
APP_ALIASES = {
    "browser": BROWSERS,
    "web browser": BROWSERS,
    "internet": BROWSERS,
    "youtube": BROWSERS,
    "netflix": (*BROWSERS, "netflix"),
    "video": BROWSERS,
    "edge": ("msedge",),
    "microsoft edge": ("msedge",),
    "google chrome": ("chrome",),
    "teams": ("ms-teams", "teams"),
    "music": ("spotify", "music.ui", "applemusic", "itunes"),
}
NICE_NAMES = {"msedge": "Edge", "ms-teams": "Teams", "music.ui": "Media Player"}
_FILLER_WORDS = re.compile(r"^(?:the|my) |(?: app| application| volume| sound| audio| tab)+$")


def app_label(session) -> str:
    """A name to say for a mixer session: "Brave", "Spotify", "WhatsApp"."""
    program = session.program or ""
    if program.lower() in NICE_NAMES:
        return NICE_NAMES[program.lower()]
    name = session.name if session.name and not session.name.startswith("@") else program
    name = name.split(".")[0] or "Windows sounds"
    return name[:1].upper() + name[1:]


def find_sessions(name: str, sessions) -> list:
    """The sessions an app's spoken name means: by alias ("browser"), program or mixer name;
    a close spelling if nothing matches exactly. Never Abdoh's own."""
    wanted = _FILLER_WORDS.sub("", " ".join(name.lower().split()))
    wanted = _FILLER_WORDS.sub("", wanted).strip()
    if not wanted:
        return []
    own = os.getpid()
    candidates = [s for s in sessions if s.pid not in (0, own)]
    programs = APP_ALIASES.get(wanted, ())
    squeezed = wanted.replace(" ", "")

    def exact(s) -> bool:
        program = (s.program or "").lower()
        label = app_label(s).lower()
        return (
            program in programs
            or squeezed in (program, label.replace(" ", ""))
            or (len(squeezed) >= 4 and (squeezed in program or squeezed in label.replace(" ", "")))
        )

    found = [s for s in candidates if exact(s)]
    if found or len(squeezed) < 4:
        return found
    return [s for s in candidates if fuzz.ratio(squeezed, (s.program or "").lower()) >= 80]


# ----- naming speakers -----

_HEADPHONE_WORDS = ("headphone", "headset", "earphone", "airpods", "buds", "earbuds")


def short_output_name(name: str) -> str:
    """'Speakers (Realtek(R) Audio)' -> 'Speakers'; 'C34H89x (NVIDIA ...)' -> 'C34H89x'."""
    return name.split(" (")[0].strip() or name


def find_output(spoken: str, outputs) -> object | None:
    """The speakers you named: "headphones", "the speakers", "the monitor", a name."""
    wanted = re.sub(r"^(?:the|my) |(?: speakers?| output| audio)$", "", spoken.lower().strip())
    if not outputs or not wanted:
        return None
    names = [(o, o.name.lower()) for o in outputs]
    if any(w in wanted for w in ("headphone", "headset", "earphone", "airpod", "bud")):
        hits = [o for o, n in names if any(w in n for w in _HEADPHONE_WORDS)]
        return hits[0] if len(hits) == 1 else None
    if wanted in ("speaker", "speakers", "laptop", "computer", "pc", "built in"):
        hits = [o for o, n in names if n.startswith("speakers")]
        return hits[0] if len(hits) == 1 else None
    if wanted in ("monitor", "screen", "display", "tv", "hdmi", "big screen"):
        hits = [
            o for o, n in names
            if not n.startswith("speakers") and not any(w in n for w in _HEADPHONE_WORDS)
        ]  # fmt: skip
        return hits[0] if len(hits) == 1 else None
    hits = [o for o, n in names if wanted.replace(" ", "") in n.replace(" ", "")]
    if len(hits) == 1:
        return hits[0]
    scored = sorted(((fuzz.partial_ratio(wanted, n), o) for o, n in names), key=lambda s: -s[0])
    if scored and scored[0][0] >= 80 and (len(scored) == 1 or scored[1][0] < scored[0][0]):
        return scored[0][1]
    return None


def display_at(rect: tuple[int, int, int, int], displays: list):
    """The display holding the middle of a window (left, top, width, height); the nearest one
    if none does."""
    left, top, width, height = rect
    x, y = left + width // 2, top + height // 2

    def distance(d) -> int:
        dl, dt, dw, dh = d.rect
        dx = max(dl - x, 0, x - (dl + dw - 1))
        dy = max(dt - y, 0, y - (dt + dh - 1))
        return dx * dx + dy * dy

    return min(displays, key=distance)
