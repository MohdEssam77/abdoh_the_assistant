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
        OpenWakeWord(tmp_path / "hey_abdoh.onnx", tmp_path)
    except FileNotFoundError as e:
        assert "hey_abdoh.onnx" in str(e) and "melspectrogram" in str(e)
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
    (tmp_path / "models" / "hey_abdoh.onnx").write_bytes(b"onnx")
    oww = Recorded()
    cfg = Config(app_dir=tmp_path, wake_word_threshold=0.6)
    engine = load_wake_engine(cfg, oww=oww)
    assert engine is oww
    assert oww.calls == [(tmp_path / "models" / "hey_abdoh.onnx", 0.6)]
    assert engine.label == "openWakeWord (hey_abdoh)"


def test_no_model_is_an_error_the_daemon_turns_into_hotkey_only(tmp_path):
    oww = Recorded()
    with pytest.raises(FileNotFoundError):
        load_wake_engine(Config(app_dir=tmp_path), oww=oww)
    assert oww.calls == []
