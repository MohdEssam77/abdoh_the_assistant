"""Short generated sounds ("earcons") played without blocking. No sound files needed."""

import logging
import threading
from collections.abc import Callable

import numpy as np

log = logging.getLogger(__name__)

RATE = 22050
# Each sound is a list of (frequency in Hz, seconds) segments played back to back; 0 Hz is a pause.
SOUNDS: dict[str, list[tuple[float, float]]] = {
    "listening": [(660, 0.06), (990, 0.08)],  # rising: I'm listening
    "ready": [(880, 0.05)],  # one soft note: go on, I'm still listening
    "thinking": [(587, 0.07)],  # soft blip: working on it
    "done": [(880, 0.06), (587, 0.08)],  # falling: stopped
    "unclear": [(494, 0.05), (0, 0.05), (494, 0.05)],  # two low taps: heard you, didn't act
    "alarm": [(880, 0.15), (0, 0.08), (880, 0.15), (0, 0.08), (880, 0.15)],  # timer finished
}


def render(segments: list[tuple[float, float]], rate: int = RATE, volume: float = 0.25):
    """Sine tones with short fades (no clicks), as float32 samples."""
    parts = []
    for freq, seconds in segments:
        n = int(rate * seconds)
        t = np.arange(n) / rate
        wave = np.sin(2 * np.pi * freq * t) if freq else np.zeros(n)
        fade = min(n // 4, int(rate * 0.01))
        if fade:
            ramp = np.linspace(0.0, 1.0, fade)
            wave[:fade] *= ramp
            wave[-fade:] *= ramp[::-1]
        parts.append(wave)
    return (np.concatenate(parts) * volume).astype(np.float32)


def _play_with_sounddevice(samples, rate: int) -> None:
    import sounddevice as sd

    sd.play(samples, rate)  # returns immediately


class Earcons:
    def __init__(self, play: Callable[[object, int], None] = _play_with_sounddevice):
        self._play = play
        self.enabled = True
        self._cache: dict[str, object] = {}
        self._ticking: threading.Event | None = None
        self._lock = threading.Lock()

    @classmethod
    def silent(cls) -> "Earcons":
        return cls(play=lambda samples, rate: None)

    def play(self, name: str) -> None:
        """Play a sound without blocking. Never raises."""
        if not self.enabled:
            return
        try:
            if name not in self._cache:
                self._cache[name] = render(SOUNDS[name])
            self._play(self._cache[name], RATE)
        except Exception:
            log.debug("Could not play earcon %r", name, exc_info=True)

    def start_ticking(self, name: str = "thinking", every: float = 3.0) -> None:
        """Play a sound now and again every few seconds, until stop_ticking()."""
        stop = threading.Event()
        with self._lock:
            if self._ticking is not None:
                self._ticking.set()
            self._ticking = stop

        def loop() -> None:
            while not stop.is_set():
                self.play(name)
                stop.wait(every)

        threading.Thread(target=loop, name="abdoh-earcon", daemon=True).start()

    def stop_ticking(self) -> None:
        with self._lock:
            if self._ticking is not None:
                self._ticking.set()
                self._ticking = None
