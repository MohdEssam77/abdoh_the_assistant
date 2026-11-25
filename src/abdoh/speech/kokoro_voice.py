"""Kokoro (82M, Apache 2.0): natural English voices, American and British, on the processor.

The ONNX export (onnx-community/Kokoro-82M-v1.0-ONNX, the full-precision model: on the owner's
laptop it makes 4 seconds of speech in 0.7 s, the quantized one takes 2.4 s and DirectML fails)
runs on onnxruntime. Text becomes phonemes with Piper's own espeak-ng, as Kokoro's own ONNX
package does with espeak, so nothing new is installed. One model (325 MB) serves every voice;
each voice is a small style file. Downloaded the first time a Kokoro voice is chosen.

Its voices are names like "kokoro:af_heart" among your Piper voices (Settings → Voice → English
voice), so the Piper speaker plays them: in blocks, with pause, stop and the Windows voice
standing in until it's downloaded.
"""

import json
import logging
import re
import threading
import unicodedata
from pathlib import Path

import numpy as np

from abdoh.download import Download

log = logging.getLogger(__name__)

PREFIX = "kokoro:"
FOLDER = "models/kokoro"
RATE = 24000
MAX_TOKENS = 510
STYLE_SIZE = 256
# The voices offered: name -> (what Settings shows, espeak's English).
VOICES = {
    "af_heart": ("Heart (American, Kokoro)", "en-us"),
    "af_bella": ("Bella (American, Kokoro)", "en-us"),
    "am_michael": ("Michael (American, Kokoro)", "en-us"),
    "am_fenrir": ("Fenrir (American, Kokoro)", "en-us"),
    "bf_emma": ("Emma (British, Kokoro)", "en-gb"),
    "bm_george": ("George (British, Kokoro)", "en-gb"),
}
_CHECKSUMS = {  # sha256 of each voice's style file
    "af_bella": "f69d836209b78eb8c66e75e3cda491e26ea838a3674257e9d4e5703cbaf55c8b",
    "af_heart": "d583ccff3cdca2f7fae535cb998ac07e9fcb90f09737b9a41fa2734ec44a8f0b",
    "am_fenrir": "c27989f741f7ee34d273a39d8a595cc0837d35f5ced9a29b7cc162614616df43",
    "am_michael": "1d1f21dd8da39c30705cd4c75d039d265e9bc4a2a93ed09bc9e1b1225eb95ba1",
    "bf_emma": "669fe0647f9dd04fcab92f1439a40eeb4c8b4ab1f82e4996fe3d918ce4a63b73",
    "bm_george": "c4b235a4c1f2cd3b939fed08b899ce9385638b763f7b73a59616c4fc9bd6c9bc",
}
MODEL = (
    "onnx/model.onnx",
    325532232,
    "8fbea51ea711f2af382e88c833d9e288c6dc82ce5e98421ea61c058ce21a34cb",
)
DOWNLOAD = Download(
    FOLDER,
    "onnx-community/Kokoro-82M-v1.0-ONNX",
    "1939ad2a8e416c0acfeecc08a694d14ef25f2231",
    (
        ("tokenizer.json", 3497, ""),
        *((f"voices/{name}.bin", 522240, _CHECKSUMS[name]) for name in VOICES),
        MODEL,  # the model last: its being there means "ready"
    ),
)
NAMES = tuple(PREFIX + name for name in VOICES)


def is_kokoro(name: str | None) -> bool:
    return bool(name) and name.startswith(PREFIX)


def label(name: str) -> str:
    return VOICES.get(name.removeprefix(PREFIX), (name, ""))[0]


def voice_file(folder: Path, name: str) -> Path:
    return Path(folder) / "voices" / f"{name.removeprefix(PREFIX)}.bin"


def ready(folder: Path) -> bool:
    from abdoh.download import ready as files_ready

    return files_ready(folder, DOWNLOAD)


def phonemes(text: str, language: str = "en-us", phonemize=None) -> str:
    """Kokoro's phonemes for a sentence (espeak-ng's IPA, adjusted as Kokoro's own code does)."""
    if phonemize is None:
        phonemize = _espeak().phonemize
    ps = "".join("".join(sentence) for sentence in phonemize(language, text))
    ps = unicodedata.normalize("NFC", ps)
    ps = ps.replace("ʲ", "j").replace("r", "ɹ").replace("x", "k").replace("ɬ", "l")
    ps = re.sub(r"(?<=[a-zɹː])(?=hˈʌndɹɪd)", " ", ps)
    ps = re.sub(r" z(?=[;:,.!?¡¿—…\"«»“” ]|$)", "z", ps)
    return ps.strip()


_espeak_lock = threading.Lock()
_espeak_made = None


def _espeak():
    global _espeak_made
    with _espeak_lock:
        if _espeak_made is None:
            from piper.phonemize_espeak import EspeakPhonemizer

            _espeak_made = EspeakPhonemizer()
        return _espeak_made


class KokoroModel:
    """The model and its phoneme table, shared by all Kokoro voices."""

    def __init__(self, folder: Path, session=None):
        self.folder = Path(folder)
        tokenizer = json.loads((self.folder / "tokenizer.json").read_text(encoding="utf-8"))
        self.vocab: dict[str, int] = tokenizer["model"]["vocab"]
        if session is None:
            import onnxruntime as ort

            session = ort.InferenceSession(
                str(self.folder / "onnx" / "model.onnx"), providers=["CPUExecutionProvider"]
            )  # DirectML fails on one of its layers
        self.session = session
        self.lock = threading.Lock()

    def ids(self, ps: str) -> list[int]:
        return [self.vocab[c] for c in ps if c in self.vocab][:MAX_TOKENS]


_models: dict[Path, KokoroModel] = {}
_models_lock = threading.Lock()


def load_model(folder: Path) -> KokoroModel:
    folder = Path(folder).resolve()
    with _models_lock:
        if folder not in _models:
            _models[folder] = KokoroModel(folder)
        return _models[folder]


class KokoroVoice:
    """One Kokoro voice: makes the audio for a sentence (int16 at 24 kHz)."""

    def __init__(self, model: KokoroModel, styles: np.ndarray, language: str, phonemize=None):
        self.model = model
        self.styles = styles  # one style per sentence length (tokens)
        self.language = language
        self._phonemize = phonemize

    @classmethod
    def load(cls, path: Path) -> "KokoroVoice":
        path = Path(path)
        styles = np.fromfile(path, dtype=np.float32).reshape(-1, 1, STYLE_SIZE)
        language = VOICES.get(path.stem, ("", "en-us"))[1]
        return cls(load_model(path.parent.parent), styles, language)

    def synthesize_audio(self, text: str, length_scale: float = 1.0) -> tuple[np.ndarray, int]:
        ids = self.model.ids(phonemes(text, self.language, self._phonemize))
        if not ids:
            return np.zeros(0, dtype=np.int16), RATE
        style = self.styles[min(len(ids), len(self.styles) - 1)]
        speed = max(0.5, min(2.0, 1.0 / max(0.1, length_scale)))
        feed = {
            "input_ids": np.array([[0, *ids, 0]], dtype=np.int64),
            "style": style.astype(np.float32),
            "speed": np.array([speed], dtype=np.float32),
        }
        with self.model.lock:
            audio = np.asarray(self.model.session.run(None, feed)[0], dtype=np.float32).reshape(-1)
        return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16), RATE
