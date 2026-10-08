"""Text-to-speech behind a small Speaker interface."""

import logging
import threading
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)


class Speaker(ABC):
    @abstractmethod
    def say(self, text: str) -> None:
        """Speak text aloud, blocking until done."""


class Pyttsx3Speaker(Speaker):
    """Offline TTS via pyttsx3.

    A fresh engine is created per call: pyttsx3 engines are not reliable when reused across
    threads or after errors, and creating one is cheap.
    """

    def __init__(self, rate: int = 175):
        self.rate = rate
        self._lock = threading.Lock()

    def say(self, text: str) -> None:
        if not text.strip():
            return
        import pyttsx3

        with self._lock:
            engine = pyttsx3.init()
            try:
                engine.setProperty("rate", self.rate)
                engine.say(text)
                engine.runAndWait()
            finally:
                engine.stop()


class FakeSpeaker(Speaker):
    """Records what would have been said. For tests."""

    def __init__(self):
        self.said: list[str] = []

    def say(self, text: str) -> None:
        self.said.append(text)
