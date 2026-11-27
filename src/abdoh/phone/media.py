"""Pictures and files for the phone, behind secret links (ABDOH_EPIC_11.md, 2.3).

The phone shows a picture with <img> and opens a file in its own viewer: neither can send the
phone's key, so each one gets a link with a secret in it instead, `/media/<32 hex characters>`
(128 bits, as strong as the key), valid for an hour and only reachable inside the owner's
tailnet. Pictures are kept in memory (a few dozen at most); files stay where they are and are
sent from disk, a piece at a time.
"""

import io
import logging
import mimetypes
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

KEEP_SECONDS = 3600.0
MAX_PICTURES = 40
MAX_PICTURE_BYTES = 8_000_000
SCREEN_SIDE = 1600  # a screenshot's long side, in pixels, at most
SCREEN_QUALITY = 80
# Opened in the phone's own viewer: what a phone shows safely by itself. Anything else (a web
# page, an SVG, a program) is only downloaded, never opened as a page of this site.
SHOWN = frozenset(
    {"image/jpeg", "image/png", "image/gif", "image/webp", "image/heic", "application/pdf",
     "text/plain", "video/mp4", "video/quicktime", "audio/mpeg", "audio/mp4", "audio/wav"}
)  # fmt: skip
KINDS = {"image": "image", "video": "video", "audio": "audio", "application/pdf": "pdf",
         "text": "text"}  # fmt: skip


@dataclass
class Media:
    type: str  # its MIME type
    name: str = ""  # a file's name
    data: bytes | None = None  # a picture
    path: Path | None = None  # a file on disk
    size: int = 0
    at: float = 0.0


def file_type(name: str) -> str:
    kind, _ = mimetypes.guess_type(name)
    if kind is None and name.lower().endswith(".heic"):
        return "image/heic"
    return kind or "application/octet-stream"


def file_kind(kind: str) -> str:
    """What the phone's card shows: image, video, audio, pdf, text, or file."""
    if kind in KINDS:
        return KINDS[kind]
    return KINDS.get(kind.split("/")[0], "file")


class MediaStore:
    def __init__(self, clock=time.monotonic, keep: float = KEEP_SECONDS):
        self._clock = clock
        self._keep = keep
        self._items: OrderedDict[str, Media] = OrderedDict()
        self._lock = threading.Lock()

    def add_picture(self, data: bytes, kind: str = "image/jpeg") -> str:
        if not data or len(data) > MAX_PICTURE_BYTES:
            raise ValueError("no picture, or too big")
        return self._add(Media(kind, data=bytes(data), size=len(data)))

    def add_file(self, path: Path) -> str:
        path = Path(path)
        size = path.stat().st_size
        return self._add(Media(file_type(path.name), name=path.name, path=path, size=size))

    def _add(self, media: Media) -> str:
        key = secrets.token_hex(16)
        media.at = self._clock()
        with self._lock:
            self._forget_old()
            self._items[key] = media
            pictures = [k for k, m in self._items.items() if m.data is not None]
            for old in pictures[: max(0, len(pictures) - MAX_PICTURES)]:
                del self._items[old]
        return key

    def get(self, key: str) -> Media | None:
        with self._lock:
            self._forget_old()
            return self._items.get(str(key or ""))

    def _forget_old(self) -> None:
        now = self._clock()
        for key in [k for k, m in self._items.items() if now - m.at > self._keep]:
            del self._items[key]


def screen_picture(grab=None, which: str = "active") -> bytes:
    """The screen you're using (or all of them) as a JPEG for the phone. Raises
    ScreenCaptureError (its message is for people) when it can't."""
    from PIL import Image

    from abdoh.claude.screen import ScreenCaptureError, is_all_black

    if grab is None:
        from abdoh.claude.screen import grab
    try:
        image = grab(which)
    except Exception as e:
        log.exception("Couldn't take a picture of the screen for the phone")
        raise ScreenCaptureError("I couldn't take a picture of the screen.") from e
    if is_all_black(image):
        raise ScreenCaptureError("The screen is off or locked, so its picture is all black.")
    image = image.convert("RGB")
    if max(image.size) > SCREEN_SIDE:
        image.thumbnail((SCREEN_SIDE, SCREEN_SIDE), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=SCREEN_QUALITY, optimize=True)
    return out.getvalue()
