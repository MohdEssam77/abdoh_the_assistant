"""ChatGPT, paid by the user's own ChatGPT plan: OpenAI's "Sign in with ChatGPT" for open-source
apps that run on the user's computer (https://developers.openai.com/siwc/token-sharing-open-source).

Signing in happens on OpenAI's page in the browser; Abdoh never sees a password. The first time,
Abdoh registers itself there (as "Abdoh", with an id for this installation) and gets its own
client id back, kept for signing in again. The browser comes back to a page Abdoh serves on
127.0.0.1 for a few minutes. The tokens stay on this computer, encrypted for this Windows user
(DPAPI), outside the settings; they never reach the log or the window.

Replies come from OpenAI's Responses API, streamed and not stored. Like an API key: Abdoh's
actions work, and looking at the screen with a model that sees images; Claude Code's own tools
(your files, web search, Gmail and Calendar) don't, and only the last exchange is remembered.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import sys
import threading
import time
import uuid
import webbrowser
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from abdoh.claude.brain import Brain, BrainError, system_prompt
from abdoh.config import Config

log = logging.getLogger(__name__)

ISSUER = "https://auth.openai.com"
AUTHORIZE_URL = f"{ISSUER}/api/accounts/authorize"
TOKEN_URL = f"{ISSUER}/api/accounts/oauth/token"
REVOKE_URL = f"{ISSUER}/api/accounts/oauth/revoke"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"
API = "https://api.openai.com/v1"  # also the "resource" the tokens are for
FIRST_CLIENT = "dynamic_agent_client"  # registering: OpenAI then issues Abdoh's own client id
APP_NAME = "Abdoh"
PLAN_SCOPE = "chatgpt.tokens.use.direct"  # without it, the plan can't be used
SCOPES = f"openid profile email offline_access resource.invoke {PLAN_SCOPE}"
PORT = 1455  # the callback's port (another free one if it's taken: only the port may vary)
CALLBACK_PATH = "/auth/callback"
USAGE_URL = "https://chatgpt.com/settings/usage"
FOLDER = "chatgpt"  # in the app folder: account.json (no secrets) and tokens.bin (encrypted)
SIGN_IN_SECONDS = 600.0  # then a sign-in nobody finished in the browser stops waiting
REFRESH_EARLY_SECONDS = 120.0  # refresh the access token this long before it runs out
TIMEOUT_SECONDS = 60.0
# A refresh that fails like this means signing in again (the session is over).
SIGNED_OUT_CODES = {
    "invalid_grant", "invalid_refresh_token", "token_expired", "refresh_token_expired",
    "refresh_token_invalidated", "refresh_token_reused",
}  # fmt: skip

SIGNED_OUT = "ChatGPT signed Abdoh out. Connect again in Settings."
NO_PLAN_USAGE = (
    "Abdoh may not use your ChatGPT plan yet. In Settings, press Reconnect and allow it to use "
    "your plan."
)
LIMIT = "You've reached your ChatGPT usage limit for now. You can see it in your ChatGPT settings."
NOT_ELIGIBLE = "Your ChatGPT plan can't be used in other apps: that needs ChatGPT Plus or Pro."
BUSY = "ChatGPT is busy right now. Try again in a moment."
UNREACHABLE = "I couldn't reach ChatGPT right now."
CUT_OFF = "ChatGPT's answer was cut off."
INCOMPLETE = "ChatGPT stopped before it finished."


class SignInError(RuntimeError):
    """Connecting ChatGPT didn't work; the message is safe to show."""


# ----- what's kept on this computer -----


def _protect(data: bytes) -> bytes:
    """Encrypted for this Windows user (DPAPI): only they, on this computer, can read it."""
    return _dpapi(data, protect=True) if sys.platform == "win32" else data


def _unprotect(data: bytes) -> bytes:
    return _dpapi(data, protect=False) if sys.platform == "win32" else data


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(data, len(data))
    given = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    out = Blob()
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    call = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    no_ui = 0x1  # CRYPTPROTECT_UI_FORBIDDEN
    if not call(ctypes.byref(given), None, None, None, None, no_ui, ctypes.byref(out)):
        raise OSError("Windows couldn't encrypt or decrypt the ChatGPT tokens")
    try:
        return ctypes.string_at(out.data, out.size)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree(ctypes.cast(out.data, ctypes.c_void_p))


def _write(path: Path, data: bytes) -> None:
    """All at once (a half-written file is never read back)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    if sys.platform != "win32":
        os.chmod(part, 0o600)
    part.replace(path)


class Account:
    """The connection's files in <app_dir>/chatgpt: account.json (this installation's id, the
    client id OpenAI issued, the email, whether the plan may be used: no secrets) and tokens.bin
    (the tokens, encrypted)."""

    def __init__(self, folder: Path, protect=_protect, unprotect=_unprotect):
        self.folder = Path(folder)
        self._protect, self._unprotect = protect, unprotect

    @classmethod
    def of(cls, cfg: Config) -> "Account":
        return cls(cfg.app_dir / FOLDER)

    @property
    def _info_path(self) -> Path:
        return self.folder / "account.json"

    @property
    def _tokens_path(self) -> Path:
        return self.folder / "tokens.bin"

    def info(self) -> dict:
        try:
            return json.loads(self._info_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def update(self, **changes) -> dict:
        info = {**self.info(), **changes}
        _write(self._info_path, json.dumps(info, indent=2).encode("utf-8"))
        return info

    def host_id(self) -> str:
        """This installation's id for OpenAI (made once; not a secret, never the user's)."""
        host = self.info().get("host_id")
        if not host:
            host = f"urn:uuid:{uuid.uuid4()}"
            self.update(host_id=host)
        return host

    def tokens(self) -> dict | None:
        try:
            return json.loads(self._unprotect(self._tokens_path.read_bytes()))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            log.warning("Couldn't read the ChatGPT tokens: connect again in Settings")
            return None

    def save_tokens(self, tokens: dict) -> None:
        _write(self._tokens_path, self._protect(json.dumps(tokens).encode("utf-8")))
        self.update(connected=True, plan_usage=PLAN_SCOPE in tokens.get("scopes", []))

    def clear_tokens(self) -> None:
        """Signed out: the tokens go; this installation's id and its client id stay, for
        connecting again."""
        self._tokens_path.unlink(missing_ok=True)
        if self._info_path.exists():
            self.update(connected=False, plan_usage=False)

    @property
    def connected(self) -> bool:
        return bool(self.info().get("connected")) and self._tokens_path.exists()

    @property
    def plan_usage(self) -> bool:
        return self.connected and bool(self.info().get("plan_usage"))


# ----- the ID token (RS256, checked with OpenAI's published keys) -----

_SHA256_INFO = bytes.fromhex("3031300d060960864801650304020105000420")  # DER DigestInfo


def _b64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def rs256_valid(message: bytes, signature: bytes, key: dict) -> bool:
    """An RSA PKCS#1 v1.5 signature over SHA-256 (what RS256 is), checked with a JWK's n and e."""
    n = int.from_bytes(_b64(key["n"]), "big")
    e = int.from_bytes(_b64(key["e"]), "big")
    size = (n.bit_length() + 7) // 8
    if len(signature) != size:
        return False
    found = pow(int.from_bytes(signature, "big"), e, n).to_bytes(size, "big")
    digest = _SHA256_INFO + hashlib.sha256(message).digest()
    expected = b"\x00\x01" + b"\xff" * (size - 3 - len(digest)) + b"\x00" + digest
    return hmac.compare_digest(found, expected)


def verify_id_token(token: str, client_id: str, nonce: str, keys: list[dict], now=None) -> dict:
    """The ID token's claims, once its signature, issuer, audience, expiry and nonce check out.
    Raises SignInError."""
    try:
        head, body, signature = token.split(".")
        header, claims = json.loads(_b64(head)), json.loads(_b64(body))
        signature_bytes = _b64(signature)
    except ValueError as e:
        raise SignInError("OpenAI's answer couldn't be read. Try again.") from e
    if header.get("alg") != "RS256":
        raise SignInError("OpenAI's answer wasn't signed as expected.")
    rsa = [k for k in keys if k.get("kty") == "RSA"]
    key = next((k for k in rsa if k.get("kid") == header.get("kid")), None)
    if key is None and len(rsa) == 1 and not header.get("kid"):
        key = rsa[0]
    if key is None or not rs256_valid(f"{head}.{body}".encode("ascii"), signature_bytes, key):
        raise SignInError("OpenAI's answer wasn't signed as expected.")
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    now = time.time() if now is None else now
    if claims.get("iss") != ISSUER or client_id not in audiences:
        raise SignInError("OpenAI's answer wasn't meant for Abdoh.")
    if float(claims.get("exp") or 0) < now - 60:
        raise SignInError("OpenAI's answer was out of date. Try again.")
    if not hmac.compare_digest(str(claims.get("nonce") or ""), nonce):
        raise SignInError("OpenAI's answer didn't match this sign-in. Try again.")
    return claims


# ----- signing in -----


def _http():
    import httpx

    return httpx.Client(timeout=TIMEOUT_SECONDS)


def _error_code(response) -> str:
    try:
        data = response.json()
    except ValueError:
        return ""
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return str(error.get("code") or error.get("type") or "")
    return str(error or "")


def _token_record(answer: dict, now: float, old: dict | None = None) -> dict:
    """What a token response becomes on disk: the access token, its expiry, the rotating refresh
    token and the granted scopes, all replaced together."""
    old = old or {}
    scope = answer.get("scope")
    scopes = scope.split() if isinstance(scope, str) else scope or old.get("scopes", [])
    return {
        "access_token": answer["access_token"],
        "refresh_token": answer.get("refresh_token") or old.get("refresh_token", ""),
        "id_token": answer.get("id_token") or old.get("id_token", ""),
        "token_type": answer.get("token_type", "Bearer"),
        "expires_at": now + float(answer.get("expires_in") or 3600),
        "scopes": sorted(scopes),
        "saved_at": now,
    }


class SignIn:
    """One "Continue with ChatGPT": OpenAI's page in the browser, which comes back to a page
    Abdoh serves on 127.0.0.1 until it's done (or SIGN_IN_SECONDS pass). `state` is
    "waiting", "done" or "failed" (then `error` says why)."""

    def __init__(self, account: Account, http=None, open_browser=webbrowser.open, clock=time.time):
        self.account = account
        self._http = http
        self._open = open_browser
        self._clock = clock
        self.state = "waiting"
        self.error = ""
        self.url = ""
        self.plan_usage = False
        self.first = False  # the first time this account was connected here
        self._state = secrets.token_urlsafe(32)
        self._nonce = secrets.token_urlsafe(32)
        self._verifier = secrets.token_urlsafe(64)
        self._server = None
        self._lock = threading.Lock()
        self.redirect_uri = ""

    def authorize_url(self, port: int) -> str:
        info = self.account.info()
        client = info.get("client_id") or FIRST_CLIENT
        self.redirect_uri = f"http://127.0.0.1:{port}{CALLBACK_PATH}"
        challenge = _b64url(hashlib.sha256(self._verifier.encode("ascii")).digest())
        params = {"client_id": client}
        if client == FIRST_CLIENT:
            params["agent_name_hint"] = APP_NAME
        params["ext_agent_host_id"] = self.account.host_id()
        if info.get("email"):
            params["login_hint"] = info["email"]
        params.update(
            response_type="code",
            redirect_uri=self.redirect_uri,
            scope=SCOPES,
            resource=API,
            state=self._state,
            nonce=self._nonce,
            code_challenge_method="S256",
            code_challenge=challenge,
        )
        return f"{AUTHORIZE_URL}?{urlencode(params)}"

    def start(self) -> str:
        """Serve the callback page, then open OpenAI's page in the browser. Returns its link
        (in case the browser didn't open)."""
        self._server = _callback_server(self)
        port = self._server.server_address[1]
        self.url = self.authorize_url(port)
        threading.Thread(
            target=self._server.serve_forever, name="abdoh-chatgpt", daemon=True
        ).start()
        timer = threading.Timer(SIGN_IN_SECONDS, self._give_up)
        timer.daemon = True
        timer.start()
        try:
            self._open(self.url)
        except Exception:
            log.info("Couldn't open the browser for the ChatGPT sign-in", exc_info=True)
        log.info("Signing in with ChatGPT in the browser (the page comes back to port %d)", port)
        return self.url

    def _give_up(self) -> None:
        with self._lock:
            if self.state == "waiting":
                self.state, self.error = "failed", "The sign-in took too long. Try again."
        self.stop()

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            threading.Thread(target=lambda: (server.shutdown(), server.server_close()),
                             daemon=True).start()  # fmt: skip

    def callback(self, path: str) -> tuple[int, str]:
        """The browser came back (`path` with its query). Returns the HTTP status and the
        words for the page."""
        url = urlparse(path)
        if url.path != CALLBACK_PATH:
            return 404, "Not found."
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if not hmac.compare_digest(query.get("state", ""), self._state):
            return 400, "This sign-in is out of date. Start again from Abdoh's Settings."
        with self._lock:
            if self.state != "waiting":
                return 400, "This sign-in is over. Start again from Abdoh's Settings."
            try:
                self._finish(query)
                self.state = "done"
            except SignInError as e:
                self.state, self.error = "failed", str(e)
        self.stop()
        if self.state == "done":
            return 200, "Abdoh is connected to ChatGPT. You can close this tab."
        return 400, f"{self.error} You can close this tab."

    def _finish(self, query: dict) -> None:
        if query.get("error") == "access_denied":
            raise SignInError("You didn't allow Abdoh to use ChatGPT.")
        if query.get("error"):
            log.info("The ChatGPT sign-in failed: %s", query.get("error"))
            raise SignInError("The ChatGPT sign-in didn't work. Try again.")
        code = query.get("code")
        if not code:
            raise SignInError("The ChatGPT sign-in didn't work. Try again.")
        known = self.account.info().get("client_id")
        issued = query.get("client_id") or known
        if not issued:
            raise SignInError("OpenAI didn't finish registering Abdoh. Try again.")
        if known and issued != known:
            raise SignInError("OpenAI answered for another app. Try again.")
        answer = self._post(
            TOKEN_URL,
            grant_type="authorization_code",
            client_id=issued,
            code=code,
            code_verifier=self._verifier,
            redirect_uri=self.redirect_uri,
            resource=API,
        )
        claims = verify_id_token(answer.get("id_token", ""), issued, self._nonce, self._keys())
        if not claims.get("sub") or not answer.get("access_token"):
            raise SignInError("OpenAI's answer couldn't be read. Try again.")
        tokens = _token_record(answer, self._clock())
        self.plan_usage = PLAN_SCOPE in tokens["scopes"]
        self.first = not known
        self.account.update(client_id=issued, email=claims.get("email", ""), subject=claims["sub"])
        self.account.save_tokens(tokens)
        log.info(
            "Connected ChatGPT (plan usage %s)", "allowed" if self.plan_usage else "not allowed"
        )

    def _client(self):
        if self._http is None:
            self._http = _http()
        return self._http

    def _post(self, url: str, **form) -> dict:
        try:
            r = self._client().post(url, data=form)
        except Exception as e:
            raise SignInError("I couldn't reach OpenAI. Check the internet and try again.") from e
        if r.status_code != 200:
            log.info("OpenAI's token endpoint said %s (%s)", r.status_code, _error_code(r))
            raise SignInError("OpenAI didn't accept the sign-in. Try again.")
        try:
            answer = r.json()
        except ValueError as e:
            raise SignInError("OpenAI's answer couldn't be read. Try again.") from e
        if not isinstance(answer, dict):
            raise SignInError("OpenAI's answer couldn't be read. Try again.")
        return answer

    def _keys(self) -> list[dict]:
        try:
            r = self._client().get(JWKS_URL)
            return r.json().get("keys") or []
        except Exception as e:
            raise SignInError("I couldn't reach OpenAI. Check the internet and try again.") from e


def _callback_server(sign_in: SignIn) -> HTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - the standard library's name
            status, words = sign_in.callback(self.path)
            page = (
                "<!doctype html><meta charset='utf-8'><title>Abdoh</title>"
                "<body style='font-family:system-ui;margin:3em'>"
                f"<h2>Abdoh</h2><p>{_escape(words)}</p></body>"
            ).encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, format, *args) -> None:  # noqa: A002
            pass  # the request line has the sign-in code in it: never logged

    try:
        return HTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        return HTTPServer(("127.0.0.1", 0), Handler)  # 1455 is taken: any free port


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ----- the session: fresh tokens, the models, signing out -----

_REFRESH = threading.Lock()  # one refresh at a time: the refresh token changes with each


class Session:
    def __init__(self, account: Account, http=None, clock=time.time):
        self.account = account
        self._http = http
        self._clock = clock

    def _client(self):
        if self._http is None:
            self._http = _http()
        return self._http

    def access_token(self, force: bool = False) -> str:
        """A token that's good for a while (refreshed first if it's nearly out, or `force`).
        Raises BrainError (SIGNED_OUT when connecting again is needed)."""
        with _REFRESH:
            tokens = self.account.tokens()
            if not tokens:
                raise BrainError(SIGNED_OUT)
            if force or tokens["expires_at"] - self._clock() < REFRESH_EARLY_SECONDS:
                tokens = self._refresh(tokens)
            return tokens["access_token"]

    def _refresh(self, tokens: dict) -> dict:
        client_id = self.account.info().get("client_id", "")
        form = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": tokens.get("refresh_token", ""),
            "resource": API,
        }
        try:
            r = self._client().post(TOKEN_URL, data=form)
        except Exception as e:
            raise BrainError(UNREACHABLE) from e
        if r.status_code == 200:
            try:
                fresh = _token_record(r.json(), self._clock(), tokens)
            except (ValueError, KeyError, TypeError, AttributeError) as e:
                raise BrainError(UNREACHABLE) from e
            self.account.save_tokens(fresh)
            return fresh
        code = _error_code(r)
        log.warning("Refreshing the ChatGPT tokens failed: %s %s", r.status_code, code)
        if code in SIGNED_OUT_CODES or r.status_code in (400, 401):
            self.account.clear_tokens()
            raise BrainError(SIGNED_OUT)
        raise BrainError(UNREACHABLE)

    def models(self) -> list[dict]:
        """The models this connection may use, in OpenAI's order: [{"id", "name"}]."""
        for attempt in (1, 2):
            token = self.access_token(force=attempt == 2)
            try:
                r = self._client().get(
                    f"{API}/models", headers={"Authorization": f"Bearer {token}"}
                )
            except Exception as e:
                raise BrainError(UNREACHABLE) from e
            if r.status_code == 401 and attempt == 1:
                continue
            if r.status_code != 200:
                raise BrainError(problem(r.status_code, _body(r)))
            found = r.json().get("models") or []
            return [
                {"id": m["slug"], "name": m.get("display_name") or m["slug"]}
                for m in found
                if m.get("slug") and m.get("visibility", "list") == "list"
            ]
        raise BrainError(SIGNED_OUT)

    def sign_out(self) -> bool:
        """Revoke the session at OpenAI and forget the tokens here. False if OpenAI didn't
        confirm it (the tokens are forgotten anyway)."""
        tokens = self.account.tokens() or {}
        confirmed = False
        if tokens.get("refresh_token"):
            form = {
                "token": tokens["refresh_token"],
                "token_type_hint": "refresh_token",
                "client_id": self.account.info().get("client_id", ""),
            }
            try:
                confirmed = self._client().post(REVOKE_URL, data=form).status_code == 200
            except Exception:
                log.info("Couldn't reach OpenAI to revoke the ChatGPT session", exc_info=True)
        self.account.clear_tokens()
        log.info("Disconnected ChatGPT%s", "" if confirmed else " (OpenAI didn't confirm it)")
        return confirmed


def _body(response) -> dict:
    try:
        data = response.json()
    except ValueError:
        return {"detail": response.text[:300]}
    return data if isinstance(data, dict) else {}


def problem(status: int, body: dict, model: str = "") -> str:
    """What to say when ChatGPT says no (the details go to the log)."""
    error = body.get("error") if isinstance(body.get("error"), dict) else {}
    code = str(error.get("code") or "")
    detail = str(error.get("message") or body.get("detail") or "")[:300]
    log.error("ChatGPT said %s %s: %s", status or "error", code, detail)
    if code == "subscription_sharing_usage_limit_exceeded" or status == 429:
        return LIMIT
    if code == "subscription_sharing_user_not_eligible":
        return NOT_ELIGIBLE
    if code in ("subscription_sharing_usage_unavailable", "subscription_sharing_user_unavailable"):
        return BUSY
    if code == "subscription_sharing_unsupported_capability":
        if "image" in str(error.get("param") or "") + detail:
            return f"The ChatGPT model {model} can't look at pictures. Pick another in Settings."
        return "ChatGPT can't do that with your plan."
    if code == "subscription_sharing_invalid_user" or status == 401:
        return SIGNED_OUT
    if code.startswith("chatpass_v2") or status == 403:
        return "ChatGPT isn't available to Abdoh for this account right now."
    if status in (400, 404) and model and "model" in (detail + code).lower():
        return f"ChatGPT couldn't use the model {model}. Pick another in Settings."
    if status == 503:
        return BUSY
    return "ChatGPT couldn't answer right now."


# ----- the brain -----


class ChatGPTBrain(Brain):
    name = "ChatGPT"

    def __init__(self, cfg: Config, session: Session | None = None, http=None):
        self.cfg = cfg
        self.account = session.account if session is not None else Account.of(cfg)
        self.session = session or Session(self.account, http)
        self._http = http
        self._first_model = ""

    @property
    def model(self) -> str:
        chosen = self.cfg.claude.chatgpt_model.strip()
        if chosen:
            return chosen
        if not self._first_model:
            models = self.session.models()
            if not models:
                raise BrainError("Your ChatGPT plan has no models Abdoh can use.")
            self._first_model = models[0]["id"]
        return self._first_model

    def _client(self):
        if self._http is None:
            self._http = _http()
        return self._http

    def request(self, prompt: str, image_png: bytes | None = None) -> dict:
        from abdoh.about import about

        state = self.state_now()  # the mode that's on, the lamps, ... (abdoh.about.state_line)
        text = f"[Abdoh now: {state}]\n{prompt}" if state else prompt
        content: list[dict] = [{"type": "input_text", "text": text}]
        if image_png:
            data = base64.standard_b64encode(image_png).decode("ascii")
            content.append({"type": "input_image", "image_url": f"data:image/png;base64,{data}"})
        return {
            "model": self.model,
            "instructions": system_prompt(self.cfg, about=about(self.cfg, "chatgpt")),
            "input": [{"type": "message", "role": "user", "content": content}],
            "stream": True,
            "store": False,
        }

    def stream(self, prompt: str, image_png: bytes | None = None) -> Iterator[str]:
        import httpx

        if not self.account.plan_usage:
            raise BrainError(NO_PLAN_USAGE if self.account.connected else SIGNED_OUT)
        body = self.request(prompt, image_png)
        for attempt in (1, 2):
            token = self.session.access_token(force=attempt == 2)  # a 401: a fresh one, once
            headers = {"Authorization": f"Bearer {token}"}
            try:
                with self._client().stream(
                    "POST", f"{API}/responses", json=body, headers=headers
                ) as r:
                    if r.status_code == 401 and attempt == 1:
                        r.read()
                        continue
                    if r.status_code != 200:
                        r.read()
                        raise BrainError(problem(r.status_code, _body(r), body["model"]))
                    yield from self._events(r.iter_lines(), body["model"])
                    return
            except httpx.HTTPError as e:
                log.error("The ChatGPT request failed: %s", e)
                raise BrainError(UNREACHABLE) from e

    @staticmethod
    def _events(lines, model: str) -> Iterator[str]:
        """The text of a streamed response; an answer that doesn't end with
        response.completed ends with BrainError."""
        for line in lines:
            if not line.startswith("data:"):
                continue  # "event: ..." lines name what the data line says itself
            try:
                event = json.loads(line[5:].strip())
            except ValueError:
                continue
            kind = event.get("type", "")
            if kind == "response.output_text.delta":
                if event.get("delta"):
                    yield event["delta"]
            elif kind == "response.completed":
                return
            elif kind == "response.failed":
                error = (event.get("response") or {}).get("error") or {}
                raise BrainError(problem(0, {"error": error}, model))
            elif kind == "response.incomplete":
                reason = (event.get("response") or {}).get("incomplete_details") or {}
                log.warning("ChatGPT's answer was incomplete: %s", reason.get("reason", "?"))
                raise BrainError(INCOMPLETE)
            elif kind == "error":
                raise BrainError(problem(0, {"error": event.get("error") or event}, model))
        raise BrainError(CUT_OFF)

    def ai(self) -> str:
        return "ChatGPT"

    def status(self) -> str:
        chosen = self.cfg.claude.chatgpt_model.strip()
        return f"your plan ({chosen})" if chosen else "your plan"

    def close(self) -> None:
        if self._http is not None:
            self._http.close()


# ----- for the Settings card -----


def connected(cfg: Config) -> bool:
    """Connected, and allowed to use the plan (for Automatic)."""
    return Account.of(cfg).plan_usage


def state(cfg: Config) -> dict:
    """What the Settings card shows (no secrets)."""
    account = Account.of(cfg)
    info = account.info()
    return {
        "connected": account.connected,
        "email": info.get("email", "") if account.connected else "",
        "plan_usage": account.plan_usage,
        "model": cfg.claude.chatgpt_model,
    }


def models(cfg: Config, session: Session | None = None) -> dict:
    try:
        found = (session or Session(Account.of(cfg))).models()
    except BrainError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "models": found, "chosen": cfg.claude.chatgpt_model}


_sign_in: dict[str, SignIn | None] = {"now": None}


def connect(cfg: Config, open_browser: Callable[[str], object] = webbrowser.open) -> dict:
    """Start "Continue with ChatGPT" (one at a time). Returns the link to OpenAI's page."""
    old = _sign_in["now"]
    if old is not None:
        old.stop()
    sign_in = SignIn(Account.of(cfg), open_browser=open_browser)
    try:
        url = sign_in.start()
    except OSError as e:
        log.warning("Couldn't start the ChatGPT sign-in: %s", e)
        return {"ok": False, "error": "Abdoh couldn't start the sign-in. Try again."}
    _sign_in["now"] = sign_in
    return {"ok": True, "url": url}


def progress() -> dict:
    """How the sign-in started last goes: "none", "waiting", "done" or "failed"."""
    sign_in = _sign_in["now"]
    if sign_in is None:
        return {"state": "none"}
    return {
        "state": sign_in.state,
        "error": sign_in.error,
        "plan_usage": sign_in.plan_usage,
        "first": sign_in.first,
    }


def disconnect(cfg: Config) -> dict:
    confirmed = Session(Account.of(cfg)).sign_out()
    return {"ok": True, "revoked": confirmed}
