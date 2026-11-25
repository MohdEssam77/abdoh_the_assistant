"""A natural voice for every language: Piper (piper-tts, offline, on the CPU).

Each language has a voice (a ~60 MB model in <app_dir>/models/piper, or bundled with the app).
English is bundled; German and other languages are downloaded from Hugging Face
(rhasspy/piper-voices) the first time they're needed, while the Windows voice speaks meanwhile.
A sentence is made in about a twentieth of the time it takes to say, then played in short
blocks, so `stop()` cuts it off at once and `pause()`/`resume()` go on from about where it was.

Piper is GPL-3.0 licensed (it includes espeak-ng); each voice has its own license on its model
card.
"""

import gc
import logging
import threading
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

import numpy as np

from abdoh.audio.devices import stream_closed, stream_opened
from abdoh.speech.tts import Speaker, text_language

log = logging.getLogger(__name__)

VOICES_DIR = "models/piper"  # relative to the app folder
# The voice for each language unless you chose another (Settings has choices for English and
# German). All "medium" quality: natural and fast.
DEFAULT_VOICES = {
    "en": "en_US-lessac-medium",
    "de": "de_DE-thorsten-medium",
    "ar": "ar_JO-kareem-medium",
    "fr": "fr_FR-siwis-medium",
    "es": "es_ES-davefx-medium",
    "it": "it_IT-paola-medium",
    "tr": "tr_TR-dfki-medium",
    "ru": "ru_RU-irina-medium",
    "nl": "nl_NL-pim-medium",
    "pt": "pt_BR-faber-medium",
    "pl": "pl_PL-gosia-medium",
    "zh": "zh_CN-huayan-medium",
    "hi": "hi_IN-priyamvada-medium",
    "fa": "fa_IR-amir-medium",
    "sv": "sv_SE-lisa-medium",
}
ENGLISH_VOICES = (
    "en_US-lessac-medium",
    "en_US-amy-medium",
    "en_US-ryan-medium",
    "en_US-joe-medium",
    "en_US-kristin-medium",
    "en_GB-alan-medium",
    "en_GB-cori-medium",
    "en_GB-jenny_dioco-medium",
)
GERMAN_VOICES = ("de_DE-thorsten-medium", "de_DE-kerstin-medium")
URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/{path}{ext}?download=true"
NORMAL_RATE = 175  # words a minute that Piper's own speed stands for
BLOCK_SECONDS = 0.05  # played in blocks this long: how quickly it stops
RESUME_BACK_SECONDS = 0.4  # after a pause, go on from a little before where it stopped
RETRY_SECONDS = 600  # a voice that couldn't be downloaded is tried again after this long


def voice_path(name: str) -> str:
    """Where a voice lives in the piper-voices repository: en/en_US/lessac/medium/en_US-..."""
    parts = name.split("-")
    code, quality, speaker = parts[0], parts[-1], "-".join(parts[1:-1])
    return f"{code.split('_')[0]}/{code}/{speaker}/{quality}/{name}"


def download_voice(name: str, folder: Path, fetch=None, progress=None) -> Path:
    """Download a voice (its .onnx model and .onnx.json settings) into `folder`.
    `progress(done, total)` hears how the model (about 60 MB) is coming along."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    fetch = fetch or _fetch
    for ext in (".onnx.json", ".onnx"):  # the model last: its presence means "ready"
        target = folder / f"{name}{ext}"
        partial = target.with_name(target.name + ".part")
        extra = {"progress": progress} if progress is not None and ext == ".onnx" else {}
        fetch(URL.format(path=voice_path(name), ext=ext), partial, **extra)
        partial.replace(target)
    return folder / f"{name}.onnx"


def _fetch(url: str, target: Path, progress=None) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Abdoh-voice-download"})
    with urllib.request.urlopen(request, timeout=60) as response, open(target, "wb") as f:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while chunk := response.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if progress is not None:
                progress(done, total)


def _load_piper(path: Path):
    from piper import PiperVoice

    return PiperVoice.load(str(path))


def _synthesize(voice, text: str, length_scale: float) -> tuple[np.ndarray, int]:
    from piper import SynthesisConfig

    chunks = list(voice.synthesize(text, syn_config=SynthesisConfig(length_scale=length_scale)))
    if not chunks:
        return np.zeros(0, dtype=np.int16), 22050
    audio = b"".join(chunk.audio_int16_bytes for chunk in chunks)
    return np.frombuffer(audio, dtype=np.int16), chunks[0].sample_rate


class SoundOutput:
    """Plays mono 16-bit audio through the default speakers (sounddevice)."""

    def open(self, rate: int):
        import sounddevice as sd

        stream_opened()  # no device reload while it plays (audio/devices.py)
        try:
            stream = sd.OutputStream(samplerate=rate, channels=1, dtype="int16", latency="low")
            stream.start()
        except Exception:
            stream_closed()
            raise
        return _Counted(stream)


class _Counted:
    """An output stream that tells audio/devices.py when it's closed."""

    def __init__(self, stream):
        self._stream = stream
        self._closed = False

    def __getattr__(self, name):
        return getattr(self._stream, name)

    def close(self) -> None:
        try:
            self._stream.close()
        finally:
            if not self._closed:
                self._closed = True
                stream_closed()


class PiperSpeaker(Speaker):
    """Speaks with Piper; `fallback` (the Windows voice) speaks what Piper can't yet: a
    language whose voice is still downloading, or if Piper fails. `find(name)` returns the path
    of an installed voice or None; downloads go to `folder`."""

    def __init__(
        self,
        find: Callable[[str], Path | None],
        folder: Path,
        rate: int = NORMAL_RATE,
        voices: dict[str, str] | None = None,
        fallback: Speaker | None = None,
        load=_load_piper,
        synthesize=_synthesize,
        output=None,
        download=download_voice,
    ):
        self.rate = rate
        self.voices = dict(voices or {})  # your choices: language -> voice name
        self.fallback = fallback
        self._find = find
        self._folder = Path(folder)
        self._load = load
        self._synthesize = synthesize
        self._output = output or SoundOutput()
        self._download = download
        self._loaded: dict[str, object] = {}
        self._lock = threading.Lock()  # loading a voice
        self._downloading: set[str] = set()
        self._tried: dict[str, float] = {}  # when each voice download was last started
        # Hears how a voice download goes: (voice name, percent), and (name, None) when done.
        self.on_download: Callable[[str, int | None], None] | None = None
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._resume = threading.Event()
        self._speaking = False
        self._fallback_paused = False
        self._language = ""

    # ----- what the daemon sets -----

    @property
    def language(self) -> str:
        return self._language

    @language.setter
    def language(self, value: str) -> None:
        self._language = value
        if self.fallback is not None:
            self.fallback.language = value

    @property
    def on_missing_voice(self):
        return getattr(self.fallback, "on_missing_voice", None)

    @on_missing_voice.setter
    def on_missing_voice(self, callback) -> None:
        if self.fallback is not None and hasattr(self.fallback, "on_missing_voice"):
            self.fallback.on_missing_voice = callback

    def configure(self, rate=None, voice=None, voices: dict[str, str] | None = None) -> None:
        """Change the speed, the Windows voice (the fallback) or your Piper voices."""
        if rate is not None:
            self.rate = rate
        if voices is not None:
            self._change_voices(dict(voices))
        configure = getattr(self.fallback, "configure", None)
        if configure:
            configure(rate=rate, voice=voice)

    def _change_voices(self, voices: dict[str, str]) -> None:
        """Your new choices: a voice you no longer use leaves memory right away (60 to 120 MB
        each), and the one that replaces it gets ready in the background, as at the start."""
        languages = set(self.voices) | set(voices)
        before = {language: self.voice_name(language) for language in languages}
        self.voices = voices
        changed = [lang for lang in languages if self.voice_name(lang) != before[lang]]
        in_use = {self.voice_name(lang) for lang in languages | set(DEFAULT_VOICES)}
        with self._lock:
            gone = [before[lang] for lang in changed if before[lang] in self._loaded]
            for name in gone:
                if name not in in_use:
                    del self._loaded[name]
        if not gone:
            return
        log.info("Let go of the voice %s", ", ".join(gone))
        gc.collect()
        ready = [lang for lang in changed if before[lang] in gone]

        def run() -> None:
            for language in ready:
                self._voice_for(language)

        threading.Thread(target=run, name="abdoh-voices", daemon=True).start()

    warm_languages = ("en", "de")

    def warm_up(self) -> None:
        """Load the English voice now (the first reply is quicker), and download the voices for
        `warm_languages` that aren't here yet. In the background."""

        def run() -> None:
            for language in self.warm_languages:
                self._voice_for(language)

        threading.Thread(target=run, name="abdoh-voices", daemon=True).start()
        warm = getattr(self.fallback, "warm_up", None)
        if warm:
            warm()

    # ----- speaking -----

    def say(self, text: str) -> None:
        if not text.strip():
            return
        self._stop.clear()
        voice = self._voice_for(text_language(text, self.language))
        if voice is not None:
            try:
                audio, rate = self._synthesize(voice, text, self._length_scale())
            except Exception:
                log.exception("Piper couldn't say that; using the Windows voice")
            else:
                self._play(audio, rate)
                return
        if self.fallback is not None and not self._stop.is_set():
            self.fallback.say(text)

    def stop(self) -> None:
        self._stop.set()
        if self.fallback is not None:
            self.fallback.stop()

    def pause(self) -> bool:
        if self._speaking:
            self._resume.clear()
            self._pause.set()
            return True
        if self.fallback is not None and self.fallback.pause():
            self._fallback_paused = True
            return True
        return False

    def resume(self) -> None:
        if self._fallback_paused:
            self._fallback_paused = False
            self.fallback.resume()
        self._pause.clear()
        self._resume.set()

    def _length_scale(self) -> float:
        return max(0.5, min(2.0, NORMAL_RATE / max(1, self.rate)))

    def _play(self, audio: np.ndarray, rate: int) -> None:
        block = max(1, int(rate * BLOCK_SECONDS))
        self._speaking = True
        stream = None
        try:
            stream = self._output.open(rate)
            position = 0
            while position < len(audio):
                if self._stop.is_set():
                    stream.abort()
                    return
                if self._pause.is_set():
                    stream.abort()  # quiet at once, without what was still queued
                    while not (self._resume.wait(0.05) or self._stop.is_set()):
                        pass
                    self._pause.clear()
                    self._resume.clear()
                    if self._stop.is_set():
                        return
                    position = max(0, position - int(rate * RESUME_BACK_SECONDS))
                    stream.start()
                stream.write(audio[position : position + block])
                position += block
            stream.stop()  # lets the last blocks play out
        except Exception:
            log.exception("Couldn't play Piper's speech")
        finally:
            self._speaking = False
            self._pause.clear()
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

    # ----- voices -----

    def voice_name(self, language: str) -> str | None:
        return self.voices.get(language) or DEFAULT_VOICES.get(language)

    def _voice_for(self, language: str):
        """The loaded voice for this language, or None (not available yet: it downloads in the
        background, or there is no Piper voice for it)."""
        name = self.voice_name(language)
        if name is None:
            return None
        with self._lock:
            if name in self._loaded:
                return self._loaded[name]
            path = self._find(name)
            if path is None:
                self._fetch(name)
                return None
            try:
                started = time.perf_counter()
                voice = self._load(path)
            except Exception:
                log.exception("Couldn't load the voice %s", name)
                return None
            log.info("Loaded the voice %s in %.1fs", name, time.perf_counter() - started)
            self._loaded[name] = voice
            return voice

    def _fetch(self, name: str) -> None:
        if name in self._downloading:
            return
        if time.monotonic() - self._tried.get(name, -RETRY_SECONDS) < RETRY_SECONDS:
            return  # it just failed (offline?): not on every sentence
        self._tried[name] = time.monotonic()
        self._downloading.add(name)

        tell = self.on_download
        shown = {"percent": 0}  # 0 is said when it starts

        def progress(done: int, total: int) -> None:
            percent = min(99, done * 100 // total) if total else 0
            if tell is not None and percent != shown["percent"]:
                shown["percent"] = percent
                tell(name, percent)

        def run() -> None:
            try:
                log.info("Downloading the voice %s (about 60 MB)", name)
                if tell is not None:
                    tell(name, 0)
                    self._download(name, self._folder, progress=progress)
                else:
                    self._download(name, self._folder)
                log.info("Voice %s is ready", name)
            except Exception as e:
                log.warning("Couldn't download the voice %s: %s", name, e)
            finally:
                self._downloading.discard(name)
                if tell is not None:
                    tell(name, None)

        threading.Thread(target=run, name="abdoh-voice-download", daemon=True).start()


def piper_available() -> bool:
    try:
        import piper  # noqa: F401
    except Exception:
        return False
    return True


def make_voice(cfg) -> Speaker:
    """The voice the settings ask for: Piper, with the Windows voice standing in where Piper
    can't speak yet; or the Windows voice alone (tts_engine: windows, or no Piper)."""
    from abdoh.speech.tts import make_speaker

    windows = make_speaker(cfg.tts_rate, cfg.tts_voice)
    if cfg.tts_engine != "piper" or not piper_available():
        return windows

    def find(name: str) -> Path | None:
        path = cfg.resolve(f"{VOICES_DIR}/{name}.onnx")  # downloaded, or bundled with the app
        return path if path.exists() and path.with_name(path.name + ".json").exists() else None

    speaker = PiperSpeaker(
        find,
        cfg.app_dir / VOICES_DIR,
        cfg.tts_rate,
        voices=your_voices(cfg),
        fallback=windows,
    )
    speaker.warm_languages = tuple(dict.fromkeys(["en", "de", *cfg.languages]))
    return speaker


def your_voices(cfg) -> dict[str, str]:
    return {"en": cfg.piper_voice_en, "de": cfg.piper_voice_de}
