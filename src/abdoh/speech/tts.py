"""Text-to-speech behind a small Speaker interface.

On Windows Abdoh drives the Windows voice (SAPI) directly: pyttsx3 2.99 cut off its own speech
there, so replies were silent. pyttsx3 is still used on macOS and Linux.
"""

import logging
import math
import queue
import sys
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable

log = logging.getLogger(__name__)


class Speaker(ABC):
    @abstractmethod
    def say(self, text: str) -> None:
        """Speak text aloud, blocking until done (or stopped)."""

    def stop(self) -> None:  # noqa: B027 - optional hook
        """Interrupt what is being said right now."""


def make_speaker(rate: int = 175, voice: str = "") -> Speaker:
    """The voice for this computer: the Windows voice on Windows, pyttsx3 elsewhere."""
    if sys.platform == "win32":
        return SapiSpeaker(rate, voice)
    return Pyttsx3Speaker(rate)


def _init_com() -> None:
    """SAPI (the Windows voice) is a COM object: initialize COM on the speaking thread."""
    if sys.platform != "win32":
        return
    try:
        import comtypes

        comtypes.CoInitialize()
    except Exception:
        log.debug("CoInitialize failed (COM may already be set up)", exc_info=True)


class _VoiceThread(Speaker):
    """Speaks on one dedicated thread, one text at a time.

    Creating a voice engine and speaking its first utterance costs over a second, so the engine
    is made once and reused (and recreated for the next text if it ever fails). It lives on its
    own thread because these engines must not be shared across threads.
    """

    def __init__(self, engine_factory: Callable[[], object]):
        self._factory = engine_factory
        self._jobs: queue.Queue[tuple[str, threading.Event]] = queue.Queue()
        self._stop = threading.Event()
        self._engine = None
        self._renew = threading.Event()  # settings changed: make a new engine for the next text
        threading.Thread(target=self._run, name="abdoh-tts", daemon=True).start()

    def configure(self, rate: int | None = None, voice: str | None = None) -> None:
        """Change the speed or the voice; used from the next text on."""
        if rate is not None:
            self.rate = rate
        if voice is not None:
            self.voice = voice
        self._renew.set()

    def say(self, text: str) -> None:
        if not text.strip():
            return
        self._stop.clear()
        done = threading.Event()
        self._jobs.put((text, done))
        done.wait()

    def stop(self) -> None:
        self._stop.set()

    def warm_up(self) -> None:
        """Create the engine and speak a blank utterance now, so the first reply is fast."""
        self._jobs.put((" ", threading.Event()))

    @abstractmethod
    def _new_engine(self):
        """Create the voice engine (called on the speaking thread)."""

    @abstractmethod
    def _speak(self, text: str) -> None:
        """Speak with self._engine until done, or until self._stop is set."""

    def _run(self) -> None:
        _init_com()
        while True:
            text, done = self._jobs.get()
            try:
                if self._renew.is_set():
                    self._renew.clear()
                    self._engine = None
                if self._engine is None:
                    self._engine = self._new_engine()
                if not self._stop.is_set():
                    self._speak(text)
            except Exception:
                log.exception("Could not speak")
                self._engine = None  # start fresh next time
            finally:
                done.set()


# ----- Windows: SAPI -----

# SAPI's SpeechVoiceSpeakFlags.
SVSF_ASYNC = 1
SVSF_PURGE_BEFORE_SPEAK = 2
SVSF_IS_NOT_XML = 16
POLL_MS = 50  # while speaking, check this often whether to stop


def _make_sapi_voice():
    import comtypes.client

    return comtypes.client.CreateObject("SAPI.SpVoice", dynamic=True)


def sapi_rate(words_per_minute: float) -> int:
    """SAPI's speed (-10 to 10) for a speaking rate in words per minute (pyttsx3's scale)."""
    return max(-10, min(10, round(math.log(max(1.0, words_per_minute) / 156.63, 1.11))))


def windows_voices(voice_factory: Callable[[], object] = _make_sapi_voice) -> list[str]:
    """The names of the installed Windows voices, e.g. "Microsoft Zira Desktop - English (United
    States)". Empty if there are none (or this isn't Windows)."""
    if sys.platform != "win32" and voice_factory is _make_sapi_voice:
        return []
    _init_com()
    try:
        tokens = voice_factory().GetVoices()
        return [tokens.Item(i).GetDescription() for i in range(tokens.Count)]
    except Exception:
        log.warning("Couldn't list the Windows voices", exc_info=True)
        return []


class SapiSpeaker(_VoiceThread):
    """The Windows voice (SAPI), driven directly. `stop()` cuts it off within POLL_MS."""

    def __init__(
        self,
        rate: int = 175,
        voice: str = "",
        voice_factory: Callable[[], object] = _make_sapi_voice,
    ):
        self.rate = rate
        self.voice = voice  # a voice's name ("" = the Windows default)
        super().__init__(voice_factory)

    def _new_engine(self):
        voice = self._factory()
        voice.Rate = sapi_rate(self.rate)
        if self.voice:
            tokens = voice.GetVoices()
            for i in range(tokens.Count):
                if tokens.Item(i).GetDescription() == self.voice:
                    voice.Voice = tokens.Item(i)
                    break
            else:
                log.warning("Voice %r isn't installed; using the default voice", self.voice)
        return voice

    def _speak(self, text: str) -> None:
        voice = self._engine
        voice.Speak(text, SVSF_ASYNC | SVSF_IS_NOT_XML)
        while not voice.WaitUntilDone(POLL_MS):
            if self._stop.is_set():
                voice.Speak("", SVSF_ASYNC | SVSF_PURGE_BEFORE_SPEAK)
                return


# ----- macOS and Linux: pyttsx3 -----


def _make_pyttsx3_engine():
    import pyttsx3

    return pyttsx3.init()


class Pyttsx3Speaker(_VoiceThread):
    """Offline TTS via pyttsx3. `stop()` interrupts at the next word."""

    def __init__(
        self, rate: int = 175, engine_factory: Callable[[], object] = _make_pyttsx3_engine
    ):
        self.rate = rate
        super().__init__(engine_factory)

    def _new_engine(self):
        engine = self._factory()
        engine.setProperty("rate", self.rate)
        engine.connect("started-word", self._on_word)
        return engine

    def _on_word(self, name, location, length) -> None:
        if self._stop.is_set() and self._engine is not None:
            self._engine.stop()

    def _speak(self, text: str) -> None:
        self._engine.say(text)
        self._engine.runAndWait()


class FakeSpeaker(Speaker):
    """Records what would have been said. For tests."""

    def __init__(self):
        self.said: list[str] = []
        self.stops = 0

    def say(self, text: str) -> None:
        self.said.append(text)

    def stop(self) -> None:
        self.stops += 1
