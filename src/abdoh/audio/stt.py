"""Speech-to-text with faster-whisper (local, offline after the first model download)."""

import logging
import threading

import numpy as np

log = logging.getLogger(__name__)

# Whisper sizes that have an English-only version (more accurate for English, same speed).
ENGLISH_ONLY = {"tiny", "base", "small", "medium"}


def model_name(size: str, language: str | None) -> str:
    """'base' + 'en' -> 'base.en'; other languages (or auto) keep the multilingual model."""
    return f"{size}.en" if language == "en" and size in ENGLISH_ONLY else size


class Transcriber:
    def __init__(self, model_size: str = "base", language: str | None = "en"):
        self.model_size = model_name(model_size, language)
        self.language = language
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            log.info("Loading Whisper model %r (downloads on first use)...", self.model_size)
            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        return self._model

    def transcribe(self, audio: bytes) -> str:
        """Transcribe 16 kHz mono int16 audio to text."""
        if not audio:
            return ""
        samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        with self._lock:
            segments, _ = self._load().transcribe(
                samples,
                language=self.language,
                beam_size=1,
                initial_prompt="Hey Abdoh.",
                condition_on_previous_text=False,
                without_timestamps=True,
            )
            text = " ".join(s.text.strip() for s in segments).strip()
        log.debug("Transcript: %r", text)
        return text
