"""Hearing you while Krekos talks: the microphone, minus Krekos's own voice, watched for speech.

The daemon feeds every microphone block to `VoiceWatch.feed()` while a reply is running. Each
block is cleaned with what the speakers played at the same time (audio/loopback.py and
audio/echo.py), then Silero VAD looks for speech in 32 ms frames. `feed()` turns True once
enough recent frames are speech that is clearly louder than what is left of the echo.

The watch also learns how much of Krekos's voice reaches the microphone at all. Where that is
very little (a quiet microphone, a laptop with its speakers far from it), the echo canceller
has nothing to learn from and plays safe: it muffles you too for a while. So speech on the
raw microphone that is much louder than Krekos's voice could be there counts as well.
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
KEEP_SECONDS = 1.0  # audio kept for the start of what you said
PRE_ROLL_SECONDS = 0.5  # how far before the moment of detection the recording starts
# The speakers' newest ~30 ms reach Krekos late; take the reference a little further back. The
# echo canceller finds the real delay itself (anything from 0 to 800 ms works).
REFERENCE_LEAD_SECONDS = 0.04
RESYNC_SECONDS = 0.03  # follow the microphone's timing when it is this far off on average
# How much of Krekos's voice reaches the microphone: learned from blocks where the speakers
# played at least REFERENCE_ACTIVE, over the last ECHO_BLOCKS of them (the median, so you
# talking now and then doesn't count). Until ECHO_LEARNED blocks, assume all of it does.
REFERENCE_ACTIVE = 32768 * 10 ** (-50 / 20)
ECHO_BLOCKS = 30
ECHO_LEARNED = 10
ECHO_SPAN = 4  # blocks: the echo can come this much later than the sound left the speakers
RAW_MARGIN = 4.0  # raw speech counts when it is this much (12 dB) louder than any echo could be


def _rms(frame: bytes) -> float:
    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(samples**2))) if samples.size else 0.0


class SpeakerEcho:
    """The microphone without what the speakers played at the same time. `tap`: SpeakerTap,
    `canceller`: EchoCanceller (one per stream: it learns from one unbroken stream).

    It learns how much of the speakers' sound reaches the microphone. While nothing plays, or
    where hardly any of it reaches the microphone, `clean()` gives back the block itself: the
    canceller only changes what it must. The voice watch below and the wake word (music or a
    video playing while you call Krekos) each have one."""

    def __init__(self, tap, canceller):
        self.tap = tap
        self.canceller = canceller
        self._echo_ratios: deque[float] = deque(maxlen=ECHO_BLOCKS)  # learned across replies
        self._played: deque[float] = deque(maxlen=ECHO_SPAN)  # the speakers' recent levels
        self.forget_timing()

    @property
    def available(self) -> bool:
        return (
            self.tap is not None
            and getattr(self.tap, "available", False)
            and self.canceller is not None
        )

    def forget_timing(self) -> None:
        """Start the speakers' stream afresh with the next block (what was learned about the
        room is kept)."""
        self._time = None
        self._drift = 0.0
        self._played.clear()

    # ----- how much of the speakers' sound reaches the microphone -----

    def echo_gain(self) -> float:
        """The microphone's level over the speakers' level while they play (1.0: unknown)."""
        if len(self._echo_ratios) < ECHO_LEARNED:
            return 1.0
        return float(np.median(self._echo_ratios))

    def _echo_level(self) -> float:
        """The loudest the speakers' sound could be at the microphone right now."""
        return self.echo_gain() * max(self._played, default=0.0)

    def _quiet_echo(self) -> bool:
        """The speakers can't be heard at the microphone now: the raw audio is as good."""
        return self._echo_level() * RAW_MARGIN < MIN_LEVEL

    def _learn(self, raw: bytes, speakers: bytes) -> None:
        self._played.append(_rms(speakers))
        played = max(self._played)
        if played >= REFERENCE_ACTIVE:
            self._echo_ratios.append(_rms(raw) / played)

    # ----- cleaning -----

    def cancel(self, block: bytes, arrival: float) -> bytes:
        """The block with the speakers' sound taken out, always (`arrival`: when it came from
        the microphone)."""
        usable = len(block) - len(block) % FRAME_BYTES
        if not usable:
            return block
        speakers = self.tap.window(self._reference_time(usable, arrival), usable // 2)
        cleaned = self.canceller.clean(block[:usable], speakers) + block[usable:]
        self._learn(block, speakers)
        return cleaned

    def clean(self, block: bytes, arrival: float) -> bytes:
        """The block without the speakers' sound; the very same block while they can't be
        heard at the microphone (nothing plays, or it hardly reaches it)."""
        cleaned = self.cancel(block, arrival)
        return block if self._quiet_echo() else cleaned

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


class VoiceWatch(SpeakerEcho):
    """Tells when you start talking over Krekos. `tap`: SpeakerTap, `canceller`: EchoCanceller,
    `vad` and `raw_vad`: SileroVads of its own, for the cleaned and the raw microphone (their
    state is separate from the recorder's). Without `raw_vad` only the cleaned audio counts."""

    def __init__(self, tap, canceller, vad, sensitivity: str = "medium", raw_vad=None):
        self.vad = vad
        self.raw_vad = raw_vad
        self.sensitivity = sensitivity
        self._floor = MIN_LEVEL
        self._recent = bytearray()  # cleaned
        self._recent_raw = bytearray()
        super().__init__(tap, canceller)
        self.idle()

    @property
    def available(self) -> bool:
        return super().available and self.vad is not None

    @property
    def sensitivity(self) -> str:
        return self._sensitivity

    @sensitivity.setter
    def sensitivity(self, value: str) -> None:
        self._sensitivity = value if value in SENSITIVITY else "medium"

    def idle(self) -> None:
        """No reply is running: forget the speech history (what was learned about the room and
        the background level is kept)."""
        self.forget_timing()
        self._recent.clear()
        self._recent_raw.clear()
        self.rearm()

    def rearm(self) -> None:
        """Listen for the next time you talk (after `feed()` fired)."""
        self._fired = False
        self._hot: deque[bool] = deque(maxlen=6)
        self._pending = b""
        self._pending_raw = b""
        for vad in (self.vad, self.raw_vad):
            if vad is not None:
                vad.reset()

    # ----- cleaning -----

    def clean(self, block: bytes, arrival: float) -> bytes:
        """As SpeakerEcho's, keeping the last second (cleaned and raw) for `pre_roll()`."""
        cleaned = self.cancel(block, arrival)
        self._keep(self._recent, cleaned)
        self._keep(self._recent_raw, block)
        return block if self._quiet_echo() else cleaned

    @staticmethod
    def _keep(buffer: bytearray, audio: bytes) -> None:
        buffer += audio
        excess = len(buffer) - int(KEEP_SECONDS * BYTES_PER_SECOND)
        if excess > 0:
            del buffer[:excess]

    # ----- listening -----

    def feed(self, block: bytes, arrival: float) -> bool:
        """Clean one microphone block and look for you talking. True once, when you are."""
        if not self.available:
            return False
        self.clean(block, arrival)
        if self._fired:
            return False
        cleaned = bytes(self._recent[-len(block) :])
        need, window, threshold = SENSITIVITY[self._sensitivity]
        audio, self._pending = self._frames(self._pending + cleaned)
        raw, self._pending_raw = self._frames(self._pending_raw + block)
        echo = self._echo_level()
        for frame, raw_frame in zip(audio, raw, strict=False):
            level = _rms(frame)
            self._floor = min(level, self._floor * FLOOR_RISE) if level > 0 else self._floor
            self._floor = max(self._floor, 1.0)
            loud = level >= max(FLOOR_FACTOR * self._floor, MIN_LEVEL)
            speech = self.vad.speech_prob(frame) >= threshold  # every frame: the model streams
            hot = loud and speech
            if self.raw_vad is not None:
                raw_speech = self.raw_vad.speech_prob(raw_frame) >= threshold
                raw_loud = _rms(raw_frame) >= max(MIN_LEVEL, RAW_MARGIN * echo)
                hot = hot or (raw_loud and raw_speech)
            self._hot.append(hot)
            if sum(list(self._hot)[-window:]) >= need:
                self._fired = True
                log.info(
                    "You started talking (%s sensitivity; Krekos's voice reaches the mic at "
                    "%.0f dB)",
                    self._sensitivity,
                    20 * np.log10(max(self.echo_gain(), 1e-9)),
                )
                return True
        return False

    @staticmethod
    def _frames(audio: bytes) -> tuple[list[bytes], bytes]:
        usable = len(audio) - len(audio) % VAD_FRAME_BYTES
        frames = [audio[at : at + VAD_FRAME_BYTES] for at in range(0, usable, VAD_FRAME_BYTES)]
        return frames, audio[usable:]

    def pre_roll(self) -> bytes:
        """Audio from a little before you were heard until now (your first words), cleaned
        unless Krekos's voice doesn't reach the microphone anyway."""
        size = int((PRE_ROLL_SECONDS + 0.1) * BYTES_PER_SECOND)
        source = self._recent_raw if self._quiet_echo() else self._recent
        return bytes(source[-size:])
