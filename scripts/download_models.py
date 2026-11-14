"""Download the offline models Abdoh needs into models/.

- openWakeWord's two shared feature models (melspectrogram, speech embedding), used with your
  own "Hey Abdoh" model (see README: train the wake word).
- The Vosk small English model, the fallback wake word engine until you have that model.

Whisper models are downloaded automatically by faster-whisper on first use.
Usage: python scripts/download_models.py
"""

import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parents[1] / "models"

VOSK = "vosk-model-small-en-us-0.15"
VOSK_URL = f"https://alphacephei.com/vosk/models/{VOSK}.zip"

OWW_DIR = MODELS_DIR / "openwakeword"
OWW_RELEASE = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1"
OWW_FILES = ["melspectrogram.onnx", "embedding_model.onnx"]


def download_openwakeword() -> None:
    OWW_DIR.mkdir(parents=True, exist_ok=True)
    for name in OWW_FILES:
        target = OWW_DIR / name
        if target.exists():
            print(f"Already downloaded: {target}")
            continue
        print(f"Downloading {OWW_RELEASE}/{name} ...")
        urllib.request.urlretrieve(f"{OWW_RELEASE}/{name}", target)
        print(f"Saved to {target}")


def download_vosk() -> None:
    target = MODELS_DIR / VOSK
    if target.exists():
        print(f"Already downloaded: {target}")
        return
    MODELS_DIR.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / f"{VOSK}.zip"
        print(f"Downloading {VOSK_URL} ...")
        urllib.request.urlretrieve(VOSK_URL, zip_path)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        shutil.move(str(Path(tmp) / VOSK), target)
    print(f"Saved to {target}")


def main() -> int:
    download_openwakeword()
    download_vosk()
    return 0


if __name__ == "__main__":
    sys.exit(main())
