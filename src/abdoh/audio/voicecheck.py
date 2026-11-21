"""Your voice check: the wake word only counts when it sounds like you.

openWakeWord's model says "that was 'Hey Krekos'"; this small second model says "and it was
the owner". It looks at the same 16 x 96 embedding window the wake word model scored, summed
up as its mean and spread over time (192 numbers), and is a logistic regression trained in
numpy on the owner's own recordings: about ten "Hey Krekos" (yes) and 20 seconds of normal
talk (no). It trains in a second, and works with this app's own openWakeWord code
(audio/oww.py), which a verifier made with the openwakeword package would not.

The recordings stay on this computer (<app_dir>/voice), so the check can be trained again for a
new wake word model without recording again. A check belongs to one wake word model: made for
another, it is ignored.
"""

import logging
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

FILE = "models/voice_check.npz"  # relative to the app folder
VOICE_DIR = "voice"  # your recordings, relative to the app folder
PHRASES = 10  # how many times you say the wake word
TALK_SECONDS = 20  # how long you talk normally
LEAD_SECONDS = 1.0  # quiet fed to the wake word model before each recording
TOP_WINDOWS = 3  # from each recording of the wake word, its best-scoring windows count
L2 = 1.0
STEPS = 400
RATE = 0.2


def features(window: np.ndarray) -> np.ndarray:
    """A 16 x 96 embedding window as 192 numbers: each column's mean and spread over time."""
    window = np.asarray(window, dtype=np.float32)
    return np.concatenate([window.mean(axis=0), window.std(axis=0)])


@dataclass
class VoiceCheck:
    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray
    bias: float
    model: str = ""  # the wake word model's file name ...
    model_size: int = 0  # ... and size: a check made for another model is ignored

    def prob(self, window: np.ndarray) -> float:
        """How sure it is that this window is you saying the wake word (0 to 1)."""
        x = (features(window) - self.mean) / self.scale
        return float(_sigmoid(x @ self.weights + self.bias))

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:  # np.savez would add ".npz" to a name without it
            np.savez(
                f,
                mean=self.mean,
                scale=self.scale,
                weights=self.weights,
                bias=np.float64(self.bias),
                model=np.array(self.model),
                model_size=np.int64(self.model_size),
            )

    @classmethod
    def load(cls, path: Path, model_path: Path | None = None) -> "VoiceCheck | None":
        """The saved check, or None if there is none, it can't be read, or it was made for
        another wake word model than `model_path`."""
        path = Path(path)
        if not path.exists():
            return None
        try:
            with np.load(path, allow_pickle=False) as data:
                check = cls(
                    data["mean"],
                    data["scale"],
                    data["weights"],
                    float(data["bias"]),
                    str(data["model"]),
                    int(data["model_size"]),
                )
        except Exception:
            log.warning("Couldn't read the voice check %s", path, exc_info=True)
            return None
        if model_path is not None and not check.fits(Path(model_path)):
            log.info("The voice check was made for another wake word model: not used")
            return None
        return check

    def fits(self, model_path: Path) -> bool:
        try:
            size = Path(model_path).stat().st_size
        except OSError:
            return False
        return (Path(model_path).name, size) == (self.model, self.model_size)


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def fit(x: np.ndarray, y: np.ndarray, l2: float = L2, steps: int = STEPS, rate: float = RATE):
    """Logistic regression with balanced classes and an L2 penalty, by gradient descent on
    standardized features. Returns (mean, scale, weights, bias)."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    mean = x.mean(axis=0)
    scale = x.std(axis=0) + 1e-6
    x = (x - mean) / scale
    weight = np.where(y == 1, 0.5 / max(y.sum(), 1), 0.5 / max((1 - y).sum(), 1))
    w, b = np.zeros(x.shape[1]), 0.0
    for _ in range(steps):
        error = (_sigmoid(x @ w + b) - y) * weight
        w -= rate * (x.T @ error + l2 * w / len(y))
        b -= rate * error.sum()
    return mean, scale, w, b


def wake_windows(scorer, audio: bytes) -> list[tuple[float, np.ndarray]]:
    """Run a recording through the wake word model: (score, window) for every 80 ms.
    `scorer` is an OpenWakeWord (or a fake with the same reset/step/last_window)."""
    from abdoh.audio.oww import FRAME

    lead = np.random.randint(-30, 30, int(16000 * LEAD_SECONDS)).astype(np.int16)
    samples = np.concatenate([lead, np.frombuffer(audio, dtype=np.int16)])
    scorer.reset()
    found = []
    for start in range(0, len(samples) - FRAME + 1, FRAME):
        score = scorer.step(samples[start : start + FRAME])
        found.append((score, np.array(scorer.last_window)))
    return found


def best_windows(windows: list[tuple[float, np.ndarray]], top: int = TOP_WINDOWS) -> list:
    return [w for _, w in sorted(windows, key=lambda item: item[0], reverse=True)[:top]]


@dataclass
class Trained:
    check: VoiceCheck
    passed: int  # recordings of the wake word it recognizes when trained without them
    total: int
    woke: int  # recordings the wake word model itself woke up for


def train(scorer, phrases: list[bytes], talk: bytes, model_path: Path, threshold: float):
    """Train a check from your recordings of the wake word and of normal talk."""
    clips = [wake_windows(scorer, clip) for clip in phrases]
    woke = sum(any(score >= threshold for score, _ in clip) for clip in clips)
    positives = [best_windows(clip) for clip in clips]
    negatives = [w for _, w in wake_windows(scorer, talk)]
    if not positives or not negatives:
        raise ValueError("Record the wake word and some normal talk first.")
    neg_x = np.array([features(w) for w in negatives])

    def build(groups):
        pos_x = np.array([features(w) for group in groups for w in group])
        x = np.vstack([pos_x, neg_x])
        y = np.concatenate([np.ones(len(pos_x)), np.zeros(len(neg_x))])
        return VoiceCheck(*fit(x, y))

    passed = 0
    for i, held_out in enumerate(positives):  # leave one recording out: is it still you?
        if len(positives) == 1:
            break
        check = build(positives[:i] + positives[i + 1 :])
        passed += max(check.prob(w) for w in held_out) >= 0.5
    check = build(positives)
    model_path = Path(model_path)
    check.model = model_path.name
    check.model_size = model_path.stat().st_size if model_path.exists() else 0
    return Trained(check, passed, len(positives) if len(positives) > 1 else 0, woke)


# ----- the recordings -----


def write_wav(path: Path, audio: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(audio)


def read_wav(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        return w.readframes(w.getnframes())


class Recordings:
    """Your recordings in <app_dir>/voice: phrase-01.wav ... and talk.wav."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def phrase_path(self, number: int) -> Path:
        return self.folder / f"phrase-{number:02d}.wav"

    @property
    def talk_path(self) -> Path:
        return self.folder / "talk.wav"

    def phrases(self) -> list[bytes]:
        return [read_wav(p) for p in sorted(self.folder.glob("phrase-*.wav"))]

    def talk(self) -> bytes:
        return read_wav(self.talk_path) if self.talk_path.exists() else b""

    def count(self) -> int:
        return len(list(self.folder.glob("phrase-*.wav"))) if self.folder.exists() else 0

    def forget(self) -> None:
        for path in self.folder.glob("*.wav") if self.folder.exists() else []:
            path.unlink(missing_ok=True)
