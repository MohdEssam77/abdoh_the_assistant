"""The four command actions: say, open_url, open_app, run."""

import logging
import os
import shutil
import subprocess
import sys
import webbrowser
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from abdoh.commands.registry import Command

log = logging.getLogger(__name__)


class ActionError(RuntimeError):
    """An action failed; the message is safe to speak."""


def render(text: str, now: datetime | None = None) -> str:
    """Fill in {time} and {date} placeholders."""
    now = now or datetime.now()
    time = f"{now.hour % 12 or 12}:{now.minute:02d} {'AM' if now.hour < 12 else 'PM'}"
    date = f"{now:%A}, {now:%B} {now.day}"
    return text.replace("{time}", time).replace("{date}", date)


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


def run_actions(
    command: Command,
    allow_run: bool = False,
    open_url: Callable[[str], object] = webbrowser.open,
    open_application: Callable[[str], None] = open_app,
    run_shell: Callable[[str], object] = lambda cmd: subprocess.Popen(cmd, shell=True),
) -> list[str]:
    """Run a command's actions in order. Returns the lines to speak."""
    spoken: list[str] = []
    for kind, arg in command.actions:
        log.info("Action %s: %s", kind, arg)
        if kind == "say":
            spoken.append(render(arg))
        elif kind == "open_url":
            if not open_url(arg):
                raise ActionError("I couldn't open that link.")
        elif kind == "open_app":
            open_application(arg)
        elif kind == "run":
            if not allow_run:
                spoken.append("Running programs is turned off. Set allow_run to true in config.")
                continue
            try:
                run_shell(arg)
            except OSError as e:
                raise ActionError("That command failed to start.") from e
    return spoken
