"""Speech-to-text with faster-whisper, on this computer.

The default speech model ships with Abdoh in models/faster-whisper-base.en (put there by
scripts/download_models.py), so nothing is downloaded on the first start. Any other model is
downloaded by faster-whisper the first time it's used.
"""

import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

# Whisper sizes that have an English-only version (more accurate for English, same speed).
ENGLISH_ONLY = {"tiny", "base", "small", "medium"}
# A model folder needs these, and not empty (an interrupted download leaves empty files).
REQUIRED_FILES = ("model.bin", "config.json")


def model_name(size: str, language: str | None) -> str:
    """'base' + 'en' -> 'base.en'; other languages (or auto) keep the multilingual model."""
    return f"{size}.en" if language == "en" and size in ENGLISH_ONLY else size


def model_folder(name: str) -> str:
    """Where a model that ships with Abdoh lives, relative to the app folder."""
    return f"models/faster-whisper-{name}"


def is_complete(folder: Path) -> bool:
    folder = Path(folder)
    return all((folder / f).is_file() and (folder / f).stat().st_size > 0 for f in REQUIRED_FILES)


class Transcriber:
    def __init__(
        self,
        model_size: str = "base",
        language: str | None = "en",
        model_dir: Path | None = None,
        make_model: Callable | None = None,
    ):
        self.model_size = model_name(model_size, language)
        self.language = language
        self.model_dir = Path(model_dir) if model_dir else None  # a bundled copy, if any
        self._make_model = make_model  # faster_whisper.WhisperModel (a fake in tests)
        self._model = None
        self._lock = threading.Lock()

    @classmethod
    def from_config(cls, cfg) -> "Transcriber":
        """The model from the settings, using the copy that ships with Abdoh when there is one."""
        name = model_name(cfg.whisper_model, cfg.language)
        return cls(cfg.whisper_model, cfg.language, model_dir=cfg.resolve(model_folder(name)))

    def _load(self):
        if self._model is None:
            make = self._make_model
            if make is None:
                # Plain HTTPS downloads: the Xet transfer path left an empty model.bin in the
                # built app (huggingface_hub 2.x).
                os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
                from faster_whisper import WhisperModel

                make = WhisperModel
            if self.model_dir is not None and is_complete(self.model_dir):
                log.info("Loading Whisper model %r from %s", self.model_size, self.model_dir)
                source = str(self.model_dir)
            else:
                log.info("Loading Whisper model %r (downloads on first use)...", self.model_size)
                source = self.model_size
            self._model = make(source, device="cpu", compute_type="int8")
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
