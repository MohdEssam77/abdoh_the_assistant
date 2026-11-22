"""Audio devices that follow Windows while Abdoh runs.

PortAudio (what sounddevice uses) reads the list of microphones and speakers once, when it
starts: a headset plugged in later, or a new default microphone, stays unknown to it, and "the
default" stays the device that was the default back then. `DeviceWatch` asks Windows every few
seconds which microphones are there and which devices are the defaults, and says when that
changes; `reload_portaudio()` then makes sounddevice read the list again.

A reload breaks every stream that is open, so it only happens while none is: the microphone and
Piper's voice count theirs with `stream_opened()` / `stream_closed()`.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

CHECK_SECONDS = 2.0  # how often Windows is asked

_open_streams = 0
_lock = threading.Lock()


def stream_opened() -> None:
    """A sounddevice stream is about to open: no reload until it is closed."""
    global _open_streams
    with _lock:
        _open_streams += 1


def stream_closed() -> None:
    global _open_streams
    with _lock:
        _open_streams = max(0, _open_streams - 1)


def reload_portaudio(sd=None) -> bool:
    """Make sounddevice read Windows' devices again. False (and nothing done) while a stream is
    open, since a reload would break it."""
    with _lock:
        if _open_streams:
            return False
        if sd is None:
            import sounddevice as sd
        sd._terminate()
        sd._initialize()
    log.info("Read the audio devices again")
    return True


@dataclass(frozen=True)
class Snapshot:
    """What Windows has right now."""

    microphone: str  # the default microphone's id ("" = none)
    speakers: str  # the default speakers' id ("" = none)
    microphones: tuple[tuple[str, str], ...] = ()  # (id, name) of every connected microphone

    def name(self, device_id: str) -> str:
        return next((name for ident, name in self.microphones if ident == device_id), "")


def windows_snapshot() -> Snapshot | None:
    """Windows' devices now, or None if they can't be read (not Windows, COM trouble)."""
    import sys

    if sys.platform != "win32":
        return None
    from abdoh import winaudio

    microphone, speakers = winaudio.default_ids()
    mics = tuple(sorted((m.id, m.name) for m in winaudio.microphones()))
    return Snapshot(microphone, speakers, mics)


class DeviceWatch:
    """Calls `on_change(old, new)` when the default microphone or speakers change, or a
    microphone comes or goes. `snapshot()` reads Windows (a fake in tests)."""

    def __init__(
        self,
        on_change: Callable[[Snapshot, Snapshot], None],
        snapshot: Callable[[], Snapshot | None] = windows_snapshot,
        every: float = CHECK_SECONDS,
    ):
        self._on_change = on_change
        self._snapshot = snapshot
        self.every = every
        self.last: Snapshot | None = None

    def check(self) -> None:
        """Look once (the thread does this every few seconds). The first look only remembers."""
        try:
            new = self._snapshot()
        except Exception:
            log.debug("Couldn't read the audio devices", exc_info=True)
            return
        if new is None:
            return
        old, self.last = self.last, new
        if old is None or new == old:
            return
        log.info("Audio devices changed: %s", describe(old, new))
        try:
            self._on_change(old, new)
        except Exception:
            log.exception("Couldn't follow the new audio devices")

    def start(self, stop: threading.Event) -> threading.Thread:
        def run() -> None:
            while not stop.is_set():
                self.check()
                stop.wait(self.every)

        thread = threading.Thread(target=run, name="abdoh-devices", daemon=True)
        thread.start()
        return thread


def describe(old: Snapshot, new: Snapshot) -> str:
    """What changed, for the log: "default microphone: Headset (WH-1000XM4); unplugged: ..."."""
    parts = []
    if new.microphone != old.microphone:
        parts.append(f"default microphone: {new.name(new.microphone) or 'none'}")
    if new.speakers != old.speakers:
        parts.append("default speakers changed")
    gone = [name for ident, name in old.microphones if ident not in dict(new.microphones)]
    came = [name for ident, name in new.microphones if ident not in dict(old.microphones)]
    if came:
        parts.append(f"plugged in: {', '.join(came)}")
    if gone:
        parts.append(f"unplugged: {', '.join(gone)}")
    return "; ".join(parts) or "something changed"
