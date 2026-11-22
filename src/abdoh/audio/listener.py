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

# How long to wait for speech right after the wake word ("Hey Abdoh … what time is it").
START_WAIT_SECONDS = 0.8
# Audio from before the wake word fed to the VAD, so it knows if you were mid-sentence.
VAD_WARMUP_SECONDS = 0.5
# After the hotkey: how long to wait for you to start talking, and for the chime to finish.
PUSH_TO_TALK_WAIT_SECONDS = 4.0
CHIME_SECONDS = 0.15
# After Claude asks you something: how long to wait for you to start answering.
ANSWER_WAIT_SECONDS = 5.0
# After the wake word ("Hey Abdoh ... what time is it"): how long to wait for the request. If
# nothing comes, Abdoh goes back to waiting without a word: it may have woken by mistake.
WAKE_WAIT_SECONDS = 5.0
# At least this much speech after the wake word (by the speech detector, not counting the quiet
# around it) with no words in it: "I heard you, but didn't catch it" (on_unclear). Less is a
# cough or a click.
UNCLEAR_MIN_SECONDS = 0.5
# A transcription slower than this is logged: the speech model was probably out of memory.
SLOW_TRANSCRIPTION_SECONDS = 0.6
# An answer that came out as no words (an "um", a breath, a click, Abdoh's own echo): listen
# again, up to this many more times, instead of giving up on the answer.
NO_WORDS_RETRIES = 2
# While Abdoh keeps listening (a role is on, no wake word needed): audio from just before your
# speech was noticed (so your first word is kept), a longer pause to think before what you said
# counts as finished, and room for a longer answer.
SPEECH_PRE_ROLL_SECONDS = 1.0
THINKING_PAUSE_SECONDS = 1.2
LONG_ANSWER_SECONDS = 30.0


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
    on_unclear: Callable[[bytes], None] = lambda audio: None,
    hear: Callable[[bytes], bool] | None = None,
    on_speech: Callable[[], None] = lambda: None,
) -> str | None:
    """Wait for the wake word and return the request that was said, or None if stopped.

    The request is what you say after the wake word; `on_listen` (a chime) confirms the
    wake-up. If you say nothing, it goes back to waiting, silently (the wake-up may have been a
    mistake: a video, people talking).
    With a `vad` (SileroVad), the end of speech is found by voice activity, else by loudness.
    If `pressed()` turns true (the hotkey), one request is recorded with no wake word needed.
    With `answer` (Claude just asked you something), one reply is recorded right away, the same
    way; "" if you don't start talking within `answer_wait` seconds.
    When nothing is said after the hotkey or a question, `on_nothing(loudest)` gets the loudest
    sample level heard meanwhile (close to 0 means the microphone is muted).
    While waiting, every block also goes to `observe`; when it returns True (you talked over a
    reply), what `on_voice(mic)` returns is the request.
    When you talked after the wake word but no words came out, `on_unclear(audio)` gets the
    recording (and "" is returned).
    While Abdoh keeps listening, every block goes to `hear`; when it returns True (you started
    talking), `on_speech()` is called and what you say is the request, no wake word needed.
    """
    if answer:
        return _push_to_talk(mic, engine, transcriber, cfg, vad, on_listen, answer_wait, on_nothing)
    trigger = wait_for_trigger(mic.read, engine, should_stop, pressed, observe, hear)
    if trigger is None:
        return None
    if trigger == "speech":
        on_speech()
        return _after_speech(mic, engine, transcriber, cfg, vad)
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
    return _after_wake_word(mic, engine, transcriber, speaker, cfg, vad, on_listen, on_unclear)


def _after_wake_word(
    mic, engine, transcriber, speaker, cfg: Config, vad, on_listen, on_unclear=lambda audio: None
) -> str:
    """The request said right after the wake word (the wake word itself is left out)."""
    detect = speech_detector(vad, mic.recent())
    spoken = 0  # bytes the detector took for speech

    def is_speech(block: bytes) -> bool:
        nonlocal spoken
        speech = detect(block)
        spoken += len(block) if speech else 0
        return speech

    on_listen()  # heard you; keep talking
    audio = record_until_silence(
        mic.read,
        is_speech,
        cfg.silence_seconds,
        cfg.max_record_seconds,
        wait_seconds=WAKE_WAIT_SECONDS,
    )
    if not audio:  # only the wake word, or a wake-up by mistake: nothing to say
        log.info("Nothing said after the wake word")
    text = _transcribe(transcriber, audio)
    mic.clear()
    engine.reset()
    if audio and not text and spoken >= UNCLEAR_MIN_SECONDS * BYTES_PER_SECOND:
        on_unclear(audio)
    return text


def _after_speech(mic, engine, transcriber, cfg: Config, vad) -> str:
    """You started talking while Abdoh keeps listening: what you said, from a moment before it
    was noticed. You may pause to think for longer than usual."""
    keep = round(SPEECH_PRE_ROLL_SECONDS * BYTES_PER_SECOND) // 2 * 2
    before = mic.recent()[-keep:]
    # The VAD warms up on what you've said so far; the loudness fallback would take your speech
    # for the room's noise, so it starts from its usual level instead.
    audio = before + record_until_silence(
        mic.read,
        speech_detector(vad, before if vad is not None else b""),
        max(cfg.silence_seconds, THINKING_PAUSE_SECONDS),
        max(cfg.max_record_seconds, LONG_ANSWER_SECONDS),
        wait_seconds=THINKING_PAUSE_SECONDS,
    )
    text = _transcribe(transcriber, audio)
    mic.clear()
    engine.reset()
    if not text:
        log.info("Heard a sound but no words; still listening")
    return text


def _transcribe(transcriber, audio: bytes) -> str:
    """Transcribe a recording (if there is one), logging how long each part took."""
    if not audio:
        return ""
    started = time.perf_counter()
    text = transcriber.transcribe(audio)
    spent = time.perf_counter() - started
    log.info(
        "Timing: you spoke for %.1fs, understood in %.2fs", len(audio) / BYTES_PER_SECOND, spent
    )
    if spent > SLOW_TRANSCRIPTION_SECONDS:
        log.warning(
            "Slow transcription (%.2fs): the speech model was probably out of memory", spent
        )
    return text


def _push_to_talk(
    mic, engine, transcriber, cfg: Config, vad, on_listen, wait_seconds: float, on_nothing
) -> str:
    on_listen()  # the "listening" chime
    time.sleep(CHIME_SECONDS)
    mic.clear()  # start fresh, without the chime (or the end of Abdoh's own reply)
    is_speech = speech_detector(vad, b"")
    loudest = 0

    def read() -> bytes:
        nonlocal loudest
        block = mic.read()
        loudest = max(loudest, peak(block))
        return block

    text = ""
    for attempt in range(NO_WORDS_RETRIES + 1):
        audio = record_until_silence(
            read,
            is_speech,
            cfg.silence_seconds,
            cfg.max_record_seconds,
            wait_seconds=wait_seconds,
        )
        if not audio:
            on_nothing(loudest)
            break
        text = _transcribe(transcriber, audio)
        if text or attempt == NO_WORDS_RETRIES:
            break
        log.info("Heard a sound but no words; listening again")
        is_speech = speech_detector(vad, b"")
    mic.clear()
    engine.reset()
    return text


def speech_detector(vad, before: bytes) -> Callable[[bytes], bool]:
    if vad is None:
        return energy_detector(estimate_threshold(before))
    vad.reset()
    vad.speech_prob(before[-int(VAD_WARMUP_SECONDS * BYTES_PER_SECOND) :])
    return vad.is_speech
