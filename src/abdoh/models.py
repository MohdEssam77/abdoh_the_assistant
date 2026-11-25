"""Settings → Advanced: the speech recognition models to choose from, and switching between them.

`speech_model` in config.yaml names the chosen one; empty means the recommended choice (Parakeet
v3 for its 25 languages, otherwise Whisper; the Speech recognition card decides as before).
Choosing one downloads it in the background (with progress), switches when it's ready, while
Abdoh keeps listening with the model it has, and then deletes downloads that are no longer used.
Never a model that's in use, never what's inside the app, never a folder Abdoh didn't download
(download.MARKER).
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from abdoh import download
from abdoh.audio.stt import (
    PARAKEET_DIR,
    PARAKEET_LANGUAGES,
    PARAKEET_MIXES,
    PARAKEET_V2_DIR,
    CanaryTranscriber,
    ParakeetTranscriber,
    WhisperTranscriber,
    model_folder,
)
from abdoh.download import Download

log = logging.getLogger(__name__)

WAIT_BEFORE_DOWNLOAD = 20.0  # seconds after Abdoh starts, for a download left from last time


def _whisper(size: str, english: tuple, multi: tuple) -> dict[str, Download]:
    """A Whisper size's two downloads: English only (more accurate in English) and multilingual."""
    files = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")

    def made(name, revision, sizes, checksum):
        spec = tuple(
            (f, n, checksum if f == "model.bin" else "") for f, n in zip(files, sizes, strict=True)
        )
        return Download(model_folder(name), f"Systran/faster-whisper-{name}", revision, spec)

    return {"en": made(f"{size}.en", *english), "any": made(size, *multi)}


def _large(size: str, repo: str, revision: str, sizes: tuple, checksum: str) -> Download:
    """Whisper large-v3 and its turbo: one multilingual model (128 mel bins, so the
    preprocessor's settings come too)."""
    config, model, preprocessor, tokenizer = sizes
    files = (
        ("config.json", config, ""),
        ("preprocessor_config.json", preprocessor, ""),
        ("tokenizer.json", tokenizer, ""),
        ("vocabulary.json", 1068114, ""),
        ("model.bin", model, checksum),
    )
    return Download(model_folder(size), repo, revision, files)


@dataclass(frozen=True)
class SpeechModel:
    id: str
    name: str
    line: str  # one line for the list: what it's good at, what it needs
    kind: str  # "parakeet", "canary" (onnx-asr) or "whisper" (faster-whisper)
    languages: frozenset[str] | None  # None: any language
    size_mb: int  # what it downloads (0: inside the app)
    gpu: bool = False  # can run on a graphics card
    bundled: bool = False  # inside the app: nothing to download, never deleted
    downloads: dict[str, Download] = field(default_factory=dict)  # "en" (English only), "any"
    size: str = ""  # for Whisper: base, small, medium, large-v3, large-v3-turbo
    onnx_name: str = ""  # for Canary: what onnx-asr calls its kind of model

    def download_for(self, languages: list[str]) -> Download | None:
        if self.bundled:
            return None
        if languages == ["en"] and "en" in self.downloads:
            return self.downloads["en"]
        return self.downloads.get("any")

    def fits(self, languages: list[str]) -> bool:
        """Does it understand all these languages (and tell them apart)?"""
        if self.languages is None:
            return True
        chosen = set(languages)
        if not chosen <= self.languages:
            return False
        if self.kind == "canary":
            return len(chosen) == 1  # it must be told the language: it can't tell them apart
        return len(chosen) == 1 or self.kind != "parakeet" or chosen <= PARAKEET_MIXES


PARAKEET_V2_FILES = (
    ("config.json", 97, ""),
    ("vocab.txt", 9384, ""),
    ("nemo128.onnx", 139764, "a9fde1486ebfcc08f328d75ad4610c67835fea58c73ba57e3209a6f6cf019e9f"),
    ("decoder_joint-model.int8.onnx", 8998286,
     "a449f49acd68979d418651dd2dcb737cc0f1bf0225e009e29ee326354edbf7d3"),
    ("encoder-model.int8.onnx", 652184014,
     "3e0581fda6ab843888b51e56d7ee78b6d5bc3237ec113af1f732d1d5286aa155"),
)  # fmt: skip

SPEECH_MODELS: tuple[SpeechModel, ...] = (
    SpeechModel(
        "parakeet-v3", "Parakeet v3",
        "English, German and 23 more European languages, and the most accurate for its speed. "
        "Inside the app. On a graphics card with 4 GB or more it runs there (downloads 2.4 GB "
        "once), otherwise on the processor.",
        "parakeet", PARAKEET_LANGUAGES, 0, gpu=True, bundled=True,
    ),
    SpeechModel(
        "parakeet-v2", "Parakeet v2",
        "English only. As accurate as v3 in English, a little better on clear speech, and as "
        "fast. Processor only. Downloads 630 MB.",
        "parakeet", frozenset({"en"}), 630,
        downloads={"any": Download(PARAKEET_V2_DIR, "istupakov/parakeet-tdt-0.6b-v2-onnx",
                                   "0bbb45a3365852604aef28b538a8f066f4ccaa85", PARAKEET_V2_FILES)},
    ),
    SpeechModel(
        "canary-180m-flash", "Canary 180M Flash",
        "English, German, Spanish or French, one language at a time (it must be told which). "
        "Small and quick, but makes more mistakes than Parakeet. Processor only. Downloads "
        "215 MB.",
        "canary", frozenset({"en", "de", "es", "fr"}), 215, onnx_name="nemo-conformer-aed",
        downloads={"any": Download(
            "models/canary-180m-flash", "istupakov/canary-180m-flash-onnx",
            "92c2231a4e2b2524277fea759be967d2e6edfc49",
            (("config.json", 68, ""), ("vocab.txt", 53555, ""),
             ("encoder-model.int8.onnx", 133710896,
              "996d1c89e6cbc891a7c88bf410884c178ffa474f7b13084522ac74a5e144cc81"),
             ("decoder-model.int8.onnx", 79520211,
              "9dd9c447872088c912e916d73751f9621a54085d5bc46788454fe904db51a914")))},
    ),
    SpeechModel(
        "canary-1b-v2", "Canary 1B v2",
        "One of Parakeet's 25 languages at a time (it must be told which). About as accurate as "
        "Parakeet, but half as fast, and it needs about 1.2 GB of memory. Processor only. "
        "Downloads 1 GB.",
        "canary", PARAKEET_LANGUAGES, 1030, onnx_name="nemo-canary-1b-v2",
        downloads={"any": Download(
            "models/canary-1b-v2", "istupakov/canary-1b-v2-onnx",
            "5ebc1520cef7b6b318b3526ad17adbfe00bc1bfc",
            (("config.json", 68, ""), ("vocab.txt", 208022, ""),
             ("encoder-model.int8.onnx", 859078138,
              "6d96e9945898e5ace48f4efecd459ca1df81859730be27b8af6b197639403ee1"),
             ("decoder-model.int8.onnx", 170040374,
              "52d83aa7aad41fbbe4f9dfcd341d784735a6eb4c6eb0d3290fc27a0d8ac39abf")))},
    ),
    SpeechModel(
        "whisper-base", "Whisper base",
        "Any language. Small and quick, but makes clearly more mistakes than Parakeet. Processor "
        "only. Downloads 150 MB.",
        "whisper", None, 150, size="base",
        downloads=_whisper(
            "base",
            ("3d3d5dee26484f91867d81cb899cfcf72b96be6c", (2227, 145216508, 2128466, 422309),
             "2a166925539a16005f14ff328359f9b9adb9dc4fb631bb3b227526862e93e2ef"),
            ("ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66", (2309, 145217532, 2203239, 459861),
             "d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9"),
        ),
    ),
    SpeechModel(
        "whisper-small", "Whisper small",
        "Any language. Good accuracy, slower than Parakeet and less accurate in English and "
        "German. Processor only. Downloads 490 MB.",
        "whisper", None, 490, size="small",
        downloads=_whisper(
            "small",
            ("d1d751a5f8271d482d14ca55d9e2deeebbae577f", (2657, 483545366, 2128466, 422309),
             "62b2a45b05ee59acb4a5341b33ee35e041395d378d418a18acfe4c9e768ee37a"),
            ("536b0662742c02347bc0e980a01041f333bce120", (2370, 483546902, 2203239, 459861),
             "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671"),
        ),
    ),
    SpeechModel(
        "whisper-medium", "Whisper medium",
        "Any language, more accurate than small, but slow without a strong processor (a second "
        "or more for each request). Processor only. Downloads 1.5 GB.",
        "whisper", None, 1530, size="medium",
        downloads=_whisper(
            "medium",
            ("a29b04bd15381511a9af671baec01072039215e3", (2643, 1527904330, 2128466, 422309),
             "11b220779aea4c6f3ce9d2549c8a95ea869ed84066864b999531ef53e594fe5b"),
            ("08e178d48790749d25932bbc082711ddcfdfbc4f", (2257, 1527906378, 2203239, 459861),
             "9b45e1009dcc4ab601eff815b61d80e60ce3fd8c74c1a14f4a282258286b51ae"),
        ),
    ),
    SpeechModel(
        "whisper-large-v3-turbo", "Whisper large-v3 turbo",
        "Any language, very accurate. Needs a strong computer: on a laptop processor each "
        "request takes 5 seconds or more. Processor only. Downloads 1.6 GB.",
        "whisper", None, 1620, size="large-v3-turbo",
        downloads={"any": _large(
            "large-v3-turbo", "deepdml/faster-whisper-large-v3-turbo-ct2",
            "4df90f75321148c3a29a9e2351b7ddf8f5b115a8", (2263, 1617884929, 340, 2710337),
            "e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da")},
    ),
    SpeechModel(
        "whisper-large-v3", "Whisper large-v3",
        "Any language, the most accurate Whisper and the slowest: 6 seconds or more for each "
        "request on a laptop processor, and about 1.7 GB of memory. Processor only. Downloads "
        "3.1 GB.",
        "whisper", None, 3090, size="large-v3",
        downloads={"any": _large(
            "large-v3", "Systran/faster-whisper-large-v3",
            "edaa852ec7e145841d8ffdb056a99866b5f0a478", (2394, 3087284237, 340, 2480617),
            "69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1")},
    ),
)  # fmt: skip
BY_ID = {m.id: m for m in SPEECH_MODELS}


def find(model_id: str) -> SpeechModel | None:
    return BY_ID.get(model_id or "")


def folder_of(cfg, model: SpeechModel) -> Path | None:
    """Where the model is (or would be downloaded) for these settings."""
    if model.bundled:
        return cfg.resolve(PARAKEET_DIR)
    spec = model.download_for(cfg.languages)
    if spec is None:
        return None
    return cfg.resolve(spec.folder)


def is_ready(cfg, model: SpeechModel) -> bool:
    if model.bundled:
        from abdoh.audio.stt import PARAKEET_FILES, is_complete

        return is_complete(cfg.resolve(PARAKEET_DIR), PARAKEET_FILES)
    spec = model.download_for(cfg.languages)
    return spec is not None and download.ready(cfg.resolve(spec.folder), spec)


def chosen(cfg) -> SpeechModel | None:
    """The model chosen in Advanced, if it fits the languages (None: the recommended one)."""
    model = find(getattr(cfg, "speech_model", ""))
    return model if model is not None and model.fits(cfg.languages) else None


def recommended_id(cfg) -> str:
    """What Abdoh uses when nothing is chosen (stt.make_transcriber without a choice)."""
    from abdoh.audio.stt import ENGLISH_FALLBACK, choose_engine, parakeet_available

    parakeet = parakeet_available(cfg)
    if choose_engine(cfg, parakeet) == "parakeet":
        return "parakeet-v2" if Path(parakeet).name.endswith("v2") else "parakeet-v3"
    fallback = cfg.speech_engine != "whisper" and cfg.languages == ["en"]
    return f"whisper-{ENGLISH_FALLBACK if fallback else cfg.whisper_model}"


def in_use(transcriber) -> str:
    """The catalog id of a transcriber ("" if there's none)."""
    if isinstance(transcriber, ParakeetTranscriber):
        return "parakeet-v3" if transcriber.v3 else "parakeet-v2"
    if isinstance(transcriber, CanaryTranscriber):
        return transcriber.catalog_id
    if isinstance(transcriber, WhisperTranscriber):
        return "whisper-" + transcriber.model_size.removesuffix(".en")
    return ""


def transcriber_for(cfg, model: SpeechModel):
    """A transcriber for a chosen model that's ready (stt.make_transcriber asks)."""
    folder = folder_of(cfg, model)
    if model.kind == "parakeet":
        gpu = None
        if model.gpu:
            from abdoh.audio.stt import gpu_model_dir

            gpu = gpu_model_dir(cfg)
        return ParakeetTranscriber(folder, languages=cfg.languages, gpu_dir=gpu)
    if model.kind == "canary":
        return CanaryTranscriber(folder, model.onnx_name, cfg.languages, catalog_id=model.id)
    return WhisperTranscriber(model.size, cfg.languages, model_dir=folder)


def downloaded_folders(cfg) -> list[Path]:
    """The catalog's models Abdoh downloaded, that are there now."""
    found = []
    for model in SPEECH_MODELS:
        for spec in model.downloads.values():
            folder = cfg.app_dir / spec.folder
            if download.downloaded_by_abdoh(folder):
                found.append(folder)
    return found


def listing(cfg, transcriber, status: dict | None = None) -> dict:
    """For the Advanced card: the models that fit your languages, and what's going on."""
    using = in_use(transcriber)
    recommended = recommended_id(cfg)
    choice = chosen(cfg)
    items = []
    for model in SPEECH_MODELS:
        if not model.fits(cfg.languages):
            continue
        items.append({
            "id": model.id, "name": model.name, "line": model.line, "size_mb": model.size_mb,
            "gpu": model.gpu, "recommended": model.id == recommended,
            "chosen": choice is not None and model.id == choice.id,
            "using": model.id == using, "ready": is_ready(cfg, model),
        })  # fmt: skip
    return {
        "speech": items,
        "speech_model": getattr(cfg, "speech_model", ""),
        "chosen_fits": choice is not None or not getattr(cfg, "speech_model", ""),
        "using": using,
        "status": status or {},
    }


class ModelSwitch:
    """Gets the chosen model ready and switches to it, in the background. `swap(new)` puts the
    new transcriber in place; `on_status(dict)` tells the window how it's going."""

    def __init__(
        self,
        cfg,
        transcriber,
        swap: Callable[[object], None],
        on_status: Callable[[dict], None] = lambda status: None,
        fetch=download.fetch,
        make: Callable | None = None,
        wait: float = WAIT_BEFORE_DOWNLOAD,
    ):
        self.cfg = cfg
        self.transcriber = transcriber
        self._swap = swap
        self._on_status = on_status
        self._fetch = fetch
        self._make = make
        self._wait = wait
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.status: dict = {}

    def _say(self, **status) -> None:
        self.status = status
        self._on_status(dict(status))

    def start(self, wait: bool = True) -> None:
        """Switch to the model the settings want, in the background (at start: after a wait)."""
        with self._lock:
            self._stop.set()  # a download for an earlier choice stops (it checks its own event)
            self._stop = threading.Event()
            self._thread = threading.Thread(
                target=self._run, args=(self._stop, wait), name="abdoh-model", daemon=True
            )
            self._thread.start()

    def apply(self) -> None:
        """`speech_model` changed in the window: right away."""
        self.start(wait=False)

    def stop(self) -> None:
        """Abdoh is closing: a download continues next time."""
        self._stop.set()

    def wanted_id(self) -> str:
        model = chosen(self.cfg)
        return model.id if model is not None else recommended_id(self.cfg)

    def _run(self, stop: threading.Event, wait: bool) -> None:
        try:
            self._switch(stop, wait)
        except download.Stopped:
            pass
        except Exception:
            log.exception("Couldn't switch the speech model")
            self._say(state="failed", id=self.wanted_id(), error="Something went wrong.")

    def _switch(self, stop: threading.Event, wait: bool) -> None:
        model = chosen(self.cfg)
        target = model.id if model is not None else recommended_id(self.cfg)
        if in_use(self.transcriber) == target:
            self._clean()
            self._say(state="ready", id=target)
            return
        if model is not None and not is_ready(self.cfg, model):
            spec = model.download_for(self.cfg.languages)
            self._say(state="downloading", id=model.id, percent=0)
            if wait and stop.wait(self._wait):
                return
            shown = [-1]

            def progress(done: int, total: int) -> None:
                percent = int(done * 100 / total) if total else 0
                if percent != shown[0] and not stop.is_set():
                    shown[0] = percent
                    self._say(state="downloading", id=model.id, percent=percent)

            try:
                self._fetch(spec, self.cfg.app_dir / spec.folder, on_progress=progress, stop=stop)
            except download.DownloadError as e:
                log.warning("Couldn't download %s: %s", model.name, e)
                self._say(state="failed", id=model.id, error=str(e))
                return
        if stop.is_set():
            return
        self._say(state="switching", id=target)
        make = self._make
        if make is None:
            from abdoh.audio.stt import make_transcriber as make
        new = make(self.cfg)
        new.warm_up()  # loads it now: Abdoh keeps listening with the old one meanwhile
        if stop.is_set():
            return
        self.transcriber = new
        self._swap(new)
        log.info("Speech recognition now uses %s", in_use(new) or target)
        self._clean()
        self._say(state="ready", id=in_use(new) or target)

    def _clean(self) -> None:
        """Delete the downloads that are neither in use nor chosen."""
        keep = set()
        for transcriber_dir in (getattr(self.transcriber, "model_dir", None),):
            if transcriber_dir is not None:
                keep.add(Path(transcriber_dir).resolve())
        model = chosen(self.cfg)
        if model is not None:
            folder = folder_of(self.cfg, model)
            if folder is not None:
                keep.add(folder.resolve())
        for folder in downloaded_folders(self.cfg):
            if folder.resolve() not in keep:
                download.delete(folder)
