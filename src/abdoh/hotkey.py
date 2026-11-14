"""A global hotkey: press it anywhere to talk to Abdoh, or to stop it talking.

Windows only for now (Win32 RegisterHotKey through ctypes, no extra dependency).
"""

import logging
import re
import sys
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)

MODIFIERS = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002, "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000  # holding the keys down doesn't repeat
KEYS = {
    "space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B, "backspace": 0x08,
    "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23, "pageup": 0x21,
    "pagedown": 0x22, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
}  # fmt: skip
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
HOTKEY_ID = 1


def parse_hotkey(text: str) -> tuple[int, int]:
    """'ctrl+alt+space' -> (modifier flags, virtual-key code). Raises ValueError."""
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    if not parts:
        raise ValueError("The hotkey is empty.")
    *mods, key = parts
    flags = 0
    for mod in mods:
        if mod not in MODIFIERS:
            raise ValueError(f"Unknown key in hotkey: {mod}")
        flags |= MODIFIERS[mod]
    if not flags:
        raise ValueError("A hotkey needs ctrl, alt, shift or win, so normal typing isn't taken.")
    if len(key) == 1 and key.isascii() and key.isalnum():
        return flags, ord(key.upper())
    if key in KEYS:
        return flags, KEYS[key]
    f_key = re.fullmatch(r"f([1-9]|1\d|2[0-4])", key)
    if f_key:
        return flags, 0x70 + int(f_key.group(1)) - 1
    raise ValueError(f"Unknown key in hotkey: {key}")


class Hotkey:
    """Calls on_press() (on its own thread) each time the hotkey is pressed."""

    def __init__(self, text: str, on_press: Callable[[], None]):
        self.text = text
        self.flags, self.key = parse_hotkey(text)
        self._on_press = on_press
        self._thread_id: int | None = None

    def start(self) -> bool:
        """Start listening for the hotkey. False if this OS isn't supported."""
        if sys.platform != "win32":
            log.info("The hotkey only works on Windows for now.")
            return False
        threading.Thread(target=self._loop, name="abdoh-hotkey", daemon=True).start()
        return True

    def _loop(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, HOTKEY_ID, self.flags | MOD_NOREPEAT, self.key):
            log.warning("Couldn't use the hotkey %s (another app may have it).", self.text)
            return
        log.info("Hotkey %s ready", self.text)
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    try:
                        self._on_press()
                    except Exception:
                        log.exception("Error handling the hotkey")
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)

    def stop(self) -> None:
        if self._thread_id is not None and sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
