"""What Abdoh heard after its wake word but couldn't make out (the keep_unclear_clips switch).

Only while the switch is on, only those recordings, and each one for a day: they show why no
words came out (a quiet microphone, another language, the start cut off). They stay in
<app_dir>/voice and are never sent anywhere. "Forget my voice" deletes them with the rest.
"""

import logging
import time
import wave
from pathlib import Path

from abdoh.audio.mic import SAMPLE_RATE

log = logging.getLogger(__name__)

KEEP_SECONDS = 24 * 3600
PATTERN = "unclear-*.wav"


def clips(folder: Path) -> list[Path]:
    folder = Path(folder)
    return sorted(folder.glob(PATTERN)) if folder.exists() else []


def save_clip(folder: Path, audio: bytes, now: float | None = None) -> Path:
    """Save one recording (16 kHz mono int16) as unclear-<date>-<time>.wav."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    path, n = folder / f"unclear-{stamp}.wav", 2
    while path.exists():
        path, n = folder / f"unclear-{stamp}-{n}.wav", n + 1
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(audio)
    return path


def prune(folder: Path, now: float | None = None, keep_seconds: float = KEEP_SECONDS) -> int:
    """Delete the clips older than a day. Returns how many went."""
    now = time.time() if now is None else now
    gone = 0
    for path in clips(folder):
        try:
            if now - path.stat().st_mtime > keep_seconds:
                path.unlink()
                gone += 1
        except OSError:
            log.debug("Couldn't delete %s", path, exc_info=True)
    return gone


def delete_all(folder: Path) -> int:
    """Delete every clip (the switch was turned off)."""
    return prune(folder, keep_seconds=-1)
