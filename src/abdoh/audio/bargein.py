"""Hearing you while Abdoh talks: the microphone, minus Abdoh's own voice, watched for speech.

The daemon feeds every microphone block to `VoiceWatch.feed()` while a reply is running. Each
block is cleaned with what the speakers played at the same time (audio/loopback.py and
audio/echo.py), then Silero VAD looks for speech in 32 ms frames. `feed()` turns True once
enough recent frames are both speech-like and clearly louder than what is left of the echo.
"""

import logging
from collections import deque

import numpy as np

from abdoh.audio.echo import FRAME_BYTES
from abdoh.audio.mic import BYTES_PER_SECOND

log = logging.getLogger(__name__)

VAD_FRAME_BYTES = 512 * 2  # one Silero step: 32 ms
# How many of the last frames must be hot, out of how many, and the speech probability needed.
SENSITIVITY = {"high": (2, 3, 0.4), "medium": (3, 5, 0.5), "low": (5, 6, 0.6)}
MIN_LEVEL = 32768 * 10 ** (-60 / 20)  # -60 dBFS: quieter than this is never you talking
FLOOR_FACTOR = 3.0  # and a frame must be this many times louder than the background
FLOOR_RISE = 1.01  # the background level creeps up by 1% a frame, and drops at once
KEEP_SECONDS = 1.0  # cleaned audio kept for the start of what you said
PRE_ROLL_SECONDS = 0.5  # how far before the moment of detection the recording starts
# The speakers' newest ~30 ms reach Abdoh late; take the reference a little further back. The
# echo canceller finds the real delay itself (anything from 0 to 800 ms works).
REFERENCE_LEAD_SECONDS = 0.04
RESYNC_SECONDS = 0.03  # follow the microphone's timing when it is this far off on average


def _rms(frame: bytes) -> float:
    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(samples**2))) if samples.size else 0.0


class VoiceWatch:
    """Tells when you start talking over Abdoh. `tap`: SpeakerTap, `canceller`: EchoCanceller,
    `vad`: a SileroVad of its own (its state is separate from the recorder's)."""

    def __init__(self, tap, canceller, vad, sensitivity: str = "medium"):
        self.tap = tap
        self.canceller = canceller
        self.vad = vad
        self.sensitivity = sensitivity
        self._floor = MIN_LEVEL
        self._recent = bytearray()
        self.idle()

    @property
    def available(self) -> bool:
        return (
            self.tap is not None
            and getattr(self.tap, "available", False)
            and self.canceller is not None
            and self.vad is not None
        )

    @property
    def sensitivity(self) -> str:
        return self._sensitivity

    @sensitivity.setter
    def sensitivity(self, value: str) -> None:
        self._sensitivity = value if value in SENSITIVITY else "medium"

    def idle(self) -> None:
        """No reply is running: forget the speech history (the background level is kept)."""
        self._time = None
        self._drift = 0.0
        self._pending = b""
        self._hot: deque[bool] = deque(maxlen=6)
        self._fired = False
        self._recent.clear()
        if self.vad is not None:
            self.vad.reset()

    def rearm(self) -> None:
        """Listen for the next time you talk (after `feed()` fired)."""
        self._fired = False
        self._hot.clear()
        self._pending = b""
        if self.vad is not None:
            self.vad.reset()

    def clean(self, block: bytes, arrival: float) -> bytes:
        """The block with the speakers' sound taken out. `arrival`: when it came from the mic."""
        usable = len(block) - len(block) % FRAME_BYTES
        if not usable:
            return block
        speakers = self.tap.window(self._reference_time(usable, arrival), usable // 2)
        cleaned = self.canceller.clean(block[:usable], speakers) + block[usable:]
        self._recent += cleaned
        excess = len(self._recent) - int(KEEP_SECONDS * BYTES_PER_SECOND)
        if excess > 0:
            del self._recent[:excess]
        return cleaned

    def _reference_time(self, size: int, arrival: float) -> float:
        """Where the speakers' audio for this block ends. The echo canceller needs one unbroken
        stream, so each block takes the speakers' audio right after the previous block's.
        Blocks arrive unevenly; only when they are late or early on average (the two sound
        cards' clocks drift apart, or blocks were dropped) does the stream jump once."""
        target = arrival - REFERENCE_LEAD_SECONDS
        if self._time is None or abs(target - self._time) > 0.5:
            self._time, self._drift = target, 0.0
            return self._time
        self._time += size / BYTES_PER_SECOND
        self._drift += 0.05 * (target - self._time - self._drift)
        if abs(self._drift) > RESYNC_SECONDS:
            log.debug("Speaker and microphone clocks drifted %.0f ms apart", self._drift * 1000)
            self._time += self._drift
            self._drift = 0.0
        return self._time

    def feed(self, block: bytes, arrival: float) -> bool:
        """Clean one microphone block and look for you talking. True once, when you are."""
        if not self.available:
            return False
        cleaned = self.clean(block, arrival)
        if self._fired:
            return False
        need, window, threshold = SENSITIVITY[self._sensitivity]
        audio = self._pending + cleaned
        usable = len(audio) - len(audio) % VAD_FRAME_BYTES
        self._pending = audio[usable:]
        for at in range(0, usable, VAD_FRAME_BYTES):
            frame = audio[at : at + VAD_FRAME_BYTES]
            level = _rms(frame)
            self._floor = min(level, self._floor * FLOOR_RISE) if level > 0 else self._floor
            self._floor = max(self._floor, 1.0)
            loud = level >= max(FLOOR_FACTOR * self._floor, MIN_LEVEL)
            speech = self.vad.speech_prob(frame) >= threshold  # every frame: the model streams
            self._hot.append(loud and speech)
            if sum(list(self._hot)[-window:]) >= need:
                self._fired = True
                log.info("You started talking (%s sensitivity)", self._sensitivity)
                return True
        return False

    def pre_roll(self) -> bytes:
        """Cleaned audio from a little before you were heard until now: your first words."""
        size = int((PRE_ROLL_SECONDS + 0.1) * BYTES_PER_SECOND)
        return bytes(self._recent[-size:])
