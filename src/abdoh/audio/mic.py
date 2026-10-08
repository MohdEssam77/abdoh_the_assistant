"""Microphone input: 16 kHz mono int16 blocks, plus a rolling buffer of recent audio."""

import logging
import queue
from collections import deque

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2  # int16 mono


class MicrophoneError(RuntimeError):
    """The microphone could not be opened or stopped delivering audio."""


class Microphone:
    """Reads audio blocks from the default input device.

    Every block returned by `read()` is also kept in a rolling buffer of the last
    `buffer_seconds`, so speech said just before the wake word can be recovered.
    """

    def __init__(self, block_seconds: float = 0.1, buffer_seconds: float = 3.0):
        self.block_seconds = block_seconds
        self._queue: queue.Queue[bytes] = queue.Queue()
        self._buffer: deque[bytes] = deque(maxlen=max(1, int(buffer_seconds / block_seconds)))
        self._stream = None

    def start(self) -> None:
        import sounddevice as sd

        try:
            self._stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                blocksize=int(SAMPLE_RATE * self.block_seconds),
                dtype="int16",
                channels=1,
                callback=self._callback,
            )
            self._stream.start()
        except Exception as e:
            self._stream = None
            raise MicrophoneError(f"Could not open microphone: {e}") from e

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

    def _callback(self, indata, frames, time, status) -> None:
        if status:
            log.debug("Mic status: %s", status)
        self._queue.put(bytes(indata))

    def read(self, timeout: float = 2.0) -> bytes:
        try:
            block = self._queue.get(timeout=timeout)
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
