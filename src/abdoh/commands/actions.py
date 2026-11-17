"""Command actions: say, open_url, open_app, play_youtube, media, timer, volume, brightness,
type, run; and Claude's (stricter) actions."""

import logging
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from abdoh.commands.registry import Command

log = logging.getLogger(__name__)


class ActionError(RuntimeError):
    """An action failed; the message is safe to speak."""


def render(
    text: str, now: datetime | None = None, slots: dict[str, str] | None = None, url: bool = False
) -> str:
    """Fill in {time}, {date} and the trigger's {slots} (URL-encoded inside links)."""
    now = now or datetime.now()
    time = f"{now.hour % 12 or 12}:{now.minute:02d} {'AM' if now.hour < 12 else 'PM'}"
    date = f"{now:%A}, {now:%B} {now.day}"
    text = text.replace("{time}", time).replace("{date}", date)
    for name, value in (slots or {}).items():
        text = text.replace("{" + name + "}", quote_plus(value) if url else value)
    return text


def _windows_start_menu_shortcut(name: str) -> Path | None:
    """Find a Start Menu shortcut named like the app (e.g. "Visual Studio Code.lnk")."""
    roots = [
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    ]
    wanted = name.lower()
    for root in roots:
        if root.is_dir():
            for lnk in root.rglob("*.lnk"):
                if lnk.stem.lower() == wanted:
                    return lnk
    return None


def open_app(name: str) -> None:
    """Open an application by name or path, cross-platform."""
    path = Path(name).expanduser()
    try:
        if sys.platform == "win32":
            if path.exists():
                os.startfile(path)  # type: ignore[attr-defined]
            elif lnk := _windows_start_menu_shortcut(name):
                os.startfile(lnk)  # type: ignore[attr-defined]
            else:
                # `start` resolves registered app names like "notepad" or "chrome".
                subprocess.run(["cmd", "/c", "start", "", name], check=True)
        elif sys.platform == "darwin":
            args = ["open", str(path)] if path.exists() else ["open", "-a", name]
            subprocess.run(args, check=True)
        elif path.exists():
            subprocess.Popen(["xdg-open", str(path)])
        elif exe := shutil.which(name):
            subprocess.Popen([exe], start_new_session=True)
        else:
            subprocess.Popen(["gtk-launch", name])
    except (OSError, subprocess.CalledProcessError) as e:
        log.error("Could not open app %r: %s", name, e)
        raise ActionError(f"I couldn't open {name}.") from e


def open_in_editor(path: Path) -> None:
    """Open a text file in the default editor (Notepad on Windows if .yaml has no app)."""
    try:
        if sys.platform == "win32":
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except OSError:
                subprocess.Popen(["notepad", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-t", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError as e:
        log.error("Could not open %s: %s", path, e)
        raise ActionError(f"I couldn't open {Path(path).name}.") from e


def _shell(cmd: str):
    return subprocess.Popen(cmd, shell=True)


def run_action(
    kind: str,
    arg: str,
    allow_run: bool = False,
    open_url: Callable[[str], object] = webbrowser.open,
    open_application: Callable[[str], None] = open_app,
    run_shell: Callable[[str], object] = _shell,
    *,
    computer=None,
    slots: dict[str, str] | None = None,
) -> str | None:
    """Run one action from commands.yaml. Returns text to speak, if any. Raises ActionError."""
    arg = render(arg, slots=slots, url=kind == "open_url")
    log.info("Action %s: %s", kind, arg)
    if kind == "say":
        return arg
    if kind in LOCAL_ONLY and computer is None:
        raise ActionError("That isn't available here.")
    if kind == "media":
        computer.media(arg)
    elif kind == "timer":
        return computer.timer(arg)
    elif kind == "play_youtube":
        return computer.play_youtube(arg) or None
    elif kind == "volume":
        computer.set_volume(percent(arg))
    elif kind == "brightness":
        computer.set_brightness(percent(arg))
    elif kind == "app_volume":
        computer.set_app_volume(*app_and_level(arg))
    elif kind in SYSTEM_ACTIONS:
        return system_action(kind, arg, computer)
    elif kind == "mode":
        modes = getattr(computer, "modes", None)
        if modes is None:
            raise ActionError("Modes aren't available here.")
        return modes.switch(arg)
    elif kind == "type":
        computer.type_text(arg)
    elif kind == "open_url":
        if computer is not None:
            computer.open_url(arg)
        elif not open_url(arg):
            raise ActionError("I couldn't open that link.")
    elif kind == "open_app":
        computer.launch(arg) if computer is not None else open_application(arg)
    elif kind == "run":
        if not allow_run:
            return "Running programs is turned off. Set allow_run to true in config."
        try:
            run_shell(arg)
        except OSError as e:
            raise ActionError("That command failed to start.") from e
    else:
        raise ActionError(f"I don't know the action {kind}.")
    return None


# Settings and controls of the computer, for your commands and modes.
SYSTEM_ACTIONS = (
    "displays", "audio_output", "dark_mode", "power_mode", "power", "keys", "wait",
    "close_app", "focus_app", "window",
)  # fmt: skip
LOCAL_ONLY = (
    "media", "timer", "play_youtube", "volume", "brightness", "app_volume", "type", "mode",
    *SYSTEM_ACTIONS,
)  # fmt: skip
ON_WORDS = {"on": True, "true": True, "yes": True, "dark": True, "off": False, "false": False,
            "no": False, "light": False}  # fmt: skip
MAX_WAIT_SECONDS = 60
WINDOW_WORDS = ("minimize", "maximize", "restore", "close", "desktop", "switch")
WINDOW_PLACES = ("maximized", "left", "right", "keep")


def system_action(kind: str, arg: str, computer) -> str | None:
    """One of SYSTEM_ACTIONS. Returns text to speak, if any. Raises ActionError."""
    arg = arg.strip()
    if kind == "displays":
        computer.screens(arg)
    elif kind == "audio_output":
        computer.set_audio_output(arg)
    elif kind == "dark_mode":
        word = arg.lower()
        on = (not computer.dark_mode()) if word == "toggle" else ON_WORDS.get(word)
        if on is None:
            raise ActionError("dark_mode is on, off or toggle.")
        computer.set_dark_mode(on)
    elif kind == "power_mode":
        computer.set_power_mode(arg.lower())
    elif kind == "power":
        computer.power(arg)
    elif kind == "keys":
        computer.press_keys(arg)
    elif kind == "wait":
        time.sleep(wait_seconds(arg))
    elif kind == "close_app":
        computer.close_app(arg)
    elif kind == "focus_app":
        computer.focus_app(arg)
    elif kind == "window":
        place = parse_window(arg)
        if isinstance(place, str):
            computer.window(place)
        else:
            computer.move_window(*place)
    return None


def wait_seconds(text: str) -> float:
    from abdoh.computer import parse_duration

    found = parse_duration(text)
    seconds = found[0] if found else None
    if seconds is None:
        try:
            seconds = float(text.lower().replace("seconds", "").replace("second", "").strip())
        except ValueError as e:
            raise ActionError(f"wait needs a time like '2 seconds', not '{text}'.") from e
    if not 0 <= seconds <= MAX_WAIT_SECONDS:
        raise ActionError(f"wait is at most {MAX_WAIT_SECONDS} seconds.")
    return seconds


def parse_window(text: str):
    """'minimize' -> 'minimize'; 'Chrome to 2 left' -> ('Chrome', '2', 'left');
    'this to the laptop' -> (None, 'the laptop', 'maximized'). Raises ActionError."""
    words = " ".join(text.lower().split())
    if words in WINDOW_WORDS:
        return words
    app, sep, rest = words.partition(" to ")
    if not sep or not rest:
        raise ActionError("window is like 'Chrome to 2 maximized' or 'minimize'.")
    how = "maximized"
    last = rest.rsplit(" ", 1)
    if len(last) == 2 and last[1] in WINDOW_PLACES:
        rest, how = last
    app = None if app in ("this", "it", "this window", "the window") else app
    return app, rest, how


def app_and_level(text: str) -> tuple[str, int]:
    """'browser | 30', 'browser 30' or 'Spotify 20%' -> ('browser', 30). Raises ActionError."""
    app, sep, level = str(text).rpartition("|")
    if not sep:
        app, _, level = str(text).strip().rpartition(" ")
    if not app.strip():
        raise ActionError(f"'{text}' needs an app and a volume, like: browser 30.")
    return app.strip(), percent(level)


def percent(text: str) -> int:
    """'70', '70%' or '70 percent' -> 70. Raises ActionError."""
    try:
        value = float(str(text).lower().replace("percent", "").replace("%", "").strip())
    except ValueError as e:
        raise ActionError(f"{text} isn't a number from 0 to 100.") from e
    if not 0 <= value <= 100:
        raise ActionError(f"{text} isn't a number from 0 to 100.")
    return round(value)


def run_actions(
    command: Command,
    allow_run: bool = False,
    open_url: Callable[[str], object] = webbrowser.open,
    open_application: Callable[[str], None] = open_app,
    run_shell: Callable[[str], object] = _shell,
    *,
    computer=None,
    slots: dict[str, str] | None = None,
) -> list[str]:
    """Run a command's actions in order. Returns the lines to speak."""
    spoken: list[str] = []
    for kind, arg in command.actions:
        text = run_action(
            kind,
            arg,
            allow_run,
            open_url,
            open_application,
            run_shell,
            computer=computer,
            slots=slots,
        )
        if text:
            spoken.append(text)
    return spoken


def claude_action(kind: str, arg: str, computer) -> None:
    """Run an action Claude asked for, with stricter rules than your own commands: only web
    links, and only apps from the installed-app list (never a path or a command). Raises
    ActionError."""
    log.info("Claude action %s: %s", kind, arg)
    if computer is None:
        raise ActionError("I can't do that here.")
    if kind == "open_url":
        if not arg.lower().startswith(("http://", "https://")):
            raise ActionError("I can only open web links.")
        computer.open_url(arg)
    elif kind == "open_app":
        computer.open_app(arg)
    elif kind == "play_youtube":
        computer.play_youtube(arg)
    elif kind == "media":
        computer.media(arg)
    elif kind == "timer":
        computer.timer(arg)
    elif kind == "volume":
        computer.set_volume(percent(arg))
    elif kind == "brightness":
        computer.set_brightness(percent(arg))
    elif kind == "app_volume":
        computer.set_app_volume(*app_and_level(arg))
    elif kind == "remind":
        computer.remind(arg)
    elif kind == "note":
        computer.notes.add(arg)
    elif kind == "mode":
        modes = getattr(computer, "modes", None)
        if modes is None:
            raise ActionError("Modes aren't available here.")
        modes.switch(arg)
    elif kind == "displays":
        computer.screens(arg)
    elif kind == "audio_output":
        computer.set_audio_output(arg)
    elif kind == "dark_mode":
        on = ON_WORDS.get(arg.strip().lower())
        if on is None:
            raise ActionError("dark_mode is on or off.")
        computer.set_dark_mode(on)
    else:
        raise ActionError(f"I can't do {kind}.")
