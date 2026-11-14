"""Record until silence. Speech is detected by the VAD, or by loudness (RMS) as a fallback."""

from collections.abc import Callable

import numpy as np

from abdoh.audio.mic import BYTES_PER_SECOND

MIN_THRESHOLD = 300.0
MAX_THRESHOLD = 1500.0


def rms(block: bytes) -> float:
    samples = np.frombuffer(block, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(samples**2))) if samples.size else 0.0


def estimate_threshold(audio: bytes, block_bytes: int = 3200) -> float:
    """Speech threshold from recent audio: a few times the background noise level."""
    blocks = [audio[i : i + block_bytes] for i in range(0, len(audio), block_bytes)]
    levels = [rms(b) for b in blocks if b]
    if not levels:
        return MIN_THRESHOLD
    noise_floor = float(np.percentile(levels, 20))
    return min(MAX_THRESHOLD, max(MIN_THRESHOLD, noise_floor * 3))


def energy_detector(threshold: float) -> Callable[[bytes], bool]:
    """Fallback speech detector: a block is speech if it's louder than threshold."""
    return lambda block: rms(block) >= threshold


def record_until_silence(
    read: Callable[[], bytes],
    is_speech: Callable[[bytes], bool],
    silence_seconds: float = 1.0,
    max_seconds: float = 10.0,
    wait_seconds: float | None = None,
) -> bytes:
    """Read blocks until `silence_seconds` of quiet after speech, or `max_seconds` total.

    Before any speech is heard, recording stops after `wait_seconds` of quiet
    (defaults to `silence_seconds`). Returns b"" if no speech was heard at all.
    """
    wait_seconds = silence_seconds if wait_seconds is None else wait_seconds
    # Count bytes rather than seconds to avoid float drift.
    max_bytes = round(max_seconds * BYTES_PER_SECOND)
    silence_bytes = round(silence_seconds * BYTES_PER_SECOND)
    wait_bytes = round(wait_seconds * BYTES_PER_SECOND)
    chunks: list[bytes] = []
    total = quiet = 0
    heard_speech = False
    while total < max_bytes:
        block = read()
        chunks.append(block)
        total += len(block)
        if is_speech(block):
            heard_speech = True
            quiet = 0
        else:
            quiet += len(block)
        if quiet >= (silence_bytes if heard_speech else wait_bytes):
            break
    return b"".join(chunks) if heard_speech else b""
