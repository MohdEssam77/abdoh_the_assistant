"""The main loop: wake → record → transcribe → route → speak, with error recovery.

Also serves requests from the UI (typed text, pause, set key, ...) on a second thread.
"""

import logging
import math
import random
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import fields

from abdoh.audio.listener import ANSWER_WAIT_SECONDS, listen_for_request, speech_detector
from abdoh.audio.mic import BYTES_PER_SECOND, MicrophoneError
from abdoh.audio.recorder import record_until_silence
from abdoh.audio.wakeword import NoWakeWord, WakeWordEngine
from abdoh.config import ClaudeConfig, Config, save_api_key
from abdoh.events import Bus
from abdoh.router import OVER_REPLY, Router
from abdoh.speech.earcons import Earcons
from abdoh.speech.tts import Speaker
from abdoh.system_skills import Done, Question

log = logging.getLogger(__name__)

MIC_RETRY_SECONDS = 5.0
# A device change waits this long for Abdoh's voice to finish before devices are read again.
RELOAD_WAIT_SECONDS = 30.0
# Housekeeping (see _housekeeping_tick): how often it looks, how often the speech model is
# warmed while idle, and how often old unclear clips are deleted.
HOUSEKEEPING_SECONDS = 30.0
WARM_EVERY_SECONDS = 240.0
PRUNE_EVERY_SECONDS = 3600.0
SORRY = "Sorry, something went wrong."
PHONE_PORT_TAKEN = (
    "The phone page couldn't start: port {port} is taken by another program. Choose another "
    "port in Settings → Phone."
)
# After the hotkey, nothing louder than this came from the mic (of 32768): it's muted or
# turned right down. Speech is usually in the thousands.
QUIET_MIC_PEAK = 100
# Teaching it your voice: louder than QUIET_MIC_PEAK but below this, the mic works but was too
# quiet to be taken for speech (far away, or turned down in Windows).
LOW_MIC_PEAK = 500


def how_quiet(loudest: int) -> str:
    """ "silent" (muted, or Windows doesn't let apps use the mic), "low", or "" (loud enough:
    it just wasn't speech)."""
    return "silent" if loudest < QUIET_MIC_PEAK else "low" if loudest < LOW_MIC_PEAK else ""


MIC_TOO_QUIET = "I didn't hear anything. Your microphone may be muted or turned down."
SAMPLE = "Hi, I'm Abdoh. This is how I sound."
# When Claude hasn't said anything after this long, Abdoh says it's still on it.
FILLER_SECONDS = 3.5
FILLERS = ("One moment.", "Let me think.", "Working on it.", "Just a second.")
NO_VOICE = (
    "I answered in {language}, but Windows has no {language} voice to read it. Add one in "
    "Windows Settings, under Time & language, Speech."
)
# After Abdoh heard you talk over it: how long to wait for the words to start.
INTERRUPTION_WAIT_SECONDS = 1.0
# A word or two said this soon after your request, before any of the answer: you were still
# saying what you wanted ("... in Berlin"), not someone else in the room.
CONTINUE_SECONDS = 3.0
# Shown (never said) after "stop listening".
STOPPED_LISTENING = "Stopped listening. Say “Abdoh, start listening” when you need me."
# Why Abdoh can't hear you over its own voice (shown in the settings).
NO_ECHO_CANCELLER = "the echo canceller couldn't be loaded"
NO_SPEAKER_TAP = "Abdoh can't hear what your speakers play"
# Why voice input is off (shown as the status; the details are in the log).
SPEECH_MODEL_FAILED = "the speech recognition model couldn't be loaded"


# What Claude's action is called in "Done: ...", where its own words would read badly.
DONE_WORDS = {"board_pdf": "saving the board as a PDF"}
# The window was asked to save the board and didn't answer in this long (the save itself takes
# a few seconds: drawings, then Edge).
BOARD_PDF_SECONDS = 45.0
BOARD_PDF_SILENT = (
    "I couldn't save the board: my window didn't answer. Try the Save as PDF button on the "
    "Act as page."
)


# Notices (say_later): said within this long, else left out; looked at this often.
LATER_SECONDS = 600.0
LATER_POLL_SECONDS = 0.2
LATER_GAP_SECONDS = 1.0  # ... and not straight after Abdoh's last words


def _still_true(check: Callable[[], bool]) -> bool:
    try:
        return bool(check())
    except Exception:
        log.debug("Couldn't check a notice", exc_info=True)
        return False


def _what_was_done(actions: list[tuple[str, str]]) -> str:
    """For the window, when Claude did something without a word: "Done: open app Spotify."."""
    from abdoh.codoh.voice import done_words

    parts = [
        done_words(arg)
        if kind == "codoh"
        else DONE_WORDS.get(kind) or f"{kind.replace('_', ' ')} {arg}"
        for kind, arg in actions
    ]
    return "Done: " + "; ".join(parts) + "."


class Daemon:
    ALARM_SECONDS = 0.7
    # While Abdoh keeps listening (a role is on): this much speech in a row starts a recording
    # (a cough or a click is shorter), and not until Abdoh's own voice has died away.
    HEAR_ONSET_SECONDS = 0.3
    HEAR_AFTER_SPEAKING_SECONDS = 0.8
    WATCH_MIN_SECONDS = 1.0  # watching the screen: never look more often than this

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
        voice_watch=None,
        ducker=None,
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
        self.voice_watch = voice_watch  # hears you talk over a reply (audio/bargein.py)
        self.ducker = ducker  # other apps go quieter while Abdoh listens (audio/ducking.py)
        # Speech recognition on the graphics card (audio/gpu_speech.py), set in create().
        self.gpu_speech = None
        self.model_switch = None  # the model chosen in Settings → Advanced (abdoh/models.py)
        self.modes = None  # abdoh.modes.engine.ModeEngine (see use_modes)
        self.acting = None  # abdoh.roles.acting.Acting (see use_roles)
        self._board_card = 0  # the board card the window last came up for
        self._board_text = ""  # and what's on it
        self._turn_board: dict[int, str] = {}  # what this reply put on the board (card: text)
        self._pictures_asked: set[str] = set()  # the board's pictures being found or found
        self._pictures = None  # abdoh.pictures.Pictures, made when first needed
        self._watching = False  # the voice watch is following a reply
        self._watch_looks = None  # the watch (its generation) a look loop runs for
        self._floor = threading.Event()  # set: Abdoh may speak; clear: you have the floor
        self._floor.set()
        self._request = ""  # the request being answered
        self._answered = False  # ... and part of its answer was said
        self._next_request: str | None = None  # said over a reply: handle it next
        self._via_voice = False  # this request interrupted a reply
        self._via_speech = False  # ... was heard while Abdoh keeps listening (no wake word)
        self._hear_vad = None  # the speech detector for that (its own state)
        self._hearing = False  # ... and it's hearing now
        self._heard_for = 0.0  # seconds of speech in a row so far
        self._hear_from = 0.0  # not before this (time.monotonic): Abdoh's voice dies away
        # A lesson (see keeps_listening): the window is open, the board shows something, and
        # when you last talked with Abdoh.
        self._window_open = False
        self._board_shown = False
        self._last_exchange = float("-inf")
        self._listening_now = False  # ... so Abdoh keeps listening right now (as last told)
        self.stop_event = threading.Event()
        self.mic = None  # the open microphone
        self._reopen_mic = threading.Event()  # a new microphone was chosen
        self.device_watch = None  # notices new microphones and speakers (audio/devices.py)
        # Reads Windows' devices again; False while a stream is open (reload_portaudio, set in
        # create(): tests never touch the real audio system).
        self.reload_devices: Callable[[], bool] = lambda: True
        self._devices_stale = False  # read the devices again before the mic opens next
        self._wake_heard = None  # how clearly the last wake word was heard (score, voice)
        self._warming = False  # the speech model is being warmed
        self._last_tick = self._last_warm = self._last_prune = None  # housekeeping
        self._interrupted = threading.Event()  # "stop speaking" for the current request
        self._listen_now = threading.Event()  # the hotkey was pressed
        self._capture: dict | None = None  # a recording for your voice check (record_voice)
        self.voice_scorer = None  # makes the wake word model the voice check trains with
        self._via_hotkey = False
        self._awaiting_answer = False  # listen for one more thing next, without the wake word
        self._answer_wait = ANSWER_WAIT_SECONDS  # ... for this long
        self._soft_chime = False  # ... announced by a softer sound than the hotkey's
        self._spoke = False  # something was said aloud for the current request
        # Abdoh from your phone (abdoh/phone): the service while the Phone switch is on, and
        # whether the request being answered came from the phone (its reply goes there).
        self.phone = None
        self._phone_turn = False
        if hasattr(speaker, "on_missing_voice"):
            speaker.on_missing_voice = self._missing_voice
        if hasattr(speaker, "on_download"):
            speaker.on_download = self._voice_download
        if hasattr(speaker, "on_playing"):
            speaker.on_playing = self._voice_playing
        self._mic_name: str | None = None  # the microphone the voice watch knows the room by
        self._recording = False
        self._you_stopped = False  # the window, tray or hotkey stopped the current reply
        self._quiet_wake = False  # woken while paused: listen without a sound, for "start"
        self.paused = False
        self.voice_enabled = True
        self._woke = time.perf_counter()
        self._handle_lock = threading.Lock()
        # One voice at a time: a reply's sentences, a filler ("Just a second"), a notice.
        self._voice_lock = threading.RLock()
        self._said: deque[tuple[float, str]] = deque(maxlen=8)  # what Abdoh said lately
        # Notices said when Abdoh is free (say_later): (text, still true?, when queued).
        self._later: deque[tuple[str, Callable[[], bool] | None, float]] = deque()
        self._later_event = threading.Event()
        self._later_thread: threading.Thread | None = None
        self._answer_window = False  # listening for an answer or an aside after a reply
        self._quiet_since = 0.0  # when Abdoh's voice last stopped (time.monotonic)
        router.on_thinking = self._thinking
        router.on_activity = self._activity
        router.on_board = self._on_board
        router.on_memory = lambda: self.bus.emit("memory", None)  # the Memory page refreshes
        router.on_self_edit = self._self_edited
        router.on_board_pdf = self._save_board  # the page prints it
        router.on_watch = self._watch_changed  # watching the screen began or ended
        router.codoh_note = self._codoh_note  # what Codoh does, while its page shows
        router.codoh = self._codoh  # ACTION codoh: chats in Codoh by voice
        router.on_codoh = self._show_codoh
        router.add_builtin("show_window", ["show window", "open window"], self._show_window)
        router.add_builtin(
            "open_codoh",
            # speech recognition often writes Codoh as Kodo, Codo or Kudo
            [
                "open codoh",
                "show codoh",
                "open the coding assistant",
                "codoh",
                "open kodo",
                "show kodo",
                "open codo",
                "open kudo",
            ],  # fmt: skip
            self._open_codoh,
        )
        router.add_builtin("stop_listening", ["stop listening"], self._stop_listening)
        router.add_builtin("start_listening", ["start listening"], self._start_listening)
        router.add_builtin(
            "reload_commands", ["reload commands", "reload my commands"], self._reload_commands
        )

    # ----- state -----

    def stop(self) -> None:
        self.stop_event.set()
        if self.gpu_speech is not None:
            self.gpu_speech.stop()  # a download continues next time
        if self.model_switch is not None:
            self.model_switch.stop()
        self._unduck()
        tap = getattr(self.voice_watch, "tap", None)
        if tap is not None:
            tap.stop()
        brain = self.router.brain
        if brain is not None:
            brain.close()
        self._phone_off()

    def _use_brain(self, brain) -> None:
        """Switch to a brain made from the settings as they are now. If nothing about Claude
        changed, the open conversation is kept."""
        old = self.router.brain
        if old is not None and brain is not None and old.same_setup(brain):
            brain.close()
        else:
            self.router.brain = brain
            if old is not None:
                old.close()
            self._connect_brain()
        self._report_claude()

    def _connect_brain(self) -> None:
        """Get Claude ready ahead of the first question, and hear what it's doing."""
        brain = self.router.brain
        if brain is None:
            return
        brain.on_activity = self._activity
        brain.state = self._state_line  # the mode that's on, with every message
        if hasattr(brain, "on_switch"):  # ChatGPT answers while Claude's limit is used up
            brain.on_switch = self._claude_switched
        warm_up = getattr(brain, "warm_up", None)
        if warm_up:
            warm_up()

    def _state_line(self) -> str:
        from abdoh.about import state_line

        mode = getattr(self.modes, "current", None) if self.modes is not None else None
        role = ""
        if self.acting is not None:
            role = self.acting.state_text(
                self.cfg.claude.voice_reply_max_sentences,
                lessons=self.cfg.lesson_listen_seconds > 0,
            )
        if role:
            role = f"{self._ai_pictures_now()}; {role}"
        return state_line(
            mode, self.voice_enabled, self.paused, self._screens_now(), role, self._lamps_now()
        )

    def _lamps_now(self) -> str:
        """Your lamps as they are now (found a minute ago in Settings, say), for Claude."""
        from abdoh.about import lamps_text

        lamps = getattr(getattr(self.router, "computer", None), "lamps", None)
        if lamps is None:
            return ""
        try:
            return lamps_text(lamps.all())
        except Exception:
            log.debug("Couldn't read the lamps", exc_info=True)
            return ""

    def _screens_now(self) -> str:
        """Which screens are connected and on right now ("" if Abdoh can't tell)."""
        displays = getattr(getattr(self.router, "computer", None), "displays", None)
        if displays is None:
            return ""
        try:
            return displays.summary()
        except Exception:
            log.debug("Couldn't read the screens", exc_info=True)
            return ""

    def _activity(self, text: str) -> None:
        """Claude started something slow (a web search, a file): show it, and say it if Claude
        didn't say what it was about to do."""
        self.bus.emit("activity", text)
        if not self._spoke and not self._phone_turn:  # the phone shows it as its status
            self._say_aside(f"{text}.")

    def _save_board(self) -> None:
        """Claude: ACTION board_pdf. The page draws the board and Abdoh prints it; the window
        answers (board_pdf_done). No answer: Abdoh says so, and it's in the log."""
        log.info("Asked the window to save the board as a PDF")
        old = getattr(self, "_board_wait", None)
        if old is not None:
            old.cancel()
        timer = threading.Timer(BOARD_PDF_SECONDS, self._board_pdf_silent)
        timer.daemon = True
        self._board_wait = timer
        timer.start()
        self.bus.emit("save_board", None)

    def _board_pdf_silent(self) -> None:
        log.warning("The window didn't answer the request to save the board as a PDF")
        self._board_wait = None
        self.say_later(BOARD_PDF_SILENT)

    def _board_pdf_done(self, ok: bool) -> None:
        timer = getattr(self, "_board_wait", None)
        self._board_wait = None
        if timer is not None:
            timer.cancel()

    def _say_aside(self, text: str) -> None:
        """Say a few words that aren't part of the answer (not shown in the conversation)."""
        if self._phone_turn:
            self.bus.emit("phone_aside", text)  # the phone shows it; the laptop stays quiet
            return
        if self.speaker.language not in ("", "en"):
            return  # these asides are English; the ticking sound says "still working"
        if self._speak(text):
            log.info("Abdoh (aside): %s", text)  # only what was said: Abdoh reads its own log
        if not self._interrupted.is_set():
            self.bus.emit("status", "Thinking...")

    def say_later(self, text: str, still: Callable[[], bool] | None = None) -> None:
        """Say this once Abdoh is free: not talking, not hearing you, not waiting for your
        answer (Codoh's notices, where the board's PDF went). Never over another reply.
        `still()`: it's still true then (Codoh still waits for that OK), else it's left out.
        It's shown in the conversation too."""
        if not text:
            return
        log.info("Abdoh will say when free: %s", text)
        self._later.append((text, still, time.monotonic()))
        self._later_event.set()
        thread = self._later_thread
        if thread is None or not thread.is_alive():
            thread = threading.Thread(target=self._say_when_free, name="abdoh-later", daemon=True)
            self._later_thread = thread
            thread.start()

    def _free_to_talk(self) -> bool:
        """Nothing else going on: no reply, nobody talking, no answer awaited, and Abdoh's last
        words have died away. (Not _hear_from: the wake-word loop moves it on every block.)"""
        return not (
            self._handle_lock.locked()
            or self._recording
            or self._heard_for > 0
            or self._awaiting_answer
            or self._answer_window
            or time.monotonic() - self._quiet_since < LATER_GAP_SECONDS
        )

    def _say_when_free(self) -> None:
        while not self.stop_event.is_set():
            if not self._later:
                self._later_event.clear()
                if not self._later:
                    self._later_event.wait(1.0)
                continue
            text, still, queued = self._later[0]
            if time.monotonic() - queued > LATER_SECONDS:
                self._later.popleft()
                log.info("Too late to say: %s", text)
                continue
            if not self._free_to_talk() or not self._handle_lock.acquire(blocking=False):
                self.stop_event.wait(LATER_POLL_SECONDS)
                continue
            try:
                self._later.popleft()
                if still is not None and not _still_true(still):
                    log.info("No longer true, not said: %s", text)
                    continue
                self._interrupted.clear()
                self._floor.set()
                log.info("Abdoh: %s", text)
                self.bus.emit("history", f"Abdoh: {text}")
                if not self.paused:
                    self._speak(text)
                    self._unduck_unless_listening()
                self._hear_from = time.monotonic() + self.HEAR_AFTER_SPEAKING_SECONDS  # a lesson
                self._status_idle()
            except Exception:
                log.exception("Couldn't say %r", text)
            finally:
                self._handle_lock.release()

    def _still_working(self) -> None:
        """Claude has been quiet for a while: say that Abdoh is on it."""
        if not self._spoke and self._handle_lock.locked():
            self._say_aside(random.choice(FILLERS))

    def _missing_voice(self, language: str) -> None:
        from abdoh.speech.tts import LANGUAGE_NAMES

        name = LANGUAGE_NAMES.get(language, language)
        self.bus.emit("history", "Abdoh: " + NO_VOICE.format(language=name))

    def mic_level(self) -> int | None:
        """How loud the microphone is right now (0 to 32768), or None if it isn't open."""
        mic = self.mic
        return getattr(mic, "level", None) if mic is not None else None

    def reopen_mic(self) -> None:
        """Switch to the microphone now in the settings (after the current request)."""
        self._reopen_mic.set()

    def devices_changed(self, old, new) -> None:
        """Windows' microphones or default devices changed (audio/devices.py): Settings lists
        them again, and after the current request the devices are read again and the mic is
        reopened, so Abdoh hears through the new default (or your mic, back again) and speaks
        through the new speakers."""
        self.bus.emit("devices", None)
        self._devices_stale = True
        self.reopen_mic()

    def _read_devices_again(self) -> None:
        """Read Windows' devices again, once nothing plays (a reload would cut a reply off)."""
        end = time.monotonic() + RELOAD_WAIT_SECONDS
        while not self.stop_event.is_set():
            try:
                if self.reload_devices():
                    self._devices_stale = False
                    return
            except Exception:
                log.exception("Couldn't read the audio devices again")
                return
            if time.monotonic() > end:
                log.info("Something is still playing; reading the audio devices later")
                return
            self.stop_event.wait(0.2)

    def apply_settings(self, new: Config) -> None:
        """Use changed settings right away. Some (like the hotkey or the speech model) are
        only read when Abdoh starts; the app says those need a restart."""
        from abdoh.claude.brain import make_brain

        old_mic = self.cfg.mic_device
        kept_clips = self.cfg.keep_unclear_clips
        used_gpu = self.cfg.use_gpu
        old_model = self.cfg.speech_model
        for f in fields(Config):
            if f.name not in ("app_dir", "claude"):
                setattr(self.cfg, f.name, getattr(new, f.name))
        for f in fields(ClaudeConfig):
            setattr(self.cfg.claude, f.name, getattr(new.claude, f.name))
        self._use_brain(make_brain(self.cfg))  # permissions, folders, API key
        self._show_listening()  # in lessons or not (lesson_listen_seconds)
        configure = getattr(self.speaker, "configure", None)
        if configure:
            changes = {"rate": self._speech_rate(), "voice": self.cfg.tts_voice}
            if hasattr(self.speaker, "voices"):  # Piper: your voices for English and German
                from abdoh.speech.piper_voice import your_voices

                changes["voices"] = your_voices(self.cfg)
            configure(**changes)
        if self.engine is not None and hasattr(self.engine, "threshold"):
            self.engine.threshold = self.cfg.wake_word_threshold
            self.engine.voice_threshold = self.cfg.wake_word_voice_threshold
        if self.voice_watch is not None:
            self.voice_watch.sensitivity = self.cfg.voice_interrupt_sensitivity
        if self.cfg.mic_device != old_mic:
            self.reopen_mic()
        if self.cfg.use_gpu != used_gpu and self.gpu_speech is not None:
            self.gpu_speech.apply()
        if self.cfg.speech_model != old_model and self.model_switch is not None:
            self.model_switch.apply()  # downloads it if needed, then switches
        self._phone_switch()
        if kept_clips and not self.cfg.keep_unclear_clips:
            from abdoh.audio.unclear import delete_all

            if delete_all(self._clips_folder()):
                log.info("Deleted the unclear recordings")
        log.info("Settings changed")

    def load_speech(self, load=None) -> None:
        """Load the speech model while Abdoh already listens for the wake word (it took 9 s on
        the owner's graphics card, and the wake word waited for it). If Parakeet won't load,
        Whisper takes over; if nothing loads, voice input is off and the window says why."""
        from abdoh.audio.stt import load_transcriber

        mine = self.transcriber
        started = time.perf_counter()
        try:
            loaded = (load or load_transcriber)(self.cfg, make=lambda cfg: mine)
        except Exception:
            log.exception("Could not load the speech recognition model")
            self.listen_error = SPEECH_MODEL_FAILED
            self.bus.emit("status", f"Error: {self.listen_error}")
            return
        log.info("The speech model is ready (%.1fs)", time.perf_counter() - started)
        if loaded is not mine:  # Parakeet didn't load: Whisper took over
            self.use_transcriber(loaded)

    def use_transcriber(self, new) -> None:
        """Another speech model takes over (chosen in Settings → Advanced, already loaded): the
        next thing you say goes to it. On a graphics card it moves there as usual."""
        self.transcriber = new
        if self.gpu_speech is not None:
            self.gpu_speech.stop()
            self.gpu_speech.transcriber = new
            self.gpu_speech.start()

    def _speak_sample(self, text: str) -> None:
        try:
            self.speaker.say(text)
        except Exception:
            log.exception("Could not speak the voice sample")

    def set_voice(self, on: bool) -> None:
        """Voice replies on or off (the window's switch, or a mode)."""
        self.voice_enabled = bool(on)
        self.bus.emit("voice", self.voice_enabled)

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        log.info("Listening %s", "paused" if paused else "resumed")
        self._status_idle()

    def _status_idle(self) -> None:
        if self.listen_error:
            self.bus.emit("status", f"Error: {self.listen_error}")
        elif self.paused:
            self.bus.emit("status", "Paused")
        else:
            no_wake_word = isinstance(self.engine, NoWakeWord)
            self.bus.emit("status", "Hotkey only" if no_wake_word else "Listening")

    def _show_window(self) -> str:
        self.bus.emit("show")
        return ""

    def _open_codoh(self) -> str:
        """ "Abdoh, open Codoh": the window, on the coding assistant page."""
        self.bus.emit("show")
        self.bus.emit("page", "codoh")
        return Done("Opening Codoh.")

    def _stop_listening(self) -> str:
        """ "Stop listening": quiet at once, not a word (the window says how to get it back)."""
        end_watch = getattr(self.router, "end_watch", None)
        if end_watch is not None:
            end_watch()  # a watch of the screen ends too
        self.set_paused(True)
        self.bus.emit("history", f"Abdoh: {STOPPED_LISTENING}")
        return ""

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

    def _speak(self, text: str) -> bool:
        """Say it, after you've finished talking and in one voice with everything else. False
        if it wasn't said (stopped meanwhile, or voice replies are off)."""
        self.earcons.stop_ticking()
        if self._phone_turn:  # a request from the phone: its reply is said there
            if self._interrupted.is_set():
                return False
            self._spoke = True
            self.bus.emit("phone_say", text)
            return True
        if not self._wait_for_floor() or not self.voice_enabled:
            return False
        with self._voice_lock:  # one voice at a time: never two things over each other
            if self._interrupted.is_set():
                return False
            self._spoke = True
            self._said.append((time.monotonic(), text))  # Abdoh's own words, if heard back
            self.bus.emit("status", "Speaking")
            self._duck()  # the others stay down while Abdoh talks (also for typed requests)
            try:
                self.speaker.say(text)
            except Exception:
                log.exception("Could not speak")
                return False
            finally:
                self._quiet_since = time.monotonic()
            return True

    def _wait_for_floor(self) -> bool:
        """Wait while you are talking over a reply. False if the reply was stopped."""
        while not self._floor.wait(0.05):
            if self._interrupted.is_set() or self.stop_event.is_set():
                return False
        return not self._interrupted.is_set()

    def _speak_stream(self, sentences, started: float) -> str:
        """Speak a streamed (Claude) reply sentence by sentence; show it in the history once."""
        spoken: list[str] = []
        first = None
        try:
            for sentence in sentences:
                if not spoken:
                    first = time.perf_counter() - started
                    self._answered = True
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
        if first is not None:
            total = time.perf_counter() - started
            log.info("Timing: Claude began after %.1fs, reply spoken after %.1fs", first, total)
        return text

    def announce(self, text: str) -> None:
        """Something finished on its own (a timer): get attention, then say it."""
        with self._handle_lock:
            self._interrupted.clear()
            self.earcons.play("alarm")  # even when voice replies are off
            self.stop_event.wait(self.ALARM_SECONDS)  # let the alarm finish before speaking
            self.say(text)
            self._unduck_unless_listening()
            self._status_idle()

    def push_to_talk(self) -> None:
        """The hotkey: stop a reply that's being spoken, otherwise listen for one request."""
        if self._handle_lock.locked():
            self._stopped_by_you()
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

    def _duck(self) -> None:
        """Other apps go quieter: you're about to talk to Abdoh."""
        if self.ducker is None or not self.cfg.duck_others:
            return
        try:
            self.ducker.duck(self.cfg.duck_percent)
        except Exception:
            log.exception("Couldn't lower the other apps")

    def _unduck(self) -> None:
        if self.ducker is None:
            return
        try:
            self.ducker.release()
        except Exception:
            log.exception("Couldn't give the other apps their volume back")

    def _unduck_unless_listening(self) -> None:
        """The others get their volume back, unless a spoken conversation is still going on
        (the main loop gives it back when that ends)."""
        if not self._recording and not self._awaiting_answer:
            self._unduck()

    def _on_listen(self) -> None:
        if self._quiet_wake:  # paused: no sound, nothing lowered, only "start listening" counts
            self._recording = True
            return
        self._duck()
        self._recording = True
        self._interrupted.clear()
        self.bus.emit("status", "Listening to you...")
        self.earcons.play("ready" if self._soft_chime else "listening")

    def _heard_nothing(self, loudest: int) -> None:
        """Nothing was said after the hotkey or Claude's question. If you pressed the hotkey
        and the mic was nearly silent, say so: it's probably muted."""
        log.info("Heard nothing (loudest sound %d of 32768)", loudest)
        if self._via_hotkey and loudest < QUIET_MIC_PEAK:
            self.say(MIC_TOO_QUIET)

    def stop_speaking(self) -> None:
        """Interrupt the current reply."""
        log.info("Stop speaking")
        self._interrupted.set()
        self.earcons.stop_ticking()
        self.speaker.stop()

    def _stopped_by_you(self) -> None:
        """The window's Stop, the tray or the hotkey: the reply ends, and whatever Abdoh is
        hearing over it right now (someone in the room, say) isn't taken as a request."""
        self._you_stopped = True
        self.stop_speaking()

    def _thinking(self) -> None:
        """A slow request (Claude) started: show it and tick until the answer comes."""
        self.bus.emit("status", "Thinking...")
        if self.voice_enabled and not self._phone_turn:
            self.earcons.start_ticking("thinking")

    def handle_text(
        self, text: str, voice: bool = False, aside: bool = False, woken=False, phone=False
    ) -> str:
        """Route one request and speak the reply. Never raises.

        `voice`: the request was spoken, so if Claude's reply ends with a question, Abdoh
        listens for the answer next (no wake word needed). `aside`: it was said right after a
        reply, without the wake word, so it may be meant for someone else in the room. `woken`: it
        came after the wake word, which a video or people talking can set off by mistake (True,
        or how clearly the name was heard: (score, voice check or None)). `phone`: it came from
        the phone (abdoh/phone): the reply goes there, and nothing is said here.
        """
        with self._handle_lock:
            self._phone_turn = phone
            try:
                return self._handle_text(text, voice, aside, woken, phone)
            finally:
                self._phone_turn = False

    def _handle_text(self, text: str, voice: bool, aside: bool, woken, phone: bool) -> str:
        self._interrupted.clear()
        self._you_stopped = False
        self._floor.set()
        # A new reply: the voice watch starts afresh. It fired for the one you just talked
        # over, and the next reply can follow straight on, with no idle moment to reset it.
        self._watching = False
        self._spoke = self._answered = False
        self._request = text
        self._turn_board = {}
        self._last_exchange = time.monotonic()  # you're talking with Abdoh
        you = "You (phone)" if phone else "You"
        log.info("%s: %s", you, text)
        self.bus.emit("history", f"{you}: {text}")
        self.bus.emit("status", "Thinking...")
        started = time.perf_counter()
        watcher = self._watch_reply() if voice else None
        kept = ""  # the answer, for the week's conversations
        try:
            try:
                maybe = {"aside": aside} if aside else {"woken": woken} if woken else {}
                reply = self.router.handle(text, **maybe)
            except Exception:
                log.exception("Error handling %r", text)
                reply = SORRY
            if isinstance(reply, str):
                spent = time.perf_counter() - started
                log.info("Timing: answered in %.2fs, without Claude", spent)
                kept = str(reply) or ("Done." if isinstance(reply, Done) else "")
                if isinstance(reply, Done) and self.cfg.confirm_actions != "words":
                    self._done(reply)  # "open Spotify": done, no words needed
                elif reply:
                    self._answered = True
                    self.say(reply)
                if phone and isinstance(reply, Question) and not self._interrupted.is_set():
                    self.bus.emit("phone_question", str(reply))  # Yes and No on the phone
                if voice and isinstance(reply, Question) and not self._interrupted.is_set():
                    self._awaiting_answer = True  # "Shut down the computer?": just answer
                    self._answer_wait, self._soft_chime = ANSWER_WAIT_SECONDS, False
            else:
                filler = threading.Timer(FILLER_SECONDS, self._still_working)
                filler.daemon = True
                filler.start()
                try:
                    reply = self._speak_stream(reply, started)
                finally:
                    filler.cancel()
                turn = getattr(self.router, "last_turn", None)
                acted = bool(turn is not None and turn.actions)
                kept = reply or (_what_was_done(turn.actions) if acted else "")
                if getattr(turn, "ignored", False):
                    kept = ""  # not meant for Abdoh: not part of the conversation
                if acted and not reply:
                    self._done(_what_was_done(turn.actions))  # Claude did it without a word
                elif woken and not reply and getattr(turn, "ignored", False):
                    self._sound("unclear")  # not for it: say it again if it was
                if voice and not getattr(turn, "failed", False):  # not after "the limit"
                    self._listen_for_more(reply, acted)
        finally:
            if watcher is not None:
                watcher()
            done = getattr(self.voice_watch, "reply_done", None)
            if done is not None:
                done()  # no false alarm this time: the watch eases off
        self._keep_exchange(text, kept, typed=not voice)
        self.earcons.stop_ticking()
        if not voice:
            self._unduck_unless_listening()  # a typed request: its reply is over
        self._quiet_for_hearing()
        self._status_idle()
        return reply

    def _sound(self, name: str) -> None:
        if self.voice_enabled:
            self.earcons.play(name)

    # ----- the week's conversations (conversations.py) -----

    def _conversations(self):
        from abdoh.conversations import FOLDER, Conversations

        return Conversations(self.cfg.app_dir / FOLDER, self.cfg.conversation_days)

    def _keep_exchange(self, request: str, answer: str, typed: bool) -> None:
        """Your request and Abdoh's answer go into today's conversation (with memory and
        "Keep conversations" on). Never raises."""
        if not (self.cfg.memory and self.cfg.keep_conversations) or not answer:
            return
        try:
            mode = getattr(getattr(self.router, "modes", None), "current", None) or ""
            acting = getattr(self.router, "acting", None)
            role = acting.current.name if acting is not None and acting.current else ""
            board = "\n\n".join(self._turn_board.values())
            if self._conversations().add(request, answer, typed, mode, role, board):
                self.bus.emit("conversations", None)  # the Memory page refreshes
        except Exception:
            log.exception("Couldn't keep the conversation")

    def _heard_unclear(self, audio: bytes) -> None:
        """You spoke after the wake word but no words came out. A soft sound, no words and no
        listening afterwards (it may have been talk on the phone or in the room); the next
        request to Claude says so. With keep_unclear_clips, the recording is kept for a day."""
        from abdoh.audio.recorder import peak

        loudest = peak(audio)
        kept = ""
        if self.cfg.keep_unclear_clips:
            from abdoh.audio.unclear import save_clip

            try:
                kept = f"; kept as {save_clip(self._clips_folder(), audio).name}"
            except OSError as e:
                log.warning("Couldn't keep the unclear recording: %s", e)
        log.info(
            "Heard %.1fs after the wake word but no words (loudest %d of 32768, %.0f dB)%s",
            len(audio) / BYTES_PER_SECOND,
            loudest,
            20 * math.log10(max(loudest, 1) / 32768),
            kept,
        )
        heard = getattr(self.router, "heard_unclear", None)
        if heard:
            heard()
        if not self._quiet_wake:
            self._sound("unclear")

    def _missed_after_wake(self, audio: bytes) -> None:
        """After the wake word nothing was taken for speech, but there was some sound: maybe
        you, too quietly or after the few seconds it waits. With keep_unclear_clips it's kept
        for a day, to check why. Claude hears of it, so "did you hear me?" gets an honest
        answer. No sound: it may have been the TV."""
        if self.cfg.keep_unclear_clips:
            from abdoh.audio.unclear import save_clip

            try:
                log.info("Kept it as %s", save_clip(self._clips_folder(), audio).name)
            except OSError as e:
                log.warning("Couldn't keep the recording: %s", e)
        heard = getattr(self.router, "heard_unclear", None)
        if heard:
            heard()

    def _clips_folder(self):
        from abdoh.audio.voicecheck import VOICE_DIR

        return self.cfg.app_dir / VOICE_DIR

    def _warm_speech(self) -> None:
        """Warm the speech model in the background (see Transcriber.keep_warm)."""
        warm = getattr(self.transcriber, "keep_warm", None)
        if warm is None or self._warming:
            return
        self._warming = True

        def run() -> None:
            try:
                warm()
            finally:
                self._warming = False

        threading.Thread(target=run, name="abdoh-warm-speech", daemon=True).start()

    def _housekeeping(self) -> None:
        while not self.stop_event.wait(HOUSEKEEPING_SECONDS):
            try:
                self._housekeeping_tick()
            except Exception:
                log.exception("Housekeeping failed")

    def _housekeeping_tick(self, wall: float | None = None, now: float | None = None) -> None:
        """Keep the speech model warm (every few minutes, and right after the computer wakes
        from sleep: Windows moves an idle model out of memory) and delete unclear clips older
        than a day (hourly). `wall`: time.time(); `now`: time.monotonic()."""
        wall = time.time() if wall is None else wall
        now = time.monotonic() if now is None else now
        slept = self._last_tick is not None and wall - self._last_tick > 3 * HOUSEKEEPING_SECONDS
        self._last_tick = wall
        if slept:
            log.info("The computer woke up: warming the speech model")
        if slept or self._last_warm is None or now - self._last_warm >= WARM_EVERY_SECONDS:
            self._last_warm = now
            self._warm_speech()
        if self._last_prune is None or now - self._last_prune >= PRUNE_EVERY_SECONDS:
            self._last_prune = now
            from abdoh.audio.unclear import prune

            if prune(self._clips_folder()):
                log.info("Deleted unclear recordings older than a day")
            try:
                self._conversations().clean()  # older than a week (conversation_days)
            except OSError:
                log.warning("Couldn't delete old conversations", exc_info=True)

    def _done(self, text: str) -> None:
        """Something you asked for was done: it shows in the window, and a short sound says so
        instead of words."""
        self._answered = True
        self.earcons.stop_ticking()
        if text:
            log.info("Abdoh (done): %s", text)
            self.bus.emit("history", f"Abdoh: {text}")
        if self.voice_enabled and not self._phone_turn:
            self.earcons.play("done")

    def _listen_for_more(self, reply: str, acted: bool = False) -> None:
        """After Claude's reply to something you said: listen again without the wake word, if
        it asked you something, or for a moment in case you want to go on (a conversation, not
        after Claude just did something for you)."""
        if not reply or self._interrupted.is_set():
            return
        if self.keeps_listening():
            return  # a role is on: the main loop hears you anyway, no chime needed
        asked = self._asked_question(reply)
        if acted and not asked:
            return
        wait = max(ANSWER_WAIT_SECONDS if asked else 0.0, float(self.cfg.follow_up_seconds))
        if wait > 0:
            self._awaiting_answer, self._answer_wait = True, wait
            self._soft_chime = not asked

    def _watch_reply(self):
        """While Abdoh answers something you said, keep an ear on the microphone: you talking
        (or the wake word) stops the reply. The main loop is busy answering, so this thread
        reads the microphone meanwhile. Returns a function that ends the watch."""
        mic, engine = self.mic, self.engine
        if mic is None or engine is None:
            return None
        wake = self.cfg.wake_word_interrupts
        if not (wake or self._can_hear_over_itself()):
            return None
        done = threading.Event()

        def watch() -> None:
            while not done.is_set():
                try:
                    block = mic.read()
                    if done.is_set():
                        return
                    if wake and engine.detect(block):
                        log.info("Wake word heard during a reply: stopping to listen")
                        self.stop_speaking()
                        self._listen_now.set()
                        return
                    if self._observe(block, mic):
                        text = self._heard_voice(mic)
                        if text:
                            self._next_request = text
                            return
                except Exception:
                    log.debug("The watch over a reply ended", exc_info=True)
                    return  # the microphone went away; the main loop deals with that

        thread = threading.Thread(target=watch, name="abdoh-barge-in", daemon=True)
        thread.start()

        def end() -> None:
            done.set()
            # If you are being listened to right now, let that finish: it reads the microphone.
            thread.join(timeout=self.cfg.max_record_seconds + 15)

        return end

    # ----- hearing you over Abdoh's own voice -----

    def _voice_playing(self, on: bool) -> None:
        """Abdoh's voice started or stopped coming out of the speakers (PiperSpeaker)."""
        speaking = getattr(self.voice_watch, "speaking", None)
        if speaking is not None:
            speaking(on, time.perf_counter())

    def _new_mic(self, mic) -> None:
        """Another microphone than before: Abdoh's voice reaches it differently."""
        name = getattr(mic, "name", "")
        if self._mic_name is not None and name != self._mic_name:
            forget = getattr(self.voice_watch, "forget_room", None)
            if forget is not None:
                forget()
        self._mic_name = name

    def _can_hear_over_itself(self) -> bool:
        watch = self.voice_watch
        return bool(self.cfg.voice_interrupts and watch is not None and watch.available)

    def _observe(self, block: bytes, mic) -> bool:
        """Every microphone block while Abdoh listens: True when you started talking over a
        reply that is running."""
        watch = self.voice_watch
        if self.paused or not self._can_hear_over_itself() or not self._handle_lock.locked():
            if self._watching:
                self._watching = False
                watch.idle()
            return False
        if not self._watching:
            self._watching = True
            watch.idle()  # a new reply: start afresh
        return watch.feed(block, getattr(mic, "last_time", 0.0) or time.perf_counter())

    def _heard_voice(self, mic) -> str:
        """You started talking over a reply: Abdoh goes quiet and listens. Returns what to do
        next, or "" if Abdoh goes on ("okay", a cough) or just stops ("wait", "thanks")."""
        from abdoh.local_skills import interruption_kind

        watch = self.voice_watch
        began = time.monotonic()
        self._duck()
        self._floor.clear()  # nothing more is said until this is decided
        self.earcons.stop_ticking()
        paused = self.speaker.pause()
        self._recording = True
        self.bus.emit("status", "Listening to you...")
        try:
            before = watch.pre_roll()

            def read() -> bytes:
                block = mic.read()
                return watch.clean(block, getattr(mic, "last_time", 0.0) or time.perf_counter())

            audio = record_until_silence(
                read,
                speech_detector(self.vad, before),
                self.cfg.silence_seconds,
                self.cfg.max_record_seconds,
                wait_seconds=INTERRUPTION_WAIT_SECONDS,
            )
            text = self.transcriber.transcribe(before + audio) if self.transcriber else ""
        finally:
            self._recording = False
        kind = interruption_kind(text)
        if (
            kind == "fragment"
            and not self._answered
            and began - self._last_exchange < (CONTINUE_SECONDS)
        ):
            kind = "request"  # the end of what you were asking ("... in Berlin")
        if kind != "stop_listening" and (self._you_stopped or self.paused):
            kind = "stop"  # you stopped it (or paused it) meanwhile: nothing more to do
        elif kind not in ("nothing", "backchannel") and self._own_words(text):
            kind = "echo"  # Abdoh's own words came back through the microphone: go on
        if kind in ("echo", "nothing"):
            false_alarm = getattr(watch, "false_alarm", None)
            if false_alarm is not None:
                false_alarm()  # it took Abdoh's voice (or a noise) for you: be harder to fool
        log.info("Heard %r over the reply (%s)", text, kind)
        if kind in ("nothing", "backchannel", "fragment", "echo"):
            if paused:
                self.speaker.resume()
            watch.rearm()
            self._floor.set()
            self.bus.emit("status", "Speaking" if paused else "Thinking...")
            if not self._answered and self.voice_enabled and not self._interrupted.is_set():
                self.earcons.start_ticking("thinking")
            return ""
        # You said you're done (or something new): the reply ends here. If none of its answer
        # was said yet, you were still asking: what you added belongs to the same request.
        earlier = "" if self._answered else self._request
        self.stop_speaking()
        self._floor.set()
        if kind == "stop_listening":
            self._stop_listening()  # not a word, and only "start listening" from now on
            return ""
        if kind == "stop":
            return ""
        self._via_voice = True
        return f"{earlier} {text}".strip()

    def _own_words(self, text: str) -> bool:
        """What was heard over the reply is what Abdoh just said (audio/echo_text.py)."""
        from abdoh.audio.echo_text import SECONDS, own_words

        now = time.monotonic()
        said = [words for at, words in list(self._said) if now - at < SECONDS]
        return own_words(text, said)

    def _asked_question(self, reply: str) -> bool:
        """Did Claude end its reply with a question (and you didn't stop it)?"""
        return (
            self.cfg.claude.listen_after_question
            and not self._interrupted.is_set()
            and reply.rstrip(" \"'”’)").endswith("?")
        )

    def handle_request(self, kind: str, value=None) -> None:
        """One request from the UI."""
        if kind == "stop_watching":
            end_watch = getattr(self.router, "end_watch", None)
            if end_watch is not None:
                end_watch()
            return
        if kind == "text":
            if value and value.strip():
                self.handle_text(value.strip())
        elif kind == "phone":  # the phone page (abdoh/phone/hub.py): {"text": ...}
            text = str((value or {}).get("text") or "").strip()
            if text:
                self.handle_text(text, phone=True)
        elif kind == "pause":
            self.set_paused(True)
        elif kind == "resume":
            self.set_paused(False)
        elif kind == "reload":
            error = self.router.registry.refresh(force=True)
            count = len(self.router.registry.commands)
            message = f"Commands file error: {error}" if error else f"Loaded {count} commands."
            self.bus.emit("history", f"Abdoh: {message}")
        elif kind == "settings_changed":  # saved in the app
            from abdoh.config import load_config

            self.apply_settings(load_config(self.cfg.app_dir))
        elif kind == "say_sample":  # the app's "test voice" button, even with voice replies off
            threading.Thread(
                target=self._speak_sample, args=(value or SAMPLE,), daemon=True
            ).start()
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
        elif kind == "mode":  # the window or the tray: a mode's name, or "" for normal
            self._switch_mode(str(value or ""))
        elif kind == "role":  # the window: a role's name, or "" to stop acting
            self._switch_role(str(value or ""))
        elif kind == "window_open":  # the window was shown, or hidden (or minimized)
            self._window_open = bool(value)
        elif kind == "say":  # the window: a few words to say (where the PDF went)
            self.say_later(str(value))  # after the reply that's being said
        elif kind == "board_pdf_done":  # the window answered "save the board"
            self._board_pdf_done(bool(value))
        elif kind == "board_cleared":  # the Act as page's Clear button
            self._board_shown = False
        elif kind == "keep_listening":  # the Act as page: listen without the wake word or not
            if self.acting is not None:
                self.acting.set_listening(bool(value))
        elif kind == "stop_speaking":
            self._stopped_by_you()
        elif kind == "listen":
            self.push_to_talk()  # the window's Talk button
        elif kind == "voice":
            self.set_voice(bool(value))
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
        self._use_brain(make_brain(self.cfg))
        self.bus.emit(
            "history", "Abdoh: Claude key saved." if key else "Abdoh: Claude key removed."
        )

    def _claude_switched(self, chatgpt: bool) -> None:
        """Your ChatGPT plan took over from Claude (its limit ran out), or Claude is back. The
        switch to ChatGPT is said in the reply; going back is only shown."""
        if not chatgpt:
            self.bus.emit("history", "Abdoh: Claude's limit has reset, so Claude answers again.")
        self._report_claude()

    def _report_claude(self) -> None:
        """Show which AI answers and how it's connected ({name, label, status}: Claude,
        ChatGPT, OpenRouter's model). Claude Code's sign-in is checked in the background."""
        from abdoh.claude.brain import ai_info, ai_names

        brain = self.router.brain
        if brain is None:
            self.bus.emit("claude", ai_info(None))
            return
        self.bus.emit("claude", {**ai_names(brain), "status": brain.name})

        def check() -> None:
            self.bus.emit("claude", ai_info(brain))

        threading.Thread(target=check, name="abdoh-claude-status", daemon=True).start()

    # ----- Abdoh from your phone (abdoh/phone) -----

    def _phone_switch(self) -> None:
        """Start or stop the phone page as the Phone switch says (a new port: start again)."""
        service = self.phone
        if service is not None and (not self.cfg.phone or service.port != self.cfg.phone_port):
            self._phone_off()
        if not self.cfg.phone or self.phone is not None:
            return
        from abdoh.phone.server import PhoneService

        service = PhoneService(self.cfg, self.bus, hear=self._phone_hear, voice=self._phone_voice)
        try:
            service.start()
        except OSError as e:
            log.warning("The phone page couldn't start on port %d: %s", self.cfg.phone_port, e)
            self.bus.emit("phone", {"error": PHONE_PORT_TAKEN.format(port=self.cfg.phone_port)})
            return
        self.phone = service
        self.bus.emit("phone", {"error": ""})

    def _phone_off(self) -> None:
        service, self.phone = self.phone, None
        if service is not None:
            try:
                service.stop()
            except Exception:
                log.exception("Couldn't stop the phone page")

    def _phone_hear(self, audio: bytes) -> str:
        """What was said in a recording from the phone (16 kHz mono 16-bit)."""
        if self.transcriber is None:
            raise RuntimeError("no speech recognition")
        text = self.transcriber.transcribe(audio)
        log.info("Heard from the phone: %r", text)
        return text

    def _phone_voice(self, text: str) -> bytes | None:
        """A sentence in Abdoh's voice as WAV for the phone, or None: the phone's own voice
        says it (the Windows voice can't make audio to send)."""
        render = getattr(self.speaker, "render", None)
        return render(text) if render is not None else None

    def serve_requests(self) -> None:
        """Process UI requests until stop().

        Typed requests run on their own thread, so "stop speaking" and "pause" are handled
        right away even while a reply is being spoken.
        """
        while not self.stop_event.is_set():
            message = self.bus.next_request(timeout=0.2)
            if not message:
                continue
            if message[0] in ("text", "phone"):
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
        self._connect_brain()
        self._report_claude()
        self._phone_switch()
        if self.engine is not None:
            self.bus.emit("wake", self.engine.label)
        self.bus.emit("hearing", self._hearing_problem())
        if self.modes is not None:
            try:
                self.modes.start()  # a mode that was on before a restart
            except Exception:
                log.exception("Couldn't restore the mode")
            threading.Thread(
                target=self.modes.run_schedule,
                args=(self.stop_event, self.announce),
                name="abdoh-mode-times",
                daemon=True,
            ).start()
        self._status_idle()
        if self.device_watch is not None:
            self.device_watch.start(self.stop_event)
        threading.Thread(target=self._housekeeping, name="abdoh-housekeeping", daemon=True).start()
        if self.gpu_speech is not None:
            self.gpu_speech.start()
        if self.model_switch is not None:
            self.model_switch.start()  # a model chosen but not downloaded yet: now
        if self.listen_error:
            log.error("Voice input unavailable: %s", self.listen_error)
            self.stop_event.wait()
            return
        while not self.stop_event.is_set():
            self._reopen_mic.clear()
            if self._devices_stale:
                self._read_devices_again()
            try:
                mic = self.mic_factory()
                mic.start()
            except MicrophoneError as e:
                self._mic_problem(e)
                continue
            self.mic = mic
            self._new_mic(mic)
            name = getattr(mic, "name", "")
            log.info("Listening for the wake word%s.", f" ({name})" if name else "")
            self._status_idle()
            try:
                while not self.stop_event.is_set() and not self._reopen_mic.is_set():
                    if self._capture is not None:
                        self._record_capture(mic)
                    else:
                        self._listen_once(mic)
            except MicrophoneError as e:
                self._mic_problem(e)
            finally:
                self.mic = None
                mic.stop()

    def _switch_mode(self, name: str) -> None:
        from abdoh.commands.actions import ActionError

        if self.modes is None:
            return
        try:
            reply = self.modes.activate(name) if name else self.modes.deactivate()
        except ActionError as e:
            reply = str(e)
        except Exception:
            log.exception("Couldn't switch the mode")
            reply = SORRY
        if isinstance(reply, Question):  # it needs screens that aren't there: ask, and listen
            self.say(reply)
            if self.voice_enabled:
                self.push_to_talk()
            return
        self.bus.emit("history", f"Abdoh: {reply}")

    # ----- roles ("act as my German teacher") -----

    def use_roles(self, acting) -> None:
        """Roles: the router starts them by name, Claude with ACTION role, modes and commands
        with the role setting and action."""
        self.acting = acting
        self.router.acting = acting
        if self.router.computer is not None:
            self.router.computer.acting = acting

    def _speech_rate(self) -> int:
        """Your voice speed, slower or faster while a role says so."""
        from abdoh.roles.model import SPEED_FACTORS

        role = self.acting.current if self.acting is not None else None
        return round(self.cfg.tts_rate * SPEED_FACTORS.get(role.speed if role else "normal", 1))

    def _role_changed(self, role) -> None:
        """A role started or ended: the voice's speed, and the window."""
        configure = getattr(self.speaker, "configure", None)
        if configure:
            try:
                configure(rate=self._speech_rate())
            except Exception:
                log.exception("Couldn't change the voice speed")
        self.bus.emit("board", None)  # a new role (or none): a clean board
        self._pictures_asked.clear()
        self.bus.emit("role", role.name if role is not None else "")
        self._board_shown = False
        self._show_listening()
        if role is not None and self.cfg.openrouter_api_key:  # AI pictures: read the credit
            threading.Thread(target=self._read_credit, name="abdoh-credit", daemon=True).start()
        lamps = getattr(self.router.computer, "lamps", None)
        if role is None and lamps is not None:  # the mood it set goes, in the background
            threading.Thread(target=self._lamps_back, args=(lamps,), daemon=True).start()

    def _read_credit(self) -> None:
        from abdoh.claude.openrouter import credit_left

        try:
            credit_left(self.cfg.openrouter_api_key, fresh=True)
        except Exception:
            log.debug("Couldn't read the OpenRouter credit", exc_info=True)

    @staticmethod
    def _lamps_back(lamps) -> None:
        try:
            if lamps.put_back():
                log.info("The lamps are back as they were before the role")
        except Exception:
            log.exception("Couldn't put the lamps back")

    # The page writes the board out at about this many characters a second (board.js); Abdoh
    # waits as long (at most BOARD_WAIT_MAX per line) before speaking on, like a teacher who
    # writes a line, then explains it.
    BOARD_CHARS_PER_SECOND = 40
    BOARD_WAIT_MAX = 3.0

    def _on_board(self, card: int, text: str) -> None:
        """A role's board card grew by a line. For a new card the window comes up on the Act as
        page; then Abdoh waits while the page writes the new part out."""
        before = self._board_text if card == self._board_card else ""
        new = text[len(before) :] if text.startswith(before) else text
        self.bus.emit("board", {"id": card, "text": text})
        if card != self._board_card:
            self._board_card = card
            self.bus.emit("show")
            self.bus.emit("page", "roles")
        self._board_text = text
        self._turn_board[card] = text
        self._board_shown = True
        self._find_pictures(text)
        self._pause(min(len(new) / self.BOARD_CHARS_PER_SECOND, self.BOARD_WAIT_MAX))

    def _pause(self, seconds: float) -> None:
        """Wait a moment in the middle of a reply (ends early if you talk over it)."""
        if seconds > 0:
            self._interrupted.wait(seconds)

    def _switch_role(self, name: str) -> None:
        """The window's Start and Stop buttons."""
        if self.acting is None:
            return
        reply = (
            self.acting.switch(name) if name else ("Stopped acting." if self.acting.stop() else "")
        )
        if reply:
            self.bus.emit("history", f"Abdoh: {reply}")

    def use_modes(self, engine) -> None:
        """Modes: the router hears "movie mode", the `mode:` action reaches them."""
        self.modes = engine
        self.router.modes = engine
        if self.router.computer is not None:
            self.router.computer.modes = engine

    def _hearing_problem(self) -> str:
        """Why Abdoh can't hear you over its own voice ("" when it can)."""
        watch = self.voice_watch
        if watch is None or watch.canceller is None:
            return NO_ECHO_CANCELLER
        if not getattr(watch.tap, "available", False):
            return NO_SPEAKER_TAP
        return ""

    def _mic_problem(self, error: Exception) -> None:
        self._awaiting_answer = False  # too late to answer once the mic is back
        self._devices_stale = True  # unplugged, or the computer slept: devices may be new
        log.warning("%s. Retrying in %.0f s.", error, self.mic_retry_seconds)
        self.bus.emit("status", "Error: microphone not available, retrying")
        self.stop_event.wait(self.mic_retry_seconds)

    # ----- keeps listening in a lesson: you just talk, no wake word -----

    def keeps_listening(self) -> bool:
        """In a lesson, Abdoh hears you without the wake word: a role is on (and you didn't say
        to stop listening), Abdoh's window is open, the board shows something, and you or Abdoh
        said something in the last lesson_listen_seconds (a setting; 0 = never). Otherwise, as
        usual: the wake word."""
        if self._watch_on():
            return True  # watching the screen: the user talks to Abdoh as they work
        acting = self.acting
        quiet = float(self.cfg.lesson_listen_seconds or 0)
        return bool(
            quiet > 0
            and acting is not None
            and acting.keeps_listening
            and self._window_open
            and self._board_shown
            and time.monotonic() - self._last_exchange < quiet
        )

    def _show_listening(self) -> None:
        """Tell the window: listening without the wake word in lessons (on), and right now."""
        acting = self.acting
        now = self.keeps_listening()
        if now != self._listening_now:
            watching = self._watch_on()
            log.info(
                ("Watching the screen" if watching else "In a lesson")
                + ": listening without the wake word"
                if now
                else "No lesson or watch going on: the wake word again"
            )
        self._listening_now = now
        on = bool(acting is not None and acting.keeps_listening and self.cfg.lesson_listen_seconds)
        self.bus.emit("listening", {"on": on, "now": now})

    def _codoh(self):
        """The app's Codoh; Abdoh says what its chats need, and when they're done (a chat typed
        on the page when the user isn't looking at it)."""
        from abdoh.codoh.manager import shared

        codoh = shared(self.cfg)
        codoh.on_notice = self.say_later
        codoh.window_open = lambda: bool(getattr(self, "_window_open", False))
        return codoh

    def _show_codoh(self, chat: str = "") -> None:
        """The window, on the Codoh page, with this chat."""
        self.bus.emit("show")
        self.bus.emit("codoh_open", chat)

    def _codoh_note(self) -> str:
        """What Codoh is doing, for Claude, while its page is the one Abdoh's window shows
        (like the board in a lesson: minimized, and Abdoh doesn't know)."""
        if not self._window_open:
            return ""
        from abdoh.codoh.manager import brief_for_abdoh

        return brief_for_abdoh()

    # ----- watching the screen (abdoh/watch.py): looking, and listening without the wake word

    def _watch_on(self) -> bool:
        return bool(getattr(self.router, "watching", False)) and not self.paused

    def _watch_changed(self, on: bool) -> None:
        """A watch began (Claude: ACTION watch), changed or ended: look every few seconds while
        it's on (one loop per watch), and show it in the window."""
        watch = getattr(self.router, "watch", None)
        if on and watch is not None:
            self.bus.emit("watch", {"goal": watch.goal, "suggest": watch.suggest})
            if self._watch_looks == watch.generation:
                return  # the same watch, changed: its loop goes on
            self._watch_looks = watch.generation
            threading.Thread(
                target=self._watch_loop,
                args=(watch.generation,),
                name="abdoh-watch",
                daemon=True,
            ).start()
        else:
            self.bus.emit("watch", None)
            self.bus.emit("history", "Abdoh: (stopped watching your screen)")
        self._show_listening()

    def _watch_busy(self) -> bool:
        """Someone is talking (Abdoh, or the user): no picture now."""
        return bool(self._handle_lock.locked() or self._recording or self._heard_for > 0)

    def _watch_loop(self, generation: int) -> None:
        """Every watch_seconds while the watch is on: a picture of the screen when it changed
        and nobody is talking. Ends with the watch, "stop listening", or after watch_minutes
        without a word from the user."""
        watch = self.router.watch
        while not self.stop_event.wait(max(self.WATCH_MIN_SECONDS, float(self.cfg.watch_seconds))):
            if watch.generation != generation or not watch.active:
                return  # ended, or a new watch took over
            if self.paused:
                self.router.end_watch()
                return
            limit = float(self.cfg.watch_minutes) * 60
            if limit > 0 and watch.quiet_for() > limit:
                self._watch_timed_out()
                return
            if self._watch_busy():
                continue
            try:
                shot = watch.look()
            except Exception as e:  # the screen can't be captured right now (locked, ...)
                log.warning("Couldn't take a picture of the screen: %s", e)
                continue
            if shot is not None:
                self._watch_frame(*shot)

    def _watch_frame(self, image: bytes, window) -> None:
        """Show Claude the screen; say what it says (usually nothing: the user is doing fine).
        Skipped when a request took the floor meanwhile."""
        if not self._handle_lock.acquire(blocking=False):
            return
        said = ""
        try:
            if self.paused or not self.router.watching:
                return
            self._interrupted.clear()
            self._you_stopped = False
            self._floor.set()
            self._watching = False  # the voice watch follows this reply afresh
            self._spoke = self._answered = False
            self._request = ""
            sentences = self.router.watch_frame(
                image, getattr(window, "title", ""), getattr(window, "program", "")
            )
            said = self._speak_stream(sentences, time.perf_counter())
        except Exception:
            log.exception("Error while watching the screen")
        finally:
            self._handle_lock.release()
        if said:
            watch = self.router.watch
            if watch is not None:
                watch.note(said)
            self._unduck_unless_listening()
            self._quiet_for_hearing()
            self._status_idle()

    def _watch_timed_out(self) -> None:
        minutes = float(self.cfg.watch_minutes)
        if not self.router.end_watch():
            return
        with self._handle_lock:
            self._interrupted.clear()
            self.say(
                f"I stopped watching your screen: you haven't said anything for {minutes:g} "
                "minutes. Ask me again if you need me."
            )
            self._unduck_unless_listening()
            self._status_idle()

    def _hearing_vad(self):
        if self._hear_vad is None and self.vad is not None:
            fresh = getattr(self.vad, "fresh", None)
            self._hear_vad = fresh() if fresh else self.vad
        return self._hear_vad

    def _hear(self, block: bytes) -> bool:
        """Every microphone block while waiting for the wake word: True when you started talking
        while Abdoh keeps listening. Never while Abdoh talks, nor just after (its own voice)."""
        now = time.monotonic()
        if self.keeps_listening() != self._listening_now:
            self._show_listening()  # a lesson began or ended (the window, the board, quiet)
        if self.paused or self._handle_lock.locked() or not self._listening_now:
            self._hearing, self._heard_for = False, 0.0
            self._hear_from = now + self.HEAR_AFTER_SPEAKING_SECONDS
            return False
        vad = self._hearing_vad()
        if vad is None or now < self._hear_from:
            return False
        if not self._hearing:
            self._hearing, self._heard_for = True, 0.0
            vad.reset()
        if vad.is_speech(block):
            self._heard_for += len(block) / BYTES_PER_SECOND
        else:
            self._heard_for = 0.0  # a click or a cough: not talking yet
        if self._heard_for < self.HEAR_ONSET_SECONDS:
            return False
        self._hearing = False  # the recording resets it; afterwards, start afresh
        return True

    def _quiet_for_hearing(self) -> None:
        """Abdoh just answered: while it keeps listening, its own voice dies away first. The
        lesson's quiet minutes count from here, not from your question (a long explanation
        would use them up)."""
        self._hearing = False
        self._hear_from = time.monotonic() + self.HEAR_AFTER_SPEAKING_SECONDS
        self._last_exchange = time.monotonic()

    def _on_speech(self) -> None:
        """You started talking while Abdoh keeps listening: hear you out (no chime: you're
        already talking)."""
        self._via_speech = True
        self._last_exchange = time.monotonic()
        self._warm_speech()
        self._duck()
        self._recording = True
        self._interrupted.clear()
        self.bus.emit("status", "Listening to you...")

    def _self_edited(self, kind: str) -> None:
        """Claude changed one of your commands, modes or roles: the role that's on follows its
        new settings, and the app's page shows the change."""
        acting = self.acting
        if kind == "role" and acting is not None and acting.current is not None:
            fresh = acting.find(acting.current.name)
            if fresh is not None and acting.current.saved:
                acting.current = fresh  # e.g. "make the German teacher speak slower"
                configure = getattr(self.speaker, "configure", None)
                if configure:
                    configure(rate=self._speech_rate())
        self.bus.emit(f"{kind}s", None)  # "commands", "modes", "roles"

    def _listening_changed(self, on: bool) -> None:
        self._show_listening()

    def _on_wake(self) -> None:
        self._warm_speech()  # back in memory by the time you've finished talking
        self._wake_heard = getattr(self.engine, "last_wake", None)
        self._quiet_wake = self.paused
        if self._quiet_wake:
            self._recording = True
            return
        self._duck()
        if self._handle_lock.locked() and self.cfg.wake_word_interrupts:
            self.stop_speaking()  # a typed request is being answered: you get the floor
        self._woke = time.perf_counter()
        self._recording = True
        self._interrupted.clear()
        self.bus.emit("status", "Thinking...")

    def _listen_once(self, mic) -> None:
        """Listen for one request and answer it. The other apps get their volume back after
        the answer, unless Abdoh goes on listening for more."""
        try:
            self._listen_and_answer(mic)
        finally:
            if not self._awaiting_answer or self.stop_event.is_set():
                self._unduck()

    def _listen_and_answer(self, mic) -> None:
        answer, self._awaiting_answer = self._awaiting_answer, False
        if not answer:
            self._soft_chime = False
        self._answer_window = answer  # no notice now: it would be heard as your answer
        try:
            text = listen_for_request(
                mic,
                self.engine,
                self.transcriber,
                self,
                self.cfg,
                should_stop=lambda: (
                    self.stop_event.is_set()
                    or self._reopen_mic.is_set()
                    or self._capture is not None
                ),
                on_wake=self._on_wake,
                vad=self.vad,
                pressed=self._take_listen_now,
                on_listen=self._on_listen,
                answer=answer,
                on_nothing=self._heard_nothing,
                answer_wait=self._answer_wait,
                observe=lambda block: self._observe(block, mic),  # a typed request's reply
                on_voice=self._heard_voice,
                on_unclear=self._heard_unclear,
                on_missed=self._missed_after_wake,
                hear=self._hear,
                on_speech=self._on_speech,
            )
        except MicrophoneError:
            raise
        except Exception:
            log.exception("Error while listening")
            self._status_idle()
            return
        finally:
            self._recording = False
            self._quiet_wake = False
            self._answer_window = False
        via_hotkey, self._via_hotkey = self._via_hotkey, False
        via_voice, self._via_voice = self._via_voice, False
        via_speech, self._via_speech = self._via_speech, False
        aside = answer and self._soft_chime  # the moment after a reply, not an answer to it
        self._soft_chime = False
        self.speaker.language = getattr(self.transcriber, "last_language", "")
        if text and (via_hotkey or answer or via_voice):
            self._handle_spoken(text, aside)  # the hotkey and answers work even while paused
        elif text and via_speech:
            self._handle_spoken(text, aside=True)  # no wake word: it may be for someone else
        elif text and self.paused:
            # While paused, only "start listening" (in any words) is honored.
            if self._wants_listening(text):
                self._handle_spoken(text)
            else:
                log.info("Paused; ignoring %r", text)
        elif text:
            # Claude decides whether it was for it, knowing how clearly its name was said.
            self._handle_spoken(text, woken=self._wake_heard or True)
            log.debug("Latency: wake word to reply spoken %.2fs", time.perf_counter() - self._woke)
        self._status_idle()
        mic.clear()  # don't react to our own voice
        self.engine.reset()

    # ----- your voice check (audio/voicecheck.py) -----

    def _find_pictures(self, text: str) -> None:
        """The board asks for pictures ([picture: ...]): each is found in the background, and
        the page shows it when it's there."""
        from abdoh.pictures import picture_lines

        for what in picture_lines(text):
            if what not in self._pictures_asked:
                self._pictures_asked.add(what)
                threading.Thread(
                    target=self._get_picture, args=(what,), name="abdoh-picture", daemon=True
                ).start()

    def _get_picture(self, what: str) -> None:
        from abdoh.pictures import FOLDER, PictureError, Pictures

        if self._pictures is None:
            self._pictures = Pictures(self.cfg.app_dir / FOLDER, ai=self._ai_picture)
            try:
                self._pictures.clean()
            except OSError:
                log.debug("Couldn't clean the board's old pictures", exc_info=True)
        try:
            found = self._pictures.find(what)
            shown = {"what": what, "ok": True, "src": found.data_url(), "credit": found.credit,
                     "title": found.title, "ai": found.ai}  # fmt: skip
            log.info("Board picture of %r: %s", what, found.credit)
        except PictureError as e:
            shown = {"what": what, "ok": False, "error": str(e)}
            log.info("No board picture of %r: %s", what, e)
            if what.lower().startswith("draw:"):  # no credit, no key: say so, not only show it
                self.say_later(str(e))  # after the reply being said
        except Exception:
            log.exception("Couldn't get a picture for the board")
            shown = {"what": what, "ok": False, "error": "That picture didn't load."}
        self.bus.emit("board_picture", shown)

    def _ai_picture(self, description: str) -> tuple[bytes, str, str]:
        """A picture made by the OpenRouter picture model (the board's [picture: draw: ...])."""
        from abdoh.claude.openrouter import PictureRefused, make_picture
        from abdoh.pictures import PictureError

        model = self.cfg.claude.openrouter_image_model
        try:
            data, mime, cost = make_picture(self.cfg.openrouter_api_key, model, description)
        except PictureRefused as e:
            raise PictureError(str(e)) from e
        name = model.split("/")[-1].replace("-", " ")
        log.info("Made a picture with %s for $%.4f", model, cost)
        return data, mime, f"Made by AI ({name}), ${cost:.3f}"

    def _ai_pictures_now(self) -> str:
        """For Claude, while a role is on: can it ask for pictures made by AI?"""
        from abdoh.claude.openrouter import known_credit

        key = self.cfg.openrouter_api_key
        if not key:
            return "AI pictures: off (they need an OpenRouter key)"
        left = known_credit(key)
        credit = f", credit left ${left:.2f}" if left is not None else ""
        model = self.cfg.claude.openrouter_image_model.split("/")[-1]
        return f"AI pictures: on ({model}{credit})"

    def _voice_download(self, voice: str, percent: int | None) -> None:
        """A natural voice is downloading (the first time Abdoh speaks its language): the
        Settings page shows how far along it is."""
        from abdoh.speech.tts import LANGUAGE_NAMES

        if percent is None:
            self.bus.emit("voice_download", None)
            return
        code = "en" if voice.startswith("kokoro:") else voice.split("_", 1)[0]
        language = LANGUAGE_NAMES.get(code, voice)
        self.bus.emit("voice_download", {"voice": voice, "language": language, "percent": percent})

    def _voice_files(self):
        from abdoh.audio.voicecheck import FILE, VOICE_DIR, Recordings

        return Recordings(self.cfg.app_dir / VOICE_DIR), self.cfg.app_dir / FILE

    def voice_status(self) -> dict:
        recordings, saved = self._voice_files()
        active = getattr(self.engine, "voice_check", None) is not None
        return {
            "possible": hasattr(self.engine, "voice_check"),  # a wake word model is running
            "active": active,
            "stale": saved.exists() and not active,  # made for another wake word model
            "recorded": recordings.count(),
            "talk": recordings.talk_path.exists(),
        }

    def record_voice(self, kind: str, number: int = 1) -> dict:
        """Record for your voice check (from the window): "phrase" (you say the wake word once,
        saved as recording `number`; number 1 starts afresh) or "talk" (TALK_SECONDS of you
        talking normally). The main loop records it from the open microphone."""
        from abdoh.audio.voicecheck import TALK_SECONDS, write_wav

        if self.mic is None:
            return {"ok": False, "error": "The microphone isn't open."}
        request = {"kind": kind, "done": threading.Event(), "audio": b""}
        self._capture = request
        if not request["done"].wait(TALK_SECONDS + 30):
            self._capture = None
            return {"ok": False, "error": "Abdoh is busy. Try again in a moment."}
        from abdoh.audio.recorder import peak

        audio = request["audio"]
        recordings, _ = self._voice_files()
        if kind == "talk":
            loudest = peak(audio)
            if len(audio) < BYTES_PER_SECOND * TALK_SECONDS / 2 or how_quiet(loudest) == "silent":
                log.info("Voice check: no talk heard (loudest sound %d of 32768)", loudest)
                return {"ok": True, "heard": False, "quiet": how_quiet(loudest)}
            write_wav(recordings.talk_path, audio)
            return {"ok": True, "heard": True}
        if not audio:  # nothing taken for speech: was the microphone silent, or just quiet?
            loudest = request.get("loudest", 0)
            log.info("Voice check: the wake word wasn't heard (loudest sound %d of 32768)", loudest)
            return {"ok": True, "heard": False, "quiet": how_quiet(loudest)}
        if number <= 1:
            for path in recordings.folder.glob("phrase-*.wav"):
                path.unlink(missing_ok=True)
        write_wav(recordings.phrase_path(number), audio)
        return {"ok": True, "heard": True}

    def _record_capture(self, mic) -> None:
        """Record what record_voice() asked for, then go back to listening."""
        from abdoh.audio.recorder import peak
        from abdoh.audio.voicecheck import TALK_SECONDS

        request, audio = self._capture, b""
        request["loudest"] = 0

        def read():  # notes the loudest sound, to tell a silent mic from a quiet word
            block = mic.read()
            request["loudest"] = max(request["loudest"], peak(block))
            return block

        self.bus.emit("status", "Learning your voice...")
        try:
            mic.clear()
            if request["kind"] == "talk":
                chunks, size = [], 0
                while size < BYTES_PER_SECOND * TALK_SECONDS and not self.stop_event.is_set():
                    block = mic.read()
                    chunks.append(block)
                    size += len(block)
                audio = b"".join(chunks)
            else:
                audio = record_until_silence(
                    read,
                    speech_detector(self.vad, b""),
                    silence_seconds=0.6,
                    max_seconds=4.0,
                    wait_seconds=5.0,
                )
        except MicrophoneError:
            raise
        except Exception:
            log.exception("Couldn't record for the voice check")
        finally:
            request["audio"] = audio
            self._capture = None
            request["done"].set()
            mic.clear()
            if self.engine is not None:
                self.engine.reset()
            self._status_idle()

    def train_voice(self) -> dict:
        """Train your voice check from the recordings, save it and use it right away."""
        from abdoh.audio.voicecheck import train
        from abdoh.audio.wakeword import use_voice_check

        recordings, saved = self._voice_files()
        phrases, talk = recordings.phrases(), recordings.talk()
        if not hasattr(self.engine, "voice_check"):
            return {"ok": False, "error": "The wake word model isn't running."}
        if not phrases or not talk:
            return {"ok": False, "error": "Record the wake word and some normal talk first."}
        model = self.cfg.resolve(self.cfg.wake_word_model)
        try:
            scorer = (self.voice_scorer or self._make_scorer)(model)
            result = train(scorer, phrases, talk, model, self.cfg.wake_word_threshold)
            result.check.save(saved)
        except Exception:
            log.exception("Couldn't train the voice check")
            return {"ok": False, "error": "Something went wrong while learning your voice."}
        use_voice_check(self.engine, self.cfg)
        self.bus.emit("wake", self.engine.label)
        log.info(
            "Voice check trained: knows you in %d of %d recordings (the wake word model woke "
            "for %d of %d)",
            result.passed,
            result.total,
            result.woke,
            len(phrases),
        )
        return {
            "ok": True,
            "passed": result.passed,
            "total": result.total,
            "woke": result.woke,
            "recorded": len(phrases),
        }

    def _make_scorer(self, model):
        from abdoh.audio.oww import FEATURES_DIR, OpenWakeWord

        # Its own copy: the main loop keeps using the running one meanwhile.
        return OpenWakeWord(model, self.cfg.resolve(FEATURES_DIR), self.cfg.wake_word_threshold)

    def forget_voice(self) -> None:
        """Delete your recordings and the voice check: any voice wakes Abdoh again."""
        recordings, saved = self._voice_files()
        recordings.forget()
        saved.unlink(missing_ok=True)
        if hasattr(self.engine, "voice_check"):
            from abdoh.audio.wakeword import use_voice_check

            use_voice_check(self.engine, self.cfg)
            self.bus.emit("wake", self.engine.label)
        log.info("Voice check forgotten")

    def _handle_spoken(self, text: str, aside=False, woken=False) -> None:
        """Answer a spoken request, then whatever you said over that answer, and so on (what
        was heard over a reply may be someone else, or Abdoh's own voice: Claude may stay
        quiet)."""
        while text and not self.stop_event.is_set():
            self.handle_text(text, voice=True, aside=aside, woken=woken)
            woken = False
            aside = OVER_REPLY
            text, self._next_request = self._next_request, None
            if text and self.paused and not self._wants_listening(text):
                log.info("Paused; ignoring %r", text)  # "stop listening" came first
                return
            if text:
                self.speaker.language = getattr(self.transcriber, "last_language", "")

    def _wants_listening(self, text: str) -> bool:
        """ "Abdoh, start listening" (in any words), while paused."""
        from abdoh.commands.matcher import strip_wake_words
        from abdoh.local_skills import start_request

        if self.router.builtin_name(text) == "start_listening":
            return True
        return start_request(strip_wake_words(text, getattr(self.router, "wake_words", [])))

    @classmethod
    def create(
        cls, cfg: Config, bus: Bus | None = None, speaker: Speaker | None = None
    ) -> "Daemon":
        """Build a daemon with the real microphone, wake word, speech recognition and TTS.

        If the wake word can't start, the hotkey still works. If speech recognition can't be
        set up, the daemon still handles typed requests and reports the problem as its status.
        """
        from abdoh.audio.devices import DeviceWatch, reload_portaudio
        from abdoh.audio.ducking import Ducker
        from abdoh.audio.mic import Microphone
        from abdoh.audio.stt import make_transcriber
        from abdoh.audio.vad import load_vad
        from abdoh.audio.wakeword import load_wake_engine
        from abdoh.claude.brain import make_brain
        from abdoh.claude.code import user_folders
        from abdoh.commands.registry import CommandRegistry
        from abdoh.computer import AppIndex, Computer, Timers
        from abdoh.desk import Notes, Reminders
        from abdoh.displays import Displays
        from abdoh.lights import Lamps
        from abdoh.speech.piper_voice import make_voice

        speaker = speaker or make_voice(cfg)
        getattr(speaker, "warm_up", lambda: None)()  # the first reply shouldn't pay for it

        engine = transcriber = None
        listen_error = None
        try:
            engine = load_wake_engine(cfg)
        except Exception:
            log.exception("Could not set up the wake word; only the hotkey wakes Abdoh")
            engine = NoWakeWord()
        try:
            # Its model loads in the background (load_speech, below): the wake word works
            # meanwhile, and what you say first waits for it.
            transcriber = make_transcriber(cfg)
        except Exception:
            log.exception("Could not set up speech recognition")
            listen_error = SPEECH_MODEL_FAILED
        router = Router(cfg, CommandRegistry(cfg.commands_path), brain=make_brain(cfg))
        daemon = cls(
            cfg,
            router,
            speaker,
            lambda: Microphone(device=cfg.mic_device),  # the mic chosen now, when (re)opened
            engine,
            transcriber,
            bus,
            listen_error=listen_error,
            earcons=Earcons(),
            vad=load_vad(),
            voice_watch=None if listen_error else make_voice_watch(cfg),
            ducker=Ducker(),
        )
        router.computer = Computer(
            timers=Timers(announce=daemon.announce),
            apps=AppIndex(),
            notes=Notes(cfg.app_dir / "notes.txt"),
            reminders=Reminders(cfg.app_dir / "reminders.json", announce=daemon.announce),
            pictures=user_folders()["Pictures"] / "Screenshots",
            displays=Displays(cfg.app_dir / "displays.json"),
        )
        router.computer.lamps = Lamps(cfg.app_dir / "lamps.json")
        if transcriber is not None:
            from abdoh.audio.gpu_speech import GpuSpeech
            from abdoh.models import ModelSwitch

            daemon.gpu_speech = GpuSpeech(cfg, transcriber, lambda t: daemon.bus.emit("gpu", t))
            daemon.model_switch = ModelSwitch(
                cfg,
                transcriber,
                daemon.use_transcriber,
                lambda s: daemon.bus.emit("speech_model", s),
            )
        daemon.device_watch = DeviceWatch(daemon.devices_changed)
        daemon.reload_devices = reload_portaudio
        router.computer.apps.load_in_background()
        daemon.use_roles(make_roles(cfg, daemon))
        daemon.use_modes(make_modes(cfg, router, daemon))
        if transcriber is not None:
            threading.Thread(
                target=daemon.load_speech, name="abdoh-speech-model", daemon=True
            ).start()
        try:
            daemon._codoh()  # the page's Codoh speaks up through Abdoh from the start
        except Exception:
            log.exception("Couldn't connect Codoh to Abdoh's voice")
        return daemon


def make_voice_watch(cfg: Config):
    """What lets Abdoh hear you over its own voice, or None if part of it is missing (then
    only the wake word and the hotkey stop a reply)."""
    from abdoh.audio.bargein import VoiceWatch
    from abdoh.audio.echo import EchoCanceller, echo_available
    from abdoh.audio.loopback import SpeakerTap
    from abdoh.audio.vad import load_vad

    canceller = None
    if echo_available():
        try:
            canceller = EchoCanceller()
        except Exception:
            log.exception("Couldn't start the echo canceller")
    else:
        log.info("No echo canceller (livekit isn't installed): only the wake word interrupts")
    tap = SpeakerTap()
    if canceller is not None:
        tap.start()
    return VoiceWatch(
        tap, canceller, load_vad(), cfg.voice_interrupt_sensitivity, raw_vad=load_vad()
    )


def make_roles(cfg: Config, daemon: Daemon):
    """Your roles (roles.yaml), played by this daemon."""
    from abdoh.roles.acting import Acting
    from abdoh.roles.store import RoleStore

    return Acting(
        RoleStore(cfg.app_dir / "roles.yaml").load,
        on_change=daemon._role_changed,
        on_listening=daemon._listening_changed,
    )


def make_modes(cfg: Config, router: Router, daemon: Daemon):
    """Your modes (modes.yaml), switched with the real computer and this daemon."""
    from abdoh.commands.actions import run_actions
    from abdoh.commands.registry import Command
    from abdoh.modes.controls import ModeControls
    from abdoh.modes.engine import ModeEngine
    from abdoh.modes.store import ModesStore

    store = ModesStore(cfg.app_dir / "modes.yaml")

    def run(actions):
        return run_actions(Command("mode", [], list(actions)), cfg.allow_run,
                           computer=router.computer)  # fmt: skip

    return ModeEngine(
        store.load,
        ModeControls(router.computer, daemon),
        run,
        cfg.app_dir / "mode_state.json",
        emit=lambda name: daemon.bus.emit("mode", name),
    )
