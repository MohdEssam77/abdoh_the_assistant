"""Wake word → record → transcribe: turns microphone audio into one request's text."""

import json
import logging
from collections.abc import Callable
from pathlib import Path

from abdoh.audio.mic import SAMPLE_RATE
from abdoh.audio.recorder import estimate_threshold, record_until_silence
from abdoh.audio.wakeword import WakeWordEngine, load_vosk_model, wait_for_wake_word
from abdoh.commands.matcher import strip_wake_words
from abdoh.config import Config
from abdoh.speech.tts import Speaker

log = logging.getLogger(__name__)

FOLLOW_UP_WAIT_SECONDS = 5.0


def listen_for_request(
    mic,
    engine: WakeWordEngine,
    transcriber,
    speaker: Speaker,
    cfg: Config,
    should_stop: Callable[[], bool] = lambda: False,
    on_wake: Callable[[], None] = lambda: None,
) -> str | None:
    """Wait for the wake word and return what was said (wake word included), or None if stopped.

    Audio from just before the wake word is included, so "Good morning Abdoh" works.
    If only the wake word was said, Abdoh asks "Yes?" and records one more utterance.
    """
    if not wait_for_wake_word(mic.read, engine, should_stop):
        return None
    on_wake()
    before = mic.recent()
    threshold = estimate_threshold(before)
    after = record_until_silence(mic.read, threshold, cfg.silence_seconds, cfg.max_record_seconds)
    text = transcriber.transcribe(before + after)

    if not strip_wake_words(text, cfg.wake_words + cfg.wake_word_aliases):
        speaker.say("Yes?")
        mic.clear()
        audio = record_until_silence(
            mic.read,
            threshold,
            cfg.silence_seconds,
            cfg.max_record_seconds,
            wait_seconds=FOLLOW_UP_WAIT_SECONDS,
        )
        text = transcriber.transcribe(audio)

    mic.clear()
    engine.reset()
    return text


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
