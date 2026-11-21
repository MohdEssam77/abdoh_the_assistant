"""More things Krekos does by itself, without Claude: screen brightness, the battery, typing what
you dictate, the window in front, screenshots, notes, reminders and quick maths.

The Windows calls are small functions that `Computer` reaches through this module, so tests
replace the module with a fake. Notes, reminders and the parsers are plain Python.
"""

import ast
import json
import logging
import operator
import re
import subprocess
import sys
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from abdoh.commands.actions import ActionError

log = logging.getLogger(__name__)

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# ----- screen brightness (the laptop's own screen) -----

_BRIGHTNESS = "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness)"
_SET_BRIGHTNESS = (
    "$m = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods; "
    "Invoke-CimMethod -InputObject $m -MethodName WmiSetBrightness "
    "-Arguments @{{Timeout = 1; Brightness = {percent}}} | Out-Null"
)
NO_BRIGHTNESS = "I can't change this screen's brightness."


def _powershell(script: str, run=subprocess.run) -> str:
    if sys.platform != "win32":
        raise ActionError("That only works on Windows for now.")
    result = run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=15,
        creationflags=NO_WINDOW,
    )
    if result.returncode != 0:
        raise OSError(result.stderr.strip() or "PowerShell failed")
    return result.stdout.strip()


def get_brightness(run=subprocess.run) -> int:
    try:
        return int(_powershell(f"{_BRIGHTNESS}.CurrentBrightness", run).split()[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError) as e:
        raise ActionError(NO_BRIGHTNESS) from e  # e.g. an external monitor


def set_brightness(percent: float, run=subprocess.run) -> int:
    percent = max(0, min(100, round(percent)))
    try:
        _powershell(_SET_BRIGHTNESS.format(percent=percent), run)
    except (OSError, subprocess.SubprocessError) as e:
        raise ActionError(NO_BRIGHTNESS) from e
    return percent


# ----- battery -----


def battery() -> tuple[int, bool] | None:
    """(percent, plugged in), or None if this computer has no battery."""
    if sys.platform != "win32":
        return None
    import ctypes

    class Status(ctypes.Structure):  # SYSTEM_POWER_STATUS
        _fields_ = [
            ("ac", ctypes.c_ubyte),
            ("flag", ctypes.c_ubyte),
            ("percent", ctypes.c_ubyte),
            ("saver", ctypes.c_ubyte),
            ("seconds", ctypes.c_ulong),
            ("full_seconds", ctypes.c_ulong),
        ]

    status = Status()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return None
    if status.flag & 128 or status.percent > 100:  # no battery / unknown
        return None
    return int(status.percent), status.ac == 1


# ----- typing into the app in front -----

KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x2, 0x4
VK_RETURN, VK_TAB, VK_MENU, VK_LWIN = 0x0D, 0x09, 0x12, 0x5B


def _send_keys(keys: list[tuple[int, int, int]]) -> None:
    """Send keyboard events: (virtual key, unicode character, flags) each."""
    import ctypes
    from ctypes import wintypes

    extra = ctypes.c_size_t

    class KeyboardInput(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", extra),
        ]

    class MouseInput(ctypes.Structure):  # only here so the union has Windows' size
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", extra),
        ]

    class Union(ctypes.Union):
        _fields_ = [("ki", KeyboardInput), ("mi", MouseInput)]

    class Input(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", Union)]

    events = (Input * len(keys))()
    for event, (key, char, flags) in zip(events, keys, strict=True):
        event.type = 1  # INPUT_KEYBOARD
        event.u.ki = KeyboardInput(key, char, flags, 0, 0)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    if user32.SendInput(len(keys), events, ctypes.sizeof(Input)) != len(keys):
        raise ActionError("I couldn't type that here.")


def key_events(text: str) -> list[tuple[int, int, int]]:
    """The key presses that type `text`: letters as Unicode, new lines as Enter."""
    keys = []
    for char in text:
        if char == "\n":
            keys += [(VK_RETURN, 0, 0), (VK_RETURN, 0, KEYEVENTF_KEYUP)]
            continue
        units = char.encode("utf-16-le")
        for i in range(0, len(units), 2):
            unit = int.from_bytes(units[i : i + 2], "little")
            keys += [(0, unit, KEYEVENTF_UNICODE), (0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]
    return keys


def type_text(text: str) -> None:
    if sys.platform != "win32":
        raise ActionError("Typing for you only works on Windows for now.")
    if text:
        _send_keys(key_events(text))


# ----- the window in front -----

WINDOW_ACTIONS = ("minimize", "maximize", "restore", "close", "desktop", "switch")
_SHOW = {"minimize": 6, "maximize": 3, "restore": 9}  # ShowWindow commands
WM_CLOSE = 0x10


def window(action: str) -> None:
    if action not in WINDOW_ACTIONS:
        raise ActionError(f"I don't know the window action {action}.")
    if sys.platform != "win32":
        raise ActionError("Window controls only work on Windows for now.")
    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    if action == "desktop":  # Win+D
        down_up = [(VK_LWIN, 0, 0), (ord("D"), 0, 0), (ord("D"), 0, 2), (VK_LWIN, 0, 2)]
        return _send_keys(down_up)
    if action == "switch":  # Alt+Tab
        return _send_keys([(VK_MENU, 0, 0), (VK_TAB, 0, 0), (VK_TAB, 0, 2), (VK_MENU, 0, 2)])
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    handle = user32.GetForegroundWindow()
    if not handle:
        raise ActionError("There's no window in front.")
    if action == "close":
        user32.PostMessageW(ctypes.c_void_p(handle), WM_CLOSE, 0, 0)
    else:
        user32.ShowWindow(ctypes.c_void_p(handle), _SHOW[action])


# ----- screenshots -----


def save_screenshot(folder: Path, capture: Callable[[], bytes] | None = None, now=None) -> Path:
    """Save a picture of the screen in `folder` and return its path."""
    if capture is None:
        from abdoh.claude.screen import capture_screen as capture
    now = now or datetime.now()
    folder = Path(folder)
    try:
        png = capture()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"Krekos {now:%Y-%m-%d %H.%M.%S}.png"
        path.write_bytes(png)
    except ActionError:
        raise
    except Exception as e:
        log.error("Couldn't save a screenshot: %s", e)
        raise ActionError("I couldn't take a screenshot.") from e
    return path


# ----- notes -----


class Notes:
    """Your notes: one line each in a text file you can also open and edit."""

    def __init__(self, path: Path, now: Callable[[], datetime] = datetime.now):
        self.path = Path(path)
        self._now = now

    def add(self, text: str) -> None:
        text = " ".join(text.split())
        if not text:
            raise ActionError("What should I note?")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(f"- [{self._now():%Y-%m-%d %H:%M}] {text}\n")
        except OSError as e:
            raise ActionError("I couldn't save that note.") from e

    def recent(self, count: int = 5) -> list[str]:
        """The latest notes, oldest first, without their dates."""
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        notes = [re.sub(r"^- (?:\[[^\]]*\] )?", "", ln).strip() for ln in lines if ln.strip()]
        return [n for n in notes if n][-count:]


# ----- reminders -----


class Reminders:
    """Reminders that are said aloud at their time, and survive a restart."""

    def __init__(
        self,
        path: Path,
        announce: Callable[[str], None],
        start_timer=threading.Timer,
        now: Callable[[], datetime] = datetime.now,
    ):
        self.path = Path(path)
        self._announce = announce
        self._start_timer = start_timer
        self._now = now
        self._lock = threading.Lock()
        self._items: list[tuple[datetime, str, object]] = []  # (when, text, its timer)
        for when, text in self._read():
            self._schedule(when, text)

    def _read(self) -> list[tuple[datetime, str]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return [(datetime.fromisoformat(d["at"]), str(d["text"])) for d in data]
        except FileNotFoundError:
            return []
        except (OSError, ValueError, KeyError, TypeError):
            log.warning("Couldn't read the reminders file %s", self.path, exc_info=True)
            return []

    def _write(self) -> None:
        data = [{"at": when.isoformat(), "text": text} for when, text, _ in self._items]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
        except OSError:
            log.warning("Couldn't save the reminders", exc_info=True)

    def _schedule(self, when: datetime, text: str) -> None:
        seconds = max(1.0, (when - self._now()).total_seconds())  # one you missed: right away
        timer = self._start_timer(seconds, self._due, args=(when, text))
        timer.daemon = True
        with self._lock:
            self._items.append((when, text, timer))
            self._items.sort(key=lambda item: item[0])
        timer.start()

    def add(self, when: datetime, text: str) -> None:
        text = " ".join(text.split())
        if not text:
            raise ActionError("What should I remind you of?")
        self._schedule(when, text)
        with self._lock:
            self._write()
        log.info("Reminder set for %s: %s", when, text)

    def _due(self, when: datetime, text: str) -> None:
        with self._lock:
            self._items = [i for i in self._items if (i[0], i[1]) != (when, text)]
            self._write()
        self._announce(f"Reminder: {text}.")

    def pending(self) -> list[tuple[datetime, str]]:
        with self._lock:
            return [(when, text) for when, text, _ in self._items]

    def cancel_all(self) -> int:
        with self._lock:
            items, self._items = self._items, []
            self._write()
        for _, _, timer in items:
            timer.cancel()
        return len(items)


_CLOCK = re.compile(
    r"(?:at\s+)?(?P<hour>\d{1,2})(?:\s*[:.]\s*(?P<minute>\d{2})|\s+(?P<minute2>[0-5]\d))?"
    r"\s*(?P<half>a\.?\s?m\.?|p\.?\s?m\.?)?(?:\s+o'?clock)?"
)


def parse_clock(text: str, now: datetime | None = None) -> datetime | None:
    """'at 5:30 pm', '17:30', 'tomorrow at 9', 'noon' -> the next time the clock says that."""
    now = now or datetime.now()
    text = " ".join(text.lower().replace(",", " ").split())
    tomorrow = bool(re.search(r"\btomorrow\b", text))
    text = re.sub(
        r"\b(?:tomorrow|today|tonight|this evening|in the (?:morning|evening))\b", " ", text
    )
    text = " ".join(text.split())
    if text in ("at noon", "noon", "at midday", "midday"):
        hour, minute, half = 12, 0, "pm"
    elif text in ("at midnight", "midnight"):
        hour, minute, half = 0, 0, "am"
    else:
        found = _CLOCK.fullmatch(text)
        if not found:
            return None
        hour = int(found["hour"])
        minute = int(found["minute"] or found["minute2"] or 0)
        half = (found["half"] or "").replace(".", "").replace(" ", "")
    if hour > 23 or minute > 59 or (half and not 1 <= hour <= 12 and (hour, half) != (0, "am")):
        return None
    if half == "pm" and hour < 12:
        hour += 12
    elif half == "am" and hour == 12:
        hour = 0
    day = now.replace(second=0, microsecond=0)
    candidates = [day.replace(hour=hour, minute=minute)]
    if not half and 1 <= hour <= 11:  # "at 5": the next 5 o'clock, morning or evening
        candidates.append(day.replace(hour=hour + 12, minute=minute))
    if tomorrow:
        return candidates[0] + timedelta(days=1)
    upcoming = [c for c in candidates if c > now]
    return min(upcoming) if upcoming else candidates[0] + timedelta(days=1)


def clock_text(when: datetime, now: datetime | None = None) -> str:
    """'5:30 PM' (or 'tomorrow at 9 AM') for saying a time."""
    now = now or datetime.now()
    minutes = f":{when.minute:02d}" if when.minute else ""
    text = f"{when.hour % 12 or 12}{minutes} {'AM' if when.hour < 12 else 'PM'}"
    days = (when.date() - now.date()).days
    return f"tomorrow at {text}" if days == 1 else text if days == 0 else f"{when:%A} at {text}"


# ----- quick maths -----

_WORDS = [
    (r"\bto the power of\b", "**"),
    (r"\bsquared\b", "**2"),
    (r"\bcubed\b", "**3"),
    (r"\b(?:multiplied by|times)\b", "*"),
    (r"(?<=\d)\s*x\s*(?=\d)", "*"),
    (r"\b(?:divided by|over)\b", "/"),
    (r"\bplus\b", "+"),
    (r"\bminus\b", "-"),
    (r"(?:%|\bpercent)\s*of\b", "/100*"),
    (r"×", "*"),
    (r"÷", "/"),
    (r"\^", "**"),
]
_ASK = re.compile(
    r"^(?:what(?:'s| is)|whats|calculate|compute|how much is|tell me)\s+|\s*(?:equals?|is)?\s*\??$"
)
_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _evaluate(node) -> float:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_evaluate(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and (abs(right) > 100 or abs(left) > 1e6):
            raise ValueError("too big")
        return _OPS[type(node.op)](left, right)
    raise ValueError("not arithmetic")


def calculate(text: str) -> str | None:
    """The answer to a spoken sum ("what's 15% of 80", "12 times 12"), or None if it isn't one."""
    expr = _ASK.sub("", text.lower().strip())
    expr = _ASK.sub("", expr)
    for pattern, symbol in _WORDS:
        expr = re.sub(pattern, f" {symbol} ", expr)
    expr = re.sub(r"(?<=\d),(?=\d{3}\b)", "", expr)  # 1,000 -> 1000
    if not re.fullmatch(r"[\d\s.+\-*/()]+", expr) or not re.search(
        r"\d\s*[-+*/]+\s*\(?\s*\d", expr
    ):
        return None
    try:
        value = _evaluate(ast.parse(expr.strip(), mode="eval"))
    except ZeroDivisionError:
        return "You can't divide by zero."
    except (SyntaxError, ValueError, OverflowError, TypeError):
        return None
    if isinstance(value, complex) or abs(value) > 1e15:
        return None
    rounded = round(value, 4)
    number = (
        f"{rounded:,.4f}".rstrip("0").rstrip(".")
        if rounded != int(rounded)
        else f"{int(rounded):,}"
    )
    return f"That's {'about ' if rounded != value else ''}{number}."
