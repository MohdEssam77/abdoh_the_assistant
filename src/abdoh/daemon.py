"""The main loop: wake → record → transcribe → route → speak, with error recovery.

Also serves requests from the UI (typed text, pause, set key, ...) on a second thread.
"""

import logging
import threading
from collections.abc import Callable

from abdoh.audio.listener import listen_for_request
from abdoh.audio.mic import MicrophoneError
from abdoh.audio.wakeword import WakeWordEngine
from abdoh.config import Config, save_api_key
from abdoh.events import Bus
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
        mic_factory: Callable[[], object] | None,
        engine: WakeWordEngine | None,
        transcriber,
        bus: Bus | None = None,
        mic_retry_seconds: float = MIC_RETRY_SECONDS,
        listen_error: str | None = None,
    ):
        self.cfg = cfg
        self.router = router
        self.speaker = speaker
        self.mic_factory = mic_factory
        self.engine = engine
        self.transcriber = transcriber
        self.bus = bus or Bus(ui_attached=False)
        self.mic_retry_seconds = mic_retry_seconds
        self.listen_error = listen_error  # set when voice input couldn't be set up
        self.stop_event = threading.Event()
        self.paused = False
        self.voice_enabled = True
        self._handle_lock = threading.Lock()
        router.notify = self.say
        router.add_builtin("show_window", ["show window", "open window"], self._show_window)
        router.add_builtin("stop_listening", ["stop listening"], self._stop_listening)
        router.add_builtin("start_listening", ["start listening"], self._start_listening)
        router.add_builtin(
            "reload_commands", ["reload commands", "reload my commands"], self._reload_commands
        )

    # ----- state -----

    def stop(self) -> None:
        self.stop_event.set()

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        log.info("Listening %s", "paused" if paused else "resumed")
        self._status_idle()

    def _status_idle(self) -> None:
        if self.listen_error:
            self.bus.emit("status", f"Error: {self.listen_error}")
        else:
            self.bus.emit("status", "Paused" if self.paused else "Listening")

    def _show_window(self) -> str:
        self.bus.emit("show")
        return ""

    def _stop_listening(self) -> str:
        self.set_paused(True)
        return "Okay, I'll stop listening. Say Abdoh, start listening, when you need me."

    def _start_listening(self) -> str:
        self.set_paused(False)
        return "I'm listening again."

    def _reload_commands(self) -> str:
        error = self.router.registry.refresh(force=True)
        if error:
            return "Your commands file has an error."
        return f"Reloaded {len(self.router.registry.commands)} commands."

    # ----- speaking and handling requests -----

    def say(self, text: str) -> None:
        """Show text in the history and speak it (if voice replies are on). Never raises."""
        log.info("Abdoh: %s", text)
        self.bus.emit("history", f"Abdoh: {text}")
        if not self.voice_enabled:
            return
        self.bus.emit("status", "Speaking")
        try:
            self.speaker.say(text)
        except Exception:
            log.exception("Could not speak")

    def handle_text(self, text: str) -> str:
        """Route one request and speak the reply. Never raises."""
        with self._handle_lock:
            log.info("You: %s", text)
            self.bus.emit("history", f"You: {text}")
            self.bus.emit("status", "Thinking...")
            try:
                reply = self.router.handle(text)
            except Exception:
                log.exception("Error handling %r", text)
                reply = SORRY
            if reply:
                self.say(reply)
            self._status_idle()
            return reply

    def handle_request(self, kind: str, value=None) -> None:
        """One request from the UI."""
        if kind == "text":
            if value and value.strip():
                self.handle_text(value.strip())
        elif kind == "pause":
            self.set_paused(True)
        elif kind == "resume":
            self.set_paused(False)
        elif kind == "reload":
            error = self.router.registry.refresh(force=True)
            count = len(self.router.registry.commands)
            message = f"Commands file error: {error}" if error else f"Loaded {count} commands."
            self.bus.emit("history", f"Abdoh: {message}")
        elif kind == "edit_commands":
            from abdoh.commands.actions import ActionError, open_in_editor

            try:
                open_in_editor(self.cfg.commands_path)
            except ActionError as e:
                self.bus.emit("history", f"Abdoh: {e}")
        elif kind == "voice":
            self.voice_enabled = bool(value)
        elif kind == "set_key":
            self._set_key(value or "")
        elif kind == "quit":
            self.stop()
            self.bus.emit("quit")

    def _set_key(self, key: str) -> None:
        from abdoh.claude.client import make_claude

        key = key.strip()
        save_api_key(self.cfg.env_path, key)
        self.cfg.anthropic_api_key = key or None
        self.router.claude = make_claude(self.cfg)
        self.bus.emit("claude", self.cfg.claude_enabled)
        self.bus.emit(
            "history", "Abdoh: Claude key saved." if key else "Abdoh: Claude key removed."
        )

    def serve_requests(self) -> None:
        """Process UI requests until stop()."""
        while not self.stop_event.is_set():
            message = self.bus.next_request(timeout=0.2)
            if message:
                try:
                    self.handle_request(*message)
                except Exception:
                    log.exception("Error handling UI request %r", message)

    # ----- listening -----

    def run(self) -> None:
        """Listen forever (until stop()). Reopens the mic every few seconds if it goes away."""
        self.bus.emit("claude", self.cfg.claude_enabled)
        self._status_idle()
        if self.listen_error:
            log.error("Voice input unavailable: %s", self.listen_error)
            self.stop_event.wait()
            return
        while not self.stop_event.is_set():
            try:
                mic = self.mic_factory()
                mic.start()
            except MicrophoneError as e:
                self._mic_problem(e)
                continue
            log.info("Listening for the wake word.")
            self._status_idle()
            try:
                while not self.stop_event.is_set():
                    self._listen_once(mic)
            except MicrophoneError as e:
                self._mic_problem(e)
            finally:
                mic.stop()

    def _mic_problem(self, error: Exception) -> None:
        log.warning("%s. Retrying in %.0f s.", error, self.mic_retry_seconds)
        self.bus.emit("status", "Error: microphone not available, retrying")
        self.stop_event.wait(self.mic_retry_seconds)

    def _listen_once(self, mic) -> None:
        try:
            text = listen_for_request(
                mic,
                self.engine,
                self.transcriber,
                self,  # speaks "Yes?" through say(), respecting the voice toggle
                self.cfg,
                should_stop=self.stop_event.is_set,
                on_wake=lambda: self.bus.emit("status", "Thinking..."),
            )
        except MicrophoneError:
            raise
        except Exception:
            log.exception("Error while listening")
            self._status_idle()
            return
        if text and self.paused:
            # While paused, only the built-in "start listening" command is honored.
            if self.router.builtin_name(text) == "start_listening":
                self.handle_text(text)
            else:
                log.info("Paused; ignoring %r", text)
        elif text:
            self.handle_text(text)
        self._status_idle()
        mic.clear()  # don't react to our own voice
        self.engine.reset()

    @classmethod
    def create(
        cls, cfg: Config, bus: Bus | None = None, speaker: Speaker | None = None
    ) -> "Daemon":
        """Build a daemon with the real microphone, Vosk, Whisper and TTS.

        If voice input can't be set up (e.g. the Vosk model is missing), the daemon still
        handles typed requests and reports the problem as its status.
        """
        from abdoh.audio.mic import Microphone
        from abdoh.audio.stt import Transcriber
        from abdoh.audio.wakeword import VoskWakeWord
        from abdoh.claude.client import make_claude
        from abdoh.commands.registry import CommandRegistry
        from abdoh.speech.tts import Pyttsx3Speaker

        engine = transcriber = None
        listen_error = None
        try:
            phrases = cfg.wake_words + cfg.wake_word_aliases
            engine = VoskWakeWord(cfg.resolve(cfg.vosk_model), phrases)
            transcriber = Transcriber(cfg.whisper_model, cfg.language)
            transcriber.transcribe(b"\0\0" * 1600)  # load the model now, not on first request
        except Exception as e:
            log.exception("Could not set up voice input")
            listen_error = str(e)
        router = Router(cfg, CommandRegistry(cfg.commands_path), claude=make_claude(cfg))
        speaker = speaker or Pyttsx3Speaker(cfg.tts_rate)
        return cls(
            cfg, router, speaker, Microphone, engine, transcriber, bus, listen_error=listen_error
        )
