"""Windows settings and controls Krekos can change: dark mode, the power mode, sleep and
shutdown, key presses, other programs' windows, folders, and the clipboard.

Small functions over the Windows API (ctypes, winreg) that `Computer` reaches through this
module, so tests replace the module with a fake. The parsers are plain Python.
"""

import logging
import os
import re
import subprocess
import sys
from pathlib import Path

from abdoh.commands.actions import ActionError
from abdoh.hotkey import KEYS, MODIFIERS

log = logging.getLogger(__name__)

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
WINDOWS_ONLY = "That only works on Windows for now."


def _windows() -> None:
    if sys.platform != "win32":
        raise ActionError(WINDOWS_ONLY)


# ----- dark mode -----

PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def dark_mode() -> bool:
    _windows()
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE) as key:
        return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0


def set_dark_mode(on: bool) -> None:
    _windows()
    import ctypes
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE, 0, winreg.KEY_SET_VALUE) as key:
        for name in ("AppsUseLightTheme", "SystemUsesLightTheme"):
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, 0 if on else 1)
    # Tell open windows (the taskbar, Explorer, apps) the colors changed.
    result = ctypes.c_size_t()
    ctypes.windll.user32.SendMessageTimeoutW(
        0xFFFF, 0x001A, 0, "ImmersiveColorSet", 0x0002, 2000, ctypes.byref(result)
    )  # HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG


# ----- night light -----
#
# Windows keeps night light's state in an undocumented binary value. Its layout (checked on
# Windows 11, build 26200, both ways): a fixed header, the time it last changed (Unix seconds
# as a 5-byte varint), a block that says on or off, and three zero bytes. Krekos only writes
# when the value has exactly this layout; otherwise it opens Windows' night light settings.

NIGHT_LIGHT_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\CloudStore\Store\DefaultAccount\Current"
    r"\default$windows.data.bluelightreduction.bluelightreductionstate"
    r"\windows.data.bluelightreduction.bluelightreductionstate"
)
_NL_HEAD = bytes.fromhex("43420100 0a020100 2a06".replace(" ", ""))
_NL_MID = bytes.fromhex("2a2b0e")
_NL_BLOCK = bytes.fromhex("43420100")
_NL_ON = bytes.fromhex("1000")
NIGHT_LIGHT_SETTINGS = "ms-settings:nightlight"


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte, value = value & 0x7F, value >> 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def parse_night_light(data: bytes) -> bool:
    """Is night light on in this value? Raises ValueError for a layout Krekos doesn't know."""
    if not data.startswith(_NL_HEAD) or len(data) < 27 or data[15:18] != _NL_MID:
        raise ValueError("unknown night light layout")
    size = data[18]
    block = data[19 : 19 + size]
    if len(block) != size or not block.startswith(_NL_BLOCK) or data[19 + size :] != b"\0\0\0":
        raise ValueError("unknown night light layout")
    return block[4:6] == _NL_ON


def night_light_value(data: bytes, on: bool, now: float) -> bytes:
    """The value with night light on or off, stamped with `now` so Windows notices it."""
    if parse_night_light(data) == on:
        return data
    stamp = _varint(int(now))
    if len(stamp) != 5:
        raise ValueError("unexpected time stamp size")
    # As Windows writes it, both ways: the on flag (only when on), then since when it changed
    # (a FILETIME: 100 ns since 1601). Without that time Windows ignores the change.
    since = _varint(int((now + 11_644_473_600) * 10_000_000))
    flag = _NL_ON if on else b""
    block = _NL_BLOCK + flag + bytes.fromhex("d00a02c614") + since + b"\0"
    return _NL_HEAD + stamp + _NL_MID + bytes([len(block)]) + block + b"\0\0\0"


def _night_light_data() -> bytes:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, NIGHT_LIGHT_KEY) as key:
        return winreg.QueryValueEx(key, "Data")[0]


def night_light() -> bool:
    _windows()
    try:
        return parse_night_light(_night_light_data())
    except (OSError, ValueError) as e:
        raise ActionError("I can't tell whether night light is on.") from e


def set_night_light(on: bool) -> None:
    _windows()
    import time
    import winreg

    try:
        value = night_light_value(_night_light_data(), on, time.time())
    except (OSError, ValueError) as e:
        log.warning("Night light: %s", e)
        os.startfile(NIGHT_LIGHT_SETTINGS)  # type: ignore[attr-defined]
        message = "I can't switch night light on this Windows; I opened its settings."
        raise ActionError(message) from e
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, NIGHT_LIGHT_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "Data", 0, winreg.REG_BINARY, value)


# ----- the power mode (Settings > System > Power) -----

POWER_MODES = {
    "best_performance": "{DED574B5-45A0-4F42-8737-46345C09C238}",
    "balanced": "{00000000-0000-0000-0000-000000000000}",
    "efficiency": "{961CC777-2547-4F9D-8174-7D86181B8A7A}",
}
POWER_NAMES = {
    "best_performance": "best performance",
    "balanced": "balanced",
    "efficiency": "best power efficiency",
}


def power_mode() -> str:
    _windows()
    import ctypes

    from comtypes import GUID

    guid = GUID()
    if ctypes.windll.powrprof.PowerGetEffectiveOverlayScheme(ctypes.byref(guid)):
        return "balanced"
    found = str(guid).upper()
    return next((name for name, g in POWER_MODES.items() if g == found), "balanced")


def set_power_mode(name: str) -> None:
    _windows()
    if name not in POWER_MODES:
        raise ActionError(f"The power mode is one of {', '.join(POWER_MODES)}.")
    import ctypes

    from comtypes import GUID

    if ctypes.windll.powrprof.PowerSetActiveOverlayScheme(ctypes.byref(GUID(POWER_MODES[name]))):
        raise ActionError("Windows didn't change the power mode.")


# ----- sleep, screens off, shutdown -----


def sleep() -> None:
    _windows()
    import ctypes

    ctypes.windll.powrprof.SetSuspendState(0, 0, 0)


def screens_off() -> None:
    """Every screen goes dark until the mouse moves or a key is pressed."""
    _windows()
    import ctypes

    # HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, 2 = off. Posted: a hung window can't block it.
    ctypes.windll.user32.PostMessageW(0xFFFF, 0x0112, 0xF170, 2)


def shutdown(seconds: int, restart: bool = False) -> None:
    _windows()
    flag = "/r" if restart else "/s"
    subprocess.run(
        ["shutdown", flag, "/t", str(max(0, int(seconds)))],
        creationflags=NO_WINDOW,
        check=True,
        capture_output=True,
    )


def cancel_shutdown() -> bool:
    """False if no shutdown was waiting."""
    _windows()
    done = subprocess.run(["shutdown", "/a"], creationflags=NO_WINDOW, capture_output=True)
    return done.returncode == 0


# ----- pressing keys -----

EXTRA_KEYS = {
    "printscreen": 0x2C, "prtsc": 0x2C, "capslock": 0x14, "numlock": 0x90, "pause": 0x13,
    "volumemute": 0xAD, "volumedown": 0xAE, "volumeup": 0xAF, "playpause": 0xB3,
    "nexttrack": 0xB0, "prevtrack": 0xB1, "comma": 0xBC, "period": 0xBE, "minus": 0xBD,
    "plus": 0xBB, "apps": 0x5D, "menu": 0x5D,
}  # fmt: skip
MODIFIER_KEYS = {"ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B}


def parse_keys(text: str) -> list[tuple[list[int], int]]:
    """'ctrl+shift+esc, win+d' -> [([modifier keys], key), ...]. Raises ValueError."""
    combos = []
    for part in re.split(r"[,;]\s*|\s+then\s+|\s+(?=\S+\+)", text.strip()):
        names = [n.strip().lower() for n in part.split("+") if n.strip()]
        if not names:
            continue
        *mods, key = names
        held = []
        for mod in mods:
            if mod not in MODIFIERS:
                raise ValueError(f"'{mod}' isn't ctrl, alt, shift or win.")
            held.append(MODIFIER_KEYS[mod])
        combos.append((held, _key_code(key)))
    if not combos:
        raise ValueError("Which keys?")
    return combos


def _key_code(key: str) -> int:
    if key in MODIFIER_KEYS:  # "win" alone opens Start
        return MODIFIER_KEYS[key]
    if len(key) == 1 and key.isascii() and key.isalnum():
        return ord(key.upper())
    if key in KEYS:
        return KEYS[key]
    if key in EXTRA_KEYS:
        return EXTRA_KEYS[key]
    f_key = re.fullmatch(r"f([1-9]|1\d|2[0-4])", key)
    if f_key:
        return 0x70 + int(f_key.group(1)) - 1
    raise ValueError(f"I don't know the key '{key}'.")


def press_keys(text: str, send=None) -> None:
    """Press key combinations one after the other, like a person would."""
    _windows()
    from abdoh.desk import KEYEVENTF_KEYUP, _send_keys

    send = send or _send_keys
    try:
        combos = parse_keys(text)
    except ValueError as e:
        raise ActionError(str(e)) from e
    for held, key in combos:
        down = [(k, 0, 0) for k in held] + [(key, 0, 0)]
        up = [(key, 0, KEYEVENTF_KEYUP)] + [(k, 0, KEYEVENTF_KEYUP) for k in reversed(held)]
        send(down + up)


# ----- other programs' windows -----


def app_windows(name: str) -> list[tuple[int, str, str]]:
    """Visible windows of a program you named: (handle, title, program), front first."""
    _windows()
    import ctypes
    from ctypes import wintypes

    from abdoh.winaudio import process_name

    user32 = ctypes.windll.user32
    wanted = re.sub(r"^(?:the|my) |(?: app| window| program)$", "", name.lower().strip())
    squeezed = wanted.replace(" ", "")
    own = os.getpid()
    found: list[tuple[int, str, str]] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindowTextLengthW(hwnd) == 0:
            return True
        if user32.GetWindowLongW(hwnd, -20) & 0x80:  # tool windows
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == own:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        program = process_name(pid.value)
        if matches_window(squeezed, program, buffer.value):
            found.append((hwnd, buffer.value, program))
        return True

    user32.EnumWindows(callback_type(visit), 0)
    return found


def matches_window(wanted: str, program: str, title: str) -> bool:
    """Does a spoken program name ("vs code", "chrome") mean this window?"""
    from abdoh.computer import APP_ALIASES

    wanted = wanted.replace(" ", "")
    if not wanted:
        return False
    program = program.lower()
    aliases = {
        "vscode": ("code",), "visualstudiocode": ("code",), "code": ("code",),
        "word": ("winword",), "excel": ("excel",), "powerpoint": ("powerpnt",),
        "fileexplorer": ("explorer",), "explorer": ("explorer",), "files": ("explorer",),
    }  # fmt: skip
    if program in aliases.get(wanted, ()) or program in APP_ALIASES.get(wanted, ()):
        return True
    if len(wanted) >= 3 and (wanted == program or wanted in program):
        return True
    return len(wanted) >= 4 and wanted in title.lower().replace(" ", "")


def close_app(name: str) -> int:
    """Ask every window of a program to close (it may still ask to save). How many."""
    windows = app_windows(name)
    import ctypes

    for hwnd, _, _ in windows:
        ctypes.windll.user32.PostMessageW(hwnd, 0x10, 0, 0)  # WM_CLOSE
    return len(windows)


def focus_window(hwnd: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    # Windows only lets the program in front hand over the focus: a tap of Alt counts.
    from abdoh.desk import KEYEVENTF_KEYUP, VK_MENU, _send_keys

    _send_keys([(VK_MENU, 0, 0), (VK_MENU, 0, KEYEVENTF_KEYUP)])
    user32.SetForegroundWindow(hwnd)


def focus_app(name: str) -> str:
    """Bring a program's window to the front. Returns its title."""
    windows = app_windows(name)
    if not windows:
        raise ActionError(f"{name.strip().capitalize()} isn't open.")
    hwnd, title, _ = windows[0]
    focus_window(hwnd)
    return title


def front_window_handle() -> int | None:
    from abdoh.claude.screen import front_window_handle as find

    return find()


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """A window's (left, top, width, height)."""
    import ctypes
    from ctypes import wintypes

    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def move_window(hwnd: int, rect: tuple[int, int, int, int], how: str = "maximized") -> None:
    """Put a window on the monitor at `rect` (left, top, width, height): maximized, on its
    left or right half, or just inside it ("keep")."""
    import ctypes
    from ctypes import wintypes

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]  # fmt: skip

    user32 = ctypes.windll.user32
    left, top, width, height = rect
    center = wintypes.POINT(left + width // 2, top + height // 2)
    user32.MonitorFromPoint.restype = ctypes.c_void_p
    monitor = user32.MonitorFromPoint(center, 2)  # MONITOR_DEFAULTTONEAREST
    info = MonitorInfo()
    info.cbSize = ctypes.sizeof(MonitorInfo)
    user32.GetMonitorInfoW(ctypes.c_void_p(monitor), ctypes.byref(info))
    work = info.rcWork
    w, h = work.right - work.left, work.bottom - work.top
    user32.ShowWindow(hwnd, 9)  # restore first: a maximized window won't move
    if how in ("left", "right"):
        x = work.left if how == "left" else work.left + w // 2
        user32.SetWindowPos(hwnd, 0, x, work.top, w // 2, h, 0x0004 | 0x0040)
        return
    user32.SetWindowPos(hwnd, 0, work.left + 40, work.top + 40, w * 3 // 4, h * 3 // 4, 0x0044)
    if how == "maximized":
        user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE


# ----- folders -----

FOLDERS = {
    "downloads": "Downloads", "documents": "Documents", "desktop": "Desktop",
    "pictures": "Pictures", "music": "Music", "videos": "Videos",
}  # fmt: skip


def folder(name: str) -> Path:
    """The user's folder for a name ("downloads", "screenshots")."""
    from abdoh.claude.code import user_folders

    name = name.lower().strip()
    known = user_folders()
    if name == "screenshots":
        return known.get("Pictures", Path.home() / "Pictures") / "Screenshots"
    if name not in FOLDERS:
        raise ActionError(f"I don't know the folder '{name}'.")
    return known.get(FOLDERS[name], Path.home() / FOLDERS[name])


def newest_file(where: Path) -> Path | None:
    """The newest file in a folder (not in its subfolders), or None."""
    try:
        files = [p for p in Path(where).iterdir() if p.is_file() and not p.name.startswith(".")]
    except OSError:
        return None
    files = [p for p in files if not p.name.lower().endswith((".crdownload", ".part", ".tmp"))]
    return max(files, key=lambda p: p.stat().st_mtime, default=None)


def open_path(path: Path) -> None:
    _windows()
    if not Path(path).exists():
        raise ActionError("That folder isn't there.")
    os.startfile(str(path))  # type: ignore[attr-defined]


# ----- the clipboard -----


def get_clipboard() -> str:
    """The text on the clipboard ("" if there is none)."""
    _windows()
    import ctypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    if not _open_clipboard(user32):
        raise ActionError("The clipboard is busy. Try again in a moment.")
    try:
        handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(pointer) if pointer else ""
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_clipboard(text: str) -> None:
    _windows()
    import ctypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    data = (text + "\0").encode("utf-16-le")
    if not _open_clipboard(user32):
        raise ActionError("The clipboard is busy. Try again in a moment.")
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        pointer = kernel32.GlobalLock(handle)
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        user32.SetClipboardData(13, handle)  # the clipboard owns it now
    finally:
        user32.CloseClipboard()


def _open_clipboard(user32) -> bool:
    import time

    for _ in range(10):  # another program may hold it for a moment
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.05)
    return False
