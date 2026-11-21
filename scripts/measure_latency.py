"""Developer tool: how long Krekos takes to start answering, end to end, without a mic or speakers.

Speaks a request into a WAV with the system voice, plays it into the real pipeline at real-time
speed (VAD, Whisper, your commands, Claude if it goes there), and reports the time from the end
of the speech until Krekos starts its reply. The wake word engine is skipped (it fires within a
frame of hearing the word), and speaking is replaced by a stopwatch.

Requests really run (apps open, media keys are pressed), so measure questions and harmless
commands like the time.

Usage: python scripts/measure_latency.py ["Hey Krekos, what time is it?" ...]
"""

import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from check_wakeword import read_wav_16k, speak_to_wav  # noqa: E402

from abdoh.audio.wakeword import WakeWordEngine  # noqa: E402
from abdoh.config import load_config  # noqa: E402
from abdoh.daemon import Daemon  # noqa: E402
from abdoh.speech.tts import Speaker  # noqa: E402

BLOCK = 1600  # 100 ms


class PacedMic:
    """Plays audio blocks at real-time speed, like a microphone, then silence."""

    def __init__(self, audio: np.ndarray):
        self.blocks = [audio[i : i + BLOCK].tobytes() for i in range(0, len(audio), BLOCK)]
        self.t0 = None
        self.read_count = 0
        self.history: list[bytes] = []

    def start(self):
        pass

    def read(self) -> bytes:
        if self.t0 is None:
            self.t0 = time.perf_counter()
        due = self.t0 + self.read_count * 0.1
        time.sleep(max(0.0, due - time.perf_counter()))
        block = (
            self.blocks[self.read_count] if self.read_count < len(self.blocks) else bytes(BLOCK * 2)
        )
        self.read_count += 1
        self.history.append(block)
        return block

    def recent(self) -> bytes:
        return b"".join(self.history[-30:])

    def clear(self) -> None:
        self.history.clear()

    def stop(self):
        pass


class WakeAt(WakeWordEngine):
    """Fires once at a given block (where the wake word ends)."""

    def __init__(self, block: int):
        self.block, self.count = block, 0

    def detect(self, data: bytes) -> bool:
        self.count += 1
        return self.count == self.block


class Stopwatch(Speaker):
    def __init__(self):
        self.first: float | None = None
        self.said: list[str] = []
        self.done = threading.Event()

    def say(self, text: str) -> None:
        if self.first is None:
            self.first = time.perf_counter()
        self.said.append(text)
        self.done.set()


def measure(daemon_parts, text: str) -> None:
    cfg, router, transcriber, vad = daemon_parts
    with tempfile.TemporaryDirectory() as tmp:
        speech = read_wav_16k(speak_to_wav(text, Path(tmp) / "request.wav"))
    voiced = np.flatnonzero(np.abs(speech.astype(np.int32)) > 500)
    speech = speech[: voiced[-1] + 1]  # trim the voice's own trailing silence
    lead = np.zeros(8000, dtype=np.int16)  # 0.5 s before speaking
    audio = np.concatenate([lead, speech, np.zeros(16000 * 5, dtype=np.int16)])
    speech_end = (len(lead) + len(speech)) / 16000
    mic = PacedMic(audio)
    speaker = Stopwatch()
    wake_block = int((len(lead) + len(speech) * 0.4) / BLOCK)  # roughly after "Hey Krekos"
    daemon = Daemon(cfg, router, speaker, lambda: mic, WakeAt(wake_block), transcriber, vad=vad)
    thread = threading.Thread(target=daemon.run, daemon=True)
    thread.start()
    speaker.done.wait(60)
    daemon.stop()
    if speaker.first is None:
        print(f"{text!r}: no reply")
        return
    waited = speaker.first - (mic.t0 + speech_end)
    print(
        f"{text!r}\n  -> {speaker.said[0]!r}\n  reply started {waited:.2f} s after the speech ended"
    )


def main() -> int:
    from abdoh.audio.stt import load_transcriber
    from abdoh.audio.vad import load_vad
    from abdoh.claude.brain import make_brain
    from abdoh.commands.registry import CommandRegistry
    from abdoh.computer import Computer
    from abdoh.router import Router

    cfg = load_config()
    transcriber = load_transcriber(cfg)
    transcriber.transcribe(b"\0\0" * 1600)
    router = Router(cfg, CommandRegistry(cfg.commands_path), brain=make_brain(cfg))
    router.computer = Computer()
    requests = sys.argv[1:] or ["Hey Krekos, what time is it?"]
    for text in requests:
        measure((cfg, router, transcriber, load_vad()), text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
