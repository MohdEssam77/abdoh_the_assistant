"""Download the Vosk small English model into models/.

Whisper models are downloaded automatically by faster-whisper on first use.
Usage: python scripts/download_models.py
"""

import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

MODEL = "vosk-model-small-en-us-0.15"
URL = f"https://alphacephei.com/vosk/models/{MODEL}.zip"
MODELS_DIR = Path(__file__).resolve().parents[1] / "models"


def main() -> int:
    target = MODELS_DIR / MODEL
    if target.exists():
        print(f"Already downloaded: {target}")
        return 0
    MODELS_DIR.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / f"{MODEL}.zip"
        print(f"Downloading {URL} ...")
        urllib.request.urlretrieve(URL, zip_path)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        shutil.move(str(Path(tmp) / MODEL), target)
    print(f"Saved to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
