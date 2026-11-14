"""Wake word detection behind a WakeWordEngine interface."""

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

from abdoh.audio.mic import SAMPLE_RATE

log = logging.getLogger(__name__)


class WakeWordEngine(ABC):
    label = "wake word"  # shown in the window

    @abstractmethod
    def detect(self, block: bytes) -> bool:
        """Feed one audio block; True when the wake word was heard."""

    def reset(self) -> None:  # noqa: B027 - optional hook
        """Forget partial audio (call after handling a request)."""


def contains_phrase(text: str, phrases: list[str]) -> bool:
    """True if any phrase appears in text as whole words (partial words don't count)."""
    padded = f" {text} "
    return any(f" {p} " in padded for p in phrases)


def load_vosk_model(model_path: Path):
    import vosk

    vosk.SetLogLevel(-1)
    if not Path(model_path).exists():
        raise FileNotFoundError(
            f"Vosk model not found at {model_path}. Run: python scripts/download_models.py"
        )
    return vosk.Model(str(model_path))


class VoskWakeWord(WakeWordEngine):
    """Offline wake word using Vosk with a grammar restricted to the wake phrases.

    Anything else is recognized as "[unk]". Phrases with words Vosk doesn't know (like "abdoh")
    are skipped, otherwise Vosk would silently shorten "hey abdoh" to "hey".
    """

    label = "Vosk (fallback until you train a Hey Abdoh model)"

    def __init__(self, model_path: Path, phrases: list[str]):
        import vosk

        self._model = load_vosk_model(model_path)
        candidates = {" ".join(p.lower().split()) for p in phrases if p.strip()}
        self.phrases = sorted(p for p in candidates if self._known(p))
        skipped = sorted(candidates - set(self.phrases))
        if skipped:
            log.info("Wake phrases not in Vosk vocabulary (skipped): %s", skipped)
        if not self.phrases:
            raise ValueError(
                "No usable wake phrases. Run `python -m abdoh calibrate` and set wake_word_aliases."
            )
        grammar = json.dumps([*self.phrases, "[unk]"])
        self._rec = vosk.KaldiRecognizer(self._model, SAMPLE_RATE, grammar)

    def _known(self, phrase: str) -> bool:
        return all(self._model.vosk_model_find_word(w) != -1 for w in phrase.split())

    def detect(self, block: bytes) -> bool:
        if self._rec.AcceptWaveform(block):
            text = json.loads(self._rec.Result()).get("text", "")
        else:
            text = json.loads(self._rec.PartialResult()).get("partial", "")
        if contains_phrase(text, self.phrases):
            log.debug("Wake word heard as %r", text)
            self._rec.Reset()
            return True
        return False

    def reset(self) -> None:
        self._rec.Reset()


def load_wake_engine(cfg, oww=None, vosk=None) -> WakeWordEngine:
    """openWakeWord with your model if it exists, otherwise Vosk (the v1 engine)."""
    model = cfg.resolve(cfg.wake_word_model)
    if model.exists():
        if oww is None:
            from abdoh.audio.oww import FEATURES_DIR, OpenWakeWord

            oww = lambda m, t: OpenWakeWord(m, cfg.resolve(FEATURES_DIR), t)  # noqa: E731
        try:
            engine = oww(model, cfg.wake_word_threshold)
            engine.label = f"openWakeWord ({model.stem})"
            return engine
        except FileNotFoundError as e:
            log.warning("%s. Run: python scripts/download_models.py. Using Vosk for now.", e)
    else:
        log.info("No wake word model at %s; using Vosk. See README: train the wake word.", model)
    vosk = vosk or (lambda path, phrases: VoskWakeWord(path, phrases))
    return vosk(cfg.resolve(cfg.vosk_model), cfg.wake_words + cfg.wake_word_aliases)


def wait_for_trigger(
    read: Callable[[], bytes],
    engine: WakeWordEngine,
    should_stop: Callable[[], bool] = lambda: False,
    pressed: Callable[[], bool] = lambda: False,
) -> str | None:
    """Read blocks until the wake word is heard ("wake") or the hotkey was pressed ("hotkey").
    None if should_stop() turned true."""
    while not should_stop():
        if pressed():
            return "hotkey"
        if engine.detect(read()):
            return "wake"
    return None


def wait_for_wake_word(
    read: Callable[[], bytes],
    engine: WakeWordEngine,
    should_stop: Callable[[], bool] = lambda: False,
) -> bool:
    """Read blocks until the wake word is heard (True) or should_stop() is true (False)."""
    return wait_for_trigger(read, engine, should_stop) == "wake"
