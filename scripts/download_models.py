"""Download the offline models Abdoh needs into models/.

- openWakeWord's two shared feature models (melspectrogram, speech embedding), used with your
  own "Hey Abdoh" model (see README: train the wake word).
- The Vosk small English model, the fallback wake word engine until you have that model.
- The Whisper speech recognition model (base.en), so the built app never has to download it on
  its first start. Other Whisper models are downloaded by faster-whisper when first used.

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

WHISPER = "base.en"  # the default model (whisper_model: base, language: en)
WHISPER_DIR = MODELS_DIR / f"faster-whisper-{WHISPER}"
# A fixed revision, so every build ships the model that was tested.
WHISPER_URL = (
    f"https://huggingface.co/Systran/faster-whisper-{WHISPER}/resolve/"
    "3d3d5dee26484f91867d81cb899cfcf72b96be6c/{name}"
)
WHISPER_FILES = ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]


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


def download_whisper(folder: Path = WHISPER_DIR, fetch=urllib.request.urlretrieve) -> None:
    """Each file is downloaded next to its final name and only kept if it isn't empty, so an
    interrupted download never leaves a broken model behind."""
    if all((folder / n).is_file() and (folder / n).stat().st_size > 0 for n in WHISPER_FILES):
        print(f"Already downloaded: {folder}")
        return
    folder.mkdir(parents=True, exist_ok=True)
    for name in WHISPER_FILES:
        target = folder / name
        if target.is_file() and target.stat().st_size > 0:
            continue
        url = WHISPER_URL.format(name=name)
        part = target.with_name(target.name + ".part")
        print(f"Downloading {url} ...")
        fetch(url, part)
        if not part.is_file() or part.stat().st_size == 0:
            part.unlink(missing_ok=True)
            raise RuntimeError(f"Downloading {url} gave an empty file.")
        part.replace(target)
    print(f"Saved to {folder}")


def main() -> int:
    download_openwakeword()
    download_vosk()
    download_whisper()
    return 0


if __name__ == "__main__":
    sys.exit(main())
