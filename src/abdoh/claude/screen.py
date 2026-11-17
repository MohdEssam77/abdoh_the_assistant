"""Screenshots for Claude: the monitor you are working on, as a downscaled PNG.

"The screen you're using" is the monitor that holds the window in front. Abdoh's own window
doesn't count (you may have just typed into it): the window behind it does.
"""

import io
import logging
import os
import sys
from dataclasses import dataclass

from PIL import Image

log = logging.getLogger(__name__)

MAX_SIDE = 2000  # text on a wide (3440 px) monitor stays readable


class ScreenCaptureError(RuntimeError):
    """The screen could not be captured; the message is safe to speak."""


@dataclass(frozen=True)
class FrontWindow:
    """The window you are working in: its title, its program, and where it is on screen."""

    title: str = ""
    program: str = ""
    rect: tuple[int, int, int, int] | None = None  # left, top, right, bottom

    @property
    def center(self) -> tuple[int, int] | None:
        if self.rect is None:
            return None
        left, top, right, bottom = self.rect
        return (left + right) // 2, (top + bottom) // 2


def downscale(img: Image.Image, max_side: int = MAX_SIDE) -> Image.Image:
    """Shrink so the long side is at most max_side (never enlarges)."""
    scale = max_side / max(img.size)
    if scale >= 1:
        return img
    return img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)


def is_all_black(img: Image.Image) -> bool:
    return img.convert("L").getextrema()[1] < 10


def to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def pick_monitor(monitors: list[dict], point: tuple[int, int] | None) -> dict:
    """The monitor (mss's dicts: left, top, width, height) that holds `point`; the nearest one
    if none does; the primary (the first) without a point."""
    if point is None or not monitors:
        return monitors[0]
    x, y = point

    def distance(m: dict) -> int:
        dx = max(m["left"] - x, 0, x - (m["left"] + m["width"] - 1))
        dy = max(m["top"] - y, 0, y - (m["top"] + m["height"] - 1))
        return dx * dx + dy * dy

    return min(monitors, key=distance)


# ----- Windows: the window in front -----


def front_window() -> FrontWindow:
    """The window you're working in (not Abdoh's own). Empty if it can't tell."""
    if sys.platform != "win32":
        return FrontWindow()
    try:
        return _front_window_windows()
    except Exception:
        log.debug("Couldn't find the window in front", exc_info=True)
        return FrontWindow()


def _front_window_windows() -> FrontWindow:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    own = os.getpid()

    def usable(hwnd) -> bool:
        if not hwnd or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return False
        if user32.GetWindowTextLengthW(hwnd) == 0:
            return False
        if user32.GetWindowLongW(hwnd, -20) & 0x80:  # GWL_EXSTYLE, WS_EX_TOOLWINDOW
            return False
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == own:
            return False
        cloaked = ctypes.c_int(0)  # hidden by Windows (another virtual desktop, a stored app)
        ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4)
        return not cloaked.value

    chosen = user32.GetForegroundWindow()
    if not usable(chosen):
        chosen = None
        found = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def visit(hwnd, _):
            if usable(hwnd):
                found.append(hwnd)
                return False  # windows come front to back: the first one is it
            return True

        user32.EnumWindows(callback_type(visit), 0)
        chosen = found[0] if found else None
    if chosen is None:
        return FrontWindow()
    length = user32.GetWindowTextLengthW(chosen)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(chosen, buffer, length + 1)
    rect = wintypes.RECT()
    user32.GetWindowRect(chosen, ctypes.byref(rect))
    return FrontWindow(
        buffer.value, _program(chosen), (rect.left, rect.top, rect.right, rect.bottom)
    )


def _program(hwnd) -> str:
    """The program a window belongs to ("chrome"), or ""."""
    import ctypes
    from ctypes import wintypes

    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFO
    if not process:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not ctypes.windll.kernel32.QueryFullProcessImageNameW(
            process, 0, buffer, ctypes.byref(size)
        ):
            return ""
        name = os.path.basename(buffer.value)
        return name[:-4] if name.lower().endswith(".exe") else name
    finally:
        ctypes.windll.kernel32.CloseHandle(process)


# ----- taking the picture -----


def grab(which: str = "active", window: FrontWindow | None = None) -> Image.Image:
    """A picture of the screen you're using ("active"), or of all of them ("all")."""
    import mss

    with mss.MSS() as sct:  # DPI-aware from here on, so window positions match the monitors
        if which == "all":
            monitor = sct.monitors[0]
        else:
            window = window or front_window()
            monitor = pick_monitor(sct.monitors[1:], window.center)
        shot = sct.grab(monitor)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def capture_screen(grab=grab, which: str = "active") -> bytes:
    """Screenshot of the screen you're using as PNG bytes, long side <= MAX_SIDE px."""
    try:
        img = grab(which)
    except Exception as e:
        log.exception("Screen capture failed")
        raise ScreenCaptureError("I couldn't capture your screen.") from e
    if is_all_black(img):
        hint = (
            " On a Mac, give Screen Recording permission to Terminal or Python in System Settings."
            if sys.platform == "darwin"
            else ""
        )
        raise ScreenCaptureError("Your screenshot came out completely black." + hint)
    return to_png(downscale(img))
