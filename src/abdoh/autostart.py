"""Start Abdoh at login: Task Scheduler (Windows), LaunchAgent (macOS), systemd unit (Linux)."""

import subprocess
import sys
from pathlib import Path

from abdoh.config import DEFAULT_APP_DIR

TASK_NAME = "Abdoh"
PLIST_LABEL = "com.abdoh.agent"
RUN_ARGS = ["-m", "abdoh", "run", "--minimized"]
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def python_for_background() -> str:
    """pythonw.exe on Windows (no console window), else the current interpreter."""
    exe = Path(sys.executable)
    if sys.platform == "win32":
        pythonw = exe.with_name("pythonw.exe")
        if pythonw.exists():
            return str(pythonw)
    return str(exe)


def launch_command(show: bool = False) -> list[str]:
    """How to start Abdoh: the built Abdoh.exe, or pythonw -m abdoh. Hidden unless show."""
    args = ["run", "--show"] if show else ["run", "--minimized"]
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [python_for_background(), "-m", "abdoh", *args]


def windows_command() -> str:
    return subprocess.list2cmdline(launch_command())


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"


def plist_text(python: str, app_dir: Path = DEFAULT_APP_DIR) -> str:
    args = "\n".join(f"    <string>{a}</string>" for a in [python, *RUN_ARGS])
    log = Path.home() / ".abdoh" / "launchd.log"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{PLIST_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
{args}
  </array>
  <key>WorkingDirectory</key>
  <string>{app_dir}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>StandardOutPath</key>
  <string>{log}</string>
  <key>StandardErrorPath</key>
  <string>{log}</string>
</dict>
</plist>
"""


def unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / "abdoh.service"


def unit_text(python: str, app_dir: Path = DEFAULT_APP_DIR) -> str:
    command = " ".join([python, *RUN_ARGS])
    return f"""[Unit]
Description=Abdoh voice assistant
After=graphical-session.target

[Service]
WorkingDirectory={app_dir}
ExecStart={command}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    # No console window flashing when this runs from the tray (pythonw).
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(cmd, capture_output=True, text=True, creationflags=flags, timeout=30)


def is_installed() -> bool:
    """Whether Abdoh is set to start at login."""
    if sys.platform == "win32":
        if _run(["schtasks", "/Query", "/TN", TASK_NAME]).returncode == 0:
            return True
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.QueryValueEx(key, TASK_NAME)
            return True
        except FileNotFoundError:
            return False
    return (plist_path() if sys.platform == "darwin" else unit_path()).exists()


def install() -> str:
    """Install autostart for this OS. Returns a message describing what was done."""
    python = python_for_background()
    if sys.platform == "win32":
        result = _run(
            ["schtasks", "/Create", "/TN", TASK_NAME, "/TR", windows_command(),
             "/SC", "ONLOGON", "/RL", "LIMITED", "/F"]
        )  # fmt: skip
        if result.returncode == 0:
            return f'Installed Task Scheduler task "{TASK_NAME}" (runs at logon).'
        # Creating logon tasks often needs admin rights; the per-user Run key doesn't.
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, TASK_NAME, 0, winreg.REG_SZ, windows_command())
        return (
            "Task Scheduler needs admin rights here "
            f"({result.stderr.strip() or result.stdout.strip()}), so Abdoh was added to your "
            "user's startup programs instead (HKCU Run key)."
        )
    if sys.platform == "darwin":
        path = plist_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        (Path.home() / ".abdoh").mkdir(exist_ok=True)
        path.write_text(plist_text(python), encoding="utf-8")
        _run(["launchctl", "unload", str(path)])
        result = _run(["launchctl", "load", "-w", str(path)])
        if result.returncode != 0:
            raise RuntimeError(f"launchctl load failed: {result.stderr.strip()}")
        return f"Installed LaunchAgent {path}."
    path = unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(unit_text(python), encoding="utf-8")
    _run(["systemctl", "--user", "daemon-reload"])
    result = _run(["systemctl", "--user", "enable", "--now", "abdoh"])
    if result.returncode != 0:
        raise RuntimeError(f"systemctl enable failed: {result.stderr.strip()}")
    return f"Installed systemd user service {path}."


def uninstall() -> str:
    """Remove autostart for this OS. Returns a message describing what was done."""
    if sys.platform == "win32":
        removed = []
        if _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]).returncode == 0:
            removed.append("Task Scheduler task")
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, TASK_NAME)
            removed.append("startup entry")
        except FileNotFoundError:
            pass
        return f"Removed {' and '.join(removed)}." if removed else "Autostart was not installed."
    if sys.platform == "darwin":
        path = plist_path()
        if not path.exists():
            return "Autostart was not installed."
        _run(["launchctl", "unload", "-w", str(path)])
        path.unlink()
        return f"Removed {path}."
    path = unit_path()
    if not path.exists():
        return "Autostart was not installed."
    _run(["systemctl", "--user", "disable", "--now", "abdoh"])
    path.unlink()
    _run(["systemctl", "--user", "daemon-reload"])
    return f"Removed {path}."
