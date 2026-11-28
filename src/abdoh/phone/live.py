"""The computer's screens on the phone, live, and the right one in a picture (story 155).

**Live.** While a phone watches, a thread takes a picture of the chosen screen about FPS times a
second, but only encodes and sends one when something changed (a 48 x 27 grey sketch of it is
compared with the last one), so a still screen costs almost nothing. The phone asks for the
next frame after the one it has (`frame(which, after)`) and waits a moment for it, like the
conversation's long polling. With nobody watching for IDLE seconds, the thread stops.

**Which screen.** `which` is one of Abdoh's screen numbers ("2": displays.json's numbers, the
ones you say: "my second screen"), or "follow": the screen of the window you're working in.
A picture after opening something is of the screen where that app's window is (`app`), once
it has settled there; the caption says which screen it is.

Windows' parts (mss, the windows) sit in `Grabber`; tests use a fake one.
"""

import io
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image

log = logging.getLogger(__name__)

FPS = 5
IDLE = 8.0  # nobody watched this long: the thread stops
SIDE = 1280  # a live frame's long side, at most
QUALITY = 60
PICTURE_SIDE = 1600
PICTURE_QUALITY = 80
SKETCH = (48, 27)
CHANGED = 1.5  # mean difference (0-255) of the sketches: something moved
FOLLOW = "follow"
SCREENS_SECONDS = 5.0
STILL_AFTER = 5  # this many looks without a change...
STILL_EVERY = 0.5  # ... and it looks only this often until something moves


@dataclass
class Screen:
    id: str  # Abdoh's number for it, as text ("2"), or its place in Windows' list
    label: str  # "Screen 2 · HP 32f"
    monitor: dict  # mss's: left, top, width, height
    primary: bool = False


def _contains(monitor: dict, point: tuple[int, int]) -> bool:
    x, y = point
    return (monitor["left"] <= x < monitor["left"] + monitor["width"]
            and monitor["top"] <= y < monitor["top"] + monitor["height"])  # fmt: skip


def _nearest(monitors: list[dict], point: tuple[int, int] | None) -> dict | None:
    from abdoh.claude.screen import pick_monitor

    return pick_monitor(monitors, point) if monitors else None


class Grabber:
    """The real screens (Windows): their places, pictures of them, where windows are."""

    def __init__(self):
        self._local = threading.local()

    def _sct(self):
        sct = getattr(self._local, "sct", None)
        if sct is None:
            import mss

            sct = self._local.sct = mss.MSS()  # one per thread: mss isn't shared
        return sct

    def monitors(self) -> list[dict]:
        return [dict(m) for m in self._sct().monitors[1:]]

    def grab(self, monitor: dict) -> Image.Image:
        shot = self._sct().grab(monitor)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    def front_point(self) -> tuple[int, int] | None:
        from abdoh.claude.screen import front_window

        return front_window().center

    def app_point(self, name: str) -> tuple[int, int] | None:
        """The middle of a program's window ("WhatsApp"), or None (none, or minimized)."""
        from abdoh import system

        try:
            found = system.app_windows(name)
        except Exception:
            log.debug("Couldn't look for %r's window", name, exc_info=True)
            return None
        for hwnd, _, _ in found:
            left, top, width, height = system.window_rect(hwnd)
            if left > -30000 and width > 0 and height > 0:  # not minimized
                return left + width // 2, top + height // 2
        return None

    def close(self) -> None:
        sct = getattr(self._local, "sct", None)
        if sct is not None:
            sct.close()
            self._local.sct = None


class LiveScreen:
    def __init__(
        self,
        grabber=None,
        names: Callable[[], list[tuple[int, str, tuple]]] | None = None,
        clock=time.monotonic,
        fps: float = FPS,
    ):
        self._grabber = grabber or Grabber()
        self._names = names  # Abdoh's screens: (number, label, (left, top, width, height))
        self._clock = clock
        self._every = 1.0 / fps
        self._cond = threading.Condition()
        self._frames: dict[str, tuple[int, bytes, str]] = {}  # which -> (number, JPEG, label)
        self._sketches: dict[str, tuple[str, bytes]] = {}  # which -> (its screen, last sketch)
        self._wanted: dict[str, float] = {}  # which -> when a phone last asked
        self._seq = 0
        self._thread: threading.Thread | None = None
        self._known: tuple[float, list[Screen]] | None = None  # the screens, looked up lately

    # ----- the screens -----

    def screens(self) -> list[Screen]:
        """The screens that are on, by Abdoh's numbers when it knows them (looked up again
        after a few seconds: a screen may have been turned on or off)."""
        known = self._known
        if known is not None and self._clock() - known[0] < SCREENS_SECONDS:
            return known[1]
        found = self._look_up()
        self._known = (self._clock(), found)
        return found

    def _look_up(self) -> list[Screen]:
        monitors = self._grabber.monitors()
        found: list[Screen] = []
        named = []
        try:
            named = list(self._names()) if self._names else []
        except Exception:
            log.debug("Couldn't read the screens' names", exc_info=True)
        for number, label, rect in named:
            if not rect:
                continue
            middle = (rect[0] + rect[2] // 2, rect[1] + rect[3] // 2)
            monitor = next((m for m in monitors if _contains(m, middle)), None)
            if monitor is not None and all(s.monitor != monitor for s in found):
                text = f"Screen {number}" + (f" · {label}" if label else "")
                found.append(Screen(str(number), text, monitor, (rect[0], rect[1]) == (0, 0)))
        for i, monitor in enumerate(monitors, 1):  # any Abdoh doesn't know (yet)
            if all(s.monitor != monitor for s in found):
                primary = (monitor["left"], monitor["top"]) == (0, 0)
                found.append(Screen(f"m{i}", f"Screen {i}", monitor, primary))
        return sorted(found, key=lambda s: (not s.id.isdigit(), int(s.id) if s.id.isdigit() else 0))

    def screen_at(self, point: tuple[int, int] | None) -> Screen | None:
        screens = self.screens()
        monitor = _nearest([s.monitor for s in screens], point)
        return next((s for s in screens if s.monitor == monitor), None)

    def _screen(self, which: str) -> Screen | None:
        if which == FOLLOW:
            return self.screen_at(self._grabber.front_point())
        return next((s for s in self.screens() if s.id == which), None) or self.screen_at(None)

    # ----- one picture -----

    def picture(self, app: str = "", which: str = "") -> tuple[bytes, Screen]:
        """A picture (JPEG) of the screen where `app`'s window is (else screen `which`, else
        the one you're working on), and that screen. Raises ScreenCaptureError."""
        from abdoh.claude.screen import ScreenCaptureError, is_all_black

        point = self._grabber.app_point(app) if app else None
        if point is None and which and which != FOLLOW:
            screen = self._screen(which)
        else:
            screen = self.screen_at(point or self._grabber.front_point())
        if screen is None:
            raise ScreenCaptureError("I couldn't find the computer's screens.")
        try:
            image = self._grabber.grab(screen.monitor)
        except Exception as e:
            log.exception("Couldn't take a picture of %s", screen.label)
            raise ScreenCaptureError("I couldn't take a picture of the screen.") from e
        if is_all_black(image):
            raise ScreenCaptureError("The screen is off or locked, so its picture is all black.")
        return _jpeg(image, PICTURE_SIDE, PICTURE_QUALITY), screen

    # ----- live -----

    def frame(self, which: str, after: int, wait: float = 2.0) -> tuple[int, bytes, str] | None:
        """The newest frame of that screen after number `after`, waiting up to `wait` seconds
        for one (None: nothing changed)."""
        which = str(which or FOLLOW)
        deadline = self._clock() + wait
        with self._cond:
            self._wanted[which] = self._clock()
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="abdoh-live", daemon=True)
                self._thread.start()
            while True:
                found = self._frames.get(which)
                if found is not None and found[0] > after:
                    return found
                left = deadline - self._clock()
                if left <= 0:
                    return None
                self._cond.wait(left)

    def _run(self) -> None:
        log.info("The phone is watching the screen live")
        still = 0  # looks in a row that found nothing new
        try:
            while True:
                now = self._clock()
                with self._cond:
                    watched = [w for w, at in self._wanted.items() if now - at < IDLE]
                    if not watched:
                        self._wanted.clear()
                        self._thread = None
                        return
                changed = False
                for which in watched:
                    try:
                        changed = self.shoot(which) or changed
                    except Exception:
                        log.debug("Couldn't take a live frame of %s", which, exc_info=True)
                still = 0 if changed else still + 1
                # a still screen is looked at less often (a picture of a big screen takes time)
                time.sleep(self._every if still < STILL_AFTER else STILL_EVERY)
        finally:
            log.info("The phone stopped watching the screen")
            close = getattr(self._grabber, "close", None)
            if close is not None:
                close()

    def shoot(self, which: str) -> bool:
        """One look at the screen: a new frame when it changed (True). The thread calls it;
        tests call it directly."""
        screen = self._screen(which)
        if screen is None:
            return False
        image = self._grabber.grab(screen.monitor)
        sketch = image.reduce(8).convert("L").resize(SKETCH).tobytes()
        last = self._sketches.get(which)
        if last is not None and last[0] == screen.id and _difference(last[1], sketch) < CHANGED:
            return False
        frame = _jpeg(image, SIDE, QUALITY)
        with self._cond:
            self._sketches[which] = (screen.id, sketch)
            self._seq += 1
            self._frames[which] = (self._seq, frame, screen.label)
            self._cond.notify_all()
        return True


def _difference(a: bytes, b: bytes) -> float:
    if len(a) != len(b):
        return 255.0
    return sum(abs(x - y) for x, y in zip(a, b, strict=True)) / max(1, len(a))


def _jpeg(image: Image.Image, side: int, quality: int) -> bytes:
    image = image.convert("RGB")
    if max(image.size) > side:
        image.thumbnail((side, side), Image.Resampling.BILINEAR)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=quality)
    return out.getvalue()
