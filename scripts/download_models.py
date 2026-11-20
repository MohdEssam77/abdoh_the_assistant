"""Download the offline models Xanthos needs into models/.

- openWakeWord's two shared feature models (melspectrogram, speech embedding), used with your
  own "Hey Xanthos" model (see README: train the wake word).
- The Parakeet v3 speech recognition model (English, German and 23 other languages, about 640
  MB), so the built app never has to download anything on its first start.
- Your trained wake word model, copied from assets/ if models/ doesn't have one yet.
- Piper's English voice (about 60 MB), bundled so Xanthos speaks naturally from the first start.
  Other languages' voices are downloaded by the app when first needed.

Whisper models (used for other languages, or with --whisper as an English fallback) are
downloaded by faster-whisper when first used.

Usage: python scripts/download_models.py [--whisper]
"""

import shutil
import sys
import urllib.request
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parents[1] / "models"


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

# NVIDIA Parakeet TDT 0.6b v3 (CC-BY-4.0), exported to ONNX for onnx-asr. (Xanthos 0.6.0 and
# earlier shipped v2, English only: the same size and speed, 0.5% against 1% English mistakes on
# synthetic clips, but 92% against 5% on German; ABDOH_EPIC_6.md.)
PARAKEET_DIR = MODELS_DIR / "parakeet-tdt-0.6b-v3"
PARAKEET_URL = (
    "https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx/resolve/"
    "8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce/{name}"
)
PARAKEET_FILES = [
    "config.json",
    "vocab.txt",
    "nemo128.onnx",
    "decoder_joint-model.int8.onnx",
    "encoder-model.int8.onnx",
]
WAKE_WORD = "hey_xanthos.onnx"
PIPER_DIR = MODELS_DIR / "piper"
# Piper's English voice (rhasspy/piper-voices, MIT; the voice's dataset is in its model card) at a
# fixed revision.
PIPER_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/"
    "e929968c3761f1c281875787685a745863db838d/en/en_US/lessac/medium/{name}"
)
PIPER_FILES = ["en_US-lessac-medium.onnx.json", "en_US-lessac-medium.onnx"]


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


def download_files(folder: Path, url: str, names: list[str], fetch=urllib.request.urlretrieve):
    """Download `names` into `folder` (url has a {name} blank). Each file is downloaded next to
    its final name and only kept if it isn't empty, so an interrupted download never leaves a
    broken model behind."""
    if all((folder / n).is_file() and (folder / n).stat().st_size > 0 for n in names):
        print(f"Already downloaded: {folder}")
        return
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        target = folder / name
        if target.is_file() and target.stat().st_size > 0:
            continue
        source = url.format(name=name)
        part = target.with_name(target.name + ".part")
        print(f"Downloading {source} ...")
        fetch(source, part)
        if not part.is_file() or part.stat().st_size == 0:
            part.unlink(missing_ok=True)
            raise RuntimeError(f"Downloading {source} gave an empty file.")
        part.replace(target)
    print(f"Saved to {folder}")


def download_whisper(folder: Path = WHISPER_DIR, fetch=urllib.request.urlretrieve) -> None:
    download_files(folder, WHISPER_URL, WHISPER_FILES, fetch)


def download_parakeet(folder: Path = PARAKEET_DIR, fetch=urllib.request.urlretrieve) -> None:
    download_files(folder, PARAKEET_URL, PARAKEET_FILES, fetch)


def download_piper_voice(folder: Path = PIPER_DIR, fetch=urllib.request.urlretrieve) -> None:
    download_files(folder, PIPER_URL, PIPER_FILES, fetch)


def copy_wake_word(models: Path = MODELS_DIR, assets: Path = MODELS_DIR.parent / "assets") -> None:
    """The trained wake word model that's kept in the repo, unless you have your own."""
    target, source = models / WAKE_WORD, assets / WAKE_WORD
    if target.exists() or not source.exists():
        return
    models.mkdir(exist_ok=True)
    shutil.copyfile(source, target)
    print(f"Copied {source} to {target}")


def main() -> int:
    download_openwakeword()
    download_parakeet()
    download_piper_voice()
    copy_wake_word()
    if "--whisper" in sys.argv[1:]:
        download_whisper()
    return 0


if __name__ == "__main__":
    sys.exit(main())
