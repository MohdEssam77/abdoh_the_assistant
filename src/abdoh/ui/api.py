"""What the app page can ask Abdoh for, and what it shows.

AppApi's public methods are called from JavaScript (window.pywebview.api.<name>). pywebview also
exposes public attributes, so everything else is kept in _underscore names. Methods return plain
data (dicts, lists, strings) and never raise to the page for expected problems.
"""

import copy
import logging
import os
import sys
import threading
import webbrowser
from collections import deque
from collections.abc import Callable
from datetime import date
from pathlib import Path

from abdoh import __version__
from abdoh.commands.registry import CommandsFileError
from abdoh.commands.store import TEMPLATES, CommandsStore
from abdoh.config import Config, load_config
from abdoh.events import Bus
from abdoh.settings import RESTART_KEYS, SettingsError, settings_view
from abdoh.settings import save_settings as _save_settings

log = logging.getLogger(__name__)

MIC_VOLUME = 90  # what "turn my microphone up" sets it to


class UiState:
    """What the page shows, kept in Python: a page that (re)loads late still shows it all.

    The conversation is today's only: at the first sign of a new day it is emptied, and the
    page is told to clear the chat (("clear", None)).
    """

    HISTORY = 200
    BOARD = 30  # board items kept for the Act as page

    def __init__(self, today=date.today):
        self._today = today
        self._day = today()
        self._lock = threading.Lock()
        self._pending: list[tuple[str, object]] = []
        self._status = "Starting..."
        self._claude = ""
        self._wake = ""
        self._hearing = ""
        self._mode = ""
        self._role = ""
        self._watch = None  # watching the screen: {goal}, or None
        # Abdoh listens without the wake word in lessons (on), and right now (now)
        self._listening = {"on": False, "now": False}
        self._board: deque[dict] = deque(maxlen=self.BOARD)  # cards {id, text}, oldest first
        self._pictures: dict[str, dict] = {}  # the board's pictures: what -> {ok, src, credit...}
        self._voice = True
        self._gpu = ""  # how speech recognition on the graphics card is going (Settings)
        self._voice_download = None  # a natural voice downloading: {voice, language, percent}
        self._history: deque[str] = deque(maxlen=self.HISTORY)

    def _new_day(self) -> None:
        """Called with the lock held: a new day starts with an empty conversation."""
        today = self._today()
        if today != self._day:
            self._day = today
            self._history.clear()
            self._pending.append(("clear", None))

    def feed(self, kind: str, value) -> None:
        """An event from the daemon (or the app): remember it and queue it for the page."""
        with self._lock:
            self._new_day()
            if kind == "status":
                self._status = value
            elif kind == "claude":
                self._claude = value
            elif kind == "wake":
                self._wake = value
            elif kind == "hearing":
                self._hearing = value
            elif kind == "mode":
                self._mode = value or ""
            elif kind == "role":
                self._role = value or ""
            elif kind == "watch":
                self._watch = dict(value) if value else None
            elif kind == "listening":
                self._listening = {"on": bool(value["on"]), "now": bool(value["now"])}
            elif kind == "board":  # a card (new, or grown), or None: clear it
                if value is None:
                    self._board.clear()
                    self._pictures.clear()
                elif self._board and self._board[-1]["id"] == value["id"]:
                    self._board[-1] = dict(value)
                else:
                    self._board.append(dict(value))
            elif kind == "board_picture":  # a picture the board asked for, found or not
                self._pictures[str(value["what"])] = dict(value)
            elif kind == "voice":
                self._voice = bool(value)
            elif kind == "gpu":
                self._gpu = str(value or "")
            elif kind == "voice_download":
                self._voice_download = value or None
            elif kind == "history":
                self._history.append(value)
            self._pending.append((kind, value))

    def drain(self) -> list[tuple[str, object]]:
        with self._lock:
            self._new_day()  # the page asks often: a chat left open clears at midnight
            pending, self._pending = self._pending, []
            return pending

    def snapshot_mode(self) -> str:
        with self._lock:
            return self._mode

    def snapshot(self) -> dict:
        """Everything so far. Queued events are dropped: the snapshot already has them."""
        with self._lock:
            self._new_day()
            self._pending.clear()
            return {
                "status": self._status,
                "claude": self._claude,
                "wake": self._wake,
                "hearing": self._hearing,
                "mode": self._mode,
                "role": self._role,
                "watch": dict(self._watch) if self._watch else None,
                "listening": dict(self._listening),
                "board": [dict(card) for card in self._board],
                "pictures": {what: dict(p) for what, p in self._pictures.items()},
                "voice": self._voice,
                "gpu": self._gpu,
                "voice_download": self._voice_download,
                "history": list(self._history),
            }


def _connected_mics() -> list[dict]:
    """The microphones as Windows has them now (full names); elsewhere sounddevice's list."""
    from abdoh import winaudio

    found = winaudio.microphones()
    if found:
        return [{"name": m.name, "default": m.default} for m in found]
    from abdoh.audio.mic import input_devices

    return input_devices()


def _open_path(target) -> None:
    """Open a folder, a file or a Windows settings page (e.g. "ms-settings:sound")."""
    if sys.platform == "win32":
        os.startfile(str(target))  # type: ignore[attr-defined]
    else:
        webbrowser.open(Path(target).resolve().as_uri())


# Installing an update: the window says so for this long, then Abdoh closes for the installer.
UPDATE_CLOSE_SECONDS = 2.0
# Edge made no PDF: the page opens the print dialog instead.
PRINT_INSTEAD = " I opened the print dialog instead: pick Microsoft Print to PDF."


class AppApi:
    def __init__(
        self,
        bus: Bus,
        state: UiState,
        cfg: Config,
        window=None,
        open_url: Callable[[str], object] = webbrowser.open,
        open_path: Callable[[object], None] = _open_path,
        autostart=None,
        list_mics=None,
        list_voices=None,
        claude_setup=None,
        check_for_update=None,
        audio=None,
        displays=None,
        lamps=None,
        codoh=None,
    ):
        self._bus = bus
        self._state = state
        self._cfg = cfg
        self._window = window  # WebWindow: hide, pick a folder, restart
        self._daemon = None  # set once the daemon is running (for the mic level)
        self._open_url = open_url
        self._open_path = open_path
        self._autostart = autostart
        self._list_mics = list_mics
        self._list_voices = list_voices
        self._claude_setup = claude_setup  # abdoh.claude.setup (a fake in tests)
        self._check_for_update = check_for_update
        self._audio = audio  # abdoh.winaudio (a fake in tests)
        self._displays = displays  # abdoh.displays.Displays (a fake backend in tests)
        self._lamps = lamps  # abdoh.lights.Lamps (a fake network in tests)
        self._codoh = codoh  # abdoh.codoh.manager.Codoh, made when the page first asks
        # What Abdoh started with, to tell which saved changes still need a restart. (The
        # daemon updates the shared Config in place when settings change.)
        self._started = {key: copy.deepcopy(getattr(cfg, key)) for key in RESTART_KEYS}

    def _attach(self, daemon) -> None:
        self._daemon = daemon

    def _config(self) -> Config:
        """The settings as saved now (the file may have changed since Abdoh started)."""
        return load_config(self._cfg.app_dir)

    def _restart_needed(self, cfg: Config) -> list[str]:
        return [key for key in RESTART_KEYS if getattr(cfg, key) != self._started[key]]

    # ----- starting up and staying up to date -----

    def boot(self) -> dict:
        """Everything the page needs to draw itself."""
        cfg = self._config()
        log.info("App window loaded (Abdoh %s)", __version__)
        return {
            "version": __version__,
            "platform": sys.platform,
            "settings": settings_view(cfg),
            "restart": self._restart_needed(cfg),
            "state": self._state.snapshot(),
        }

    def events(self) -> list:
        """What happened since the last call, as [kind, value] pairs."""
        return [[kind, value] for kind, value in self._state.drain()]

    # ----- talking to Abdoh -----

    def send(self, text) -> bool:
        """A typed request."""
        text = str(text or "").strip()
        if not text:
            return False
        self._bus.request("text", text)
        return True

    def talk(self) -> None:
        """Listen for one request now (like the hotkey)."""
        self._bus.request("listen")

    def stop_speaking(self) -> None:
        self._bus.request("stop_speaking")

    def set_paused(self, paused) -> None:
        """Stop or start listening for the wake word."""
        self._bus.request("pause" if paused else "resume")

    def set_voice(self, on) -> None:
        self._bus.request("voice", bool(on))

    # ----- your commands -----

    def _store(self) -> CommandsStore:
        return CommandsStore(self._cfg.commands_path)

    def commands(self) -> dict:
        """Your commands and the templates. If the file has an error, says what it is."""
        try:
            items = self._store().load()
        except CommandsFileError as e:
            return {"ok": False, "error": str(e), "commands": [], "templates": TEMPLATES}
        return {"ok": True, "commands": items, "templates": TEMPLATES}

    def save_command(self, command, old_name=None) -> dict:
        """Add a command, or change the one called old_name."""
        try:
            saved = self._store().save(command, old_name or None)
        except CommandsFileError as e:
            return {"ok": False, "error": str(e)}
        self._bus.request("commands_changed")
        return {"ok": True, "command": saved}

    def delete_command(self, name) -> dict:
        try:
            self._store().delete(str(name))
        except CommandsFileError as e:
            return {"ok": False, "error": str(e)}
        self._bus.request("commands_changed")
        return {"ok": True}

    def open_commands_file(self) -> None:
        """Open commands.yaml in a text editor (e.g. to fix an error made by hand)."""
        self._bus.request("edit_commands")

    # ----- your modes and your screens -----

    # ----- roles ("act as my German teacher") -----

    # ----- memory (the Memory page) -----

    def _memory(self):
        from abdoh.memory import Memory

        return Memory(self._cfg.app_dir / "memory.yaml")

    def memory(self) -> dict:
        """What Abdoh remembers about you, oldest first, and how full it is."""
        from abdoh.memory import MAX_CHARS, MAX_ENTRIES, MemoryFileError, size

        result = {"ok": True, "entries": [], "max_entries": MAX_ENTRIES, "max_chars": MAX_CHARS}
        try:
            entries = self._memory().load()
        except MemoryFileError as e:
            return {**result, "ok": False, "error": str(e), "chars": 0}
        return {**result, "entries": [e.as_item() for e in entries], "chars": size(entries)}

    def _memory_change(self, change) -> dict:
        from abdoh.memory import MemoryChangeError

        try:
            entry = change(self._memory())
        except MemoryChangeError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "entry": entry.as_item()}

    def add_memory(self, text, kind="fact") -> dict:
        return self._memory_change(lambda memory: memory.add(str(text or ""), str(kind)))

    def change_memory(self, old_text, text, kind) -> dict:
        return self._memory_change(
            lambda memory: memory.change(str(old_text or ""), str(text or ""), str(kind))
        )

    def forget_memory(self, text) -> dict:
        return self._memory_change(lambda memory: memory.forget(str(text or "")))

    # ----- the week's conversations (the Memory page) -----

    def _conversations(self):
        from abdoh.conversations import FOLDER, Conversations

        cfg = self._config()
        return Conversations(cfg.app_dir / FOLDER, cfg.conversation_days)

    def conversations(self) -> dict:
        """The days kept, newest first, with how many exchanges each has."""
        from abdoh.conversations import day_label

        kept = self._conversations()
        today = kept.today()
        days = [
            {"date": d.isoformat(), "label": day_label(d, today), "count": n}
            for d, n in kept.days_kept()
        ]
        since = days[-1] if days else None
        return {
            "days": days,
            "keep_days": kept.days,
            "since": since["label"] if since else "",
            "since_date": since["date"] if since else "",
        }

    def conversation_day(self, day) -> dict:
        from abdoh.conversations import day_label

        try:
            when = date.fromisoformat(str(day))
        except ValueError:
            return {"ok": False, "error": "That day isn't kept."}
        kept = self._conversations()
        exchanges = kept.day(when)
        if not exchanges:
            return {"ok": False, "error": "That day isn't kept anymore."}
        return {
            "ok": True,
            "label": day_label(when, kept.today()),
            "exchanges": [e.as_item() for e in exchanges],
        }

    def delete_conversation_day(self, day) -> dict:
        try:
            when = date.fromisoformat(str(day))
        except ValueError:
            return {"ok": False, "error": "That day isn't kept."}
        self._conversations().delete_day(when)
        return {"ok": True}

    def forget_conversations(self) -> dict:
        return {"ok": True, "days": self._conversations().forget_all()}

    def _roles_store(self):
        from abdoh.roles.store import RoleStore

        return RoleStore(self._cfg.app_dir / "roles.yaml")

    def _role_names(self) -> list[str]:
        from abdoh.roles.model import RolesFileError

        try:
            return [r.name for r in self._roles_store().load()]
        except RolesFileError:
            return []

    def roles(self) -> dict:
        """Your roles, the suggestions, and the role that's on (also one made up on the spot)."""
        from abdoh.roles.model import RolesFileError, as_form
        from abdoh.roles.store import SUGGESTIONS

        result = {"ok": True, "roles": [], "suggestions": SUGGESTIONS, "current": None}
        try:
            result["roles"] = self._roles_store().forms()
        except RolesFileError as e:
            result.update(ok=False, error=str(e))
        acting = getattr(self._daemon, "acting", None)
        if acting is not None and acting.current is not None:
            result["current"] = as_form(acting.current)
        return result

    def save_role(self, role, old_name=None) -> dict:
        from abdoh.roles.model import RolesFileError, as_form

        try:
            saved = self._roles_store().save(role, old_name or None)
        except RolesFileError as e:
            return {"ok": False, "error": str(e)}
        acting = getattr(self._daemon, "acting", None)
        current = acting.current if acting is not None else None
        if current is not None and current.name.lower() in (
            saved.name.lower(),
            str(old_name or "").lower(),
        ):
            acting.start(saved.name)  # the role that's on, as you just saved it (its speed too)
        return {"ok": True, "role": as_form(saved)}

    def delete_role(self, name) -> dict:
        from abdoh.roles.model import RolesFileError

        try:
            self._roles_store().delete(str(name))
        except RolesFileError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True}

    def start_role(self, name) -> None:
        self._bus.request("role", str(name))

    def stop_role(self) -> None:
        self._bus.request("role", "")

    def stop_watching(self) -> None:
        """Stop watching the screen (the chip's stop button)."""
        self._bus.request("stop_watching")

    def keep_listening(self, on) -> None:
        """While a role is on: listen without the wake word (True), or only after it."""
        self._bus.request("keep_listening", bool(on))

    def board_pdf(self, cards, title, spoken=False, phone=False) -> dict:
        """Save the board (the page's cards, as it shows them) as a PDF in
        Documents\\Abdoh\\Boards and open it. `spoken`: Claude was asked ("save the board"):
        Abdoh says where it is, or why not. `phone`: for the phone (ABDOH_EPIC_11.md, story
        154): it's sent there, not opened or talked about here."""
        from abdoh.board_pdf import BoardPdfError, save

        cards = [str(c) for c in cards or []]
        log.info("Saving the board as a PDF (%d cards%s)", len(cards), ", asked" if spoken else "")
        try:
            path = save(cards, str(title or "Board"))
        except Exception as e:  # BoardPdfError, or anything else: said and in the log
            message = str(e) if isinstance(e, BoardPdfError) else "The PDF couldn't be made."
            if not isinstance(e, BoardPdfError):
                log.exception("Saving the board as a PDF failed")
            # Edge missing or failing: the page opens the print dialog (Microsoft Print to PDF)
            printing = bool(cards) and "folder" not in message
            log.warning("The board wasn't saved as a PDF: %s", message)
            if spoken:
                self._bus.request("say", message + (PRINT_INSTEAD if printing else ""))
            self._bus.request("board_pdf_done", {"ok": False, "error": message} if phone else False)
            return {"ok": False, "error": message, "print": printing and not phone}
        self._bus.request("board_pdf_done", {"ok": True, "path": str(path)} if phone else True)
        if phone:
            return {"ok": True, "path": str(path), "folder": str(path.parent)}
        if spoken:
            self._bus.request(
                "say", "The board is saved as a PDF in your Documents, Abdoh, Boards."
            )
        try:
            self._open_path(str(path))
        except OSError:
            log.debug("Couldn't open the PDF", exc_info=True)
        return {"ok": True, "path": str(path), "folder": str(path.parent)}

    def board_pdf_failed(self, reason, spoken=False, phone=False) -> None:
        """The page couldn't even get the board ready (an error drawing it): in the log, said."""
        log.warning("The window couldn't get the board ready for the PDF: %s", str(reason)[:300])
        failed = "The board couldn't be saved: drawing it for the PDF failed."
        if spoken:
            self._bus.request("say", failed)
        self._bus.request("board_pdf_done", {"ok": False, "error": failed} if phone else False)

    def clear_board(self) -> None:
        self._state.feed("board", None)
        self._bus.request("board_cleared")  # nothing on it: no lesson going on

    def _modes_store(self):
        from abdoh.modes.store import ModesStore

        return ModesStore(self._cfg.app_dir / "modes.yaml")

    def _screens(self):
        if self._displays is None:
            from abdoh.displays import Displays

            self._displays = Displays(self._cfg.app_dir / "displays.json")
        return self._displays

    def modes(self) -> dict:
        """Your modes, the templates, which one is on, and what the editor offers: your
        screens, your speakers and the icons."""
        from abdoh.modes.model import ICONS, ModesFileError
        from abdoh.modes.store import TEMPLATES

        result = {
            "ok": True,
            "modes": [],
            "templates": TEMPLATES,
            "current": self._state.snapshot_mode(),
            "displays": self._display_list(),
            "outputs": self._output_names(),
            "icons": list(ICONS),
            "roles": self._role_names(),
        }
        try:
            result["modes"] = self._modes_store().forms()
        except ModesFileError as e:
            result.update(ok=False, error=str(e))
        return result

    def save_mode(self, mode, old_name=None) -> dict:
        from abdoh.modes.model import ModesFileError

        try:
            saved = self._modes_store().save(mode, old_name or None)
        except ModesFileError as e:
            return {"ok": False, "error": str(e)}
        from abdoh.modes.model import as_form

        return {"ok": True, "mode": as_form(saved)}

    def delete_mode(self, name) -> dict:
        from abdoh.modes.model import ModesFileError

        try:
            self._modes_store().delete(str(name))
        except ModesFileError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True}

    def activate_mode(self, name) -> None:
        """Switch a mode on (on Abdoh's own thread: screens can take a second)."""
        self._bus.request("mode", str(name))

    def end_mode(self) -> None:
        """Back to normal."""
        self._bus.request("mode", "")

    def _display_list(self) -> list[dict]:
        try:
            found = self._screens().all()
        except Exception:
            log.exception("Couldn't list the screens")
            return []
        return [
            {
                "id": d.id, "number": d.number, "label": d.label, "name": d.name,
                "nickname": d.nickname, "active": d.active, "internal": d.internal,
                "primary": d.primary, "rect": list(d.rect) if d.rect else None,
            }
            for d in found
        ]  # fmt: skip

    def _output_names(self) -> list[str]:
        from abdoh.computer import short_output_name

        audio = self._audio
        if audio is None:
            from abdoh import winaudio as audio
        try:
            return [short_output_name(o.name) for o in audio.outputs()]
        except Exception:
            return []

    def displays(self) -> dict:
        return {"displays": self._display_list()}

    def rename_display(self, display_id, nickname) -> dict:
        self._screens().rename(str(display_id), str(nickname or ""))
        return self.displays()

    def reorder_displays(self, ids) -> dict:
        self._screens().renumber([str(i) for i in ids or []])
        return self.displays()

    def identify_displays(self) -> None:
        """Show each screen's number on it for a few seconds."""
        if self._window is not None and hasattr(self._window, "identify"):
            self._window.identify(self._display_list())

    # ----- settings and permissions -----

    def settings(self) -> dict:
        cfg = self._config()
        return {"settings": settings_view(cfg), "restart": self._restart_needed(cfg)}

    def save_settings(self, changes) -> dict:
        """Save changed settings (shaped like config.yaml) and use them right away."""
        try:
            cfg = _save_settings(self._cfg.app_dir, changes)
        except SettingsError as e:
            return {"ok": False, "error": str(e)}
        self._bus.request("settings_changed")
        return {"ok": True, "settings": settings_view(cfg), "restart": self._restart_needed(cfg)}

    def models(self) -> dict:
        """Settings → Advanced: the speech models for your languages, the one in use, and how a
        switch is going."""
        from abdoh.models import listing

        daemon = self._daemon
        switch = getattr(daemon, "model_switch", None)
        return listing(
            self._config(),
            getattr(daemon, "transcriber", None),
            switch.status if switch is not None else None,
        )

    def microphones(self) -> dict:
        """The microphones connected right now, and the chosen one ("" = the default). When the
        chosen one isn't connected, `using` names the one Abdoh listens with instead."""
        from abdoh.audio.mic import same_name

        try:
            if self._list_mics is None:
                self._list_mics = _connected_mics
            devices = self._list_mics()
        except Exception:
            log.warning("Couldn't list the microphones", exc_info=True)
            devices = []
        current = self._config().mic_device
        result = {"devices": devices, "current": current}
        if current:
            match = next((d for d in devices if same_name(d["name"], current)), None)
            if match is not None:
                result["current"] = match["name"]  # a name saved cut short: the full one
            elif devices:
                default = next((d for d in devices if d["default"]), None)
                result["using"] = default["name"] if default else ""
        return result

    def mic_level(self):
        """How loud the microphone is right now (0 to 32768), or None if it isn't open."""
        return self._daemon.mic_level() if self._daemon is not None else None

    def _mic_endpoint(self):
        if self._audio is None:
            from abdoh import winaudio

            self._audio = winaudio
        return self._audio.microphone(self._config().mic_device)

    def mic_volume(self) -> dict:
        """The microphone's volume in Windows (0 to 100) and whether it's muted there."""
        try:
            mic = self._mic_endpoint()
            return {"ok": True, "name": mic.name, "volume": mic.volume(), "muted": mic.muted()}
        except Exception as e:
            log.debug("Couldn't read the microphone's volume: %s", e)
            return {"ok": False}

    def fix_mic_volume(self) -> dict:
        """Unmute the microphone in Windows and turn it up, so Abdoh hears you clearly."""
        try:
            mic = self._mic_endpoint()
            mic.set_muted(False)
            mic.set_volume(MIC_VOLUME)
        except Exception as e:
            log.warning("Couldn't change the microphone's volume: %s", e)
            return {"ok": False, "error": "Couldn't change it. Try Windows' sound settings."}
        return self.mic_volume()

    def voices(self) -> dict:
        """The installed voices to choose from, and the chosen one ("" = the default)."""
        if self._list_voices is None:
            from abdoh.speech.tts import windows_voices

            self._list_voices = windows_voices
        return {"voices": self._list_voices(), "current": self._config().tts_voice}

    def test_voice(self) -> None:
        self._bus.request("say_sample")

    # ----- your voice check: the wake word only counts in your voice -----

    def voice_check(self) -> dict:
        if self._daemon is None:  # still loading its models: ask again in a moment
            return {"starting": True, "possible": False, "active": False, "recorded": 0}
        return self._daemon.voice_status()

    def record_voice(self, kind, number=1) -> dict:
        """Record once for the voice check: "phrase" (the wake word) or "talk" (20 s)."""
        if self._daemon is None:
            return {"ok": False, "error": "Abdoh is still starting."}
        return self._daemon.record_voice(str(kind), int(number or 1))

    def train_voice(self) -> dict:
        if self._daemon is None:
            return {"ok": False, "error": "Abdoh is still starting."}
        return self._daemon.train_voice()

    def forget_voice(self) -> dict:
        if self._daemon is not None:
            self._daemon.forget_voice()
        return self.voice_check()

    def _login(self):
        if self._autostart is None:
            from abdoh import autostart

            self._autostart = autostart
        return self._autostart

    def login_item(self) -> dict:
        """Does Abdoh start when you sign in to your computer?"""
        try:
            return {"ok": True, "on": bool(self._login().is_installed())}
        except Exception as e:
            log.warning("Couldn't check start at login", exc_info=True)
            return {"ok": False, "on": False, "error": str(e)}

    def set_login_item(self, on) -> dict:
        try:
            message = self._login().install() if on else self._login().uninstall()
        except Exception as e:
            log.exception("Couldn't change start at login")
            return {"ok": False, "error": f"Couldn't change it: {e}"}
        return {"ok": True, "on": bool(on), "message": message}

    def pick_folder(self):
        """Let you choose a folder (for the folders Claude may use). None if cancelled."""
        if self._window is None:
            return None
        return self._window.pick_folder()

    def open_folder(self, which) -> bool:
        """Open Abdoh's data folder ("data": settings and commands) or its log folder."""
        cfg = self._config()
        folders = {"data": cfg.app_dir, "logs": cfg.resolve(cfg.log_file).parent}
        if which not in folders:
            return False
        self._open_path(folders[which])
        return True

    # ----- the Catalog: everything Abdoh can do (abdoh/catalog.py) -----

    def catalog(self) -> dict:
        from abdoh import catalog

        return catalog.catalog(self._config())

    # ----- Codoh: the coding assistant page (abdoh/codoh) -----

    def _codoh_manager(self):
        if self._codoh is None:
            from abdoh.codoh.manager import shared

            self._codoh = shared(self._cfg)  # the same Codoh Abdoh's voice uses
        return self._codoh

    def codoh_state(self) -> dict:
        return self._codoh_manager().state()

    def codoh_models(self, refresh=False) -> dict:
        return self._codoh_manager().models(bool(refresh))

    def codoh_open_folder(self, path=None) -> dict:
        """Open a project folder: the one given, or one picked in the folder dialog."""
        if not path:
            path = self.pick_folder()
            if not path:
                return {"ok": False, "cancelled": True}
        return self._codoh_manager().open_folder(str(path))

    def codoh_folder(self, path) -> dict:
        return self._codoh_manager().folder_info(str(path))

    def codoh_forget_folder(self, path) -> dict:
        return self._codoh_manager().forget_folder(str(path))

    def codoh_new_chat(self, folder, engine="", model="", mode="") -> dict:
        return self._codoh_manager().new_chat(str(folder), str(engine), str(model), str(mode))

    def codoh_chat(self, chat_id, since=0) -> dict:
        return self._codoh_manager().chat(str(chat_id), int(since or 0))

    def codoh_send(self, chat_id, text) -> dict:
        return self._codoh_manager().send(str(chat_id), str(text or ""))

    def codoh_stop(self, chat_id) -> dict:
        return self._codoh_manager().stop(str(chat_id))

    def codoh_answer(self, chat_id, item_id, decision, answers=None) -> dict:
        return self._codoh_manager().answer(
            str(chat_id), str(item_id), str(decision), dict(answers or {})
        )

    def page_shown(self, name) -> None:
        """The page the window shows now: while it's Codoh, Abdoh knows what Codoh does."""
        if str(name) == "codoh":
            self._codoh_manager().page_open = True
        elif self._codoh is not None:
            self._codoh.page_open = False

    def codoh_configure(self, chat_id, changes) -> dict:
        return self._codoh_manager().configure(str(chat_id), dict(changes or {}))

    def codoh_rename(self, chat_id, title) -> dict:
        return self._codoh_manager().rename(str(chat_id), str(title or ""))

    def codoh_delete(self, chat_id) -> dict:
        return self._codoh_manager().delete(str(chat_id))

    def codoh_changes(self, folder) -> dict:
        return self._codoh_manager().changes(str(folder))

    def codoh_diff(self, folder, path) -> dict:
        return self._codoh_manager().diff(str(folder), str(path))

    def codoh_reveal(self, path) -> bool:
        """Show a project folder (or a file in it) in Explorer."""
        target = Path(str(path or ""))
        if not target.exists():
            return False
        self._open_path(target if target.is_dir() else target.parent)
        return True

    def codoh_open_editor(self, folder) -> dict:
        """Open the project in VS Code (or Cursor) when installed, else in Explorer."""
        import shutil
        import subprocess

        target = Path(str(folder or ""))
        if not target.is_dir():
            return {"ok": False, "error": "That folder doesn't exist."}
        for name in ("code", "cursor"):
            exe = shutil.which(name)
            if exe:
                try:
                    subprocess.Popen(  # noqa: S603 - the user's own editor, their own folder
                        [exe, str(target)],
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    return {"ok": True, "editor": "VS Code" if name == "code" else "Cursor"}
                except OSError:
                    continue
        self._open_path(target)
        return {"ok": True, "editor": "Explorer"}

    # ----- Abdoh's log (Settings → Advanced → Log) -----

    def logs(self, problems=False, search="", limit=400) -> dict:
        """The log's latest entries, newest first: today's and yesterday's."""
        from abdoh import logs

        path = logs.log_path(self._cfg)  # the file Abdoh writes now (changing it needs a restart)
        try:
            entries = logs.read_entries(path)
        except Exception as e:
            log.exception("Couldn't read the log")
            return {"ok": False, "error": f"Couldn't read the log: {e}", "entries": []}
        found = logs.pick(entries, problems=bool(problems), search=str(search or ""))
        found = found[-max(1, min(int(limit or 400), 2000)) :]
        return {
            "ok": True,
            "entries": [logs.for_page(e) for e in reversed(found)],
            "total": len(entries),
            "problems": sum(1 for e in entries if e.problem),
            "path": str(path),
        }

    def open_log(self) -> bool:
        """Open today's log file in the editor Windows picks for it."""
        from abdoh import logs

        path = logs.log_path(self._cfg)
        if not path.exists():
            return False
        self._open_path(path)
        return True

    # ----- Abdoh from your phone (abdoh/phone, ABDOH_EPIC_10.md) -----

    def _tailscale(self):
        if getattr(self, "_tailscale_cli", None) is None:
            from abdoh.phone.tailscale import Tailscale

            self._tailscale_cli = Tailscale()
        return self._tailscale_cli

    def _phones(self):
        """The paired phones: the running page's (it holds the pairing code), or the file."""
        service = getattr(self._daemon, "phone", None)
        if service is not None:
            return service.phones
        from abdoh.phone.devices import FILE, Phones

        return Phones(self._cfg.app_dir / FILE)

    def phone_state(self) -> dict:
        """Settings → Phone: the switch, Tailscale's state, the paired phones."""
        from abdoh.phone.tailscale import DOWNLOAD

        cfg = self._config()
        service = getattr(self._daemon, "phone", None)
        return {
            "on": cfg.phone,
            "running": service is not None,
            "port": cfg.phone_port,
            "error": getattr(self._daemon, "phone_error", "") if cfg.phone else "",
            "tailscale": self._tailscale().state(cfg.phone_port),
            "phones": self._phones().list(),
            "download": DOWNLOAD,
        }

    def phone_share(self) -> dict:
        """Share the phone page in your Tailscale network (tailscale serve)."""
        result = self._tailscale().share(self._config().phone_port)
        return {**result, "state": self.phone_state()}

    def phone_unshare(self) -> dict:
        return {"ok": self._tailscale().unshare()}

    def phone_pair(self) -> dict:
        """A one-time pairing link for a new phone, and its QR code (SVG)."""
        import segno

        from abdoh.phone.devices import CODE_SECONDS

        service = getattr(self._daemon, "phone", None)
        if service is None:
            return {"ok": False, "error": "Turn on “Use Abdoh from your phone” first."}
        tailscale = self._tailscale().state(self._config().phone_port)
        if not tailscale["address"] or not tailscale["shared"]:
            return {"ok": False, "error": "Finish the Tailscale steps above first."}
        code = service.phones.new_code()
        url = f"{tailscale['address']}/#pair={code}"
        qr = segno.make(url, error="m").svg_inline(scale=5, border=2, dark="#111", light="#fff")
        return {"ok": True, "url": url, "code": code, "qr": qr, "minutes": CODE_SECONDS // 60}

    def phone_remove(self, phone_id) -> dict:
        phones = self._phones()
        return {"ok": phones.remove(str(phone_id)), "phones": phones.list()}

    def open_power_settings(self) -> None:
        """Windows' power and sleep settings: a laptop that sleeps can't answer the phone."""
        self._open_path("ms-settings:powersleep")

    def open_sound_settings(self) -> None:
        """Windows' sound settings, where a muted microphone can be turned on."""
        self._open_path("ms-settings:sound")

    def open_mic_privacy(self) -> None:
        """Windows' microphone privacy page: with "Let desktop apps access your microphone"
        off, Abdoh gets only silence."""
        self._open_path("ms-settings:privacy-microphone")

    # ----- Claude: your own account or API key -----

    def _claude(self):
        if self._claude_setup is None:
            from abdoh.claude import setup

            self._claude_setup = setup
        return self._claude_setup

    def claude_status(self) -> dict:
        """Is Claude Code installed and signed in (and with which plan), or is there a key?"""
        return self._claude().claude_state(self._config())

    def _claude_action(self, action, *args, refresh: bool = False) -> dict:
        try:
            action(*args)
        except self._claude().SetupError as e:
            return {"ok": False, "error": str(e)}
        if refresh:
            self.refresh_claude()
        return {"ok": True}

    # ----- smart lamps -----

    def _lamp_list(self):
        if self._lamps is None:
            from abdoh.lights import Lamps

            self._lamps = Lamps(self._cfg.app_dir / "lamps.json")
        return self._lamps

    def lamps(self) -> dict:
        """Your lamps (with what each can do), and the colours, whites and scenes there are
        (the lamp pickers in commands and modes)."""
        from abdoh.lights import options

        return {"lamps": [vars(lamp) for lamp in self._lamp_list().all()], "options": options()}

    def lamp_states(self) -> dict:
        """The Lamps page: each lamp and how it is right now."""
        from abdoh.lights import options

        return {"lamps": self._lamp_list().states(), "options": options()}

    def set_lamp(self, which, how) -> dict:
        """Change a lamp now, from the Lamps page ("Desk lamp", "40%")."""
        from abdoh.commands.actions import ActionError

        try:
            self._lamp_list().set(str(which or "all"), str(how or ""))
        except ActionError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True}

    def try_lamp(self, which, how) -> dict:
        """Show a lamp setting for a few seconds, from the lamp dialog ("Desk lamp", "party
        fast 60%"); then the lamps go back as they were."""
        return self._lamp_action(self._lamp_list().preview, str(which or "all"), str(how or ""))

    def find_lamps(self) -> dict:
        """Look for WiZ lamps on your network (a couple of seconds)."""
        try:
            found = self._lamp_list().find_new()
        except Exception:
            log.warning("Couldn't look for lamps", exc_info=True)
            return {"ok": False, "error": "Couldn't look for lamps on your network."}
        return {"ok": True, **self.lamps(), "lamps": [vars(lamp) for lamp in found]}

    def rename_lamp(self, mac, name) -> dict:
        return self._lamp_action(self._lamp_list().rename, str(mac), str(name))

    def blink_lamp(self, mac) -> dict:
        return self._lamp_action(self._lamp_list().blink, str(mac))

    def forget_lamp(self, mac) -> dict:
        return self._lamp_action(self._lamp_list().forget, str(mac))

    def _lamp_action(self, action, *args) -> dict:
        from abdoh.commands.actions import ActionError

        try:
            action(*args)
        except ActionError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, **self.lamps()}

    def connectors(self) -> dict:
        """Your claude.ai connectors (Gmail, Google Calendar, ...) and which ones Claude may use."""
        try:
            return self._claude().connectors(self._config())
        except Exception:
            log.warning("Couldn't list the connectors", exc_info=True)
            return {"available": False, "reason": "Couldn't check your connectors."}

    def install_claude(self) -> dict:
        """Run Anthropic's installer for Claude Code in a window you can watch."""
        return self._claude_action(self._claude().install_claude_code)

    def _claude_code(self):
        return self._claude().find_claude_code(self._config().claude.code_path)

    def claude_sign_in(self) -> dict:
        """Start Claude Code's own sign-in (in the background): it opens your browser. The
        link comes back too, in case the browser didn't open."""
        exe = self._claude_code()
        if not exe:
            return {"ok": False, "error": "Install Claude Code first."}
        try:
            url = self._claude().sign_in(exe)
        except self._claude().SetupError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "url": url or ""}

    def claude_sign_out(self) -> dict:
        exe = self._claude_code()
        if not exe:
            return {"ok": False, "error": "Claude Code isn't installed."}
        return self._claude_action(self._claude().sign_out, exe, refresh=True)

    def set_api_key(self, key) -> dict:
        """Save your own Anthropic API key on this computer ("" removes it)."""
        return self._claude_action(
            self._claude().set_api_key, self._config(), str(key or ""), refresh=True
        )

    def set_openrouter_key(self, key) -> dict:
        """Save your own OpenRouter key on this computer ("" removes it)."""
        return self._claude_action(
            self._claude().set_openrouter_key, self._config(), str(key or ""), refresh=True
        )

    def openrouter_models(self) -> dict:
        """The models on OpenRouter (its public list), to pick one in Settings."""
        return self._claude().openrouter_models()

    def openrouter_pictures(self) -> dict:
        """The picture models, the chosen one's price, and the credit left."""
        return self._claude().openrouter_pictures(self._config())

    def picture_price(self, model) -> dict:
        return self._claude().picture_price(str(model or ""))

    def claude_test(self) -> dict:
        """Ask Claude for one word, to check the connection."""
        return self._claude().check_connection(self._config())

    # ----- your ChatGPT plan (Sign in with ChatGPT) -----

    def chatgpt_connect(self) -> dict:
        """Start "Continue with ChatGPT": OpenAI's page opens in your browser. The link comes
        back too, in case the browser didn't open."""
        from abdoh.claude import chatgpt

        return chatgpt.connect(self._config(), open_browser=self._open_url)

    def chatgpt_progress(self) -> dict:
        """How the sign-in goes; once it's done, Abdoh reconnects."""
        from abdoh.claude import chatgpt

        return chatgpt.progress()

    def chatgpt_models(self) -> dict:
        """The models your ChatGPT plan may use here."""
        from abdoh.claude import chatgpt

        return chatgpt.models(self._config())

    def chatgpt_disconnect(self) -> dict:
        """Sign Abdoh out of ChatGPT: revoked at OpenAI, the tokens deleted here."""
        from abdoh.claude import chatgpt

        result = chatgpt.disconnect(self._config())
        self.refresh_claude()
        return result

    def refresh_claude(self) -> None:
        """The connection changed (signed in, installed, key): Abdoh reconnects."""
        self._bus.request("settings_changed")

    # ----- updates -----

    def check_update(self, force=False) -> dict:
        """Is a newer Abdoh out? At most one check a day (unless force), and only if
        check_updates is on (or you pressed Check now)."""
        if not force and not self._config().check_updates:
            return {"available": False, "current": __version__}
        if self._check_for_update is None:
            from abdoh.updates import check_for_update

            self._check_for_update = check_for_update
        latest = self._check_for_update(force=bool(force))
        if not latest:
            return {"available": False, "current": __version__}
        return {"available": True, "current": __version__, **latest,
                "installing": self._update_job().status}  # fmt: skip

    def _update_job(self):
        if getattr(self, "_updater", None) is None:
            from abdoh.updates import Updater

            self._updater = Updater(
                on_status=lambda status: self._state.feed("update", status),
                on_ready=self._close_for_update,
            )
        return self._updater

    def install_update(self) -> dict:
        """Download the newer Abdoh and install it: the installer runs quietly after Abdoh
        closes, and the new Abdoh opens. Returns how it's going ({state, percent, error})."""
        check = self._check_for_update
        if check is None:
            from abdoh.updates import check_for_update as check
        latest = check(force=False)
        if not latest:
            return {"state": "failed", "error": "You already have the latest version."}
        return self._update_job().install(latest)

    def update_status(self) -> dict:
        return dict(self._update_job().status)

    def _close_for_update(self) -> None:
        """The installer is ready and waits for Abdoh to close: close, after a moment for the
        window to say so."""
        import threading

        def close() -> None:
            import time

            time.sleep(UPDATE_CLOSE_SECONDS)
            self._bus.request("quit")

        threading.Thread(target=close, name="abdoh-update-close", daemon=True).start()

    # ----- the window -----

    def hide(self) -> None:
        if self._window is not None:
            self._window.hide()

    def quit(self) -> None:
        self._bus.request("quit")

    def restart(self) -> None:
        """Quit and start again (for settings that are only read at start)."""
        if self._window is not None:
            self._window.restart_requested = True
        self._bus.request("quit")

    def open_link(self, url) -> bool:
        """Open a web link in the browser (only http and https)."""
        url = str(url or "")
        if not url.lower().startswith(("https://", "http://")):
            return False
        self._open_url(url)
        return True
