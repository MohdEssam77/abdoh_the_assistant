"""Wake word → record → transcribe: turns microphone audio into one request's text."""

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

from abdoh.audio.mic import BYTES_PER_SECOND, SAMPLE_RATE
from abdoh.audio.recorder import energy_detector, estimate_threshold, peak, record_until_silence
from abdoh.audio.wakeword import WakeWordEngine, load_vosk_model, wait_for_trigger
from abdoh.commands.matcher import has_wake_word, strip_wake_words
from abdoh.config import Config
from abdoh.speech.tts import Speaker

log = logging.getLogger(__name__)

FOLLOW_UP_WAIT_SECONDS = 5.0
# How long to wait for speech right after the wake word ("Hey Abdoh … what time is it").
START_WAIT_SECONDS = 0.8
# Audio from before the wake word fed to the VAD, so it knows if you were mid-sentence.
VAD_WARMUP_SECONDS = 0.5
# After the hotkey: how long to wait for you to start talking, and for the chime to finish.
PUSH_TO_TALK_WAIT_SECONDS = 4.0
CHIME_SECONDS = 0.15
# After Claude asks you something: how long to wait for you to start answering.
ANSWER_WAIT_SECONDS = 5.0
# After a trusted wake word ("Hey Abdoh ... what time is it"): how long to wait for the request.
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
) -> str | None:
    """Wait for the wake word and return the request that was said, or None if stopped.

    With a trusted wake word engine (your trained model), the request is what you say after the
    wake word; `on_listen` (a chime) confirms the wake-up. If you say nothing, Abdoh asks
    "Yes?" and records one more utterance.

    With the Vosk fallback, the audio from just before the wake word is transcribed too (so
    "Good morning Abdoh" works) and the wake word is included in the result; "" is returned
    if the transcript doesn't contain the wake word (a false wake-up).
    With a `vad` (SileroVad), the end of speech is found by voice activity, else by loudness.
    If `pressed()` turns true (the hotkey), one request is recorded with no wake word needed.
    With `answer` (Claude just asked you something), one reply is recorded right away, the same
    way; "" if you don't start talking within `answer_wait` seconds.
    When nothing is said after the hotkey or a question, `on_nothing(loudest)` gets the loudest
    sample level heard meanwhile (close to 0 means the microphone is muted).
    """
    if answer:
        return _push_to_talk(mic, engine, transcriber, cfg, vad, on_listen, answer_wait, on_nothing)
    trigger = wait_for_trigger(mic.read, engine, should_stop, pressed)
    if trigger is None:
        return None
    if trigger == "hotkey":
        return _push_to_talk(
            mic, engine, transcriber, cfg, vad, on_listen, PUSH_TO_TALK_WAIT_SECONDS, on_nothing
        )
    on_wake()
    if engine.trusted:
        return _after_wake_word(mic, engine, transcriber, speaker, cfg, vad, on_listen)
    t_wake = time.perf_counter()
    before = mic.recent()
    is_speech = _speech_detector(vad, before)
    after = record_until_silence(
        mic.read,
        is_speech,
        cfg.silence_seconds,
        cfg.max_record_seconds,
        wait_seconds=max(cfg.silence_seconds, START_WAIT_SECONDS),
    )
    t_recorded = time.perf_counter()
    text = transcriber.transcribe(before + after)
    log.debug(
        "Latency: recording %.2fs, transcription %.2fs",
        t_recorded - t_wake,
        time.perf_counter() - t_recorded,
    )
    wake_words = cfg.wake_words + cfg.wake_word_aliases

    if not has_wake_word(text, wake_words):
        log.info("Ignoring false wake-up (heard %r)", text)
        text = ""
    elif not strip_wake_words(text, wake_words):
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
        text = transcriber.transcribe(audio)

    mic.clear()
    engine.reset()
    return text


def _after_wake_word(mic, engine, transcriber, speaker, cfg: Config, vad, on_listen) -> str:
    """The request said right after a trusted wake word (the wake word itself is left out)."""
    is_speech = _speech_detector(vad, mic.recent())
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
    text = transcriber.transcribe(audio) if audio else ""
    mic.clear()
    engine.reset()
    return text


def _push_to_talk(
    mic, engine, transcriber, cfg: Config, vad, on_listen, wait_seconds: float, on_nothing
) -> str:
    on_listen()  # the "listening" chime
    time.sleep(CHIME_SECONDS)
    mic.clear()  # start fresh, without the chime (or the end of Abdoh's own reply)
    is_speech = _speech_detector(vad, b"")
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
    text = transcriber.transcribe(audio) if audio else ""
    mic.clear()
    engine.reset()
    return text


def _speech_detector(vad, before: bytes) -> Callable[[bytes], bool]:
    if vad is None:
        return energy_detector(estimate_threshold(before))
    vad.reset()
    vad.speech_prob(before[-int(VAD_WARMUP_SECONDS * BYTES_PER_SECOND) :])
    return vad.is_speech


def calibrate(mic, model_path: Path, times: int = 5, out: Callable[[str], None] = print) -> None:
    """Print what Vosk (full vocabulary) hears, to find good wake_word_aliases."""
    import vosk

    rec = vosk.KaldiRecognizer(load_vosk_model(model_path), SAMPLE_RATE)
    out(f'Say "Abdoh" {times} times, pausing between each.')
    heard = 0
    while heard < times:
        if rec.AcceptWaveform(mic.read()):
            text = json.loads(rec.Result()).get("text", "")
            if text:
                heard += 1
                out(f"  {heard}: {text}")
    out("Add the words you saw above to wake_word_aliases in config.yaml.")
