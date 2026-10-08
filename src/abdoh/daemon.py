"""The main loop: wake → record → transcribe → route → speak, with error recovery."""

import logging
import threading
from collections.abc import Callable

from abdoh.audio.listener import listen_for_request
from abdoh.audio.mic import MicrophoneError
from abdoh.audio.wakeword import WakeWordEngine
from abdoh.config import Config
from abdoh.router import Router
from abdoh.speech.tts import Speaker

log = logging.getLogger(__name__)

MIC_RETRY_SECONDS = 5.0
SORRY = "Sorry, something went wrong."


class Daemon:
    def __init__(
        self,
        cfg: Config,
        router: Router,
        speaker: Speaker,
        mic_factory: Callable[[], object],
        engine: WakeWordEngine,
        transcriber,
        mic_retry_seconds: float = MIC_RETRY_SECONDS,
    ):
        self.cfg = cfg
        self.router = router
        self.speaker = speaker
        self.mic_factory = mic_factory
        self.engine = engine
        self.transcriber = transcriber
        self.mic_retry_seconds = mic_retry_seconds
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    def handle_text(self, text: str) -> str:
        """Route one request and speak the reply. Never raises."""
        log.info("You: %s", text)
        try:
            reply = self.router.handle(text)
        except Exception:
            log.exception("Error handling %r", text)
            reply = SORRY
        if reply:
            log.info("Abdoh: %s", reply)
            try:
                self.speaker.say(reply)
            except Exception:
                log.exception("Could not speak reply")
        return reply

    def run(self) -> None:
        """Listen forever (until stop()). Reopens the mic every few seconds if it goes away."""
        while not self.stop_event.is_set():
            try:
                mic = self.mic_factory()
                mic.start()
            except MicrophoneError as e:
                log.warning("%s. Retrying in %.0f s.", e, self.mic_retry_seconds)
                self.stop_event.wait(self.mic_retry_seconds)
                continue
            log.info("Listening for the wake word.")
            try:
                while not self.stop_event.is_set():
                    self._listen_once(mic)
            except MicrophoneError as e:
                log.warning("%s. Retrying in %.0f s.", e, self.mic_retry_seconds)
                self.stop_event.wait(self.mic_retry_seconds)
            finally:
                mic.stop()

    @classmethod
    def create(cls, cfg: Config, speaker: Speaker | None = None) -> "Daemon":
        """Build a daemon with the real microphone, Vosk, Whisper and TTS."""
        from abdoh.audio.mic import Microphone
        from abdoh.audio.stt import Transcriber
        from abdoh.audio.wakeword import VoskWakeWord
        from abdoh.commands.registry import CommandRegistry
        from abdoh.speech.tts import Pyttsx3Speaker

        engine = VoskWakeWord(cfg.resolve(cfg.vosk_model), cfg.wake_words + cfg.wake_word_aliases)
        transcriber = Transcriber(cfg.whisper_model, cfg.language)
        transcriber.transcribe(b"\0\0" * 1600)  # load the model now, not on the first request
        router = Router(cfg, CommandRegistry(cfg.commands_path))
        speaker = speaker or Pyttsx3Speaker(cfg.tts_rate)
        return cls(cfg, router, speaker, Microphone, engine, transcriber)

    def _listen_once(self, mic) -> None:
        try:
            text = listen_for_request(
                mic,
                self.engine,
                self.transcriber,
                self.speaker,
                self.cfg,
                should_stop=self.stop_event.is_set,
            )
        except MicrophoneError:
            raise
        except Exception:
            log.exception("Error while listening")
            return
        if text:
            self.handle_text(text)
            mic.clear()  # don't react to our own voice
            self.engine.reset()
