"""openWakeWord engine with fake ONNX sessions (the real math is checked by
scripts/check_wakeword.py against the official package)."""

import numpy as np
import pytest
from fakes import silent_block

from abdoh.audio.oww import FRAME, MEL_CONTEXT, WARMUP_FRAMES, OpenWakeWord
from abdoh.audio.wakeword import load_wake_engine
from abdoh.config import Config


class Shape:
    def __init__(self, name, shape):
        self.name = name
        self.shape = shape


class FakeMel:
    def __init__(self):
        self.lengths = []

    def run(self, outputs, feeds):
        samples = feeds["input"]
        self.lengths.append(samples.shape[1])
        frames = int(np.ceil(samples.shape[1] / 160 - 3))
        level = np.abs(samples).mean() / 1000.0
        return [np.full((1, 1, frames, 32), level, dtype=np.float32)]


class FakeEmbed:
    def run(self, outputs, feeds):
        x = feeds["input_1"]
        return [np.full((x.shape[0], 1, 1, 96), x[:, -8:].mean(), dtype=np.float32)]


class FakeWake:
    """Score = how loud the most recent embedding is (so a tone 'says' the wake word)."""

    def __init__(self):
        self.inputs = []

    def get_inputs(self):
        return [Shape("x", [1, 16, 96])]

    def run(self, outputs, feeds):
        x = feeds["x"]
        self.inputs.append(x.shape)
        loud = x[0, -1, 0] > 2.5  # mel scaled by /10 + 2: loud audio pushes it above 2.5
        return [np.array([[0.9 if loud else 0.1]], dtype=np.float32)]


def engine(threshold=0.5):
    mel, wake = FakeMel(), FakeWake()
    return OpenWakeWord(None, None, threshold, sessions=(mel, FakeEmbed(), wake)), mel, wake


def test_first_frames_never_trigger():
    oww, _, _ = engine()
    loud = (np.ones(FRAME) * 30000).astype(np.int16)
    scores = [oww.step(loud) for _ in range(WARMUP_FRAMES + 1)]
    assert scores[:WARMUP_FRAMES] == [0.0] * WARMUP_FRAMES
    assert scores[-1] > 0.5


def test_blocks_of_any_size_are_cut_into_80ms_frames():
    oww, mel, wake = engine()
    for _ in range(4):
        oww.detect(silent_block())  # 4 x 1600 samples = 5 frames of 1280
    assert len(wake.inputs) == 5
    assert wake.inputs[0] == (1, 16, 96)
    # first frame has no context yet, later ones get 480 samples from the previous frame
    assert mel.lengths[1:3] == [FRAME, FRAME + MEL_CONTEXT]


def test_detects_loud_audio_after_warmup_and_reset_restarts_warmup():
    oww, _, _ = engine()
    quiet = [oww.detect(silent_block()) for _ in range(10)]
    assert not any(quiet)
    loud = (np.ones(1600) * 30000).astype(np.int16).tobytes()
    assert oww.detect(loud)
    oww.reset()
    assert not oww.detect(loud)  # warming up again


def test_threshold():
    oww, _, _ = engine(threshold=0.95)
    for _ in range(10):
        oww.detect(silent_block())
    assert not oww.detect((np.ones(1600) * 30000).astype(np.int16).tobytes())
    assert 0.5 < oww.last_score < 0.95


def test_missing_files_are_reported(tmp_path):
    try:
        OpenWakeWord(tmp_path / "hey_krekos.onnx", tmp_path)
    except FileNotFoundError as e:
        assert "hey_krekos.onnx" in str(e) and "melspectrogram" in str(e)
    else:
        raise AssertionError("expected FileNotFoundError")


class Recorded:
    def __init__(self, error=None):
        self.calls = []
        self.error = error
        self.label = "fake"

    def __call__(self, *args):
        self.calls.append(args)
        if self.error:
            raise self.error
        return self


def test_uses_openwakeword_with_your_model(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "hey_krekos.onnx").write_bytes(b"onnx")
    oww = Recorded()
    cfg = Config(app_dir=tmp_path, wake_word_threshold=0.6)
    engine = load_wake_engine(cfg, oww=oww)
    assert engine is oww
    assert oww.calls == [(tmp_path / "models" / "hey_krekos.onnx", 0.6)]
    assert engine.label == "openWakeWord (hey_krekos)"


def test_no_model_is_an_error_the_daemon_turns_into_hotkey_only(tmp_path):
    oww = Recorded()
    with pytest.raises(FileNotFoundError):
        load_wake_engine(Config(app_dir=tmp_path), oww=oww)
    assert oww.calls == []


# ----- the second try: you call again when it missed you -----


def scripted(scores, threshold=0.45):
    """An engine whose model gives these scores, one per 80 ms."""
    oww, _, _ = engine(threshold)
    feed = iter(scores)
    oww.step = lambda frame: next(feed)
    return oww


def run(oww, steps):
    """Feed `steps` frames one block at a time; the steps at which it woke."""
    woke = []
    for i in range(steps):
        oww._steps = i  # step() is scripted, so count the frames here
        if oww.detect(np.zeros(FRAME, dtype=np.int16).tobytes()):
            woke.append(i)
    return woke


def quiet(n):
    return [0.05] * n


def test_two_near_misses_a_moment_apart_wake_it():
    # "Hey Krekos" (0.36) ... 2 seconds ... "Hey Krekos" again (0.38): it was you.
    scores = quiet(5) + [0.30, 0.36, 0.33] + quiet(25) + [0.31, 0.38] + quiet(5)
    assert run(scripted(scores), len(scores)) == [34]  # 0.31 is under the 0.315 floor: 0.38 counts


def test_one_near_miss_is_not_enough():
    scores = quiet(5) + [0.30, 0.36, 0.33] + quiet(40)
    assert run(scripted(scores), len(scores)) == []


def test_a_dip_inside_one_call_is_not_a_second_try():
    scores = quiet(5) + [0.34, 0.05, 0.36] + quiet(20)  # 80 ms apart: the same "Hey Krekos"
    assert run(scripted(scores), len(scores)) == []


def test_near_misses_far_apart_dont_add_up():
    scores = quiet(5) + [0.36] + quiet(60) + [0.37] + quiet(5)  # almost 5 seconds apart
    assert run(scripted(scores), len(scores)) == []


def test_too_low_to_count_as_a_try():
    scores = quiet(5) + [0.25] + quiet(20) + [0.28] + quiet(5)  # under 70% of 0.45
    assert run(scripted(scores), len(scores)) == []


def test_the_second_try_still_needs_your_voice():
    class NotYou:
        def prob(self, window):
            return 0.1

    oww = scripted(quiet(5) + [0.36] + quiet(20) + [0.37] + quiet(5))
    oww.voice_check = NotYou()
    assert run(oww, 32) == []


class AlwaysYou:
    def prob(self, window):
        return 0.9


def test_with_your_voice_a_weaker_second_try_is_enough():
    scores = quiet(5) + [0.25] + quiet(20) + [0.28] + quiet(5)  # under 70% of 0.45, over 50%
    oww = scripted(scores)
    oww.voice_check = AlwaysYou()
    assert run(oww, len(scores)) == [26]
    assert run(scripted(scores), len(scores)) == []  # without it: still too low


def test_every_moment_of_the_second_try_can_convince_the_voice_check():
    class SureLater:
        def __init__(self):
            self.asked = 0

        def prob(self, window):
            self.asked += 1
            return 0.9 if self.asked > 1 else 0.2  # not sure at the very start of the word

    scores = quiet(5) + [0.36] + quiet(20) + [0.36, 0.37, 0.36] + quiet(5)
    oww = scripted(scores)
    oww.voice_check = SureLater()
    assert run(oww, len(scores)) == [27]
