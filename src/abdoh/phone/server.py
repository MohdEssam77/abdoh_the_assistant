"""The phone page's web server: 127.0.0.1 only; Tailscale Serve shares it with your phones
over HTTPS (phone/tailscale.py).

`PhoneApp.handle(method, path, headers, body)` answers one request (tests call it directly);
`PhoneServer` is the thin HTTP part around it. Every API call except pairing needs the key of a
paired phone (`Authorization: Bearer <key>`).
"""

import json
import logging
import re
import sys
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from abdoh.phone.devices import FILE, Phones, phone_name
from abdoh.phone.files import MAX_UPLOAD
from abdoh.phone.hub import MAX_CLIPBOARD, PhoneError, PhoneGone, PhoneHub
from abdoh.phone.media import SHOWN

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent / "web"
# The window's board (board.js and the libraries it draws with): the phone draws the same board.
SHARED_DIR = Path(__file__).resolve().parents[1] / "ui" / "web"
_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
HOST = "127.0.0.1"
MAX_JSON = 64 * 1024
MAX_VOICE = 60 * 16000 * 2  # a minute of 16 kHz 16-bit audio
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".webmanifest": "application/manifest+json",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
}
SECURITY = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'wasm-unsafe-eval'; "
        "connect-src 'self'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
# A picture or file behind a secret link: never run as a page of this site.
MEDIA_SECURITY = {
    "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self'; media-src 'self'; "
    "style-src 'unsafe-inline'",
    "Cache-Control": "private, max-age=3600",
}
_MEDIA = re.compile(r"/media/([0-9a-f]{32})")
_RANGE = re.compile(r"bytes=(\d*)-(\d*)")
CHUNK = 256 * 1024
NOT_PAIRED = "This phone isn't paired with Abdoh. Scan the code in Settings → Phone again."
OLD_CODE = "That code doesn't work any more. Make a new one in Settings → Phone."
_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")


@dataclass
class Response:
    status: int
    body: bytes = b""
    type: str = "application/json"
    headers: dict = field(default_factory=dict)
    path: Path | None = None  # a file sent from disk instead of `body`: from `start`, `size` bytes
    start: int = 0
    size: int = 0


def answer(data, status: int = 200) -> Response:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return Response(status, body, "application/json; charset=utf-8", {"Cache-Control": "no-store"})


def error(status: int, message: str) -> Response:
    return answer({"error": message}, status)


def _bearer(headers: dict) -> str | None:
    value = headers.get("authorization") or ""
    return value[7:].strip() if value[:7].lower() == "bearer " else None


def _json(body: bytes) -> dict:
    try:
        data = json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, ValueError):
        raise PhoneError("That request wasn't readable.") from None
    if not isinstance(data, dict):
        raise PhoneError("That request wasn't readable.")
    return data


class PhoneApp:
    def __init__(
        self,
        hub: PhoneHub,
        phones: Phones,
        web: Path = WEB_DIR,
        shared: Path = SHARED_DIR,
        codoh=None,
    ):
        self.hub = hub
        self.phones = phones
        self.codoh = codoh  # the app's Codoh, when it's there (a function: made when needed)
        self.web = Path(web)
        self.shared = Path(shared)

    def handle(self, method: str, path: str, headers: dict, body: bytes = b"") -> Response:
        """One request. `headers` with lowercase names."""
        url = urlsplit(path)
        route = url.path
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        media = _MEDIA.fullmatch(route)
        if media:
            return self._media(method, media.group(1), query, headers)
        if not route.startswith("/api/"):
            return self._static(method, route)
        try:
            if route == "/api/pair":
                if method != "POST":
                    return error(405, "Not allowed.")
                return self._pair(headers, body)
            phone = self.phones.check(_bearer(headers))
            if phone is None:
                return error(401, NOT_PAIRED)
            return self._api(method, route, query, body, phone)
        except PhoneGone as e:
            return error(410, str(e))
        except PhoneError as e:
            return error(400, str(e))

    def _pair(self, headers: dict, body: bytes) -> Response:
        data = _json(body[:MAX_JSON])
        name = data.get("name") or phone_name(headers.get("user-agent", ""))
        key = self.phones.pair(str(data.get("code") or ""), str(name))
        if key is None:
            return error(403, OLD_CODE)
        return answer({"key": key})

    def _codoh(self, method: str, route: str, query: dict, body: bytes, phone: dict) -> Response:
        """Codoh from the phone (phone/codoh.py)."""
        from abdoh.phone import codoh as desk

        try:
            codoh = self.codoh() if self.codoh is not None else None
        except Exception:
            log.exception("Codoh isn't there for the phone")
            codoh = None
        if codoh is None:
            raise PhoneError(desk.NO_CODOH)
        if method == "GET" and route == "/api/codoh":
            return answer({"ok": True, **desk.chats(codoh.state())})
        if method == "GET" and route == "/api/codoh/chat":
            try:
                since = int(query.get("since", "0"))
            except ValueError:
                since = 0
            return answer(desk.chat(codoh, str(query.get("id", "")), since))
        if method != "POST":
            return error(405, "Not allowed.")
        data = _json(body[: MAX_JSON + desk.TEXT * 4])
        chat_id = str(data.get("id") or "")
        if route in ("/api/codoh/send", "/api/codoh/answer"):
            self.hub.codoh_sent(chat_id, phone["id"])  # what the chat needs goes to this phone
        if route == "/api/codoh/send":
            return answer(codoh.send(chat_id, str(data.get("text") or ""), by_phone=True))
        if route == "/api/codoh/stop":
            return answer(codoh.stop(chat_id))
        if route == "/api/codoh/answer":
            answers = data.get("answers") if isinstance(data.get("answers"), dict) else None
            decision = str(data.get("decision") or "")
            if decision not in ("allow", "always", "deny"):
                raise PhoneError("That answer isn't one Codoh knows.")
            return answer(codoh.answer(chat_id, str(data.get("item") or ""), decision, answers))
        if route == "/api/codoh/new":
            made = desk.new_chat(codoh, str(data.get("folder") or ""), str(data.get("text") or ""))
            self.hub.codoh_sent(str(made.get("chat") or ""), phone["id"])
            return answer(made)
        return error(404, "Not found.")

    def _api(self, method: str, route: str, query: dict, body: bytes, phone: dict) -> Response:
        if route == "/api/codoh" or route.startswith("/api/codoh/"):
            return self._codoh(method, route, query, body, phone)
        if method == "GET" and route == "/api/state":
            return answer({**self.hub.state(), "phone": phone["name"], "phone_id": phone["id"]})
        if method == "GET" and route == "/api/events":
            try:
                after = int(query.get("after", "0"))
            except ValueError:
                after = 0
            return answer(self.hub.events(after))
        if method == "GET" and route == "/api/controls":
            return answer(self.hub.controls())
        if method == "GET" and route == "/api/live/screens":
            if self.hub.live is None:
                raise PhoneError("Abdoh can't show the screen here.")
            screens = [{"id": s.id, "label": s.label, "primary": s.primary}
                       for s in self.hub.live.screens()]  # fmt: skip
            return answer({"ok": True, "screens": screens})
        if method == "GET" and route == "/api/live":  # the next frame (story 155)
            if self.hub.live is None:
                raise PhoneError("Abdoh can't show the screen here.")
            try:
                after = int(query.get("after", "0"))
            except ValueError:
                after = 0
            found = self.hub.live.frame(str(query.get("screen") or "follow"), after)
            if found is None:
                return Response(204, b"", "text/plain", {"Cache-Control": "no-store"})
            number, jpeg, label = found
            return Response(200, jpeg, "image/jpeg", {"Cache-Control": "no-store",
                            "X-Frame": str(number), "X-Screen": quote(label)})  # fmt: skip
        if method == "GET" and route == "/api/clipboard":
            return answer({"ok": True, "text": self.hub.clipboard()})
        if method == "GET" and route.startswith("/api/audio/"):
            wav = self.hub.audio(route.rsplit("/", 1)[-1])
            if wav is None:
                return error(404, "That reply's sound is gone.")
            return Response(200, wav, "audio/wav", {"Cache-Control": "no-store"})
        if method != "POST":
            return error(405 if route in _ROUTES else 404, "Not found.")
        if route == "/api/text":
            data = _json(body[:MAX_JSON])
            files = [str(f) for f in data.get("files") or [] if isinstance(f, str)]
            text = self.hub.ask(str(data.get("text") or ""), bool(data.get("speak")), phone["id"],
                                files=files)  # fmt: skip
            return answer({"ok": True, "text": text})
        if route == "/api/clipboard":
            data = _json(body[: MAX_JSON + MAX_CLIPBOARD * 4])
            self.hub.put_clipboard(str(data.get("text") or ""))
            return answer({"ok": True})
        if route == "/api/voice":
            if len(body) > MAX_VOICE:
                raise PhoneError("That recording is too long: a minute at most.")
            speak = query.get("speak") == "1"
            if query.get("over") == "1":  # said over Abdoh's answer on a call (story 146)
                return answer({"ok": True, **self.hub.hear_over(body, speak, phone["id"])})
            files = [f for f in str(query.get("files") or "").split(",") if f]
            heard = self.hub.hear(body, speak, phone["id"], files=files)
            return answer({"ok": True, "text": heard})
        if route == "/api/stop":
            self.hub.stop()
            return answer({"ok": True})
        if route == "/api/board_pdf":  # the board's Save as PDF
            self.hub.board_pdf(phone["id"])
            return answer({"ok": True})
        if route == "/api/screen":  # the live view's Picture: into the conversation
            data = _json(body[:MAX_JSON]) if body else {}
            key = self.hub.screen_now(str(data.get("screen") or ""), phone["id"])
            return answer({"ok": True, "id": key})
        if route == "/api/control":
            data = _json(body[:MAX_JSON])
            self.hub.control(str(data.get("kind") or ""), str(data.get("value") or ""),
                             bool(data.get("speak")), phone["id"])  # fmt: skip
            return answer({"ok": True})
        if route == "/api/forget":
            self.phones.remove(phone["id"])
            return answer({"ok": True})
        return error(404, "Not found.")

    def upload(self, headers: dict, path: str, reader, length: int) -> Response:
        """POST /api/upload?name=...: a file from the phone, its bytes read from `reader` a
        piece at a time (never all in memory). Checked before any of it is read."""
        if self.phones.check(_bearer(headers)) is None:
            return error(401, NOT_PAIRED)
        query = {k: v[-1] for k, v in parse_qs(urlsplit(path).query).items()}
        try:
            return answer({"ok": True, **self.hub.save(query.get("name", ""), reader, length)})
        except PhoneError as e:
            return error(400, str(e))

    def _media(self, method: str, key: str, query: dict, headers: dict) -> Response:
        """A picture or a file behind its secret link (media.py). ?download=1: saved, not
        shown; and anything a phone shouldn't open as a page of this site is only saved."""
        if method not in ("GET", "HEAD"):
            return error(405, "Not allowed.")
        found = self.hub.media.get(key)
        if found is None:
            return Response(404, b"This link has expired.", "text/plain; charset=utf-8")
        kind = found.type if found.type in SHOWN else "application/octet-stream"
        how = "attachment" if query.get("download") == "1" or kind not in SHOWN else "inline"
        extra = {**MEDIA_SECURITY, "Accept-Ranges": "bytes"}
        if found.name:
            extra["Content-Disposition"] = f"{how}; filename*=UTF-8''{quote(found.name)}"
        if found.data is not None:
            return Response(200, found.data, kind, extra)
        if not found.path or not found.path.is_file():
            return Response(404, b"That file isn't there any more.", "text/plain; charset=utf-8")
        size = found.path.stat().st_size
        start, length, status = 0, size, 200
        asked = _RANGE.fullmatch(str(headers.get("range") or "").strip())
        if asked and size and (asked.group(1) or asked.group(2)):  # a piece (video, PDF)
            if asked.group(1):
                start = int(asked.group(1))
                end = min(int(asked.group(2)) if asked.group(2) else size - 1, size - 1)
            else:  # the last N bytes
                start, end = max(0, size - int(asked.group(2))), size - 1
            if start > end or start >= size:
                return Response(416, b"", kind, {"Content-Range": f"bytes */{size}"})
            length, status = end - start + 1, 206
            extra["Content-Range"] = f"bytes {start}-{end}/{size}"
        return Response(status, b"", kind, extra, path=found.path, start=start, size=length)

    def _static(self, method: str, route: str) -> Response:
        if method not in ("GET", "HEAD"):
            return error(405, "Not allowed.")
        name = "index.html" if route in ("", "/") else route.lstrip("/")
        if name == "board.js" or name.startswith("vendor/"):  # the window's own (story 150)
            parts = name.split("/")
            path = self.shared.joinpath(*parts)
            if not all(_PART.fullmatch(p) for p in parts) or not path.is_file():
                return Response(404, b"Not found.", "text/plain; charset=utf-8")
        else:
            path = self.web / name
            if not _NAME.fullmatch(name) or not path.is_file():
                return Response(404, b"Not found.", "text/plain; charset=utf-8")
        kind = TYPES.get(path.suffix)
        if kind is None:
            return Response(404, b"Not found.", "text/plain; charset=utf-8")
        return Response(200, path.read_bytes(), kind, {"Cache-Control": "no-cache"})


_ROUTES = {"/api/state", "/api/events", "/api/text", "/api/voice", "/api/stop", "/api/forget",
           "/api/controls", "/api/control", "/api/screen", "/api/clipboard",
           "/api/upload", "/api/board_pdf", "/api/live", "/api/live/screens"}  # fmt: skip


def _handler(app: PhoneApp):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "Abdoh"
        sys_version = ""

        def log_message(self, fmt, *args) -> None:  # not on the console
            log.debug("Phone: " + fmt, *args)

        def _serve(self, method: str) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if method == "POST" and urlsplit(self.path).path == "/api/upload" and length >= 0:
                self._upload(length)
                return
            if length < 0 or length > MAX_VOICE + MAX_JSON:
                self.close_connection = True
                self._send(error(413, "That's too big."), method)
                return
            body = self.rfile.read(length) if length else b""
            headers = {k.lower(): v for k, v in self.headers.items()}
            try:
                response = app.handle(method, self.path, headers, body)
            except Exception:
                log.exception("The phone page's request failed: %s %s", method, self.path)
                response = error(500, "Something went wrong on your computer.")
            self._send(response, method)

        def _upload(self, length: int) -> None:
            headers = {k.lower(): v for k, v in self.headers.items()}
            reader = _Counted(self.rfile)
            try:
                response = app.upload(headers, self.path, reader, length)
            except Exception:
                log.exception("A file from the phone couldn't be saved")
                response = error(500, "Something went wrong on your computer.")
            if response.status != 200:
                left = length - reader.count
                if response.status != 401 and 0 < left <= MAX_UPLOAD:  # so the phone hears why
                    while left > 0 and (piece := self.rfile.read(min(CHUNK, left))):
                        left -= len(piece)
                self.close_connection = True
            self._send(response, "POST")

        def _send(self, response: Response, method: str) -> None:
            self.send_response(response.status)
            for name, value in {**SECURITY, **response.headers}.items():
                self.send_header(name, value)
            self.send_header("Content-Type", response.type)
            size = response.size if response.path is not None else len(response.body)
            self.send_header("Content-Length", str(size))
            self.end_headers()
            if method == "HEAD":
                return
            if response.path is None:
                self.wfile.write(response.body)
                return
            with open(response.path, "rb") as file:  # a piece at a time, never all of it
                file.seek(response.start)
                left = response.size
                while left > 0:
                    piece = file.read(min(CHUNK, left))
                    if not piece:
                        break
                    self.wfile.write(piece)
                    left -= len(piece)

        def do_GET(self) -> None:  # noqa: N802 - http.server's names
            self._serve("GET")

        def do_HEAD(self) -> None:  # noqa: N802
            self._serve("HEAD")

        def do_POST(self) -> None:  # noqa: N802
            self._serve("POST")

    return Handler


class _Counted:
    """A reader that counts what was read (an upload: what's left of it)."""

    def __init__(self, raw):
        self.raw = raw
        self.count = 0

    def read(self, size: int = -1) -> bytes:
        piece = self.raw.read(size)
        self.count += len(piece)
        return piece


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        """To the log, not the console (the app has none). A phone that hung up (it went to
        the background, or lost its network) is normal."""
        error = sys.exc_info()[1]
        if isinstance(error, ConnectionError | TimeoutError):
            log.debug("The phone hung up: %s", error)
        else:
            log.exception("The phone page's connection failed")


class PhoneServer:
    """The HTTP server around a PhoneApp, on its own thread."""

    def __init__(self, app: PhoneApp, port: int, host: str = HOST):
        self.app = app
        self.port = port
        self.host = host
        self._server: ThreadingHTTPServer | None = None

    def start(self) -> None:
        """Raises OSError if the port is taken."""
        server = _Server((self.host, self.port), _handler(self.app))
        self._server = server
        thread = threading.Thread(target=server.serve_forever, name="abdoh-phone", daemon=True)
        thread.start()
        log.info("The phone page is on http://%s:%d", self.host, self.port)

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()
            log.info("The phone page stopped")


class PhoneService:
    """Abdoh from your phone: the paired phones, the hub and the server, started and stopped
    with the Phone switch in Settings."""

    def __init__(self, cfg, bus, hear=None, voice=None, modes=None, screen=None,
                 clipboard=None, set_clipboard=None, codoh=None, live=None,
                 server_class=None):  # fmt: skip
        from abdoh.phone.files import upload_folder

        self.port = cfg.phone_port
        self.phones = Phones(cfg.app_dir / FILE)
        self.hub = PhoneHub(bus, hear=hear, voice=voice, modes=modes, screen=screen,
                            uploads_to=lambda: upload_folder(cfg), clipboard=clipboard,
                            set_clipboard=set_clipboard, live=live)  # fmt: skip
        self.app = PhoneApp(self.hub, self.phones, codoh=codoh)
        self.server = (server_class or PhoneServer)(self.app, self.port)

    def start(self) -> None:
        self.server.start()  # first: a taken port leaves nothing half-started
        self.hub.start()

    def stop(self) -> None:
        self.hub.close()
        self.server.stop()
