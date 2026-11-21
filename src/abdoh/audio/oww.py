"""Wake word with openWakeWord models, run directly on onnxruntime.

The same three small models, in the same order, as the openwakeword package (0.6), without
importing that package: it loads scipy and scikit-learn (~100 MB of RAM) for training-only
features. Every 80 ms of audio:

    audio → melspectrogram (32 bands) → speech embedding of the last 76 mel frames (96 numbers)
          → wake word model on the last 16 embeddings (~1.3 s) → score 0..1

`scripts/check_wakeword.py` compares the scores with the official package.
"""

import logging
from pathlib import Path

import numpy as np

from abdoh.audio.wakeword import WakeWordEngine

log = logging.getLogger(__name__)

FEATURES_DIR = "models/openwakeword"  # relative to the app folder
MELSPEC = "melspectrogram.onnx"
EMBEDDING = "embedding_model.onnx"

FRAME = 1280  # samples per step: 80 ms at 16 kHz
MEL_CONTEXT = 160 * 3  # samples from the previous step the melspectrogram needs
MEL_WINDOW = 76  # mel frames per embedding
MEL_STEP = 8  # mel frames per 80 ms
MEL_KEEP = 10 * 97  # ~10 s of mel frames
EMBED_KEEP = 120  # ~10 s of embeddings
WARMUP_FRAMES = 5  # like openWakeWord, ignore the first predictions after a reset
# The second try: when it misses you, you say it again. Two near misses (each at least this share
# of the threshold) that start between MIN_GAP and REPEAT seconds apart count as a wake-up.
# With your voice check, which still has to agree, a weaker pair is enough.
SECOND_TRY = 0.7
SECOND_TRY_YOUR_VOICE = 0.5
REPEAT_SECONDS = 4.0
MIN_GAP_SECONDS = 0.8
STEP_SECONDS = FRAME / 16000


def _session(path: Path):
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.inter_op_num_threads = 1
    opts.intra_op_num_threads = 1
    opts.log_severity_level = 3
    return ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])


class OpenWakeWord(WakeWordEngine):
    """Detects the wake word when the model's score reaches `threshold` (0.5 by default)."""

    def __init__(self, model_path: Path, features_dir: Path, threshold: float = 0.5, sessions=None):
        if sessions is None:
            paths = [Path(model_path), Path(features_dir) / MELSPEC, Path(features_dir) / EMBEDDING]
            missing = [str(p) for p in paths if not p.exists()]
            if missing:
                raise FileNotFoundError(f"openWakeWord files missing: {', '.join(missing)}")
            sessions = (_session(paths[1]), _session(paths[2]), _session(paths[0]))
        self._mel, self._embed, self._wake = sessions
        wake_input = self._wake.get_inputs()[0]
        self._wake_input = wake_input.name
        self._wake_frames = int(wake_input.shape[1])  # embeddings per prediction (16)
        self.threshold = threshold
        self.voice_check = None  # audio/voicecheck.py: the wake word only counts in your voice
        self.voice_threshold = 0.5
        self.last_score = 0.0
        self.reset()

    def reset(self) -> None:
        self._previous = np.zeros(0, dtype=np.int16)  # end of the last step, for the mel context
        self._pending = np.zeros(0, dtype=np.int16)  # samples not yet making a full step
        self._mel_buffer = np.ones((MEL_WINDOW, 32), dtype=np.float32)
        noise = np.random.randint(-1000, 1000, 16000 * 4).astype(np.int16)
        self._embeddings = self._embed_clip(noise)  # start from noise, as openWakeWord does
        self.last_window = self._embeddings[-self._wake_frames :]
        self._steps = 0
        self._trying = False  # a near miss is going on right now
        self._again = False  # ... and it is the second try
        self._tried_at: int | None = None  # the step the last near miss ended at
        self._first_try = self._try_best = 0.0  # the best score of the last and the current one

    def detect(self, block: bytes) -> bool:
        audio = np.concatenate([self._pending, np.frombuffer(block, dtype=np.int16)])
        usable = len(audio) // FRAME * FRAME
        self._pending = audio[usable:]
        heard, best, voice, again = False, 0.0, None, None
        for start in range(0, usable, FRAME):
            score = self.step(audio[start : start + FRAME])
            best = max(best, score)
            if heard:
                continue
            candidate = score >= self.threshold
            if not candidate and self._second_try(score):
                candidate, again = True, (self._first_try, score)
            if candidate:
                if self.voice_check is None:
                    heard = True
                else:
                    voice = max(voice or 0.0, self.voice_check.prob(self.last_window))
                    heard = voice >= self.voice_threshold
        if heard:
            self._trying, self._tried_at, self._again = False, None, False
        if heard and again is not None:
            log.info("Wake word on the second try (%.2f, then %.2f)", *again)
        elif heard and voice is None:
            log.info("Wake word score %.2f", best)
        elif heard:
            log.info("Wake word score %.2f (your voice %.2f)", best, voice)
        elif voice is not None:
            log.info("Wake word score %.2f, but it didn't sound like you (%.2f)", best, voice)
        elif best >= self.threshold / 2:
            log.info("Wake word near miss %.2f (needs %.2f)", best, self.threshold)
        return heard

    def _second_try(self, score: float) -> bool:
        """Follow near misses; True while this one is the second within REPEAT_SECONDS (each of
        its frames counts: your voice check may only be sure once more of it was heard)."""
        share = SECOND_TRY if self.voice_check is None else SECOND_TRY_YOUR_VOICE
        if score < self.threshold * share:
            if self._trying:  # that near miss is over
                self._trying, self._tried_at = False, self._steps
                self._first_try, self._again = self._try_best, False
            return False
        if self._trying:  # still the same one
            self._try_best = max(self._try_best, score)
            return self._again
        self._trying, self._try_best = True, score  # a new near miss starts
        gap = None if self._tried_at is None else (self._steps - self._tried_at) * STEP_SECONDS
        self._again = gap is not None and MIN_GAP_SECONDS <= gap <= REPEAT_SECONDS
        return self._again

    def step(self, frame: np.ndarray) -> float:
        """Process 80 ms (1280 samples) and return the wake word score."""
        clip = np.concatenate([self._previous, frame])
        self._previous = clip[-MEL_CONTEXT:]
        mel = self._melspectrogram(clip)
        self._mel_buffer = np.vstack([self._mel_buffer, mel])[-MEL_KEEP:]
        window = self._mel_buffer[-MEL_WINDOW:][None, :, :, None].astype(np.float32)
        embedding = self._embed.run(None, {"input_1": window})[0].reshape(1, -1)
        self._embeddings = np.vstack([self._embeddings, embedding])[-EMBED_KEEP:]
        features = self._embeddings[-self._wake_frames :][None].astype(np.float32)
        self.last_window = features[0]  # what was scored: the voice check looks at it too
        score = float(np.ravel(self._wake.run(None, {self._wake_input: features})[0])[0])
        self._steps += 1
        if self._steps <= WARMUP_FRAMES:
            score = 0.0
        self.last_score = score
        return score

    def _melspectrogram(self, clip: np.ndarray) -> np.ndarray:
        out = self._mel.run(None, {"input": clip[None, :].astype(np.float32)})[0]
        return np.squeeze(out) / 10 + 2  # openWakeWord's scaling, closer to Google's original

    def _embed_clip(self, audio: np.ndarray) -> np.ndarray:
        mel = self._melspectrogram(audio)
        windows = [
            mel[i : i + MEL_WINDOW]
            for i in range(0, mel.shape[0], MEL_STEP)
            if i + MEL_WINDOW <= mel.shape[0]
        ]
        batch = np.array(windows, dtype=np.float32)[..., None]
        return self._embed.run(None, {"input_1": batch})[0].reshape(len(windows), -1)
