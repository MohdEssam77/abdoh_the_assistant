"""Text-to-speech behind a small Speaker interface.

On Windows Abdoh drives the Windows voice (SAPI) directly: pyttsx3 2.99 cut off its own speech
there, so replies were silent. pyttsx3 is still used on macOS and Linux.
"""

import logging
import math
import queue
import re
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

    def pause(self) -> bool:
        """Go quiet now, ready to go on from the same word with resume(). False if nothing was
        being said or this voice can't continue (then it has simply stopped)."""
        self.stop()
        return False

    def resume(self) -> None:  # noqa: B027 - optional hook
        """Go on with the text that pause() interrupted."""

    # The language you last spoke ("" = unknown): a hint for choosing the voice.
    language = ""


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
        self._pause = threading.Event()  # go quiet, and wait for _resume (or _stop)
        self._resume = threading.Event()
        self._speaking = False  # a text is being read right now
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

    def resume(self) -> None:
        self._pause.clear()
        self._resume.set()

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


# ----- languages -----

# Windows language ids (the low 10 bits of a voice's LCID) and their codes and names.
LANGUAGE_IDS = {
    0x01: "ar", 0x04: "zh", 0x07: "de", 0x08: "el", 0x09: "en", 0x0A: "es", 0x0C: "fr",
    0x0D: "he", 0x10: "it", 0x11: "ja", 0x12: "ko", 0x13: "nl", 0x15: "pl", 0x16: "pt",
    0x19: "ru", 0x1D: "sv", 0x1F: "tr", 0x20: "ur", 0x21: "id", 0x29: "fa", 0x39: "hi",
}  # fmt: skip
LANGUAGE_NAMES = {
    "ar": "Arabic", "zh": "Chinese", "de": "German", "el": "Greek", "en": "English",
    "es": "Spanish", "fr": "French", "he": "Hebrew", "it": "Italian", "ja": "Japanese",
    "ko": "Korean", "nl": "Dutch", "pl": "Polish", "pt": "Portuguese", "ru": "Russian",
    "sv": "Swedish", "tr": "Turkish", "ur": "Urdu", "id": "Indonesian", "fa": "Persian",
    "hi": "Hindi",
}  # fmt: skip
# Writing systems that tell the language (or narrow it down): (first, last, languages).
_SCRIPTS = [
    (0x0600, 0x06FF, ("ar", "ur", "fa")),
    (0x0590, 0x05FF, ("he",)),
    (0x0400, 0x04FF, ("ru",)),
    (0x0370, 0x03FF, ("el",)),
    (0x0900, 0x097F, ("hi",)),
    (0x3040, 0x30FF, ("ja",)),  # kana: Japanese even when mixed with Chinese characters
    (0xAC00, 0xD7AF, ("ko",)),
    (0x4E00, 0x9FFF, ("zh", "ja")),
]
LATIN = ("en", "fr", "de", "es", "it", "pt", "nl", "pl", "sv", "tr", "id")


def voice_language(attribute: str) -> str:
    """A SAPI voice's "Language" attribute ("409", "401;1") as a language code ("en", "ar")."""
    try:
        return LANGUAGE_IDS.get(int(str(attribute).split(";")[0], 16) & 0x3FF, "")
    except ValueError:
        return ""


# Everyday German words that aren't English words too (so "die", "was", "war", "in", "man" and
# "bin" are left out), to hear a German sentence in Latin letters.
GERMAN_WORDS = frozenset(
    "ich du er sie es wir ihr und oder aber auch nicht kein keine ein eine einen einem der das dem "
    "ist sind bin bist habe hast haben hatte wird werden kann kannst muss soll will gibt geht "
    "mit von zu auf aus bei nach für über um im zum zur vom beim ans mir dir mich dich uns euch "
    "sich mein dein sein wie wo wer wann warum weil wenn dass noch schon nur sehr ja nein "
    "danke bitte hallo guten morgen heute gestern jetzt hier dort gut gern genau vielleicht "
    "doch mal denn dann also wirklich ganz mehr immer nichts alles etwas".split()
)
_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?")


def looks_german(text: str) -> bool:
    """Is this Latin-letter sentence German? Two German function words, or one in a very short
    sentence ("Ja.", "Guten Morgen!"). Mixed sentences ("Das war Wie geht's, right?") count."""
    words = [w.lower() for w in _WORD.findall(text)]
    found = sum(w in GERMAN_WORDS or w.split("'")[0] in GERMAN_WORDS for w in words)
    return found >= 2 or (found == 1 and len(words) <= 3)


def text_language(text: str, hint: str = "") -> str:
    """The language to read `text` in: its writing system decides when it can (Arabic letters
    are never read by an English voice). For Latin letters, `hint` (the language you spoke)
    unless that's English (or unknown) and the sentence itself is German: Claude answers in
    German even when speech recognition only knew English. Otherwise English."""
    letters = [ord(c) for c in text if c.isalpha()]
    if letters:
        for first, last, languages in _SCRIPTS:
            if sum(first <= c <= last for c in letters) >= max(1, len(letters) * 0.3):
                return hint if hint in languages else languages[0]
    if hint in LATIN and hint != "en":
        return hint
    return "de" if looks_german(text) else "en"


# ----- Windows: SAPI -----

# SAPI's SpeechVoiceSpeakFlags.
SVSF_ASYNC = 1
SVSF_PURGE_BEFORE_SPEAK = 2
SVSF_IS_NOT_XML = 16
POLL_MS = 50  # while speaking, check this often whether to stop
# Windows' newer voices (Settings > Time & language > Speech), which include other languages.
ONECORE_VOICES = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices"


def _make_sapi_voice():
    import comtypes.client

    return comtypes.client.CreateObject("SAPI.SpVoice", dynamic=True)


def _onecore_tokens() -> list:
    import comtypes.client

    category = comtypes.client.CreateObject("SAPI.SpObjectTokenCategory", dynamic=True)
    category.SetId(ONECORE_VOICES, False)
    tokens = category.EnumerateTokens()
    return [tokens.Item(i) for i in range(tokens.Count)]


def installed_voices(voice, onecore: Callable[[], list] | None = None) -> list[tuple]:
    """Every voice this SAPI voice object can use, as (name, language code, token): the classic
    desktop voices, then Windows' newer ones."""
    tokens = voice.GetVoices()
    found = [tokens.Item(i) for i in range(tokens.Count)]
    if onecore is not None:
        try:
            found += onecore()
        except Exception:
            log.debug("Couldn't list Windows' newer voices", exc_info=True)
    voices, seen = [], set()
    for token in found:
        name = token.GetDescription()
        if name not in seen:
            seen.add(name)
            voices.append((name, voice_language(token.GetAttribute("Language")), token))
    return voices


def sapi_rate(words_per_minute: float) -> int:
    """SAPI's speed (-10 to 10) for a speaking rate in words per minute (pyttsx3's scale)."""
    return max(-10, min(10, round(math.log(max(1.0, words_per_minute) / 156.63, 1.11))))


def windows_voices(voice_factory: Callable[[], object] = _make_sapi_voice) -> list[str]:
    """The names of the installed Windows voices, e.g. "Microsoft Zira Desktop - English (United
    States)". Empty if there are none (or this isn't Windows)."""
    real = voice_factory is _make_sapi_voice
    if sys.platform != "win32" and real:
        return []
    _init_com()
    try:
        voices = installed_voices(voice_factory(), _onecore_tokens if real else None)
        return [name for name, _, _ in voices]
    except Exception:
        log.warning("Couldn't list the Windows voices", exc_info=True)
        return []


class SapiSpeaker(_VoiceThread):
    """The Windows voice (SAPI), driven directly. `stop()` cuts it off within POLL_MS.

    Each text is read by a voice for its language: your chosen voice when it speaks that
    language, otherwise the first installed voice that does. `language` is the language you
    last spoke (a hint for text in Latin letters).
    """

    def __init__(
        self,
        rate: int = 175,
        voice: str = "",
        voice_factory: Callable[[], object] = _make_sapi_voice,
        onecore: Callable[[], list] | None = None,
    ):
        self.rate = rate
        self.voice = voice  # a voice's name ("" = the Windows default)
        self.language = ""
        self.on_missing_voice: Callable[[str], None] | None = None
        self._onecore = onecore or (_onecore_tokens if voice_factory is _make_sapi_voice else None)
        self._voices: list[tuple] = []
        self._default = ("", "en", None)  # the voice SAPI starts with
        self._missing: set[str] = set()
        super().__init__(voice_factory)

    def _new_engine(self):
        voice = self._factory()
        voice.Rate = sapi_rate(self.rate)
        self._voices = installed_voices(voice, self._onecore)
        start = getattr(voice, "Voice", None)
        try:
            language = voice_language(start.GetAttribute("Language")) or "en"
            self._default = (start.GetDescription(), language, start)
        except Exception:
            self._default = ("", "en", None)
        chosen = next((v for v in self._voices if v[0] == self.voice), None)
        if chosen is not None:
            self._default = chosen
        elif self.voice:
            log.warning("Voice %r isn't installed; using the default voice", self.voice)
        return voice

    def _voice_for(self, language: str):
        """The (name, language, token) to read this language with, or None if nothing can."""
        if self._default[1] == language:
            return self._default
        return next((v for v in self._voices if v[1] == language), None)

    def pause(self) -> bool:
        if not self._speaking:
            return False
        self._resume.clear()
        self._pause.set()
        return True

    def _speak(self, text: str) -> None:
        self._speaking = True
        try:
            self._read(text)
        finally:
            self._speaking = False
            self._pause.clear()

    def _read(self, text: str) -> None:
        voice = self._engine
        language = text_language(text, self.language)
        chosen = self._voice_for(language)
        if chosen is None:
            if language not in self._missing:
                self._missing.add(language)
                log.warning("No installed voice speaks %s", LANGUAGE_NAMES.get(language, language))
                if self.on_missing_voice:
                    self.on_missing_voice(language)
            if language not in LATIN:
                return  # an English voice can't read these letters at all
            chosen = self._default
        if chosen[2] is not None:
            voice.Voice = chosen[2]
        start = 0  # where in `text` the voice was last started
        voice.Speak(text, SVSF_ASYNC | SVSF_IS_NOT_XML)
        while not voice.WaitUntilDone(POLL_MS):
            if self._stop.is_set():
                voice.Speak("", SVSF_ASYNC | SVSF_PURGE_BEFORE_SPEAK)
                return
            if not self._pause.is_set():
                continue
            # Purging stops it within a few milliseconds; SAPI's own Pause() takes a second.
            start += _word_position(voice)
            voice.Speak("", SVSF_ASYNC | SVSF_PURGE_BEFORE_SPEAK)
            while not (self._resume.wait(POLL_MS / 1000) or self._stop.is_set()):
                pass
            self._resume.clear()
            rest = text[start:]
            if self._stop.is_set() or not rest.strip():
                return
            voice.Speak(rest, SVSF_ASYNC | SVSF_IS_NOT_XML)


def _word_position(voice) -> int:
    """Where the voice is in the text it was given: the start of the word being spoken."""
    try:
        return max(0, int(voice.Status.InputWordPosition))
    except Exception:
        return 0


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
        self.language = ""
        self.said: list[str] = []
        self.stops = 0
        self.pauses = 0
        self.resumes = 0
        self.can_pause = True  # set False to act like a voice that can't continue

    def say(self, text: str) -> None:
        self.said.append(text)

    def stop(self) -> None:
        self.stops += 1

    def pause(self) -> bool:
        self.pauses += 1
        return self.can_pause

    def resume(self) -> None:
        self.resumes += 1
