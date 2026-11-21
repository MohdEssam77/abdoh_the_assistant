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
    array: about -95 dBFS while the speakers played; raw: the room as it is)."""
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
        self.raw = raw  # try raw mode first (see raw_settings); where it fails, the usual way
        self.raw_mode = False  # ... and whether it is on
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
        ways = []
        if self.raw and hasattr(sd, "WasapiSettings"):
            device = find_raw_device(self.device, sd)
            if device is not None:
                ways.append((device, "raw"))
        ways.append((None, ""))
        error = None
        for device, kind in ways:
            stream = None
            try:
                extra = raw_settings(sd) if kind else None
                if not kind:
                    device = find_input_device(self.device, sd)
                stream = sd.RawInputStream(
                    samplerate=SAMPLE_RATE,
                    blocksize=int(SAMPLE_RATE * self.block_seconds),
                    dtype="int16",
                    channels=1,
                    callback=self._callback,
                    device=device,
                    extra_settings=extra,
                )
                stream.start()
            except Exception as e:
                error = e
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        log.debug("Couldn't close the microphone stream", exc_info=True)
                if kind:
                    log.info("The microphone can't open in raw mode (%s): the usual way", e)
                continue
            self._stream, self.raw_mode = stream, bool(kind)
            log.info("Microphone open%s", " in raw mode" if kind else "")
            return
        self._stream = None
        raise MicrophoneError(f"Could not open microphone: {error}") from error

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                log.debug("Error closing mic stream", exc_info=True)
            self._stream = None

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
        """Drop queued and buffered audio (e.g. after Krekos has spoken)."""
        self._buffer.clear()
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
