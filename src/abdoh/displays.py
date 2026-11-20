"""Your monitors: which are on, turning them on and off, their numbers and names, brightness.

Windows numbers monitors in ways that change (DISPLAY1, 5 and 6 on a laptop with two
graphics chips), so Xanthos keeps its own numbers in displays.json: a monitor gets the next
free number the first time it's seen, and keeps it. A monitor is known by its device path,
which stays the same across restarts (adapter ids don't).

The Windows parts (the CCD display API and DDC/CI brightness) sit in `WindowsDisplays`; tests
use a fake backend.
"""

import json
import logging
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from abdoh.commands.actions import ActionError

log = logging.getLogger(__name__)

APPLY_WAIT_SECONDS = 3.0
NO_SCREEN_LEFT = "At least one screen has to stay on."
NOT_ACCEPTED = "Windows didn't accept that screen layout."
_ORDINALS = {
    "first": 1, "one": 1, "second": 2, "two": 2, "third": 3, "three": 3, "fourth": 4,
    "four": 4, "fifth": 5, "five": 5, "sixth": 6, "six": 6,
}  # fmt: skip
_INTERNAL_WORDS = ("laptop", "built in", "builtin", "internal", "laptops")


@dataclass(frozen=True)
class Monitor:
    """A connected monitor as Windows reports it (no Xanthos number yet)."""

    id: str  # the device path: stable
    name: str  # "HP 32f" ("" for most laptop panels)
    internal: bool
    active: bool
    primary: bool = False
    rect: tuple[int, int, int, int] | None = None  # left, top, width, height while on
    gdi: str = ""  # \\.\DISPLAY5 while on


@dataclass(frozen=True)
class Display(Monitor):
    """A monitor with Xanthos's number for it, and the nickname you gave it."""

    number: int = 0
    nickname: str = ""

    @property
    def label(self) -> str:
        """What to call it out loud: "screen 2 (TV)", "the laptop screen"."""
        return self.nickname or self.name or ("Laptop screen" if self.internal else "Monitor")


class Displays:
    def __init__(self, registry_path: Path, backend=None):
        self.path = Path(registry_path)
        self.backend = backend or WindowsDisplays()

    # ----- the registry -----

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return [d for d in data if isinstance(d, dict) and d.get("id")]
        except (OSError, ValueError):
            return []

    def _save(self, entries: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def all(self) -> list[Display]:
        """Every connected monitor, on or off, in number order. New ones get a number."""
        monitors = self.backend.monitors()
        entries = self._load()
        known = {e["id"]: e for e in entries}
        new = [m for m in monitors if m.id not in known]
        if new:
            # On first sight, number them the way Windows lists them (DISPLAY1 first).
            new.sort(key=lambda m: (not m.active, _gdi_number(m.gdi), m.id))
            used = {e.get("number", 0) for e in entries}
            for monitor in new:
                number = next(n for n in range(1, 100) if n not in used)
                used.add(number)
                entry = {"id": monitor.id, "number": number, "name": monitor.name, "nickname": ""}
                entries.append(entry)
                known[monitor.id] = entry
            self._save(entries)
        found = []
        for m in monitors:
            entry = known[m.id]
            found.append(
                Display(**vars(m), number=entry["number"], nickname=entry.get("nickname", ""))
            )
        return sorted(found, key=lambda d: d.number)

    def rename(self, display_id: str, nickname: str) -> None:
        self.all()  # every connected monitor is in the registry
        entries = self._load()
        for entry in entries:
            if entry["id"] == display_id:
                entry["nickname"] = nickname.strip()[:30]
        self._save(entries)

    def renumber(self, ids_in_order: list[str]) -> None:
        """Give the monitors new numbers: the first id is 1, and so on."""
        self.all()
        entries = self._load()
        order = {display_id: i + 1 for i, display_id in enumerate(ids_in_order)}
        rest = len(order)
        for entry in sorted(entries, key=lambda e: e.get("number", 99)):
            if entry["id"] in order:
                entry["number"] = order[entry["id"]]
            else:
                rest += 1
                entry["number"] = rest
        self._save(entries)

    # ----- finding monitors by what you say -----

    def find(self, spoken: str) -> list[Display]:
        """The monitors you named: "2", "two", "the second", "laptop", "the TV", "hp",
        "1 and 3", "all". [] if any part names nothing."""
        displays = self.all()
        text = re.sub(r"\b(?:the|my|monitors?|screens?|displays?|number|no)\b", " ", spoken.lower())
        text = re.sub(r"[,&+]| and ", " | ", f" {text} ")
        if text.strip(" |") in ("all", "every", "everything", "all of them"):
            return displays
        chosen: list[Display] = []
        for part in (p.strip() for p in text.split("|")):
            if not part:
                continue
            match = _find_one(part, displays)
            if match is None:
                return []
            if match not in chosen:
                chosen.append(match)
        return chosen

    def numbers(self, displays: list[Display]) -> str:
        """Spoken: "screen 2", "screens 1 and 3"."""
        numbers = [str(d.number) for d in sorted(displays, key=lambda d: d.number)]
        if len(numbers) == 1:
            return f"screen {numbers[0]}"
        return f"screens {', '.join(numbers[:-1])} and {numbers[-1]}"

    # ----- on and off -----

    def set_active(self, wanted_ids: set[str]) -> list[Display]:
        """Exactly these monitors on, the others off. Returns the monitors afterwards."""
        wanted_ids = set(wanted_ids)
        if not wanted_ids:
            raise ActionError(NO_SCREEN_LEFT)
        displays = self.all()
        if {d.id for d in displays if d.active} == wanted_ids:
            return displays
        unknown = wanted_ids - {d.id for d in displays}
        if unknown:
            raise ActionError("That screen isn't connected right now.")
        try:
            self.backend.set_active(wanted_ids)
        except OSError as e:
            log.warning("Screen layout refused: %s", e)
            raise ActionError(NOT_ACCEPTED) from e
        end = time.monotonic() + APPLY_WAIT_SECONDS
        while True:
            displays = self.all()
            if {d.id for d in displays if d.active} == wanted_ids or time.monotonic() > end:
                return displays
            time.sleep(0.2)

    def apply(self, spec: str) -> str:
        """A screen layout in words: "all", "only 2", "1 off", "3 on", "1 and 3 off".
        Returns what happened, to say."""
        spec = " ".join(spec.lower().split())
        displays = self.all()
        on = {d.id for d in displays if d.active}
        if spec in ("all", "all on"):
            wanted = {d.id for d in displays}
        elif spec.startswith("only "):
            wanted = {d.id for d in self._named(spec[5:])}
        elif spec.endswith(" off"):
            wanted = on - {d.id for d in self._named(spec[:-4])}
        elif spec.endswith(" on"):
            wanted = on | {d.id for d in self._named(spec[:-3])}
        else:
            raise ActionError(f"I don't understand the screen layout '{spec}'.")
        after = self.set_active(wanted)
        return self.describe(after)

    def _named(self, spoken: str) -> list[Display]:
        found = self.find(spoken)
        if not found:
            raise ActionError(f"I don't know which screen '{spoken.strip()}' is.")
        return found

    def describe(self, displays: list[Display] | None = None) -> str:
        """Which screens are on, to say."""
        displays = self.all() if displays is None else displays
        on = [d for d in displays if d.active]
        if len(on) == len(displays):
            return "All screens are on." if len(on) > 1 else "Your screen is on."
        if len(on) == 1:
            return f"Only {self.numbers(on)}, {on[0].label}, is on."
        return f"{self.numbers(on).capitalize()} are on."

    # ----- brightness (DDC/CI: only monitors that support it) -----

    def brightness(self, display: Display) -> int | None:
        if not display.active or display.internal:
            return None
        return self.backend.brightness(display)

    def set_brightness(self, display: Display, percent: int) -> bool:
        if not display.active or display.internal:
            return False
        return self.backend.set_brightness(display, percent)


def _gdi_number(gdi: str) -> int:
    found = re.search(r"(\d+)$", gdi or "")
    return int(found.group(1)) if found else 99


def _find_one(part: str, displays: list[Display]) -> Display | None:
    words = part.split()
    if len(words) == 1 and (words[0].isdigit() or words[0] in _ORDINALS):
        number = int(words[0]) if words[0].isdigit() else _ORDINALS[words[0]]
        return next((d for d in displays if d.number == number), None)
    if any(w in part for w in _INTERNAL_WORDS):
        return next((d for d in displays if d.internal), None)
    for d in displays:
        names = [n.lower() for n in (d.nickname, d.name) if n]
        if any(part == n or part in n.split() or (len(part) >= 3 and n.startswith(part))
               for n in names):  # fmt: skip
            return d
    return None


# ----- Windows: the CCD display API and DDC/CI -----


class WindowsDisplays:
    """The real monitors (Windows 7 and later). Every call is self-contained."""

    def __init__(self):
        self.available = sys.platform == "win32"

    def monitors(self) -> list[Monitor]:
        if not self.available:
            return []
        try:
            return _ccd().monitors()
        except Exception as e:
            log.warning("Couldn't read the monitors: %s", e)
            return []

    def set_active(self, wanted_ids: set[str]) -> None:
        if not self.available:
            raise OSError("Turning screens on and off only works on Windows for now.")
        _ccd().set_active(wanted_ids)

    def brightness(self, display: Display) -> int | None:
        try:
            return _ddc_brightness(display.gdi)
        except Exception:
            log.debug("No DDC/CI brightness for %s", display.label, exc_info=True)
            return None

    def set_brightness(self, display: Display, percent: int) -> bool:
        try:
            return _ddc_brightness(display.gdi, percent) is not None
        except Exception:
            log.debug("Couldn't set DDC/CI brightness for %s", display.label, exc_info=True)
            return False


def _ccd():
    """The CCD structures and calls (verified on Windows 11; sizes asserted)."""
    if hasattr(_ccd, "cache"):
        return _ccd.cache
    import ctypes
    from ctypes import Structure, Union, byref, c_int32, c_uint16, c_uint32, c_wchar, sizeof

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    QDC_ALL_PATHS, QDC_ONLY_ACTIVE_PATHS, PATH_ACTIVE = 1, 2, 1  # noqa: N806
    MODE_IDX_INVALID = 0xFFFFFFFF  # noqa: N806
    SDC_TOPOLOGY_SUPPLIED, SDC_USE_SUPPLIED_DISPLAY_CONFIG, SDC_APPLY = 0x10, 0x20, 0x80  # noqa: N806
    SDC_SAVE_TO_DATABASE, SDC_ALLOW_CHANGES, SDC_ALLOW_PATH_ORDER_CHANGES = 0x200, 0x400, 0x2000  # noqa: N806
    INTERNAL = {0x80000000, 6, 11, 13}  # noqa: N806

    class LUID(Structure):
        _fields_ = [("LowPart", c_uint32), ("HighPart", c_int32)]

    class PathSource(Structure):
        _fields_ = [("adapterId", LUID), ("id", c_uint32), ("modeInfoIdx", c_uint32),
                    ("statusFlags", c_uint32)]  # fmt: skip

    class Rational(Structure):
        _fields_ = [("Numerator", c_uint32), ("Denominator", c_uint32)]

    class PathTarget(Structure):
        _fields_ = [("adapterId", LUID), ("id", c_uint32), ("modeInfoIdx", c_uint32),
                    ("outputTechnology", c_uint32), ("rotation", c_uint32),
                    ("scaling", c_uint32), ("refreshRate", Rational),
                    ("scanLineOrdering", c_uint32), ("targetAvailable", c_int32),
                    ("statusFlags", c_uint32)]  # fmt: skip

    class PathInfo(Structure):
        _fields_ = [("sourceInfo", PathSource), ("targetInfo", PathTarget), ("flags", c_uint32)]

    class Point(Structure):
        _fields_ = [("x", c_int32), ("y", c_int32)]

    class SourceMode(Structure):
        _fields_ = [("width", c_uint32), ("height", c_uint32), ("pixelFormat", c_uint32),
                    ("position", Point)]  # fmt: skip

    class ModeUnion(Union):
        _fields_ = [("sourceMode", SourceMode), ("raw", ctypes.c_byte * 48)]

    class ModeInfo(Structure):
        _fields_ = [("infoType", c_uint32), ("id", c_uint32), ("adapterId", LUID),
                    ("u", ModeUnion)]  # fmt: skip

    class DeviceInfoHeader(Structure):
        _fields_ = [("type", c_uint32), ("size", c_uint32), ("adapterId", LUID), ("id", c_uint32)]

    class SourceName(Structure):
        _fields_ = [("header", DeviceInfoHeader), ("viewGdiDeviceName", c_wchar * 32)]

    class TargetName(Structure):
        _fields_ = [("header", DeviceInfoHeader), ("flags", c_uint32),
                    ("outputTechnology", c_uint32), ("edidManufactureId", c_uint16),
                    ("edidProductCodeId", c_uint16), ("connectorInstance", c_uint32),
                    ("monitorFriendlyDeviceName", c_wchar * 64),
                    ("monitorDevicePath", c_wchar * 128)]  # fmt: skip

    assert (sizeof(PathInfo), sizeof(ModeInfo), sizeof(TargetName)) == (72, 64, 420)

    def query(flags):
        for _ in range(3):
            n_paths, n_modes = c_uint32(), c_uint32()
            err = user32.GetDisplayConfigBufferSizes(flags, byref(n_paths), byref(n_modes))
            if err:
                raise OSError(f"GetDisplayConfigBufferSizes failed ({err})")
            paths, modes = (PathInfo * n_paths.value)(), (ModeInfo * n_modes.value)()
            err = user32.QueryDisplayConfig(
                flags, byref(n_paths), paths, byref(n_modes), modes, None
            )
            if err == 0:
                return list(paths[: n_paths.value]), list(modes[: n_modes.value])
            if err != 122:  # the layout changed in between: try again
                raise OSError(f"QueryDisplayConfig failed ({err})")
        raise OSError("The screen layout kept changing")

    def target(path):
        info = TargetName()
        t = path.targetInfo
        info.header = DeviceInfoHeader(2, sizeof(TargetName), t.adapterId, t.id)
        if user32.DisplayConfigGetDeviceInfo(byref(info)):
            return "", "", 0
        return info.monitorFriendlyDeviceName, info.monitorDevicePath, info.outputTechnology

    def source(path):
        info = SourceName()
        s = path.sourceInfo
        info.header = DeviceInfoHeader(1, sizeof(SourceName), s.adapterId, s.id)
        return info.viewGdiDeviceName if user32.DisplayConfigGetDeviceInfo(byref(info)) == 0 else ""

    def key(path):
        t = path.targetInfo
        return t.adapterId.LowPart, t.adapterId.HighPart, t.id

    def source_key(path):
        s = path.sourceInfo
        return s.adapterId.LowPart, s.adapterId.HighPart, s.id

    def all_targets():
        """{target key: [possible paths]} for every connected monitor."""
        every, _ = query(QDC_ALL_PATHS)
        targets: dict = {}
        for p in every:
            if p.targetInfo.targetAvailable:
                targets.setdefault(key(p), []).append(p)
        return targets

    class Api:
        def monitors(self) -> list[Monitor]:
            active, modes = query(QDC_ONLY_ACTIVE_PATHS)
            on = {}
            for p in active:
                rect, primary = None, False
                if p.sourceInfo.modeInfoIdx != MODE_IDX_INVALID:
                    mode = modes[p.sourceInfo.modeInfoIdx].u.sourceMode
                    rect = (mode.position.x, mode.position.y, mode.width, mode.height)
                    primary = mode.position.x == 0 and mode.position.y == 0
                on[key(p)] = (rect, primary, source(p))
            found = []
            for k, paths in all_targets().items():
                name, device, tech = target(paths[0])
                if not device:
                    continue
                rect, primary, gdi = on.get(k, (None, False, ""))
                found.append(Monitor(device, name, tech in INTERNAL, k in on, primary, rect, gdi))
            return found

        def set_active(self, wanted_ids: set[str]) -> None:
            targets = all_targets()
            by_id = {target(paths[0])[1]: paths for paths in targets.values()}
            chosen, used = [], set()
            # Monitors that stay on keep their source; the others take a free one.
            order = sorted(
                (by_id[i] for i in wanted_ids if i in by_id),
                key=lambda ps: not any(p.flags & PATH_ACTIVE for p in ps),
            )
            for paths in order:
                pick = next((p for p in paths if p.flags & PATH_ACTIVE), None)
                if pick is None:
                    pick = next((p for p in paths if source_key(p) not in used), None)
                if pick is None:
                    raise OSError("No free graphics output for that screen")
                used.add(source_key(pick))
                copy = PathInfo.from_buffer_copy(pick)
                copy.flags = PATH_ACTIVE
                copy.sourceInfo.modeInfoIdx = MODE_IDX_INVALID
                copy.targetInfo.modeInfoIdx = MODE_IDX_INVALID
                chosen.append(copy)
            array = (PathInfo * len(chosen))(*chosen)
            flags = SDC_APPLY | SDC_TOPOLOGY_SUPPLIED | SDC_ALLOW_PATH_ORDER_CHANGES
            err = user32.SetDisplayConfig(len(chosen), array, 0, None, flags)
            if err:  # this set of monitors was never used together: let Windows lay them out
                flags = (
                    SDC_APPLY | SDC_USE_SUPPLIED_DISPLAY_CONFIG | SDC_ALLOW_CHANGES
                    | SDC_SAVE_TO_DATABASE
                )  # fmt: skip
                err = user32.SetDisplayConfig(len(chosen), array, 0, None, flags)
            if err:
                raise OSError(f"SetDisplayConfig failed ({err})")

    _ccd.cache = Api()
    return _ccd.cache


def _ddc_brightness(gdi: str, percent: int | None = None) -> int | None:
    """Read (or set) a monitor's brightness over DDC/CI, by its GDI name (DISPLAYn). None if
    the monitor doesn't support it."""
    import ctypes
    from ctypes import Structure, byref, c_int32, c_uint32, c_wchar, sizeof

    user32, dxva2 = ctypes.windll.user32, ctypes.windll.dxva2

    class PhysicalMonitor(Structure):
        _fields_ = [("handle", ctypes.c_void_p), ("description", c_wchar * 128)]

    class MonitorInfoEx(Structure):
        _fields_ = [("cbSize", c_uint32), ("rcMonitor", c_int32 * 4), ("rcWork", c_int32 * 4),
                    ("dwFlags", c_uint32), ("szDevice", c_wchar * 32)]  # fmt: skip

    result: list[int | None] = [None]
    callback_type = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
    )

    def visit(hmon, _dc, _rect, _data):
        info = MonitorInfoEx()
        info.cbSize = sizeof(MonitorInfoEx)
        user32.GetMonitorInfoW(ctypes.c_void_p(hmon), byref(info))
        if info.szDevice != gdi:
            return 1
        count = c_uint32()
        dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(ctypes.c_void_p(hmon), byref(count))
        if not count.value:
            return 0
        monitors = (PhysicalMonitor * count.value)()
        if not dxva2.GetPhysicalMonitorsFromHMONITOR(ctypes.c_void_p(hmon), count.value, monitors):
            return 0
        try:
            handle = ctypes.c_void_p(monitors[0].handle)
            low, now, high = c_uint32(), c_uint32(), c_uint32()
            if not dxva2.GetMonitorBrightness(handle, byref(low), byref(now), byref(high)):
                return 0
            span = max(1, high.value - low.value)
            if percent is None:
                result[0] = round((now.value - low.value) * 100 / span)
            else:
                value = low.value + round(span * max(0, min(100, percent)) / 100)
                if dxva2.SetMonitorBrightness(handle, value):
                    result[0] = percent
        finally:
            dxva2.DestroyPhysicalMonitors(count.value, monitors)
        return 0

    user32.EnumDisplayMonitors(None, None, callback_type(visit), 0)
    return result[0]
