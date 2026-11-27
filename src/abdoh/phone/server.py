"""The phone page's web server: 127.0.0.1 only; Tailscale Serve shares it with your phones
over HTTPS (phone/tailscale.py).

`PhoneApp.handle(method, path, headers, body)` answers one request (tests call it directly);
`PhoneServer` is the thin HTTP part around it. Every API call except pairing needs the key of a
paired phone (`Authorization: Bearer <key>`).
"""

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from abdoh.phone.devices import FILE, Phones, phone_name
from abdoh.phone.hub import PhoneError, PhoneHub

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent / "web"
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
}
SECURITY = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
NOT_PAIRED = "This phone isn't paired with Abdoh. Scan the code in Settings → Phone again."
OLD_CODE = "That code doesn't work any more. Make a new one in Settings → Phone."
_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")


@dataclass
class Response:
    status: int
    body: bytes = b""
    type: str = "application/json"
    headers: dict = field(default_factory=dict)


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
    def __init__(self, hub: PhoneHub, phones: Phones, web: Path = WEB_DIR):
        self.hub = hub
        self.phones = phones
        self.web = Path(web)

    def handle(self, method: str, path: str, headers: dict, body: bytes = b"") -> Response:
        """One request. `headers` with lowercase names."""
        url = urlsplit(path)
        route = url.path
        if not route.startswith("/api/"):
            return self._static(method, route)
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        try:
            if route == "/api/pair":
                if method != "POST":
                    return error(405, "Not allowed.")
                return self._pair(headers, body)
            phone = self.phones.check(_bearer(headers))
            if phone is None:
                return error(401, NOT_PAIRED)
            return self._api(method, route, query, body, phone)
        except PhoneError as e:
            return error(400, str(e))

    def _pair(self, headers: dict, body: bytes) -> Response:
        data = _json(body[:MAX_JSON])
        name = data.get("name") or phone_name(headers.get("user-agent", ""))
        key = self.phones.pair(str(data.get("code") or ""), str(name))
        if key is None:
            return error(403, OLD_CODE)
        return answer({"key": key})

    def _api(self, method: str, route: str, query: dict, body: bytes, phone: dict) -> Response:
        if method == "GET" and route == "/api/state":
            return answer({**self.hub.state(), "phone": phone["name"]})
        if method == "GET" and route == "/api/events":
            try:
                after = int(query.get("after", "0"))
            except ValueError:
                after = 0
            return answer(self.hub.events(after))
        if method == "GET" and route.startswith("/api/audio/"):
            wav = self.hub.audio(route.rsplit("/", 1)[-1])
            if wav is None:
                return error(404, "That reply's sound is gone.")
            return Response(200, wav, "audio/wav", {"Cache-Control": "no-store"})
        if method != "POST":
            return error(405 if route in _ROUTES else 404, "Not found.")
        if route == "/api/text":
            data = _json(body[:MAX_JSON])
            text = self.hub.ask(str(data.get("text") or ""), bool(data.get("speak")))
            return answer({"ok": True, "text": text})
        if route == "/api/voice":
            if len(body) > MAX_VOICE:
                raise PhoneError("That recording is too long: a minute at most.")
            heard = self.hub.hear(body, query.get("speak") == "1")
            return answer({"ok": True, "text": heard})
        if route == "/api/stop":
            self.hub.stop()
            return answer({"ok": True})
        if route == "/api/forget":
            self.phones.remove(phone["id"])
            return answer({"ok": True})
        return error(404, "Not found.")

    def _static(self, method: str, route: str) -> Response:
        if method not in ("GET", "HEAD"):
            return error(405, "Not allowed.")
        name = "index.html" if route in ("", "/") else route.lstrip("/")
        path = self.web / name
        if not _NAME.fullmatch(name) or not path.is_file():
            return Response(404, b"Not found.", "text/plain; charset=utf-8")
        kind = TYPES.get(path.suffix)
        if kind is None:
            return Response(404, b"Not found.", "text/plain; charset=utf-8")
        return Response(200, path.read_bytes(), kind, {"Cache-Control": "no-cache"})


_ROUTES = {"/api/state", "/api/events", "/api/text", "/api/voice", "/api/stop", "/api/forget"}


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

        def _send(self, response: Response, method: str) -> None:
            self.send_response(response.status)
            for name, value in {**SECURITY, **response.headers}.items():
                self.send_header(name, value)
            self.send_header("Content-Type", response.type)
            self.send_header("Content-Length", str(len(response.body)))
            self.end_headers()
            if method != "HEAD":
                self.wfile.write(response.body)

        def do_GET(self) -> None:  # noqa: N802 - http.server's names
            self._serve("GET")

        def do_HEAD(self) -> None:  # noqa: N802
            self._serve("HEAD")

        def do_POST(self) -> None:  # noqa: N802
            self._serve("POST")

    return Handler


class PhoneServer:
    """The HTTP server around a PhoneApp, on its own thread."""

    def __init__(self, app: PhoneApp, port: int, host: str = HOST):
        self.app = app
        self.port = port
        self.host = host
        self._server: ThreadingHTTPServer | None = None

    def start(self) -> None:
        """Raises OSError if the port is taken."""
        server = ThreadingHTTPServer((self.host, self.port), _handler(self.app))
        server.daemon_threads = True
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

    def __init__(self, cfg, bus, hear=None, voice=None, server_class=None):
        self.port = cfg.phone_port
        self.phones = Phones(cfg.app_dir / FILE)
        self.hub = PhoneHub(bus, hear=hear, voice=voice)
        self.app = PhoneApp(self.hub, self.phones)
        self.server = (server_class or PhoneServer)(self.app, self.port)

    def start(self) -> None:
        self.server.start()  # first: a taken port leaves nothing half-started
        self.hub.start()

    def stop(self) -> None:
        self.hub.close()
        self.server.stop()
