import threading

import numpy as np

from abdoh.speech.earcons import RATE, SOUNDS, Earcons, render


class Recorder:
    def __init__(self):
        self.calls = []
        self.event = threading.Event()

    def __call__(self, samples, rate):
        self.calls.append((samples, rate))
        self.event.set()


def test_render_length_and_volume():
    samples = render([(440, 0.1), (0, 0.05)], volume=0.2)
    assert samples.dtype == np.float32
    assert len(samples) == int(RATE * 0.1) + int(RATE * 0.05)
    assert np.abs(samples).max() <= 0.2 + 1e-6
    assert samples[0] == 0  # faded in: no click


def test_every_sound_renders():
    for segments in SOUNDS.values():
        assert len(render(segments)) > 0


def test_play_uses_cached_samples():
    rec = Recorder()
    earcons = Earcons(play=rec)
    earcons.play("listening")
    earcons.play("listening")
    assert len(rec.calls) == 2
    assert rec.calls[0][0] is rec.calls[1][0]
    assert rec.calls[0][1] == RATE


def test_play_never_raises():
    def broken(samples, rate):
        raise OSError("no audio device")

    Earcons(play=broken).play("thinking")
    Earcons(play=Recorder()).play("no-such-sound")


def test_disabled_plays_nothing():
    rec = Recorder()
    earcons = Earcons(play=rec)
    earcons.enabled = False
    earcons.play("done")
    assert rec.calls == []


def test_ticking_repeats_until_stopped():
    rec = Recorder()
    earcons = Earcons(play=rec)
    earcons.start_ticking("thinking", every=0.01)
    for _ in range(200):
        if len(rec.calls) >= 3:
            break
        threading.Event().wait(0.01)
    earcons.stop_ticking()
    count = len(rec.calls)
    assert count >= 3
    threading.Event().wait(0.05)
    assert len(rec.calls) <= count + 1  # at most one tick was already in flight
