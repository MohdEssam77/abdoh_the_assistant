"""Test doubles for hardware-dependent pieces."""

import numpy as np

from abdoh.audio.wakeword import WakeWordEngine

BLOCK = 1600  # samples per 0.1 s block


def tone_block(level: int = 3000) -> bytes:
    return (np.ones(BLOCK, dtype=np.int16) * level).tobytes()


def silent_block() -> bytes:
    return np.zeros(BLOCK, dtype=np.int16).tobytes()


class FakeMic:
    """Plays back a list of blocks; then silence forever."""

    def __init__(self, blocks: list[bytes]):
        self.blocks = list(blocks)
        self.history: list[bytes] = []
        self.cleared = 0

    def read(self) -> bytes:
        block = self.blocks.pop(0) if self.blocks else silent_block()
        self.history.append(block)
        return block

    def recent(self) -> bytes:
        return b"".join(self.history[-30:])

    def clear(self) -> None:
        self.cleared += 1
        self.history.clear()


class FakeWakeWord(WakeWordEngine):
    """Detects the wake word on the Nth block read."""

    def __init__(self, fire_on: int = 1):
        self.fire_on = fire_on
        self.count = 0

    def detect(self, block: bytes) -> bool:
        self.count += 1
        return self.count == self.fire_on


class FakeTranscriber:
    def __init__(self, texts: list[str]):
        self.texts = list(texts)
        self.calls: list[bytes] = []

    def transcribe(self, audio: bytes) -> str:
        self.calls.append(audio)
        return self.texts.pop(0) if self.texts else ""
