"""Voice activity detection with the Silero VAD model that ships with faster-whisper.

It tells speech from background noise much better than loudness does, so Xanthos can stop
recording sooner after you finish talking. Runs on onnxruntime (already installed by
faster-whisper); no extra download.
"""

import importlib.util
import logging
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

WINDOW = 512  # samples per model step (32 ms at 16 kHz)
CONTEXT = 64  # samples of the previous window the model also sees


def bundled_model_path() -> Path | None:
    """faster-whisper's copy of the Silero VAD model, without importing faster-whisper."""
    spec = importlib.util.find_spec("faster_whisper")
    if not spec or not spec.submodule_search_locations:
        return None
    path = Path(next(iter(spec.submodule_search_locations))) / "assets" / "silero_vad_v6.onnx"
    return path if path.exists() else None


class SileroVad:
    """Streaming speech detector: feed 16 kHz int16 blocks of any size, in order."""

    def __init__(self, model_path: Path | None = None, threshold: float = 0.5, session=None):
        self.threshold = threshold
        if session is None:
            import onnxruntime as ort

            path = model_path or bundled_model_path()
            if path is None:
                raise FileNotFoundError("Silero VAD model not found (is faster-whisper installed?)")
            opts = ort.SessionOptions()
            opts.inter_op_num_threads = 1
            opts.intra_op_num_threads = 1
            opts.log_severity_level = 4
            session = ort.InferenceSession(
                str(path), sess_options=opts, providers=["CPUExecutionProvider"]
            )
        self._session = session
        self.reset()

    def reset(self) -> None:
        """Forget everything heard so far (call before a new recording)."""
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros(CONTEXT, dtype=np.float32)
        self._pending = np.zeros(0, dtype=np.float32)
        self._last = 0.0

    def speech_prob(self, block: bytes) -> float:
        """Highest speech probability (0-1) in this block."""
        samples = np.frombuffer(block, dtype=np.int16).astype(np.float32) / 32768.0
        audio = np.concatenate([self._pending, samples])
        usable = len(audio) // WINDOW * WINDOW
        self._pending = audio[usable:]
        probs = []
        for start in range(0, usable, WINDOW):
            window = audio[start : start + WINDOW]
            x = np.concatenate([self._context, window])[None, :]
            out, self._h, self._c = self._session.run(
                None, {"input": x, "h": self._h, "c": self._c}
            )
            self._context = window[-CONTEXT:]
            probs.append(float(np.ravel(out)[0]))
        if probs:
            self._last = max(probs)
        return self._last

    def is_speech(self, block: bytes) -> bool:
        return self.speech_prob(block) >= self.threshold


def load_vad() -> SileroVad | None:
    """The bundled VAD, or None (Xanthos then falls back to loudness)."""
    try:
        return SileroVad()
    except Exception as e:
        log.warning("Voice activity detection unavailable, using loudness instead: %s", e)
        return None
