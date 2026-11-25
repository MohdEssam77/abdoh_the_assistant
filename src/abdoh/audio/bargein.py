"""Hearing you while Abdoh talks: the microphone, minus Abdoh's own voice, watched for speech.

The daemon feeds every microphone block to `VoiceWatch.feed()` while a reply is running. Each
block is cleaned with what the speakers played at the same time (audio/loopback.py and
audio/echo.py), then Silero VAD looks for speech in 32 ms frames. `feed()` turns True once
enough recent frames are speech that is clearly louder than what is left of the echo.

The watch also learns how much of Abdoh's voice reaches the microphone at all. Where that is
very little (a quiet microphone, a laptop with its speakers far from it), the echo canceller
has nothing to learn from and plays safe: it muffles you too for a while. So speech on the
raw microphone that is much louder than Abdoh's voice could be there counts as well.

Speakers can be slow: a monitor's (over HDMI or DisplayPort) or Bluetooth speakers play what
they get a few hundred milliseconds later, so Abdoh's voice keeps coming out after the reply
stopped, and the echo canceller needs a while to learn where it comes from. So the watch
judges by the loudest Abdoh played in the last second, and by how much of its voice the
canceller is known to leave: until it knows, only talk clearly louder than Abdoh's voice could
be there counts. New speakers (or a new microphone) and it learns the room again.
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
# The speakers' newest ~30 ms reach Abdoh late; take the reference a little further back. The
# echo canceller finds the real delay itself (anything from 0 to 800 ms works).
REFERENCE_LEAD_SECONDS = 0.04
RESYNC_SECONDS = 0.03  # follow the microphone's timing when it is this far off on average
# How much of Abdoh's voice reaches the microphone, and how much of it the echo canceller
# leaves: learned from blocks where the speakers played at least REFERENCE_ACTIVE, over the last
# ECHO_BLOCKS of them (the median, so you talking now and then doesn't count). Until
# ECHO_LEARNED blocks, assume all of it does, and that the canceller takes none of it out.
REFERENCE_ACTIVE = 32768 * 10 ** (-50 / 20)
ECHO_BLOCKS = 30
ECHO_LEARNED = 10
# The echo can come this much later than the sound left the speakers: slow speakers (a
# monitor, Bluetooth) play it a few hundred milliseconds late, and the room adds its reverb.
ECHO_SPAN_SECONDS = 1.0
LEVEL_CHUNK = 1600  # the speakers' level is the loudest of these 100 ms pieces
MARGIN = 4.0  # you count when you're this much (12 dB) louder than any echo could be
# Abdoh's voice has been playing this long, but the speakers it hears are silent: it plays on
# other speakers than the ones it listens to (or hearing them failed), so its own voice can't
# be told from yours. Talking over it waits until they aren't silent.
MISSING_AFTER_SECONDS = 0.6


def _rms(frame: bytes) -> float:
    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(samples**2))) if samples.size else 0.0


def _db(ratio: float) -> float:
    return 20 * float(np.log10(max(ratio, 1e-9)))


def _loudest(audio: bytes) -> float:
    """The level of the loudest LEVEL_CHUNK of `audio`."""
    samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32)
    whole = len(samples) // LEVEL_CHUNK * LEVEL_CHUNK
    if not whole:
        return _rms(audio)
    chunks = samples[-whole:].reshape(-1, LEVEL_CHUNK)
    return float(np.sqrt((chunks**2).mean(axis=1)).max())


class VoiceWatch:
    """Tells when you start talking over Abdoh. `tap`: SpeakerTap, `canceller`: EchoCanceller,
    `vad` and `raw_vad`: SileroVads of its own, for the cleaned and the raw microphone (their
    state is separate from the recorder's). Without `raw_vad` only the cleaned audio counts."""

    def __init__(self, tap, canceller, vad, sensitivity: str = "medium", raw_vad=None):
        self.tap = tap
        self.canceller = canceller
        self.vad = vad
        self.raw_vad = raw_vad
        self.sensitivity = sensitivity
        self._floor = MIN_LEVEL
        self._recent = bytearray()  # cleaned
        self._recent_raw = bytearray()
        # Learned across replies: how loud Abdoh is at the mic, and how much the canceller
        # leaves of that (cleaned over raw).
        self._echo_ratios: deque[float] = deque(maxlen=ECHO_BLOCKS)
        self._residuals: deque[float] = deque(maxlen=ECHO_BLOCKS)
        self._played = 0.0  # the loudest the speakers played in the last ECHO_SPAN_SECONDS
        self._speakers = getattr(tap, "generation", 0)  # changes when the speakers do
        self.heard_on = ""  # where you were heard last: "cleaned" or "raw" microphone (the log)
        self._speaking_since: float | None = None  # Abdoh's voice has been playing since then
        self._missing_told = False
        self.idle()

    def speaking(self, on: bool, at: float) -> None:
        """Abdoh's voice started (`on`) or stopped coming out of the speakers, at `at`
        (`time.perf_counter()`). From the speaker (PiperSpeaker.on_playing)."""
        self._speaking_since = at if on else None

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
        """No reply is running: forget the speech history (what was learned about the room and
        the background level is kept)."""
        self._time = None
        self._drift = 0.0
        self._recent.clear()
        self._recent_raw.clear()
        self.rearm()

    def forget_room(self) -> None:
        """New speakers, or a new microphone: what was learned about how Abdoh's voice reaches
        the microphone no longer holds. The echo canceller starts learning again too."""
        self._echo_ratios.clear()
        self._residuals.clear()
        self._floor = MIN_LEVEL
        reset = getattr(self.canceller, "reset", None)
        if reset is not None:
            reset()
        log.info("Learning afresh how Abdoh's voice reaches the microphone")

    def rearm(self) -> None:
        """Listen for the next time you talk (after `feed()` fired)."""
        self._fired = False
        self._hot: deque[bool] = deque(maxlen=6)
        self._pending = b""
        self._pending_raw = b""
        for vad in (self.vad, self.raw_vad):
            if vad is not None:
                vad.reset()

    # ----- how much of Abdoh reaches the microphone -----

    def echo_gain(self) -> float:
        """The microphone's level over the speakers' level while Abdoh talks (1.0: unknown)."""
        if len(self._echo_ratios) < ECHO_LEARNED:
            return 1.0
        return float(np.median(self._echo_ratios))

    def residual(self) -> float:
        """How much of Abdoh's voice the echo canceller leaves in (1.0: unknown, all of it)."""
        if len(self._residuals) < ECHO_LEARNED:
            return 1.0
        return float(np.median(self._residuals))

    def _echo_level(self) -> float:
        """The loudest Abdoh's voice could be at the microphone right now."""
        return self.echo_gain() * self._played

    def _quiet_echo(self) -> bool:
        """Abdoh's voice can't be heard at the microphone now: the raw audio is as good."""
        return self._echo_level() * MARGIN < MIN_LEVEL

    def _learn(self, raw: bytes, cleaned: bytes) -> None:
        if self._played < REFERENCE_ACTIVE:
            return
        raw_level = _rms(raw)
        self._echo_ratios.append(raw_level / self._played)
        if raw_level >= MIN_LEVEL:  # Abdoh's voice is there: what's left of it once cleaned?
            self._residuals.append(min(1.0, _rms(cleaned) / raw_level))

    def _check_speakers(self) -> None:
        speakers = getattr(self.tap, "generation", 0)
        if speakers != self._speakers:
            self._speakers = speakers
            self.forget_room()

    # ----- cleaning -----

    def clean(self, block: bytes, arrival: float) -> bytes:
        """The block without the speakers' sound (`arrival`: when it came from the mic). Where
        Abdoh's voice doesn't reach the microphone anyway, the block as it was."""
        usable = len(block) - len(block) % FRAME_BYTES
        if not usable:
            return block
        self._check_speakers()
        span = max(int(ECHO_SPAN_SECONDS * BYTES_PER_SECOND // 2), usable // 2)
        played = self.tap.window(self._reference_time(usable, arrival), span)
        speakers = played[-usable:]  # what played while this block was heard
        cleaned = self.canceller.clean(block[:usable], speakers) + block[usable:]
        self._played = _loudest(played)
        self._learn(block[:usable], cleaned[:usable])
        self._keep(self._recent, cleaned)
        self._keep(self._recent_raw, block)
        return block if self._quiet_echo() else cleaned

    @staticmethod
    def _keep(buffer: bytearray, audio: bytes) -> None:
        buffer += audio
        excess = len(buffer) - int(KEEP_SECONDS * BYTES_PER_SECOND)
        if excess > 0:
            del buffer[:excess]

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

    # ----- listening -----

    def feed(self, block: bytes, arrival: float) -> bool:
        """Clean one microphone block and look for you talking. True once, when you are."""
        if not self.available:
            return False
        self.clean(block, arrival)
        if self._fired or self._own_voice_unheard(arrival):
            return False
        cleaned = bytes(self._recent[-len(block) :])
        need, window, threshold = SENSITIVITY[self._sensitivity]
        audio, self._pending = self._frames(self._pending + cleaned)
        raw, self._pending_raw = self._frames(self._pending_raw + block)
        echo = self._echo_level()
        left = echo * self.residual()  # what the canceller may leave of Abdoh's voice
        for frame, raw_frame in zip(audio, raw, strict=False):
            level = _rms(frame)
            self._floor = min(level, self._floor * FLOOR_RISE) if level > 0 else self._floor
            self._floor = max(self._floor, 1.0)
            loud = level >= max(FLOOR_FACTOR * self._floor, MIN_LEVEL, MARGIN * left)
            speech = self.vad.speech_prob(frame) >= threshold  # every frame: the model streams
            hot = "cleaned" if loud and speech else ""
            if self.raw_vad is not None:
                raw_speech = self.raw_vad.speech_prob(raw_frame) >= threshold
                raw_loud = _rms(raw_frame) >= max(MIN_LEVEL, MARGIN * echo)
                hot = hot or ("raw" if raw_loud and raw_speech else "")
            self._hot.append(bool(hot))
            if hot:
                self.heard_on = hot
            if sum(list(self._hot)[-window:]) >= need:
                self._fired = True
                log.info(
                    "You started talking (%s sensitivity, on the %s mic; Abdoh's voice reaches "
                    "the mic at %.0f dB, %.0f dB of it left once cleaned)",
                    self._sensitivity,
                    self.heard_on,
                    _db(self.echo_gain()),
                    _db(self.residual()),
                )
                return True
        return False

    def _own_voice_unheard(self, now: float) -> bool:
        """Abdoh's voice is playing, but the speakers it hears are silent: nothing the
        microphone hears can be told from Abdoh's own voice (said once in the log)."""
        since = self._speaking_since
        if since is None or self._played >= REFERENCE_ACTIVE:
            if self._missing_told and since is not None:
                self._missing_told = False
                log.info("Abdoh's voice is heard on the speakers again")
            return False
        if now - since >= MISSING_AFTER_SECONDS and not self._missing_told:
            self._missing_told = True
            log.warning(
                "Abdoh is speaking, but %s sound silent to it: it may be playing on other "
                "speakers. Talking over it waits until they don't (the wake word and the "
                "hotkey still stop it).",
                getattr(self.tap, "device_name", "") or "the speakers",
            )
        return True

    @staticmethod
    def _frames(audio: bytes) -> tuple[list[bytes], bytes]:
        usable = len(audio) - len(audio) % VAD_FRAME_BYTES
        frames = [audio[at : at + VAD_FRAME_BYTES] for at in range(0, usable, VAD_FRAME_BYTES)]
        return frames, audio[usable:]

    def pre_roll(self) -> bytes:
        """Audio from a little before you were heard until now (your first words), cleaned
        unless Abdoh's voice doesn't reach the microphone anyway."""
        size = int((PRE_ROLL_SECONDS + 0.1) * BYTES_PER_SECOND)
        source = self._recent_raw if self._quiet_echo() else self._recent
        return bytes(source[-size:])
