"""How well Abdoh hears you over its own voice, measured in your room. MAKES SOUND.

Abdoh says two sentences with your Windows voice at the current volume, while it records the
microphone and what the speakers play. Then it prints:
  - how loud Abdoh's own voice is at the microphone,
  - the delay between the speakers and the microphone,
  - how much quieter the echo canceller makes Abdoh's voice, second by second,
  - how often each sensitivity would wrongly think you were talking (should be 0).
With --talk, Abdoh talks longer and asks you to talk over it; it prints when it heard you and
what you said.

Nothing is saved or sent. Usage: python scripts/echo_check.py [--talk]
"""

import sys
import threading
import time

import numpy as np

from abdoh.audio.bargein import SENSITIVITY, VoiceWatch
from abdoh.audio.echo import EchoCanceller, echo_available
from abdoh.audio.loopback import SpeakerTap
from abdoh.audio.mic import BYTES_PER_SECOND, Microphone
from abdoh.audio.vad import SileroVad
from abdoh.config import load_config
from abdoh.speech.tts import make_speaker

SENTENCES = (
    "This is Abdoh, checking how well I can hear you while I talk. "
    "Please stay quiet for a few seconds while I measure the room.",
    "Every word I say comes out of the speakers and back into the microphone, and I try to "
    "take it back out again.",
)
TALK = (
    "Now please talk over me. Say anything you like, for example, what is the weather "
    "tomorrow. I will keep talking for a while so that you have time to start. The quick brown "
    "fox jumps over the lazy dog, and then it runs off into the woods to find its friends."
)


class Recorder:
    """Records each microphone block with the speakers' audio a VoiceWatch would pair it with."""

    def __init__(self, tap):
        self.tap = tap
        self.pairs: list[tuple[bytes, bytes]] = []

    def window(self, end_time, samples):
        reference = self.tap.window(end_time, samples)
        self.pairs[-1] = (self.pairs[-1][0], reference)
        return reference


class Replay:
    """Gives back recorded speaker audio, block by block."""

    available = True

    def __init__(self, references):
        self.references = list(references)

    def window(self, end_time, samples):
        return self.references.pop(0)


def dbfs(audio: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))) if audio.size else 0.0
    return 20 * np.log10(max(rms, 1e-3) / 32768)


def lag_ms(reference: np.ndarray, mic: np.ndarray) -> float:
    """How much later the microphone hears what the speakers played (GCC-PHAT)."""
    n = 1 << int(np.ceil(np.log2(len(reference) + len(mic))))
    cross = np.fft.rfft(mic.astype(float), n) * np.fft.rfft(reference.astype(float), n).conj()
    corr = np.fft.irfft(cross / (np.abs(cross) + 1e-9), n)
    return float(np.argmax(corr[: int(0.8 * 16000)])) / 16


def record_while(speak, tap, mic, recorder) -> None:
    """Read the microphone (pairing blocks with the speakers' audio) until `speak` is done."""
    watch = VoiceWatch(recorder, _Silent(), None)  # only for its timing; cleans nothing
    done = threading.Event()
    threading.Thread(target=lambda: (speak(), done.set()), daemon=True).start()
    while not done.is_set():
        block = mic.read()
        recorder.pairs.append((block, b""))
        watch.clean(block, mic.last_time)
    for _ in range(5):  # the echo's tail
        block = mic.read()
        recorder.pairs.append((block, b""))
        watch.clean(block, mic.last_time)


class _Silent:
    def clean(self, mic, speakers):
        return mic


def main() -> int:
    talk = "--talk" in sys.argv
    if not echo_available():
        print("The echo canceller isn't installed: pip install livekit")
        return 1
    cfg = load_config()
    tap = SpeakerTap()
    tap.start()
    speaker = make_speaker(cfg.tts_rate, cfg.tts_voice)
    speaker.say(" ")
    recorder = Recorder(tap)
    with Microphone(device=cfg.mic_device) as mic:
        time.sleep(0.5)
        mic.clear()
        print("Speaking (stay quiet)...")
        record_while(lambda: [speaker.say(s) for s in SENTENCES], tap, mic, recorder)
    tap.stop()
    mic_audio = np.frombuffer(b"".join(m for m, _ in recorder.pairs), np.int16)
    ref_audio = np.frombuffer(b"".join(r for _, r in recorder.pairs), np.int16)
    if not np.abs(ref_audio).max():
        print("Nothing was heard from the speakers. Is the volume up, and the voice working?")
        return 1
    print(f"\nAbdoh's voice at the microphone: {dbfs(mic_audio):.0f} dBFS "
          f"(the speakers played {dbfs(ref_audio):.0f} dBFS)")  # fmt: skip
    print(f"Delay from the speakers to the microphone: {lag_ms(ref_audio, mic_audio):.0f} ms "
          "(the canceller copes with 0 to 800)")  # fmt: skip

    canceller = EchoCanceller()
    cleaned = np.frombuffer(
        b"".join(canceller.clean(m, r) for m, r in recorder.pairs if len(m) == len(r)), np.int16
    )
    per_second = []
    for s in range(len(cleaned) // 16000):
        part = slice(s * 16000, (s + 1) * 16000)
        if np.abs(ref_audio[part]).max() > 300:  # only while Abdoh was talking
            per_second.append(round(dbfs(mic_audio[part]) - dbfs(cleaned[part]), 1))
    print(f"Echo removed, second by second (dB, 20 or more is good): {per_second}")

    print("\nWrongly heard you (should be 0) at each sensitivity:")
    for name in SENSITIVITY:
        replay = Replay([r for _, r in recorder.pairs])
        watch = VoiceWatch(replay, EchoCanceller(), SileroVad(), raw_vad=SileroVad())
        watch.sensitivity = name
        false = 0
        for i, (block, _) in enumerate(recorder.pairs):
            if watch.feed(block, 100.0 + i * 0.1):
                false += 1
                watch.rearm()
        print(f"  {name:6}: {false} time(s)")

    if talk:
        return talk_over(cfg, speaker)
    return 0


def talk_over(cfg, speaker) -> int:
    from abdoh.audio.stt import load_transcriber

    print("\nNow talk over Abdoh...")
    transcriber = load_transcriber(cfg)
    tap = SpeakerTap()
    tap.start()
    watch = VoiceWatch(
        tap, EchoCanceller(), SileroVad(), cfg.voice_interrupt_sensitivity, raw_vad=SileroVad()
    )
    heard = threading.Event()
    probe = SileroVad()  # for the timeline only
    started = time.perf_counter()
    threading.Thread(target=lambda: speaker.say(TALK), daemon=True).start()
    audio = b""
    print("  time   mic level   after cleaning   speech?")
    row: list[tuple[bytes, bytes]] = []
    with Microphone(device=cfg.mic_device) as mic:
        while time.perf_counter() - started < 30:
            block = mic.read()
            if not heard.is_set():
                fired = watch.feed(block, mic.last_time)
                row.append((block, bytes(watch._recent[-len(block) :])))
                if len(row) == 5 or fired:  # a timeline line every half second
                    raw = np.frombuffer(b"".join(b for b, _ in row), np.int16)
                    clean = b"".join(c for _, c in row)
                    chance = probe.speech_prob(clean)
                    print(f"  {time.perf_counter() - started:4.1f}s   {dbfs(raw):5.0f} dBFS"
                          f"   {dbfs(np.frombuffer(clean, np.int16)):5.0f} dBFS"
                          f"       {chance:.2f}")  # fmt: skip
                    row = []
                if fired:
                    heard.set()
                    speaker.stop()
                    print(f"Heard you {time.perf_counter() - started:.1f} s after Abdoh started.")
                    audio = watch.pre_roll()
            else:
                audio += watch.clean(block, mic.last_time)
                if len(audio) > 4 * BYTES_PER_SECOND:
                    break
    tap.stop()
    if not heard.is_set():
        print("Didn't hear you. Try a higher sensitivity, or a lower volume.")
        return 1
    print(f"You said: {transcriber.transcribe(audio)!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
