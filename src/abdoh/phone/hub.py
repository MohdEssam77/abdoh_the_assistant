"""What the phone sees and asks.

The hub listens to the bus (Bus.listen) and keeps the last events with numbers. The phone page
asks for the events after the last one it has and waits up to WAIT_SECONDS for new ones (long
polling: it works through Tailscale's proxy and on a flaky mobile network, and the page never
misses an event). Today's conversation, the status, the AI's name and the mode are kept too, so
a page that opens late shows them.

Events for the page (each with its number, "seq"):
  {"type": "history", "line": "You (phone): ..." | "Abdoh: ..." | ...}  the conversation
  {"type": "clear"}                       a new day: the conversation starts empty
  {"type": "status", "text": ...}         "Thinking...", "Speaking", ...
  {"type": "activity", "text": ...}       "Searching the web"
  {"type": "ai", "name", "label", "status"}
  {"type": "mode", "name": ...}
  {"type": "say", "text", "audio", "for"} a sentence of the reply to the phone that asked
                                          ("for": its id; only that phone speaks it); "audio" is
                                          the id of its WAV (/api/audio/<id>) or None: the phone
                                          speaks it with its own voice, if it speaks replies
  {"type": "aside", "text": ...}          "One moment" while the AI works
  {"type": "question", "text": ...}       Abdoh asked a yes/no question
  {"type": "done", "for": ...}            the phone's request is answered (after its last
                                          "say"): a call listens again (story 145)
  {"type": "step", "text", "for"}         what Abdoh is doing for it: "Reading CV.pdf"
  {"type": "note", "text", "for"}         a line for it that isn't Abdoh's answer
  {"type": "image", "id", "caption", "for"} a picture of the screen: /media/<id>
  {"type": "file", "id", "name", "size", "kind", "for"} a file sent to it: /media/<id>
  {"type": "board", "card": {id, text} | None} the board grew (None: cleared)
  {"type": "board_picture", "picture"}   a picture on it was found: {what, ok, src, credit}

Every event goes through one worker thread, in order: the audio of a sentence is made there,
so a reply's sentences and the line with the whole reply arrive in the order they were said.
"""

import logging
import queue
import secrets
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from datetime import date
from pathlib import Path

from abdoh.phone.media import KEEP_SECONDS, MediaStore, file_kind, file_type

log = logging.getLogger(__name__)

MAX_EVENTS = 300
WAIT_SECONDS = 25.0
HISTORY = 200
MAX_TEXT = 2000
AUDIO_SECONDS = 600.0  # a reply's audio can be fetched for this long
MAX_AUDIO = 60
MEDIA = ("play_pause", "next", "previous", "volume_up", "volume_down", "mute")
SHOWN = 30  # pictures and files kept for a page that opens later
BOARD_CARDS = 30  # as many board cards as the window keeps
MAX_CLIPBOARD = 100_000
# What was said to the phone, for telling its own voice coming back from yours: the phone plays
# a reply's sentences one after another, well after they were sent.
SAID_SECONDS = 120.0
SAID_KEPT = 12
# What you said over a reply on a call (local_skills.interruption_kind, or "echo") -> what the
# phone does: the reply goes on, it stops, the call ends, or it stops and this is asked instead.
OVER = {"stop": "stop", "stop_listening": "end", "request": "request"}
KINDS = frozenset(
    {"history", "status", "activity", "claude", "mode", "phone_say", "phone_aside",
     "phone_question", "phone_done", "phone_step", "phone_image", "phone_note", "phone_file",
     "board", "board_picture"}
)  # fmt: skip


class PhoneError(Exception):
    """Something the phone asked for can't be done; the message is safe to show."""


class PhoneHub:
    def __init__(
        self,
        bus,
        hear: Callable[[bytes], str] | None = None,
        voice: Callable[[str], bytes | None] | None = None,
        modes: Callable[[], list[str]] | None = None,
        screen: Callable[[], bytes] | None = None,
        uploads_to: Callable[[], Path] | None = None,
        clipboard: Callable[[], str] | None = None,
        set_clipboard: Callable[[str], None] | None = None,
        today=date.today,
        clock=time.monotonic,
    ):
        self.bus = bus
        self._hear = hear  # 16 kHz mono 16-bit audio -> text
        self._voice = voice  # a sentence -> WAV bytes, or None (the phone's own voice speaks)
        self._modes = modes  # your modes' names, for the phone's controls
        self._screen = screen  # a picture of the screen (JPEG), for "See the screen"
        self.media = MediaStore(clock)  # pictures and files behind secret links (media.py)
        self._uploads_to = uploads_to  # where files from the phone go (files.upload_folder)
        self._uploads: dict[str, tuple[Path, float]] = {}  # saved, for the next request
        self._clipboard = clipboard  # the computer's clipboard: read...
        self._set_clipboard = set_clipboard  # ... and written
        self._today = today
        self._clock = clock
        self.boot = secrets.token_hex(4)  # a new hub (Abdoh restarted): the page starts over
        self._said: deque[tuple[float, str]] = deque(maxlen=SAID_KEPT)  # said to the phone
        self._cond = threading.Condition()
        self._events: deque[tuple[int, dict]] = deque(maxlen=MAX_EVENTS)
        self._seq = 0
        self._history: deque[str] = deque(maxlen=HISTORY)
        self._lines = 0  # today's conversation lines so far: where a picture or file falls
        self._shown: deque[dict] = deque(maxlen=SHOWN)  # pictures and files sent today
        self._board: list[dict] = []  # the board's cards: {id, text} (story 150)
        self._pictures: dict[str, dict] = {}  # its pictures, by what they show
        self._day = today()
        self._status = ""
        self._ai: dict = {}
        self._mode = ""
        self._speak = False  # the phone that asked last wants the replies spoken
        self._asker = ""  # ... and its id
        self._audio: OrderedDict[str, tuple[bytes, float]] = OrderedDict()
        self._audio_lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue()
        self._closed = False
        self._worker: threading.Thread | None = None

    # ----- running -----

    def start(self) -> None:
        self._worker = threading.Thread(target=self._work, name="abdoh-phone-hub", daemon=True)
        self._worker.start()
        self.bus.listen(self.on_event)

    def close(self) -> None:
        self.bus.unlisten(self.on_event)
        with self._cond:
            self._closed = True
            self._cond.notify_all()
        self._queue.put(None)

    def on_event(self, kind: str, value) -> None:
        """From the bus (the emitting thread): queued for the worker."""
        if kind in KINDS:
            self._queue.put((kind, value))

    def _work(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            try:
                self.take(*item)
            except Exception:
                log.exception("The phone couldn't take the event %r", item[0])

    def take(self, kind: str, value) -> None:
        """One event, turned into what the page gets (on the worker thread; tests call it)."""
        if kind == "history":
            line = str(value or "")
            if not line.strip():
                return
            self._new_day()
            with self._cond:
                self._history.append(line)
                self._lines += 1
            self._add({"type": "history", "line": line})
        elif kind == "status":
            self._status = str(value or "")
            self._add({"type": "status", "text": self._status})
        elif kind == "activity":
            self._add({"type": "activity", "text": str(value or "")})
        elif kind == "claude":
            info = value if isinstance(value, dict) else {"status": str(value or "")}
            self._ai = {
                "name": str(info.get("name") or "Claude"),
                "label": str(info.get("label") or info.get("name") or "Claude"),
                "status": str(info.get("status") or ""),
            }
            self._add({"type": "ai", **self._ai})
        elif kind == "mode":
            self._mode = str(value or "")
            self._add({"type": "mode", "name": self._mode})
        elif kind == "phone_say":
            text = str(value or "")
            if text.strip():
                self._said.append((self._clock(), text))
                audio = self._render(text)
                self._add({"type": "say", "text": text, "audio": audio, "for": self._asker})
        elif kind == "phone_aside":
            self._add({"type": "aside", "text": str(value or "")})
        elif kind == "phone_question":
            self._add({"type": "question", "text": str(value or "")})
        elif kind == "phone_done":
            self._add({"type": "done", "for": self._asker})
        elif kind == "phone_step":
            self._add({"type": "step", "text": str(value or "")[:200], "for": self._asker})
        elif kind == "phone_note":
            self._add({"type": "note", "text": str(value or "")[:500], "for": self._asker})
        elif kind == "phone_image":  # {"data": JPEG bytes, "caption"}: a picture of the screen
            value = value if isinstance(value, dict) else {}
            try:
                data, kind = value.get("data") or b"", value.get("type", "image/jpeg")
                key = self.media.add_picture(data, kind)
            except ValueError:
                log.warning("A picture for the phone was empty or too big")
                return
            self._show({"type": "image", "id": key, "caption": str(value.get("caption") or "")})
        elif kind == "board":  # {"id", "text"}: a card grew; None: the board was cleared
            self._take_board(value)
        elif kind == "board_picture":  # {"what", "ok", "src" (a data: URL), "credit", ...}
            picture = self._board_picture(value if isinstance(value, dict) else {})
            if picture:
                self._add({"type": "board_picture", "picture": picture})
        elif kind == "phone_file":  # {"path"}: a file Claude sent (ACTION send_file), checked
            path = Path(str((value or {}).get("path") or ""))
            try:
                key = self.media.add_file(path)
            except OSError:
                log.warning("The file for the phone is gone: %s", path)
                return
            found = self.media.get(key)
            self._show({"type": "file", "id": key, "name": found.name, "size": found.size,
                        "kind": file_kind(found.type)})  # fmt: skip

    def _new_day(self) -> None:
        today = self._today()
        if today != self._day:
            self._day = today
            with self._cond:
                self._history.clear()
                self._lines = 0
                self._shown.clear()
            self._add({"type": "clear"})

    def _take_board(self, card) -> None:
        with self._cond:
            if not isinstance(card, dict):
                self._board, self._pictures = [], {}
                card = None
            else:
                card = {"id": card.get("id"), "text": str(card.get("text") or "")}
                if self._board and self._board[-1]["id"] == card["id"]:
                    self._board[-1] = card
                else:  # a new card: it has its place in the conversation, for everyone
                    self._board = [*self._board, card][-BOARD_CARDS:]
                    self._shown.append({"type": "board", "id": card["id"], "for": "",
                                        "line": self._lines})  # fmt: skip
        self._add({"type": "board", "card": card})

    def _board_picture(self, value: dict) -> dict | None:
        """A board picture, its data: URL swapped for a link (a few MB in every page's state
        and event otherwise)."""
        import base64
        import binascii

        what = str(value.get("what") or "")
        if not what:
            return None
        picture = {k: value.get(k) for k in ("what", "ok", "credit", "title", "ai", "error")}
        src = str(value.get("src") or "")
        head, _, data = src.partition(",")
        if head.startswith("data:image/") and head.endswith(";base64"):
            try:
                key = self.media.add_picture(base64.b64decode(data), head[5:-7])
                src = f"/media/{key}"
            except (binascii.Error, ValueError):
                log.warning("A board picture for the phone couldn't be read")
                src = ""
        picture["src"] = src
        with self._cond:
            self._pictures[what] = picture
        return picture

    def _show(self, event: dict) -> None:
        """A picture or a file for the phone that asked: sent now, and kept with where it falls
        in the conversation, for a page that opens later."""
        self._new_day()
        event = {**event, "for": self._asker}
        with self._cond:
            self._shown.append({**event, "line": self._lines})
        self._add(event)

    def _add(self, event: dict) -> None:
        with self._cond:
            self._seq += 1
            self._events.append((self._seq, event))
            self._cond.notify_all()

    # ----- what the page reads -----

    def state(self) -> dict:
        with self._cond:
            return {
                "boot": self.boot,
                "seq": self._seq,
                "history": list(self._history),
                "first_line": self._lines - len(self._history),  # the first one's number
                "media": [
                    dict(m)
                    for m in self._shown
                    if m["type"] == "board" or self.media.get(m["id"]) is not None
                ],
                "board": [dict(c) for c in self._board],
                "pictures": dict(self._pictures),
                "status": self._status,
                "ai": dict(self._ai),
                "mode": self._mode,
            }

    def events(self, after: int, wait: float = WAIT_SECONDS) -> dict:
        """The events after number `after`, waiting up to `wait` seconds for one. "reset":
        the page missed some (or Abdoh restarted): it reads the state again."""
        deadline = self._clock() + wait
        with self._cond:
            while True:
                head = {"boot": self.boot, "seq": self._seq}
                if after > self._seq or (self._events and self._events[0][0] > after + 1):
                    return {**head, "reset": True, "events": []}
                new = [{"seq": n, **e} for n, e in self._events if n > after]
                left = deadline - self._clock()
                if new or self._closed or left <= 0:
                    return {**head, "events": new}
                self._cond.wait(left)

    # ----- what the phone asks -----

    def ask(
        self,
        text: str,
        speak: bool = False,
        phone: str = "",
        spoken: bool = False,
        files: list[str] | None = None,
    ) -> str:
        """A request from the phone (`phone`: its id; its reply is spoken there). `spoken`: it
        was said, not typed (the week's conversations keep which). `files`: the ids of files
        it sent first (save); the request names them ("[sent photo.jpg]"), and Claude gets
        where they are."""
        text = " ".join(str(text or "").split())[:MAX_TEXT]
        sent = self._sent_files(files or [])
        if sent:
            text = f"{text} [sent {', '.join(p.name for p in sent)}]".strip()
        if not text:
            raise PhoneError("Type something to ask Abdoh.")
        self._speak, self._asker = bool(speak), phone
        request = {"text": text}
        if spoken:
            request["spoken"] = True
        if sent:
            request["files"] = [str(p) for p in sent]
        self.bus.request("phone", request)
        return text

    def _sent_files(self, ids: list[str]) -> list[Path]:
        now = self._clock()
        with self._audio_lock:
            for old in [k for k, (_, at) in self._uploads.items() if now - at > KEEP_SECONDS]:
                del self._uploads[old]
            found = [self._uploads.pop(str(i), None) for i in ids[:10]]
        return [path for path, _ in filter(None, found) if path.is_file()]

    # ----- files from the phone, and the clipboard -----

    def save(self, name: str, reader, length: int) -> dict:
        """A file from the phone, saved on the computer (files.save_upload): its id for the
        request that comes with it."""
        from abdoh.phone.files import FileProblem, save_upload

        if self._uploads_to is None:
            raise PhoneError("Abdoh can't take files from the phone here.")
        try:
            path = save_upload(self._uploads_to(), name, reader, length)
        except FileProblem as e:
            raise PhoneError(str(e)) from e
        except OSError as e:
            log.exception("Couldn't save a file from the phone")
            raise PhoneError("Abdoh couldn't save that file on the computer.") from e
        key = secrets.token_hex(8)
        with self._audio_lock:
            self._uploads[key] = (path, self._clock())
        size = path.stat().st_size
        return {"id": key, "name": path.name, "size": size, "kind": file_kind(file_type(path.name))}

    def clipboard(self) -> str:
        if self._clipboard is None:
            raise PhoneError("Abdoh can't reach the clipboard here.")
        try:
            return str(self._clipboard() or "")[:MAX_CLIPBOARD]
        except Exception as e:
            log.exception("Couldn't read the clipboard for the phone")
            raise PhoneError("Abdoh couldn't read the computer's clipboard.") from e

    def put_clipboard(self, text: str) -> None:
        if self._set_clipboard is None:
            raise PhoneError("Abdoh can't reach the clipboard here.")
        text = str(text or "")
        if len(text) > MAX_CLIPBOARD:
            raise PhoneError("That's too much text for the clipboard.")
        try:
            self._set_clipboard(text)
        except Exception as e:
            log.exception("Couldn't set the clipboard from the phone")
            raise PhoneError("Abdoh couldn't set the computer's clipboard.") from e

    def hear(self, audio: bytes, speak: bool = False, phone: str = "") -> str:
        """A spoken request from the phone: what was heard ("" if nothing), then asked."""
        text = self._transcribe(audio)
        if text:
            self.ask(text, speak, phone, spoken=True)
        return text

    def hear_over(self, audio: bytes, speak: bool = False, phone: str = "") -> dict:
        """What you said over Abdoh's answer on a call (story 146): {"text", "kind", "heard"}.
        "kind": "go_on" (no words, "okay", a word or two, or Abdoh's own voice coming back
        through the phone's microphone: the answer goes on), "stop" ("wait": it stops),
        "end" ("stop listening": the call ends) or "request" (it stops, and this is asked
        instead). "heard": how it was taken (local_skills.interruption_kind, or "echo")."""
        from abdoh.audio.echo_text import own_words
        from abdoh.local_skills import interruption_kind

        text = self._transcribe(audio)
        heard = interruption_kind(text)
        now = self._clock()
        said = [words for at, words in list(self._said) if now - at < SAID_SECONDS]
        if heard not in ("nothing", "backchannel") and own_words(text, said):
            heard = "echo"
        kind = OVER.get(heard, "go_on")
        log.info("Heard %r over the reply on the phone (%s)", text, heard)
        if kind != "go_on":
            self.stop()
        if kind == "request":
            self.ask(text, speak, phone, spoken=True)
        return {"text": text, "kind": kind, "heard": heard}

    def _transcribe(self, audio: bytes) -> str:
        if self._hear is None:
            raise PhoneError("Speech recognition isn't working on your computer right now.")
        if not audio:
            return ""
        if len(audio) % 2:
            raise PhoneError("That recording wasn't readable.")
        try:
            return (self._hear(audio) or "").strip()
        except Exception as e:
            log.exception("Couldn't understand the phone's recording")
            raise PhoneError("Abdoh couldn't understand that recording.") from e

    def stop(self) -> None:
        """Stop the reply (the phone's Stop button)."""
        self.bus.request("stop_speaking")

    def screen_now(self) -> str:
        """A picture of the computer's screen right now (the controls' "See the screen"): its
        link's key. Not part of the conversation."""
        from abdoh.claude.screen import ScreenCaptureError

        if self._screen is None:
            raise PhoneError("Abdoh can't take pictures of the screen here.")
        try:
            return self.media.add_picture(self._screen())
        except ScreenCaptureError as e:
            raise PhoneError(str(e)) from e
        except ValueError as e:
            raise PhoneError("The picture of the screen didn't come out.") from e

    # ----- the phone's quick controls -----

    def controls(self) -> dict:
        """What the controls show: your modes and the one that's on."""
        try:
            modes = list(self._modes()) if self._modes else []
        except Exception:
            log.exception("Couldn't list the modes for the phone")
            modes = []
        return {"modes": modes, "mode": self._mode}

    def control(self, kind: str, value: str = "", speak: bool = False, phone: str = "") -> None:
        """A mode ("" = normal), a media key (MEDIA), or locking the computer."""
        value = str(value or "")
        if kind == "media" and value not in MEDIA:
            raise PhoneError("That button doesn't do anything.")
        if kind == "mode" and value and value not in self.controls()["modes"]:
            raise PhoneError("That mode is gone. Open the controls again.")
        if kind not in ("mode", "media", "lock"):
            raise PhoneError("That button doesn't do anything.")
        self._speak, self._asker = bool(speak), phone
        self.bus.request("phone_control", {"kind": kind, "value": value})

    # ----- the replies' audio -----

    def _render(self, text: str) -> str | None:
        if not self._speak or self._voice is None:
            return None
        try:
            wav = self._voice(text)
        except Exception:
            log.exception("Couldn't make the audio for the phone")
            return None
        if not wav:
            return None
        key = secrets.token_hex(8)
        now = self._clock()
        with self._audio_lock:
            self._audio[key] = (wav, now)
            while len(self._audio) > MAX_AUDIO:
                self._audio.popitem(last=False)
        return key

    def audio(self, key: str) -> bytes | None:
        now = self._clock()
        with self._audio_lock:
            for old in [k for k, (_, at) in self._audio.items() if now - at > AUDIO_SECONDS]:
                del self._audio[old]
            found = self._audio.get(key)
        return found[0] if found else None
