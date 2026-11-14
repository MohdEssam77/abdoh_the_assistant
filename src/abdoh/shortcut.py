"""A Start Menu shortcut for Abdoh, with its own icon (Windows)."""

import os
import subprocess
import sys
from pathlib import Path

from abdoh.autostart import launch_command
from abdoh.config import DEFAULT_APP_DIR

STATE_DIR = Path.home() / ".abdoh"
ICON = STATE_DIR / "abdoh.ico"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Values are passed in environment variables, so paths with spaces or quotes are safe.
_SCRIPT = (
    "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:ABDOH_LNK); "
    "$s.TargetPath = $env:ABDOH_TARGET; $s.Arguments = $env:ABDOH_ARGS; "
    "$s.WorkingDirectory = $env:ABDOH_DIR; $s.IconLocation = $env:ABDOH_ICON; "
    "$s.Description = 'Abdoh, your voice assistant'; $s.Save()"
)


def start_menu_shortcut() -> Path:
    programs = (
        Path(os.environ.get("APPDATA", Path.home())) / "Microsoft/Windows/Start Menu/Programs"
    )
    return programs / "Abdoh.lnk"


def make_icon(path: Path = ICON) -> Path:
    from abdoh.ui.tray import GREEN, icon_image

    path.parent.mkdir(parents=True, exist_ok=True)
    icon_image(GREEN, size=256).save(path, sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    return path


def create_shortcut(
    path: Path, command: list[str], workdir: Path, icon: Path, run=subprocess.run
) -> Path:
    env = {
        **os.environ,
        "ABDOH_LNK": str(path),
        "ABDOH_TARGET": command[0],
        "ABDOH_ARGS": subprocess.list2cmdline(command[1:]),
        "ABDOH_DIR": str(workdir),
        "ABDOH_ICON": str(icon),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _SCRIPT],
        env=env,
        check=True,
        capture_output=True,
        creationflags=NO_WINDOW,
    )
    return path


def install(login: bool = False, autostart=None, run=subprocess.run) -> list[str]:
    """Add Abdoh to the Start Menu (and optionally start it at login). Returns what was done."""
    if autostart is None:
        from abdoh import autostart
    if sys.platform != "win32":
        done = ["The Start Menu shortcut is Windows-only."]
    else:
        command = launch_command(show=True)
        lnk = create_shortcut(start_menu_shortcut(), command, DEFAULT_APP_DIR, make_icon(), run)
        done = [f"Added Abdoh to the Start Menu ({lnk})."]
    if login:
        done.append(autostart.install())
    return done


def uninstall(autostart=None) -> list[str]:
    if autostart is None:
        from abdoh import autostart
    done = []
    lnk = start_menu_shortcut()
    if lnk.exists():
        lnk.unlink()
        done.append("Removed the Start Menu shortcut.")
    done.append(autostart.uninstall())
    return done
