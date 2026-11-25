"""Speech-to-text, on this computer.

Two engines behind one small interface (`transcribe(audio) -> text`):

- **Parakeet** (NVIDIA Parakeet TDT 0.6b v3, through onnx-asr): English, German and 23 other
  European languages, detected by itself. On accented English the v2 model made half the
  mistakes of Whisper base.en at the same speed (ABDOH_EPIC_4.md); v3 is as fast and as big
  (checked in ABDOH_EPIC_6.md: English about equal, German 5% mistakes against Whisper small's
  14% and seven times faster). Older installs have v2 (English only); it still works.
- **Whisper** (faster-whisper): any language. Used for languages Parakeet doesn't have
  (Arabic, Turkish, Hindi, ...), when its model isn't there, or when you choose it.

The models ship with Abdoh in models/ (scripts/download_models.py puts them there); a Whisper
model that isn't there is downloaded the first time it's used.
"""

import gc
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

# Whisper sizes that have an English-only version (more accurate for English, same speed).
ENGLISH_ONLY = {"tiny", "base", "small", "medium"}
ENGLISH_FALLBACK = "base"  # Whisper size for English when Parakeet can't be used
PARAKEET = "nemo-parakeet-tdt-0.6b-v3"
PARAKEET_DIR = "models/parakeet-tdt-0.6b-v3"
PARAKEET_V2 = "nemo-parakeet-tdt-0.6b-v2"  # English only: what Abdoh 0.5 and 0.6.0 shipped
PARAKEET_V2_DIR = "models/parakeet-tdt-0.6b-v2"
# The 25 languages of Parakeet v3 (NVIDIA's model card).
PARAKEET_LANGUAGES = frozenset(
    "bg hr cs da nl en et fi fr de el hu it lv lt mt pl pt ro sk sl es sv ru uk".split()
)
# With several languages Parakeet is used for these two: they can be told apart from the text.
PARAKEET_MIXES = frozenset({"en", "de"})
PARAKEET_FILES = (
    "config.json",
    "vocab.txt",
    "nemo128.onnx",
    "decoder_joint-model.int8.onnx",
    "encoder-model.int8.onnx",
)
WHISPER_FILES = ("model.bin", "config.json")
# The full model on the graphics card (abdoh/gpu.py): DirectML, on the most capable card (not
# a laptop's built-in graphics), with the processor for what DirectML can't run.
GPU_PROVIDERS = [
    (
        "DmlExecutionProvider",
        {"performance_preference": "high_performance", "device_filter": "gpu"},
    ),
    "CPUExecutionProvider",
]
# Quiet recordings (a microphone turned down in Windows) are brought up to this peak level,
# but never amplified more than MAX_GAIN (that would only amplify noise).
TARGET_PEAK = 0.9
MAX_GAIN = 100.0


def model_name(size: str, languages: list[str]) -> str:
    """'base' for English only -> 'base.en'; other languages keep the multilingual model."""
    return f"{size}.en" if languages == ["en"] and size in ENGLISH_ONLY else size


def model_folder(name: str) -> str:
    """Where a Whisper model that ships with Abdoh lives, relative to the app folder."""
    return f"models/faster-whisper-{name}"


def is_complete(folder: Path, files: tuple[str, ...] = WHISPER_FILES) -> bool:
    """A model folder with every file, none empty (an interrupted download leaves empty files)."""
    folder = Path(folder)
    return all((folder / f).is_file() and (folder / f).stat().st_size > 0 for f in files)


def to_float(audio: bytes) -> np.ndarray:
    return np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0


def level(samples: np.ndarray) -> np.ndarray:
    """The same audio at a healthy volume (see TARGET_PEAK)."""
    peak = float(np.abs(samples).max()) if samples.size else 0.0
    if peak <= 0:
        return samples
    return samples * min(TARGET_PEAK / peak, MAX_GAIN)


class Transcriber:
    """Base class: loads its model on first use, one transcription at a time."""

    name = "speech recognition"

    def __init__(self):
        self._model = None
        self._lock = threading.Lock()
        self.last_language = "en"  # the language of the last thing heard

    def _load(self):
        raise NotImplementedError

    def _recognize(self, model, samples: np.ndarray) -> str:
        raise NotImplementedError

    def warm_up(self) -> None:
        """Load the model now (not on the first request)."""
        self.transcribe(b"\0\0" * 1600)

    def keep_warm(self) -> None:
        """Run the loaded model on a moment of silence, so it's in memory when you talk: Windows
        moves an idle model out, and the next request then waits while it comes back. Skipped
        while a real transcription runs (that one warms it anyway)."""
        if self._model is None or not self._lock.acquire(blocking=False):
            return
        try:
            language = self.last_language
            self._warm(self._model, np.zeros(1600, dtype=np.float32))
            self.last_language = language  # a warm-up isn't something you said
        except Exception:
            log.debug("Couldn't warm the speech model", exc_info=True)
        finally:
            self._lock.release()

    def _warm(self, model, samples: np.ndarray) -> None:
        self._recognize(model, samples)

    def transcribe(self, audio: bytes) -> str:
        """Transcribe 16 kHz mono int16 audio to text."""
        if not audio:
            return ""
        samples = level(to_float(audio))
        with self._lock:
            if self._model is None:
                self._model = self._load()
            text = self._recognize(self._model, samples).strip()
        log.debug("Transcript: %r", text)
        return text


class ParakeetTranscriber(Transcriber):
    """Parakeet: the compact model on the processor, or (`gpu_dir`, v3 only) the full-size one
    on the graphics card. If the card fails, it goes back to the processor until Abdoh restarts."""

    name = "Parakeet"

    def __init__(
        self,
        model_dir: Path,
        make_model: Callable | None = None,
        languages: list[str] | None = None,
        gpu_dir: Path | None = None,
    ):
        super().__init__()
        self.model_dir = Path(model_dir)
        self.v3 = not self.model_dir.name.endswith("v2")
        self.model_id = PARAKEET if self.v3 else PARAKEET_V2
        self.languages = list(languages or ["en"])
        self._make_model = make_model  # onnx_asr.load_model (a fake in tests)
        self.gpu_dir = Path(gpu_dir) if gpu_dir is not None and self.v3 else None
        self.on_gpu = False  # the model now in use runs on the graphics card
        self.gpu_failed = False  # it did, then failed: the processor until Abdoh restarts

    def _make(self) -> Callable:
        if self._make_model is not None:
            return self._make_model
        import onnx_asr

        return onnx_asr.load_model

    def _load(self):
        if self.gpu_dir is not None:
            try:
                model = self._load_gpu(self.gpu_dir)
                self.on_gpu = True
                return model
            except Exception:
                log.exception("Couldn't use the graphics card for speech; using the processor")
                self.gpu_dir, self.gpu_failed = None, True
        self.on_gpu = False
        return self._load_cpu()

    def _load_cpu(self):
        log.info("Loading the Parakeet speech model from %s", self.model_dir)
        return self._make()(self.model_id, self.model_dir, quantization="int8")

    def _load_gpu(self, folder: Path):
        log.info("Loading the full Parakeet model on the graphics card from %s", folder)
        model = self._make()(
            self.model_id,
            folder,
            quantization=None,
            providers=GPU_PROVIDERS,
            sess_options=_gpu_session_options(),
        )
        model.recognize(np.zeros(1600, dtype=np.float32), sample_rate=16000)  # fails here, if
        return model

    def use_gpu(self, folder: Path | None) -> bool:
        """Move to the full model on the graphics card (`folder`), or back to the processor
        (None). The new model loads while the old one keeps working, then takes over. Returns
        whether speech recognition runs on the graphics card now."""
        if not self.v3 or (folder is not None and self.gpu_failed):
            return False
        if (folder is not None) == self.on_gpu and self._model is not None:
            return self.on_gpu
        try:
            model = self._load_gpu(Path(folder)) if folder is not None else self._load_cpu()
        except Exception:
            log.exception("Couldn't move speech recognition to the graphics card")
            self.gpu_failed = True
            return self.on_gpu
        with self._lock:
            self._model = model
            self.gpu_dir = Path(folder) if folder is not None else None
            self.on_gpu = folder is not None
        gc.collect()  # the old model's memory goes back
        where = "graphics card" if self.on_gpu else "processor"
        log.info("Speech recognition runs on the %s", where)
        return self.on_gpu

    def _recognize(self, model, samples: np.ndarray) -> str:
        samples = samples.astype(np.float32)
        try:
            text = str(model.recognize(samples, sample_rate=16000))
        except Exception:
            if not self.on_gpu:
                raise
            # A driver update or a reset card: carry on with the processor.
            log.exception("Speech recognition failed on the graphics card; using the processor")
            self.gpu_dir, self.on_gpu, self.gpu_failed = None, False, True
            self._model = model = self._load_cpu()
            text = str(model.recognize(samples, sample_rate=16000))
        self.last_language = self._language_of(text)
        return text

    def _language_of(self, text: str) -> str:
        """The language it was in. v3 picks the language itself and doesn't say which; German
        shows in the words, and with one language chosen that is it."""
        if not self.v3:
            return "en"
        from abdoh.speech.tts import looks_german

        if looks_german(text):
            return "de"
        return self.languages[0] if len(self.languages) == 1 else "en"


class WhisperTranscriber(Transcriber):
    name = "Whisper"

    def __init__(
        self,
        model_size: str = "base",
        languages: list[str] | None = None,
        model_dir: Path | None = None,
        make_model: Callable | None = None,
    ):
        super().__init__()
        self.languages = list(languages or ["en"])
        self.model_size = model_name(model_size, self.languages)
        self.model_dir = Path(model_dir) if model_dir else None  # a bundled copy, if any
        self._make_model = make_model  # faster_whisper.WhisperModel (a fake in tests)
        self.last_language = self.languages[0]

    def _load(self):
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
        return make(source, device="cpu", compute_type="int8")

    def _run(self, model, samples, language: str | None):
        segments, info = model.transcribe(
            samples,
            language=language,
            beam_size=1,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        return " ".join(s.text.strip() for s in segments), info

    def _warm(self, model, samples: np.ndarray) -> None:
        self._run(model, samples, self.languages[0])  # no language detection for silence

    def _recognize(self, model, samples: np.ndarray) -> str:
        if len(self.languages) == 1:
            self.last_language = self.languages[0]
            return self._run(model, samples, self.languages[0])[0]
        text, info = self._run(model, samples, None)  # Whisper detects the language
        heard = getattr(info, "language", None)
        if heard not in self.languages:
            # It guessed a language you don't speak (short or noisy audio does that): use the
            # most likely one of yours instead.
            scores = dict(getattr(info, "all_language_probs", None) or [])
            heard = max(self.languages, key=lambda code: scores.get(code, 0.0))
            log.info("Heard %r as %s; transcribing again as %s", text, info.language, heard)
            text = self._run(model, samples, heard)[0]
        self.last_language = heard
        return text


def _gpu_session_options():
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.enable_mem_pattern = False  # DirectML needs these two
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    opts.log_severity_level = 3  # not the note that some steps run on the processor
    return opts


def parakeet_available(cfg) -> Path | None:
    """The Parakeet model's folder if it's complete (and onnx-asr is installed): v3, or else
    the English-only v2 of older installs."""
    import importlib.util

    if not importlib.util.find_spec("onnx_asr"):
        return None
    for name in (PARAKEET_DIR, PARAKEET_V2_DIR):
        folder = cfg.resolve(name)
        if is_complete(folder, PARAKEET_FILES):
            return folder
    return None


def parakeet_handles(cfg, parakeet: Path) -> bool:
    """Can this Parakeet model (v3, or the English-only v2) understand all your languages?"""
    v3 = not Path(parakeet).name.endswith("v2")
    languages = set(cfg.languages)
    if not languages <= (PARAKEET_LANGUAGES if v3 else {"en"}):
        return False
    return len(languages) == 1 or languages <= PARAKEET_MIXES


def choose_engine(cfg, parakeet: Path | None) -> str:
    """'parakeet' or 'whisper' for these settings."""
    if cfg.speech_engine == "whisper":
        return "whisper"
    if parakeet is None:
        if cfg.speech_engine == "parakeet":
            log.warning("The Parakeet speech model isn't in %s; using Whisper.", PARAKEET_DIR)
        return "whisper"
    return "parakeet" if parakeet_handles(cfg, parakeet) else "whisper"


def gpu_model_dir(cfg, find_gpu=None) -> Path | None:
    """The full model's folder, when speech recognition should run on the graphics card now:
    switched on, downloaded, and a suitable card is there."""
    from abdoh.audio import gpu_model

    folder = cfg.app_dir / gpu_model.FOLDER
    if not getattr(cfg, "use_gpu", False) or not gpu_model.ready(folder):
        return None
    if find_gpu is None:
        from abdoh.gpu import find_gpu
    return folder if find_gpu() is not None else None


def make_transcriber(cfg) -> Transcriber:
    """The speech recognizer for these settings: the model chosen in Settings → Advanced once
    it's downloaded (abdoh/models.py), otherwise the recommended one."""
    from abdoh import models

    model = models.chosen(cfg)
    if model is not None and models.is_ready(cfg, model):
        return models.transcriber_for(cfg, model)
    parakeet = parakeet_available(cfg)
    if choose_engine(cfg, parakeet) == "parakeet":
        gpu = gpu_model_dir(cfg) if not Path(parakeet).name.endswith("v2") else None
        return ParakeetTranscriber(parakeet, languages=cfg.languages, gpu_dir=gpu)
    return _whisper(cfg, fallback=cfg.speech_engine != "whisper" and cfg.languages == ["en"])


def _whisper(cfg, fallback: bool = False) -> WhisperTranscriber:
    size = ENGLISH_FALLBACK if fallback else cfg.whisper_model
    name = model_name(size, cfg.languages)
    return WhisperTranscriber(size, cfg.languages, model_dir=cfg.resolve(model_folder(name)))


def load_transcriber(cfg, make=make_transcriber, fallback=_whisper) -> Transcriber:
    """The recognizer for these settings with its model loaded. If Parakeet can't be loaded
    (a damaged file, too little memory), Whisper takes over. Raises if nothing loads."""
    transcriber = make(cfg)
    try:
        transcriber.warm_up()
    except Exception:
        if not isinstance(transcriber, ParakeetTranscriber):
            raise
        log.exception("Couldn't load the Parakeet speech model; using Whisper instead")
        transcriber = fallback(cfg, fallback=True)
        transcriber.warm_up()
    return transcriber
