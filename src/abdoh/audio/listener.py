"""Wake word → record → transcribe: turns microphone audio into one request's text."""

import logging
import time
from collections.abc import Callable

from abdoh.audio.mic import BYTES_PER_SECOND
from abdoh.audio.recorder import energy_detector, estimate_threshold, peak, record_until_silence
from abdoh.audio.wakeword import WakeWordEngine, wait_for_trigger
from abdoh.config import Config
from abdoh.speech.tts import Speaker

log = logging.getLogger(__name__)

FOLLOW_UP_WAIT_SECONDS = 5.0
# How long to wait for speech right after the wake word ("Hey Xanthos … what time is it").
START_WAIT_SECONDS = 0.8
# Audio from before the wake word fed to the VAD, so it knows if you were mid-sentence.
VAD_WARMUP_SECONDS = 0.5
# After the hotkey: how long to wait for you to start talking, and for the chime to finish.
PUSH_TO_TALK_WAIT_SECONDS = 4.0
CHIME_SECONDS = 0.15
# After Claude asks you something: how long to wait for you to start answering.
ANSWER_WAIT_SECONDS = 5.0
# After the wake word ("Hey Xanthos ... what time is it"): how long to wait for the request.
WAKE_WAIT_SECONDS = 3.0


def listen_for_request(
    mic,
    engine: WakeWordEngine,
    transcriber,
    speaker: Speaker,
    cfg: Config,
    should_stop: Callable[[], bool] = lambda: False,
    on_wake: Callable[[], None] = lambda: None,
    vad=None,
    pressed: Callable[[], bool] = lambda: False,
    on_listen: Callable[[], None] = lambda: None,
    answer: bool = False,
    on_nothing: Callable[[int], None] = lambda loudest: None,
    answer_wait: float = ANSWER_WAIT_SECONDS,
    observe: Callable[[bytes], bool] | None = None,
    on_voice: Callable[[object], str] = lambda mic: "",
) -> str | None:
    """Wait for the wake word and return the request that was said, or None if stopped.

    The request is what you say after the wake word; `on_listen` (a chime) confirms the
    wake-up. If you say nothing, Xanthos asks "Yes?" and records one more utterance.
    With a `vad` (SileroVad), the end of speech is found by voice activity, else by loudness.
    If `pressed()` turns true (the hotkey), one request is recorded with no wake word needed.
    With `answer` (Claude just asked you something), one reply is recorded right away, the same
    way; "" if you don't start talking within `answer_wait` seconds.
    When nothing is said after the hotkey or a question, `on_nothing(loudest)` gets the loudest
    sample level heard meanwhile (close to 0 means the microphone is muted).
    While waiting, every block also goes to `observe`; when it returns True (you talked over a
    reply), what `on_voice(mic)` returns is the request.
    """
    if answer:
        return _push_to_talk(mic, engine, transcriber, cfg, vad, on_listen, answer_wait, on_nothing)
    trigger = wait_for_trigger(mic.read, engine, should_stop, pressed, observe)
    if trigger is None:
        return None
    if trigger == "voice":
        text = on_voice(mic)
        mic.clear()
        engine.reset()
        return text
    if trigger == "hotkey":
        return _push_to_talk(
            mic, engine, transcriber, cfg, vad, on_listen, PUSH_TO_TALK_WAIT_SECONDS, on_nothing
        )
    on_wake()
    return _after_wake_word(mic, engine, transcriber, speaker, cfg, vad, on_listen)


def _after_wake_word(mic, engine, transcriber, speaker, cfg: Config, vad, on_listen) -> str:
    """The request said right after the wake word (the wake word itself is left out)."""
    is_speech = speech_detector(vad, mic.recent())
    on_listen()  # heard you; keep talking
    audio = record_until_silence(
        mic.read,
        is_speech,
        cfg.silence_seconds,
        cfg.max_record_seconds,
        wait_seconds=WAKE_WAIT_SECONDS,
    )
    if not audio:  # only the wake word
        speaker.say("Yes?")
        mic.clear()
        if vad is not None:
            vad.reset()
        audio = record_until_silence(
            mic.read,
            is_speech,
            cfg.silence_seconds,
            cfg.max_record_seconds,
            wait_seconds=FOLLOW_UP_WAIT_SECONDS,
        )
    text = _transcribe(transcriber, audio)
    mic.clear()
    engine.reset()
    return text


def _transcribe(transcriber, audio: bytes) -> str:
    """Transcribe a recording (if there is one), logging how long each part took."""
    if not audio:
        return ""
    started = time.perf_counter()
    text = transcriber.transcribe(audio)
    log.info(
        "Timing: you spoke for %.1fs, understood in %.2fs",
        len(audio) / BYTES_PER_SECOND,
        time.perf_counter() - started,
    )
    return text


def _push_to_talk(
    mic, engine, transcriber, cfg: Config, vad, on_listen, wait_seconds: float, on_nothing
) -> str:
    on_listen()  # the "listening" chime
    time.sleep(CHIME_SECONDS)
    mic.clear()  # start fresh, without the chime (or the end of Xanthos's own reply)
    is_speech = speech_detector(vad, b"")
    loudest = 0

    def read() -> bytes:
        nonlocal loudest
        block = mic.read()
        loudest = max(loudest, peak(block))
        return block

    audio = record_until_silence(
        read,
        is_speech,
        cfg.silence_seconds,
        cfg.max_record_seconds,
        wait_seconds=wait_seconds,
    )
    if not audio:
        on_nothing(loudest)
    text = _transcribe(transcriber, audio)
    mic.clear()
    engine.reset()
    return text


def speech_detector(vad, before: bytes) -> Callable[[bytes], bool]:
    if vad is None:
        return energy_detector(estimate_threshold(before))
    vad.reset()
    vad.speech_prob(before[-int(VAD_WARMUP_SECONDS * BYTES_PER_SECOND) :])
    return vad.is_speech
