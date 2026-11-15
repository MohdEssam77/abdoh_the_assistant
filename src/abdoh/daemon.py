"""The main loop: wake → record → transcribe → route → speak, with error recovery.

Also serves requests from the UI (typed text, pause, set key, ...) on a second thread.
"""

import logging
import threading
import time
from collections.abc import Callable

from abdoh.audio.listener import listen_for_request
from abdoh.audio.mic import MicrophoneError
from abdoh.audio.wakeword import WakeWordEngine
from abdoh.config import Config, save_api_key
from abdoh.events import Bus
from abdoh.router import Router
from abdoh.speech.earcons import Earcons
from abdoh.speech.tts import Speaker

log = logging.getLogger(__name__)

MIC_RETRY_SECONDS = 5.0
SORRY = "Sorry, something went wrong."
# After the hotkey, nothing louder than this came from the mic (of 32768): it's muted or
# turned right down. Speech is usually in the thousands.
QUIET_MIC_PEAK = 100
MIC_TOO_QUIET = "I didn't hear anything. Your microphone may be muted or turned down."


class Daemon:
    ALARM_SECONDS = 0.7

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
        earcons: Earcons | None = None,
        vad=None,
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
        self.earcons = earcons or Earcons.silent()
        self.vad = vad  # SileroVad, or None to detect the end of speech by loudness
        self.stop_event = threading.Event()
        self._interrupted = threading.Event()  # "stop speaking" for the current request
        self._listen_now = threading.Event()  # the hotkey was pressed
        self._via_hotkey = False
        self._awaiting_answer = False  # Claude asked a question: listen for the answer next
        self._recording = False
        self.paused = False
        self.voice_enabled = True
        self._woke = time.perf_counter()
        self._handle_lock = threading.Lock()
        router.on_thinking = self._thinking
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
        self._speak(text)

    def _speak(self, text: str) -> None:
        self.earcons.stop_ticking()
        if not self.voice_enabled or self._interrupted.is_set():
            return
        self.bus.emit("status", "Speaking")
        try:
            self.speaker.say(text)
        except Exception:
            log.exception("Could not speak")

    def _speak_stream(self, sentences, started: float) -> str:
        """Speak a streamed (Claude) reply sentence by sentence; show it in the history once."""
        spoken: list[str] = []
        try:
            for sentence in sentences:
                if not spoken:
                    log.debug("Latency: first sentence after %.2fs", time.perf_counter() - started)
                spoken.append(sentence)
                self._speak(sentence)
                if self._interrupted.is_set():
                    break  # don't wait for (or read) the rest of the answer
        except Exception:
            log.exception("Error while speaking a streamed reply")
            spoken.append(SORRY)
            self._speak(SORRY)
        finally:
            close = getattr(sentences, "close", None)
            if close:
                close()  # stops Claude if we were interrupted
        text = " ".join(spoken)
        if text:
            log.info("Abdoh: %s", text)
            self.bus.emit("history", f"Abdoh: {text}")
        return text

    def announce(self, text: str) -> None:
        """Something finished on its own (a timer): get attention, then say it."""
        with self._handle_lock:
            self._interrupted.clear()
            self.earcons.play("alarm")  # even when voice replies are off
            self.stop_event.wait(self.ALARM_SECONDS)  # let the alarm finish before speaking
            self.say(text)
            self._status_idle()

    def push_to_talk(self) -> None:
        """The hotkey: stop a reply that's being spoken, otherwise listen for one request."""
        if self._handle_lock.locked():
            self.stop_speaking()
        elif self._recording:
            return  # already listening to you
        elif self.listen_error:
            self.bus.emit("history", f"Abdoh: Voice input isn't available ({self.listen_error}).")
        else:
            self._listen_now.set()

    def _take_listen_now(self) -> bool:
        if self._listen_now.is_set():
            self._listen_now.clear()
            self._via_hotkey = True
            return True
        return False

    def _on_listen(self) -> None:
        self._recording = True
        self._interrupted.clear()
        self.bus.emit("status", "Listening to you...")
        self.earcons.play("listening")

    def _heard_nothing(self, loudest: int) -> None:
        """Nothing was said after the hotkey or Claude's question. If you pressed the hotkey
        and the mic was nearly silent, say so: it's probably muted."""
        log.info("Heard nothing (loudest sound %d of 32768)", loudest)
        if self._via_hotkey and loudest < QUIET_MIC_PEAK:
            self.say(MIC_TOO_QUIET)

    def stop_speaking(self) -> None:
        """Interrupt the current reply (from the window, tray or hotkey)."""
        log.info("Stop speaking")
        self._interrupted.set()
        self.earcons.stop_ticking()
        self.speaker.stop()

    def _thinking(self) -> None:
        """A slow request (Claude) started: show it and tick until the answer comes."""
        self.bus.emit("status", "Thinking...")
        if self.voice_enabled:
            self.earcons.start_ticking("thinking")

    def handle_text(self, text: str, voice: bool = False) -> str:
        """Route one request and speak the reply. Never raises.

        `voice`: the request was spoken, so if Claude's reply ends with a question, Abdoh
        listens for the answer next (no wake word needed).
        """
        with self._handle_lock:
            self._interrupted.clear()
            log.info("You: %s", text)
            self.bus.emit("history", f"You: {text}")
            self.bus.emit("status", "Thinking...")
            started = time.perf_counter()
            try:
                reply = self.router.handle(text)
            except Exception:
                log.exception("Error handling %r", text)
                reply = SORRY
            if isinstance(reply, str):
                log.debug("Latency: reply ready in %.2fs", time.perf_counter() - started)
                if reply:
                    self.say(reply)
            else:
                reply = self._speak_stream(reply, started)
                if voice:
                    self._awaiting_answer = self._asked_question(reply)
            self.earcons.stop_ticking()
            self._status_idle()
            return reply

    def _asked_question(self, reply: str) -> bool:
        """Did Claude end its reply with a question (and you didn't stop it)?"""
        return (
            self.cfg.claude.listen_after_question
            and not self._interrupted.is_set()
            and reply.rstrip(" \"'”’)").endswith("?")
        )

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
        elif kind == "commands_changed":  # saved in the app: use them right away
            error = self.router.registry.refresh(force=True)
            if error:
                self.bus.emit("history", f"Abdoh: Commands file error: {error}")
        elif kind == "edit_commands":
            from abdoh.commands.actions import ActionError, open_in_editor

            try:
                open_in_editor(self.cfg.commands_path)
            except ActionError as e:
                self.bus.emit("history", f"Abdoh: {e}")
        elif kind == "stop_speaking":
            self.stop_speaking()
        elif kind == "listen":
            self.push_to_talk()  # the window's Talk button
        elif kind == "voice":
            self.voice_enabled = bool(value)
            self.bus.emit("voice", self.voice_enabled)
        elif kind == "set_key":
            self._set_key(value or "")
        elif kind == "quit":
            self.stop()
            self.bus.emit("quit")

    def _set_key(self, key: str) -> None:
        from abdoh.claude.brain import make_brain

        key = key.strip()
        save_api_key(self.cfg.env_path, key)
        self.cfg.anthropic_api_key = key or None
        self.router.brain = make_brain(self.cfg)
        self._report_claude()
        self.bus.emit(
            "history", "Abdoh: Claude key saved." if key else "Abdoh: Claude key removed."
        )

    def _report_claude(self) -> None:
        """Show how Claude is connected. Claude Code's sign-in is checked in the background."""
        brain = self.router.brain
        if brain is None:
            self.bus.emit("claude", "not connected")
            return
        self.bus.emit("claude", brain.name)

        def check() -> None:
            try:
                self.bus.emit("claude", brain.status())
            except Exception:
                log.exception("Couldn't check the Claude connection")

        threading.Thread(target=check, name="abdoh-claude-status", daemon=True).start()

    def serve_requests(self) -> None:
        """Process UI requests until stop().

        Typed requests run on their own thread, so "stop speaking" and "pause" are handled
        right away even while a reply is being spoken.
        """
        while not self.stop_event.is_set():
            message = self.bus.next_request(timeout=0.2)
            if not message:
                continue
            if message[0] == "text":
                threading.Thread(
                    target=self._safe_request, args=message, name="abdoh-typed", daemon=True
                ).start()
            else:
                self._safe_request(*message)

    def _safe_request(self, kind: str, value=None) -> None:
        try:
            self.handle_request(kind, value)
        except Exception:
            log.exception("Error handling UI request %r", (kind, value))

    # ----- listening -----

    def run(self) -> None:
        """Listen forever (until stop()). Reopens the mic every few seconds if it goes away."""
        self._report_claude()
        if self.engine is not None:
            self.bus.emit("wake", self.engine.label)
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
        self._awaiting_answer = False  # too late to answer once the mic is back
        log.warning("%s. Retrying in %.0f s.", error, self.mic_retry_seconds)
        self.bus.emit("status", "Error: microphone not available, retrying")
        self.stop_event.wait(self.mic_retry_seconds)

    def _on_wake(self) -> None:
        self._woke = time.perf_counter()
        self._recording = True
        self._interrupted.clear()
        self.bus.emit("status", "Thinking...")

    def _listen_once(self, mic) -> None:
        answer, self._awaiting_answer = self._awaiting_answer, False
        try:
            text = listen_for_request(
                mic,
                self.engine,
                self.transcriber,
                self,  # speaks "Yes?" through say(), respecting the voice toggle
                self.cfg,
                should_stop=self.stop_event.is_set,
                on_wake=self._on_wake,
                vad=self.vad,
                pressed=self._take_listen_now,
                on_listen=self._on_listen,
                answer=answer,
                on_nothing=self._heard_nothing,
            )
        except MicrophoneError:
            raise
        except Exception:
            log.exception("Error while listening")
            self._status_idle()
            return
        finally:
            self._recording = False
        via_hotkey, self._via_hotkey = self._via_hotkey, False
        if text and (via_hotkey or answer):
            self.handle_text(text, voice=True)  # the hotkey and answers work even while paused
        elif text and self.paused:
            # While paused, only the built-in "start listening" command is honored.
            if self.router.builtin_name(text) == "start_listening":
                self.handle_text(text, voice=True)
            else:
                log.info("Paused; ignoring %r", text)
        elif text:
            self.handle_text(text, voice=True)
            log.debug("Latency: wake word to reply spoken %.2fs", time.perf_counter() - self._woke)
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
        from abdoh.audio.vad import load_vad
        from abdoh.audio.wakeword import load_wake_engine
        from abdoh.claude.brain import make_brain
        from abdoh.commands.registry import CommandRegistry
        from abdoh.computer import AppIndex, Computer, Timers
        from abdoh.speech.tts import make_speaker

        speaker = speaker or make_speaker(cfg.tts_rate)
        getattr(speaker, "warm_up", lambda: None)()  # the first reply shouldn't pay for it

        engine = transcriber = None
        listen_error = None
        try:
            engine = load_wake_engine(cfg)
            transcriber = Transcriber(cfg.whisper_model, cfg.language)
            transcriber.transcribe(b"\0\0" * 1600)  # load the model now, not on first request
        except Exception as e:
            log.exception("Could not set up voice input")
            listen_error = str(e)
        router = Router(cfg, CommandRegistry(cfg.commands_path), brain=make_brain(cfg))
        daemon = cls(
            cfg,
            router,
            speaker,
            Microphone,
            engine,
            transcriber,
            bus,
            listen_error=listen_error,
            earcons=Earcons(),
            vad=load_vad(),
        )
        router.computer = Computer(timers=Timers(announce=daemon.announce), apps=AppIndex())
        router.computer.apps.load_in_background()
        return daemon
