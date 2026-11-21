"""What the speakers are playing, as 16 kHz mono audio by time (Windows' loopback capture).

Krekos hears its own voice through the microphone. Knowing exactly what the speakers played lets
the echo canceller (audio/echo.py) take it back out, so Krekos can tell when you talk over it.
The audio is kept in memory for a few seconds only; nothing is saved or sent.

Windows sends no packets at all while nothing is playing, so the tap places every packet by
its time stamp and treats gaps as silence.
"""

import logging
import sys
import threading
import time

import numpy as np

from abdoh.audio.mic import SAMPLE_RATE

log = logging.getLogger(__name__)

RING_SECONDS = 3.0
POLL_SECONDS = 0.01  # packets are 10 ms long
CHECK_DEVICE_SECONDS = 2.0  # how often to see if the default speakers changed
RETRY_SECONDS = 2.0


class SpeakerTap:
    """The last few seconds of what the default speakers played, placed on the
    `time.perf_counter()` clock. Feed it with `write()` (the capture thread does)."""

    def __init__(self, capture_factory=None, clock=time.perf_counter):
        self._factory = capture_factory  # () -> LoopbackCapture-like; None: Windows' own
        self._clock = clock
        self._size = int(RING_SECONDS * SAMPLE_RATE)
        self._ring = np.zeros(self._size, dtype=np.int16)
        self._lock = threading.Lock()
        self._origin = clock()  # sample 0 is at this time
        self._end = 0  # one past the last sample written (an absolute sample number)
        self._stop = threading.Event()
        self._thread = None
        self.available = sys.platform == "win32" or capture_factory is not None

    # ----- the timeline -----

    def _index(self, at: float) -> int:
        return round((at - self._origin) * SAMPLE_RATE)

    def write(self, samples: np.ndarray, start_time: float) -> None:
        """Place samples that started playing at `start_time` (perf_counter seconds)."""
        n = len(samples)
        if not n:
            return
        with self._lock:
            start = self._index(start_time)
            # Time stamps jitter by a sample or two; keep consecutive packets back to back.
            if abs(start - self._end) <= SAMPLE_RATE // 100:
                start = self._end
            if start - self._end >= self._size:  # a long gap: nothing was playing
                self._ring[:] = 0
            elif start > self._end:
                self._put(self._end, np.zeros(start - self._end, np.int16))
            self._put(start, samples)
            self._end = max(self._end, start + n)

    def _put(self, start: int, samples: np.ndarray) -> None:
        if len(samples) > self._size:  # only the newest part fits
            start += len(samples) - self._size
            samples = samples[-self._size :]
        first = start % self._size
        room = self._size - first
        self._ring[first : first + min(room, len(samples))] = samples[:room]
        if len(samples) > room:
            self._ring[: len(samples) - room] = samples[room:]

    def window(self, end_time: float, samples: int) -> bytes:
        """The `samples` that played up to `end_time`, as int16 bytes (zeros where nothing did)."""
        out = np.zeros(samples, dtype=np.int16)
        with self._lock:
            end = self._index(end_time)
            start = end - samples
            lo = max(start, self._end - self._size)  # older than the ring: gone
            hi = min(end, self._end)  # not played yet (or nothing was playing)
            if hi > lo:
                index = np.arange(lo, hi) % self._size
                out[lo - start : hi - start] = self._ring[index]
        return out.tobytes()

    def level(self, seconds: float = 0.2) -> int:
        """The loudest sample the speakers played in the last `seconds` (0 to 32768)."""
        audio = np.frombuffer(self.window(self._clock(), int(seconds * SAMPLE_RATE)), np.int16)
        return int(np.abs(audio.astype(np.int32)).max()) if audio.size else 0

    # ----- capturing -----

    def start(self) -> None:
        if not self.available or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="abdoh-speakers", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2)

    def _run(self) -> None:
        if self._factory is None:
            try:
                import comtypes

                comtypes.CoInitialize()
            except Exception:
                log.debug("CoInitialize failed (COM may already be set up)", exc_info=True)
        factory = self._factory or LoopbackCapture
        failures = 0
        while not self._stop.is_set():
            try:
                capture = factory()
            except Exception as e:
                failures += 1
                if failures == 1:
                    log.warning("Can't hear what the speakers play: %s", e)
                self._stop.wait(RETRY_SECONDS)
                continue
            if failures:
                log.info("Hearing what the speakers play again")
            failures = 0
            try:
                self._capture(capture)
            except Exception as e:
                log.info("Speaker capture stopped (%s); starting it again", e)
            finally:
                capture.close()

    def _capture(self, capture) -> None:
        """Read packets until stopped, or until the default speakers change."""
        checked = self._clock()
        while not self._stop.wait(POLL_SECONDS):
            for samples, start_time in capture.packets():
                self.write(samples, start_time)
            if self._clock() - checked >= CHECK_DEVICE_SECONDS:
                checked = self._clock()
                if capture.device_changed():
                    log.info("The default speakers changed")
                    return


class LoopbackCapture:
    """Windows' loopback capture of the default speakers, converted by Windows to 16 kHz mono
    16-bit. Only used on the capture thread (COM objects stay on the thread that made them)."""

    LOOPBACK, AUTOCONVERT, SRC_QUALITY = 0x00020000, 0x80000000, 0x08000000
    SILENT = 0x2  # AUDCLNT_BUFFERFLAGS_SILENT
    BUFFER = 2_000_000  # 200 ms, in 100-ns units

    def __init__(self):
        import ctypes

        import comtypes

        from abdoh import winaudio

        com = _com()
        device = winaudio.default_device()
        self.device = winaudio.device_id(device)
        client = device.Activate(com["client"]._iid_, comtypes.CLSCTX_ALL, None)
        self._client = client.QueryInterface(com["client"])
        wanted = com["format"](1, 1, SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16, 0)  # PCM mono 16-bit
        flags = self.LOOPBACK | self.AUTOCONVERT | self.SRC_QUALITY
        self._client.Initialize(0, flags, self.BUFFER, 0, ctypes.byref(wanted), None)
        capture = self._client.GetService(com["capture"]._iid_)
        self._capture = capture.QueryInterface(com["capture"])
        self._client.Start()

    def packets(self):
        """(samples, start time) for every packet waiting. Times are on perf_counter's clock:
        Windows stamps each packet with the performance counter in 100-ns units."""
        import ctypes

        while self._capture.GetNextPacketSize():
            data, frames, flags, _position, qpc = self._capture.GetBuffer()
            arrived = time.perf_counter()
            if flags & self.SILENT or not data:
                samples = np.zeros(frames, dtype=np.int16)
            else:
                pointer = ctypes.cast(data, ctypes.POINTER(ctypes.c_int16))
                samples = np.ctypeslib.as_array(pointer, shape=(frames,)).copy()
            self._capture.ReleaseBuffer(frames)
            start = qpc * 1e-7 if qpc else arrived - frames / SAMPLE_RATE
            if abs(start - arrived) > 1.0:  # a time stamp from another clock: don't trust it
                start = arrived - frames / SAMPLE_RATE
            yield samples, start

    def device_changed(self) -> bool:
        from abdoh import winaudio

        try:
            return winaudio.device_id(winaudio.default_device()) != self.device
        except Exception:
            return True

    def close(self) -> None:
        try:
            self._client.Stop()
        except Exception:
            log.debug("Couldn't stop the speaker capture", exc_info=True)


def _com():
    """The COM interface definitions for loopback capture, made on first use."""
    if hasattr(_com, "cache"):
        return _com.cache
    from ctypes import (
        HRESULT,
        POINTER,
        Structure,
        c_longlong,
        c_ubyte,
        c_uint,
        c_ulong,
        c_ulonglong,
        c_ushort,
        c_void_p,
    )

    from comtypes import COMMETHOD, GUID, IUnknown

    class WAVEFORMATEX(Structure):
        _pack_ = 1
        _fields_ = [
            ("wFormatTag", c_ushort),
            ("nChannels", c_ushort),
            ("nSamplesPerSec", c_ulong),
            ("nAvgBytesPerSec", c_ulong),
            ("nBlockAlign", c_ushort),
            ("wBitsPerSample", c_ushort),
            ("cbSize", c_ushort),
        ]

    def unused(name):  # keeps the method order right for calls we never make
        return COMMETHOD([], HRESULT, name)

    class IAudioClient(IUnknown):
        _iid_ = GUID("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")
        _methods_ = (
            COMMETHOD([], HRESULT, "Initialize",
                      (["in"], c_uint, "mode"), (["in"], c_ulong, "flags"),
                      (["in"], c_longlong, "buffer"), (["in"], c_longlong, "period"),
                      (["in"], POINTER(WAVEFORMATEX), "format"), (["in"], c_void_p, "session")),
            unused("GetBufferSize"),
            unused("GetStreamLatency"),
            unused("GetCurrentPadding"),
            unused("IsFormatSupported"),
            unused("GetMixFormat"),
            unused("GetDevicePeriod"),
            COMMETHOD([], HRESULT, "Start"),
            COMMETHOD([], HRESULT, "Stop"),
            unused("Reset"),
            unused("SetEventHandle"),
            COMMETHOD([], HRESULT, "GetService",
                      (["in"], POINTER(GUID), "iid"),
                      (["out"], POINTER(POINTER(IUnknown)), "service")),
        )  # fmt: skip

    class IAudioCaptureClient(IUnknown):
        _iid_ = GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")
        _methods_ = (
            COMMETHOD([], HRESULT, "GetBuffer",
                      (["out"], POINTER(POINTER(c_ubyte)), "data"),
                      (["out"], POINTER(c_uint), "frames"), (["out"], POINTER(c_ulong), "flags"),
                      (["out"], POINTER(c_ulonglong), "position"),
                      (["out"], POINTER(c_ulonglong), "qpc")),
            COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], c_uint, "frames")),
            COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], POINTER(c_uint), "frames")),
        )  # fmt: skip

    _com.cache = {"format": WAVEFORMATEX, "client": IAudioClient, "capture": IAudioCaptureClient}
    return _com.cache
