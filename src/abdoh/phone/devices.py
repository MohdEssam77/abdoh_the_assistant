"""The phones that may use Abdoh, and the one-time codes that pair a new one.

A paired phone has its own key (256 random bits). Only the key's SHA-256 is kept, in
phones.json; the phone keeps the key itself. A pairing code works once, for 30 minutes, and is
only kept in memory: a restart makes it invalid.

The code is short enough to type ("K7MX-2Q9P": 8 of 31 letters and digits that can't be mixed
up, about 40 bits), for a phone whose home-screen app opened without it: after 10 wrong tries
it stops working, so guessing it is hopeless.
"""

import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from pathlib import Path

from abdoh.config import write_atomic

log = logging.getLogger(__name__)

FILE = "phones.json"
CODE_SECONDS = 30 * 60
CODE_LETTERS = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # no 0/O, 1/I/L
WRONG_CODES = 10  # this many wrong codes and the current one stops working
SEEN_EVERY = 60.0  # "last used" is written at most this often (seconds)
MAX_PHONES = 20
NAME_LENGTH = 40


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def make_code(choice=secrets.choice) -> str:
    """A new pairing code: "K7MX-2Q9P"."""
    letters = "".join(choice(CODE_LETTERS) for _ in range(8))
    return f"{letters[:4]}-{letters[4:]}"


def clean_code(code: str) -> str:
    """A code as typed ("k7mx 2q9p", "K7MX2Q9P") in its own form ("K7MX-2Q9P")."""
    letters = "".join(ch for ch in str(code or "").upper() if ch.isalnum())
    return f"{letters[:4]}-{letters[4:]}" if len(letters) == 8 else letters


def phone_name(user_agent: str) -> str:
    """A name for a phone from its browser: "iPhone", "iPad", "Android phone", "Phone"."""
    agent = user_agent or ""
    for word, name in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android phone")):
        if word in agent:
            return name
    return "Phone"


class Phones:
    """The paired phones (phones.json in Abdoh's folder) and the current pairing code."""

    def __init__(self, path: Path, clock=time.time, token=secrets.token_urlsafe, code=make_code):
        self.path = Path(path)
        self._clock = clock
        self._token = token
        self._make_code = code
        self._lock = threading.Lock()
        self._code: tuple[str, float] | None = None  # (code, made at)
        self._wrong = 0
        self._phones = self._read()
        self._written_seen: dict[str, float] = {}

    def _read(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError):
            log.warning("Couldn't read %s; no phones are paired", self.path, exc_info=True)
            return []
        phones = data.get("phones") if isinstance(data, dict) else None
        if not isinstance(phones, list):
            return []
        keep = ("id", "name", "key_hash", "added", "seen")
        return [
            {k: p.get(k) for k in keep}
            for p in phones
            if isinstance(p, dict) and isinstance(p.get("key_hash"), str) and p.get("id")
        ]

    def _write(self) -> None:
        write_atomic(self.path, json.dumps({"phones": self._phones}, indent=2) + "\n")

    # ----- pairing -----

    def new_code(self) -> str:
        """A new pairing code (the one before stops working)."""
        with self._lock:
            self._code = (self._make_code(), self._clock())
            self._wrong = 0
            return self._code[0]

    def code_left(self) -> float:
        """Seconds the current code still works (0: none)."""
        with self._lock:
            if self._code is None:
                return 0.0
            return max(0.0, CODE_SECONDS - (self._clock() - self._code[1]))

    def pair(self, code: str, name: str = "Phone") -> str | None:
        """The new phone's key, or None if the code isn't (or no longer) valid."""
        with self._lock:
            current = self._code
            if current is None or self._clock() - current[1] > CODE_SECONDS:
                return None
            if not isinstance(code, str) or not hmac.compare_digest(clean_code(code), current[0]):
                self._wrong += 1
                if self._wrong >= WRONG_CODES:
                    log.warning("Too many wrong pairing codes: the code no longer works")
                    self._code = None
                return None
            self._code = None  # once
            key = self._token(32)
            now = self._clock()
            clean = " ".join(str(name or "Phone").split())[:NAME_LENGTH] or "Phone"
            self._phones.append(
                {"id": self._token(6), "name": clean, "key_hash": _digest(key),
                 "added": now, "seen": now}
            )  # fmt: skip
            self._phones = self._phones[-MAX_PHONES:]
            self._write()
            log.info("Paired a phone (%s)", clean)
            return key

    # ----- checking -----

    def check(self, key: str | None) -> dict | None:
        """The phone with this key (and it was seen now), or None."""
        if not key or not isinstance(key, str):
            return None
        digest = _digest(key)
        with self._lock:
            for phone in self._phones:
                if hmac.compare_digest(phone["key_hash"], digest):
                    now = self._clock()
                    phone["seen"] = now
                    if now - self._written_seen.get(phone["id"], float("-inf")) >= SEEN_EVERY:
                        self._written_seen[phone["id"]] = now
                        try:
                            self._write()
                        except OSError:
                            log.debug("Couldn't note when the phone was used", exc_info=True)
                    return {k: phone[k] for k in ("id", "name", "added", "seen")}
        return None

    def list(self) -> list[dict]:
        """The paired phones, newest first, without their keys."""
        with self._lock:
            phones = [{k: p[k] for k in ("id", "name", "added", "seen")} for p in self._phones]
        return sorted(phones, key=lambda p: p.get("added") or 0, reverse=True)

    def remove(self, phone_id: str) -> bool:
        with self._lock:
            kept = [p for p in self._phones if p["id"] != phone_id]
            if len(kept) == len(self._phones):
                return False
            self._phones = kept
            self._write()
            log.info("Removed a paired phone")
            return True
