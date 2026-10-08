"""Wake word detection behind a WakeWordEngine interface."""

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

from abdoh.audio.mic import SAMPLE_RATE

log = logging.getLogger(__name__)


class WakeWordEngine(ABC):
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


def wait_for_wake_word(
    read: Callable[[], bytes],
    engine: WakeWordEngine,
    should_stop: Callable[[], bool] = lambda: False,
) -> bool:
    """Read blocks until the wake word is heard (True) or should_stop() is true (False)."""
    while not should_stop():
        if engine.detect(read()):
            return True
    return False
