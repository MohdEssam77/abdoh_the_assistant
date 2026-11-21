"""Hearing you while Abdoh talks: the speaker tap, the echo canceller and the voice watch, with
fakes (no speakers, microphone or livekit needed)."""

import numpy as np

from abdoh.audio.bargein import SENSITIVITY, VoiceWatch
from abdoh.audio.echo import FRAME_BYTES, EchoCanceller
from abdoh.audio.loopback import SpeakerTap

RATE = 16000


def tone(seconds, level=3000):
    return (np.ones(int(seconds * RATE)) * level).astype(np.int16)


# ----- the speaker tap -----


def make_tap():
    tap = SpeakerTap(capture_factory=lambda: None, clock=lambda: 100.0)
    tap._origin = 100.0
    return tap


def test_the_tap_places_audio_by_time():
    tap = make_tap()
    tap.write(tone(0.01, 1000), 100.0)
    tap.write(tone(0.01, 2000), 100.01)
    got = np.frombuffer(tap.window(100.02, 320), np.int16)
    assert list(got[:160]) == [1000] * 160 and list(got[160:]) == [2000] * 160


def test_silence_between_packets_is_zeros():
    tap = make_tap()
    tap.write(tone(0.01, 1000), 100.0)
    tap.write(tone(0.01, 2000), 100.5)  # nothing played in between: Windows sends nothing
    got = np.frombuffer(tap.window(100.51, int(0.51 * RATE)), np.int16)
    assert got[:160].tolist() == [1000] * 160
    assert not got[160:-160].any()
    assert got[-160:].tolist() == [2000] * 160


def test_what_hasnt_played_yet_or_is_too_old_is_zeros():
    tap = make_tap()
    tap.write(tone(0.01, 1000), 100.0)
    ahead = np.frombuffer(tap.window(100.03, 480), np.int16)
    assert ahead[:160].tolist() == [1000] * 160 and not ahead[160:].any()
    tap.write(tone(0.01, 5), 110.0)  # ten seconds later: the first packet is long gone
    assert not np.frombuffer(tap.window(100.01, 160), np.int16).any()


def test_packets_a_sample_off_stay_back_to_back():
    tap = make_tap()
    tap.write(tone(0.01, 1000), 100.0)
    tap.write(tone(0.01, 2000), 100.01 + 1 / RATE)  # time stamps jitter a little
    got = np.frombuffer(tap.window(100.02, 320), np.int16)
    assert got.tolist() == [1000] * 160 + [2000] * 160


def test_the_ring_wraps_around():
    tap = make_tap()
    for i in range(500):  # 5 s of 10 ms packets into a 3 s ring
        tap.write(tone(0.01, i), 100.0 + i * 0.01)
    got = np.frombuffer(tap.window(105.0, 320), np.int16)
    assert got[:160].tolist() == [498] * 160 and got[160:].tolist() == [499] * 160


def test_the_tap_level():
    clock = {"now": 100.0}
    tap = SpeakerTap(capture_factory=lambda: None, clock=lambda: clock["now"])
    tap._origin = 100.0
    tap.write(tone(0.1, 4000), 100.0)
    clock["now"] = 100.1
    assert tap.level() == 4000
    clock["now"] = 101.0
    assert tap.level() == 0


class FakeCapture:
    def __init__(self, packets, changed_after=None):
        self._packets = list(packets)
        self.closed = False
        self.changed_after = changed_after
        self.checks = 0

    def packets(self):
        while self._packets:
            yield self._packets.pop(0)

    def device_changed(self):
        self.checks += 1
        return self.changed_after is not None and self.checks > self.changed_after

    def close(self):
        self.closed = True


def test_the_capture_thread_fills_the_tap_and_reopens_on_new_speakers(monkeypatch):
    import time

    monkeypatch.setattr("abdoh.audio.loopback.CHECK_DEVICE_SECONDS", 0.0)
    made = []

    def factory():
        capture = FakeCapture([(tone(0.01, 1234), 100.0)], changed_after=0)
        made.append(capture)
        return capture

    tap = SpeakerTap(capture_factory=factory, clock=time.perf_counter)
    tap._origin = 100.0
    tap.start()
    end = time.perf_counter() + 2
    while len(made) < 2 and time.perf_counter() < end:
        time.sleep(0.01)
    tap.stop()
    assert len(made) >= 2 and made[0].closed  # the speakers changed: opened again
    assert np.frombuffer(tap.window(100.01, 160), np.int16).tolist() == [1234] * 160


def test_a_capture_that_cant_open_leaves_the_tap_empty(monkeypatch):
    import time

    monkeypatch.setattr("abdoh.audio.loopback.RETRY_SECONDS", 0.01)

    def broken():
        raise OSError("no speakers")

    tap = SpeakerTap(capture_factory=broken)
    tap.start()
    time.sleep(0.05)
    tap.stop()
    assert tap.level() == 0


# ----- the echo canceller -----


class FakeFrame:
    def __init__(self, data):
        self.data = bytearray(data)


class FakeModule:
    """Records the order of calls; "cancels" by subtracting the last speaker frame."""

    def __init__(self):
        self.calls = []
        self.delay = None
        self._last = None

    def set_stream_delay_ms(self, ms):
        self.delay = ms

    def process_reverse_stream(self, frame):
        self.calls.append("speakers")
        self._last = np.frombuffer(bytes(frame.data), np.int16)

    def process_stream(self, frame):
        self.calls.append("mic")
        mic = np.frombuffer(bytes(frame.data), np.int16)
        frame.data[:] = (mic - self._last).astype(np.int16).tobytes()


def test_frames_go_in_strictly_alternating():
    modules = []

    def factory():
        modules.append(FakeModule())
        return modules[-1]

    canceller = EchoCanceller(factory, FakeFrame, delay_ms=120)
    mic = (tone(0.1, 3000) + 0).tobytes()
    speakers = tone(0.1, 1000).tobytes()
    cleaned = np.frombuffer(canceller.clean(mic, speakers), np.int16)
    assert cleaned.tolist() == [2000] * 1600
    assert modules[0].calls == ["speakers", "mic"] * 10  # one of each per 10 ms
    assert modules[0].delay == 120
    canceller.reset()
    assert len(modules) == 2 and modules[1].delay == 120


def test_the_canceller_wants_whole_matching_frames():
    import pytest

    canceller = EchoCanceller(FakeModule, FakeFrame)
    with pytest.raises(ValueError):
        canceller.clean(b"\0" * FRAME_BYTES, b"\0" * FRAME_BYTES * 2)
    with pytest.raises(ValueError):
        canceller.clean(b"\0" * 10, b"\0" * 10)


# ----- the voice watch -----


class FakeVad:
    """Speech wherever the samples are loud (above 500)."""

    def __init__(self):
        self.resets = 0

    def reset(self):
        self.resets += 1

    def speech_prob(self, frame):
        samples = np.frombuffer(frame, np.int16)
        return 0.9 if np.abs(samples.astype(np.int32)).mean() > 500 else 0.05


class PassThrough:
    """The canceller, faked: takes the speakers' samples straight off the microphone's."""

    def clean(self, mic, speakers):
        a = np.frombuffer(mic, np.int16).astype(np.int32)
        b = np.frombuffer(speakers, np.int16).astype(np.int32)
        return np.clip(a - b, -32768, 32767).astype(np.int16).tobytes()


class StillTap:
    """Speakers that play `level` all the time."""

    available = True

    def __init__(self, level=0):
        self.level_ = level

    def window(self, end_time, samples):
        return (np.ones(samples) * self.level_).astype(np.int16).tobytes()


def make_watch(sensitivity="medium", tap_level=0):
    return VoiceWatch(StillTap(tap_level), PassThrough(), FakeVad(), sensitivity)


def feed_blocks(watch, blocks):
    """Feed 0.1 s blocks; the index of the block that fired, or None."""
    for i, block in enumerate(blocks):
        if watch.feed(block, 10.0 + i * 0.1):
            return i
    return None


def test_talking_is_heard_and_abdohs_own_voice_is_not():
    echo_only = make_watch(tap_level=3000)  # the mic hears exactly what the speakers play
    assert feed_blocks(echo_only, [tone(0.1, 3000).tobytes()] * 20) is None
    talking = make_watch(tap_level=3000)
    blocks = [tone(0.1, 3000).tobytes()] * 5 + [tone(0.1, 6000).tobytes()] * 5
    assert feed_blocks(talking, blocks) == 5  # heard in the first block you speak in


def test_each_sensitivity_needs_its_own_number_of_frames():
    for name, (need, _, _) in SENSITIVITY.items():
        watch = make_watch(name)
        frames = 0
        audio = tone(0.032 * 8, 3000).tobytes()  # loud speech, frame by frame
        for at in range(0, len(audio), 1024):
            frames += 1
            if watch.feed(audio[at : at + 1024], 10.0 + frames * 0.032):
                break
        assert frames == need, name


def test_it_fires_once_until_rearmed():
    watch = make_watch()
    loud = [tone(0.1, 3000).tobytes()] * 3
    assert feed_blocks(watch, loud) == 0
    assert feed_blocks(watch, loud) is None
    watch.rearm()
    assert feed_blocks(watch, loud) == 0


def test_quiet_sounds_never_fire():
    watch = make_watch()
    assert feed_blocks(watch, [tone(0.1, 20).tobytes()] * 20) is None  # under -60 dBFS


def test_the_start_of_what_you_said_is_kept():
    watch = make_watch()
    blocks = [tone(0.1, 0).tobytes()] * 12 + [tone(0.1, 3000).tobytes()]
    assert feed_blocks(watch, blocks) == 12
    before = np.frombuffer(watch.pre_roll(), np.int16)
    assert len(before) == int(0.6 * RATE)  # half a second before it fired, and the block
    assert before[-1600:].tolist() == [3000] * 1600


def test_idle_forgets_the_history():
    watch = make_watch()
    watch.feed(tone(0.1, 3000).tobytes()[:2048], 10.0)  # 2 hot frames: one short of firing
    watch.idle()
    assert watch.pre_roll() == b""
    assert not watch.feed(tone(0.032, 3000).tobytes(), 11.0)  # starts counting again


def test_without_the_parts_it_never_fires():
    assert not VoiceWatch(None, PassThrough(), FakeVad()).available
    assert not VoiceWatch(StillTap(), None, FakeVad()).available
    watch = VoiceWatch(StillTap(), PassThrough(), None)
    assert not watch.feed(tone(0.1, 9000).tobytes(), 10.0)


def test_an_unknown_sensitivity_is_medium():
    assert make_watch("extreme").sensitivity == "medium"


class RecordingTap(StillTap):
    def __init__(self):
        super().__init__()
        self.ends = []

    def window(self, end_time, samples):
        self.ends.append(end_time)
        return super().window(end_time, samples)


def test_the_speakers_audio_is_one_unbroken_stream_despite_uneven_blocks():
    tap = RecordingTap()
    watch = VoiceWatch(tap, PassThrough(), FakeVad())
    rng = np.random.default_rng(0)
    for i in range(50):
        watch.feed(tone(0.1, 0).tobytes(), 10.0 + i * 0.1 + rng.uniform(0, 0.03))
    steps = np.diff(tap.ends)
    assert np.allclose(steps, 0.1)  # each block takes the next 100 ms: no gaps, no overlaps


def test_the_stream_follows_a_clock_that_drifts():
    tap = RecordingTap()
    watch = VoiceWatch(tap, PassThrough(), FakeVad())
    for i in range(200):  # the microphone runs 1% fast
        watch.feed(tone(0.1, 0).tobytes(), 10.0 + i * 0.101)
    expected = 10.0 + 199 * 0.101 - 0.04
    assert abs(tap.ends[-1] - expected) < 0.05


# ----- a microphone that hardly hears Abdoh -----


class Muffler:
    """An echo canceller that hasn't learned anything yet: it muffles everything."""

    def clean(self, mic, speakers):
        return bytes(len(mic))


def raw_watch(tap_level=3000, sensitivity="medium"):
    return VoiceWatch(StillTap(tap_level), Muffler(), FakeVad(), sensitivity, raw_vad=FakeVad())


def test_where_abdoh_barely_reaches_the_mic_your_voice_counts_at_once():
    watch = raw_watch()
    quiet = [tone(0.1, 2).tobytes()] * 12  # Abdoh plays loudly; the mic hears almost nothing
    assert feed_blocks(watch, quiet) is None
    assert watch.echo_gain() < 0.01
    assert feed_blocks(watch, [tone(0.1, 3000).tobytes()]) == 0  # you: heard in one block
    assert np.frombuffer(watch.pre_roll(), np.int16)[-1] == 3000  # your words, not muffled


def test_where_abdoh_is_loud_at_the_mic_its_echo_never_counts():
    watch = raw_watch()
    echo = [tone(0.1, 3000).tobytes()] * 30  # the mic hears Abdoh as loudly as it plays
    assert feed_blocks(watch, echo) is None
    assert 0.9 < watch.echo_gain() < 1.1
    assert feed_blocks(watch, [tone(0.1, 6000).tobytes()] * 5) is None  # not 12 dB above it
    assert feed_blocks(watch, [tone(0.1, 20000).tobytes()]) == 0  # far louder: that's you


def test_until_it_knows_the_room_the_raw_mic_only_counts_when_nothing_plays():
    playing = raw_watch(tap_level=3000)
    assert feed_blocks(playing, [tone(0.1, 3000).tobytes()] * 3) is None  # might be echo
    silent = raw_watch(tap_level=0)
    assert feed_blocks(silent, [tone(0.1, 3000).tobytes()]) == 0  # nothing to be an echo of


def test_what_it_learned_about_the_room_outlasts_a_reply():
    watch = raw_watch()
    feed_blocks(watch, [tone(0.1, 2).tobytes()] * 12)
    watch.idle()
    assert watch.echo_gain() < 0.01
