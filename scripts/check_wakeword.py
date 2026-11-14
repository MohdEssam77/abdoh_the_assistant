"""Developer check: Abdoh's openWakeWord code gives the same scores as the official package.

Needs `pip install openwakeword` (not an Abdoh dependency) and the feature models from
`python scripts/download_models.py`. Downloads the pre-trained "hey jarvis" model, speaks
"Hey Jarvis, what time is it?" with the system voice into a WAV (or uses the WAV you give it),
and compares both implementations' scores for every 80 ms frame.

Usage: python scripts/check_wakeword.py [clip.wav]
"""

import sys
import tempfile
import urllib.request
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from abdoh.audio.oww import EMBEDDING, FEATURES_DIR, FRAME, MELSPEC, OpenWakeWord  # noqa: E402

MODEL_URL = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/hey_jarvis_v0.1.onnx"


def read_wav_16k(path: Path) -> np.ndarray:
    """A WAV file as 16 kHz mono int16 (simple linear resampling)."""
    with wave.open(str(path), "rb") as w:
        rate, channels = w.getframerate(), w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    if rate != 16000:
        old = np.arange(len(data)) / rate
        data = np.interp(np.arange(int(len(data) * 16000 / rate)) / 16000, old, data)
    return data.astype(np.int16)


def speak_to_wav(text: str, path: Path) -> Path:
    import pyttsx3

    engine = pyttsx3.init()
    engine.save_to_file(text, str(path))
    engine.runAndWait()
    return path


def main() -> int:
    import openwakeword

    features = ROOT / FEATURES_DIR
    with tempfile.TemporaryDirectory() as tmp:
        model = Path(tmp) / "hey_jarvis_v0.1.onnx"
        urllib.request.urlretrieve(MODEL_URL, model)
        if len(sys.argv) > 1:
            clip_path = Path(sys.argv[1])
        else:
            clip_path = speak_to_wav("Hey Jarvis, what time is it?", Path(tmp) / "clip.wav")
        clip = read_wav_16k(clip_path)
        rng = np.random.default_rng(0)
        noise = rng.normal(0, 50, 16000).astype(np.int16)
        audio = np.concatenate([noise, clip, noise])

        np.random.seed(0)
        ours = OpenWakeWord(model, features)
        np.random.seed(0)
        theirs = openwakeword.Model(
            wakeword_models=[str(model)],
            inference_framework="onnx",
            melspec_model_path=str(features / MELSPEC),
            embedding_model_path=str(features / EMBEDDING),
        )
        name = next(iter(theirs.models))
        a, b = [], []
        for start in range(0, len(audio) - FRAME + 1, FRAME):
            frame = audio[start : start + FRAME]
            a.append(ours.step(frame))
            b.append(float(theirs.predict(frame)[name]))

    a, b = np.array(a), np.array(b)
    diff = float(np.abs(a - b).max())
    print(f"frames: {len(a)}, peak score ours {a.max():.3f} / official {b.max():.3f}")
    print(f"largest difference: {diff:.2e}")
    ok = diff < 1e-4 and a.max() >= 0.5
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
