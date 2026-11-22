"""Microphone input: 16 kHz mono int16 blocks, plus a rolling buffer of recent audio."""

import logging
import queue
import time
from collections import deque

import numpy as np

from abdoh.audio.devices import stream_closed, stream_opened

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2  # int16 mono
NAME_LIMIT = 31  # the classic audio API cuts device names here


class MicrophoneError(RuntimeError):
    """The microphone could not be opened or stopped delivering audio."""


# Inputs that aren't real microphones: Windows' "mappers" that stand for the default device.
_NOT_MICS = ("Microsoft Sound Mapper", "Primary Sound Capture Driver")


def input_devices(sd=None) -> list[dict]:
    """The microphones to choose from: [{"name": ..., "default": bool}].

    Only the default host API's devices are listed (on Windows: MME), so each mic appears once.
    """
    if sd is None:
        import sounddevice as sd
    devices = sd.query_devices()
    default = sd.default.device[0]
    hostapi = devices[default]["hostapi"] if default is not None and default >= 0 else 0
    return [
        {"name": d["name"], "default": i == default}
        for i, d in enumerate(devices)
        if d["max_input_channels"] > 0
        and d["hostapi"] == hostapi
        and not d["name"].startswith(_NOT_MICS)
    ]


def same_name(listed: str, wanted: str) -> bool:
    """Is the microphone sounddevice lists as `listed` the one called `wanted`? Either may be
    cut short: the classic audio API (what sounddevice lists) keeps 31 characters of a name,
    Windows' own list (Settings) the whole name."""
    return bool(wanted) and listed[:NAME_LIMIT].strip() == wanted[:NAME_LIMIT].strip()


def find_input_device(name: str, sd=None) -> int | None:
    """The device index for a microphone's name (full or cut short), or None (= the default)."""
    if not name:
        return None
    if sd is None:
        import sounddevice as sd
    devices = sd.query_devices()
    default = sd.default.device[0]
    hostapi = devices[default]["hostapi"] if default is not None and default >= 0 else 0
    for i, d in enumerate(devices):
        if same_name(d["name"], name) and d["max_input_channels"] > 0 and d["hostapi"] == hostapi:
            return i
    log.warning("Microphone %r isn't connected; using the default microphone.", name)
    return None


def _device_name(sd, index: int | None) -> str:
    try:
        return sd.query_devices(sd.default.device[0] if index is None else index)["name"]
    except Exception:
        return ""


class Microphone:
    """Reads audio blocks from a microphone (`device`: its name; "" = the system default).

    Every block returned by `read()` is also kept in a rolling buffer of the last
    `buffer_seconds`, so speech said just before the wake word can be recovered. `level` is the
    loudest sample of the latest block (0 to 32768), for a level meter. `last_time` is when the
    block last returned by read() arrived from the microphone (`time.perf_counter()`).
    """

    def __init__(self, block_seconds: float = 0.1, buffer_seconds: float = 3.0, device: str = ""):
        self.block_seconds = block_seconds
        self.device = device
        self.level = 0
        self.last_time = 0.0
        self._queue: queue.Queue[tuple[bytes, float]] = queue.Queue()
        self._buffer: deque[bytes] = deque(maxlen=max(1, int(buffer_seconds / block_seconds)))
        self._stream = None
        self.name = ""  # the microphone it opened (for the log)

    def start(self) -> None:
        import sounddevice as sd

        stream_opened()  # no device reload while it's open
        try:
            index = find_input_device(self.device, sd)
            self._stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                blocksize=int(SAMPLE_RATE * self.block_seconds),
                dtype="int16",
                channels=1,
                callback=self._callback,
                device=index,
            )
            self._stream.start()
            self.name = _device_name(sd, index)
        except Exception as e:
            self._stream = None
            stream_closed()
            raise MicrophoneError(f"Could not open microphone: {e}") from e

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                log.debug("Error closing mic stream", exc_info=True)
            self._stream = None
            stream_closed()

    def __enter__(self) -> "Microphone":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def _callback(self, indata, frames, timing, status) -> None:
        if status:
            log.debug("Mic status: %s", status)
        block = bytes(indata)
        samples = np.frombuffer(block, dtype=np.int16)
        self.level = int(np.abs(samples.astype(np.int32)).max()) if samples.size else 0
        self._queue.put((block, time.perf_counter()))

    def read(self, timeout: float = 2.0) -> bytes:
        try:
            block, self.last_time = self._queue.get(timeout=timeout)
        except queue.Empty as e:
            raise MicrophoneError("Microphone stopped delivering audio") from e
        self._buffer.append(block)
        return block

    def recent(self) -> bytes:
        """The last few seconds of audio returned by read()."""
        return b"".join(self._buffer)

    def clear(self) -> None:
        """Drop queued and buffered audio (e.g. after Abdoh has spoken)."""
        self._buffer.clear()
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
