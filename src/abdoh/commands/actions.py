"""Command actions: say, open_url, open_app, run, media, timer; and Claude's (stricter) actions."""

import logging
import os
import shutil
import subprocess
import sys
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
    if kind in ("media", "timer") and computer is None:
        raise ActionError("That isn't available here.")
    if kind == "media":
        computer.media(arg)
    elif kind == "timer":
        return computer.timer(arg)
    elif kind == "open_url":
        if not open_url(arg):
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
    elif kind == "media":
        computer.media(arg)
    elif kind == "timer":
        computer.timer(arg)
    else:
        raise ActionError(f"I can't do {kind}.")
