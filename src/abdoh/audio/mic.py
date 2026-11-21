"""Microphone input: 16 kHz mono int16 blocks, plus a rolling buffer of recent audio."""

import logging
import queue
import time
from collections import deque

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2  # int16 mono


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


# MME (the list above) cuts names to 31 characters; WASAPI has them in full.
MME_NAME_LENGTH = 31
RAW = 1  # PortAudio's eStreamOptionRaw (sounddevice has no name for it)
RAW_KEEP = 20  # raw blocks kept (2 s)
RAW_FRESH_SECONDS = 0.5  # older raw blocks are stale


def _close(stream) -> None:
    try:
        stream.stop()
        stream.close()
    except Exception:
        log.debug("Error closing a microphone stream", exc_info=True)


def find_raw_device(name: str, sd) -> int | None:
    """The WASAPI twin of a microphone from input_devices ("" = the default), or None."""
    apis = sd.query_hostapis()
    wasapi = next((i for i, a in enumerate(apis) if a["name"] == "Windows WASAPI"), None)
    if wasapi is None:
        return None
    if not name:
        default = apis[wasapi].get("default_input_device", -1)
        return default if default >= 0 else None
    for i, d in enumerate(sd.query_devices()):
        if d["hostapi"] != wasapi or d["max_input_channels"] <= 0:
            continue
        cut = len(name) == MME_NAME_LENGTH and d["name"].startswith(name)
        if d["name"] == name or cut:
            return i
    return None


def raw_settings(sd):
    """WASAPI in raw mode: without the sound driver's and Windows' effects. Their echo and noise
    suppression can mute the microphone while music plays (measured on a Realtek microphone
    array: about -95 dBFS while the speakers played; raw: the room as it is). Only the wake word
    uses it, and only while something plays (daemon.py): everything else hears the microphone
    the usual way, where the driver keeps the music and Krekos's own voice out."""
    settings = sd.WasapiSettings(auto_convert=True)  # auto_convert: 16 kHz from any mixer rate
    settings._streaminfo.streamOption = RAW
    return settings


def find_input_device(name: str, sd=None) -> int | None:
    """The device index for a microphone's name (from input_devices), or None (= the default)."""
    if not name:
        return None
    if sd is None:
        import sounddevice as sd
    devices = sd.query_devices()
    default = sd.default.device[0]
    hostapi = devices[default]["hostapi"] if default is not None and default >= 0 else 0
    for i, d in enumerate(devices):
        if d["name"] == name and d["max_input_channels"] > 0 and d["hostapi"] == hostapi:
            return i
    log.warning("Microphone %r not found; using the default microphone.", name)
    return None


class Microphone:
    """Reads audio blocks from a microphone (`device`: its name; "" = the system default).

    Every block returned by `read()` is also kept in a rolling buffer of the last
    `buffer_seconds`, so speech said just before the wake word can be recovered. `level` is the
    loudest sample of the latest block (0 to 32768), for a level meter. `last_time` is when the
    block last returned by read() arrived from the microphone (`time.perf_counter()`).
    """

    def __init__(
        self,
        block_seconds: float = 0.1,
        buffer_seconds: float = 3.0,
        device: str = "",
        raw: bool = True,
        sd=None,
    ):
        self.block_seconds = block_seconds
        self.device = device
        self.raw = raw  # also open the microphone in raw mode, for the wake word (raw_settings)
        self.raw_mode = False  # ... and whether that worked
        self._raw: deque[tuple[bytes, float]] = deque(maxlen=RAW_KEEP)
        self._sd = sd
        self.level = 0
        self.last_time = 0.0
        self._queue: queue.Queue[tuple[bytes, float]] = queue.Queue()
        self._buffer: deque[bytes] = deque(maxlen=max(1, int(buffer_seconds / block_seconds)))
        self._stream = None

    def start(self) -> None:
        sd = self._sd
        if sd is None:
            import sounddevice as sd
        try:
            self._stream = self._open(sd, find_input_device(self.device, sd), self._callback)
        except Exception as e:
            self._stream = None
            raise MicrophoneError(f"Could not open microphone: {e}") from e
        device = find_raw_device(self.device, sd) if self.raw else None
        if device is None or not hasattr(sd, "WasapiSettings"):
            return
        try:
            self._raw_stream = self._open(sd, device, self._raw_callback, raw_settings(sd))
        except Exception as e:
            log.info("No raw microphone for the wake word over music (%s)", e)
            return
        self.raw_mode = True
        log.info("Microphone open, and in raw mode for the wake word over music")

    def _open(self, sd, device, callback, extra=None):
        stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=int(SAMPLE_RATE * self.block_seconds),
            dtype="int16",
            channels=1,
            callback=callback,
            device=device,
            extra_settings=extra,
        )
        try:
            stream.start()
        except Exception:
            _close(stream)
            raise
        return stream

    def stop(self) -> None:
        for name in ("_stream", "_raw_stream"):
            stream = getattr(self, name, None)
            if stream is not None:
                _close(stream)
                setattr(self, name, None)
        self.raw_mode = False

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

    def _raw_callback(self, indata, frames, timing, status) -> None:
        self._raw.append((bytes(indata), time.perf_counter()))

    def take_raw(self) -> list[tuple[bytes, float]]:
        """The raw microphone's blocks since the last call, with when each arrived: only the
        fresh ones (older ones piled up while nobody asked)."""
        fresh = time.perf_counter() - RAW_FRESH_SECONDS
        taken = []
        while self._raw:
            block, arrived = self._raw.popleft()
            if arrived >= fresh:
                taken.append((block, arrived))
        return taken

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
        """Drop queued and buffered audio (e.g. after Krekos has spoken)."""
        self._buffer.clear()
        self._raw.clear()
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
