"""Text-to-speech behind a small Speaker interface."""

import logging
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


def _make_pyttsx3_engine():
    import pyttsx3

    return pyttsx3.init()


def _init_com() -> None:
    """SAPI (the Windows voice) is a COM object: initialize COM on the speaking thread."""
    if sys.platform != "win32":
        return
    try:
        import comtypes

        comtypes.CoInitialize()
    except Exception:
        log.debug("CoInitialize failed (COM may already be set up)", exc_info=True)


class Pyttsx3Speaker(Speaker):
    """Offline TTS via pyttsx3, with one engine kept alive on its own thread.

    Creating an engine and speaking its first utterance costs over a second, so the engine is
    made once and reused. It lives on a dedicated thread because pyttsx3 engines must not be
    shared across threads. `stop()` interrupts at the next word; if the engine ever fails it is
    recreated for the next utterance.
    """

    def __init__(
        self, rate: int = 175, engine_factory: Callable[[], object] = _make_pyttsx3_engine
    ):
        self.rate = rate
        self._factory = engine_factory
        self._jobs: queue.Queue[tuple[str, threading.Event]] = queue.Queue()
        self._stop = threading.Event()
        self._engine = None
        threading.Thread(target=self._run, name="abdoh-tts", daemon=True).start()

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

    def _new_engine(self):
        engine = self._factory()
        engine.setProperty("rate", self.rate)
        engine.connect("started-word", self._on_word)
        return engine

    def _on_word(self, name, location, length) -> None:
        if self._stop.is_set() and self._engine is not None:
            self._engine.stop()

    def _run(self) -> None:
        _init_com()
        while True:
            text, done = self._jobs.get()
            try:
                if self._engine is None:
                    self._engine = self._new_engine()
                if not self._stop.is_set():
                    self._engine.say(text)
                    self._engine.runAndWait()
            except Exception:
                log.exception("Could not speak")
                self._engine = None  # start fresh next time
            finally:
                done.set()


class FakeSpeaker(Speaker):
    """Records what would have been said. For tests."""

    def __init__(self):
        self.said: list[str] = []
        self.stops = 0

    def say(self, text: str) -> None:
        self.said.append(text)

    def stop(self) -> None:
        self.stops += 1
