"""Capture the primary monitor as a downscaled PNG."""

import io
import logging
import sys

from PIL import Image

log = logging.getLogger(__name__)

MAX_SIDE = 1600


class ScreenCaptureError(RuntimeError):
    """The screen could not be captured; the message is safe to speak."""


def downscale(img: Image.Image, max_side: int = MAX_SIDE) -> Image.Image:
    """Shrink so the long side is at most max_side (never enlarges)."""
    scale = max_side / max(img.size)
    if scale >= 1:
        return img
    return img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)


def is_all_black(img: Image.Image) -> bool:
    return img.convert("L").getextrema()[1] < 10


def to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def grab_primary() -> Image.Image:
    import mss

    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[1])  # monitors[0] is all screens combined
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def capture_screen(grab=grab_primary) -> bytes:
    """Screenshot of the primary monitor as PNG bytes, long side <= 1600 px."""
    try:
        img = grab()
    except Exception as e:
        log.exception("Screen capture failed")
        raise ScreenCaptureError("I couldn't capture your screen.") from e
    if is_all_black(img):
        hint = (
            " On a Mac, give Screen Recording permission to Terminal or Python in System Settings."
            if sys.platform == "darwin"
            else ""
        )
        raise ScreenCaptureError("Your screenshot came out completely black." + hint)
    return to_png(downscale(img))
