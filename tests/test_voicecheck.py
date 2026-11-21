"""Your voice check: trained on recordings, saved, loaded for its own model only, and asked
before the wake word counts. The wake word model is faked."""

import numpy as np
import pytest
from fakes import FakeMic
from test_interrupt import Router
from test_oww import engine as fake_oww

from abdoh.audio.oww import FRAME
from abdoh.audio.voicecheck import FILE, VoiceCheck, features, fit, train
from abdoh.audio.wakeword import use_voice_check
from abdoh.config import Config
from abdoh.daemon import Daemon
from abdoh.events import Bus
from abdoh.speech.tts import FakeSpeaker

YOU, OTHER = 1000, -1000  # what a recording's samples are: you, or someone/something else


def recording(who, seconds=1.0):
    return (np.ones(int(16000 * seconds)) * who).astype(np.int16).tobytes()


class FakeScorer:
    """Stands in for the wake word model: your samples give windows from one cluster and a high
    score, anything else windows from another cluster."""

    def __init__(self):
        self.rng = np.random.default_rng(1)
        self.last_window = None

    def reset(self):
        pass

    def step(self, frame):
        you = frame.mean() > 500
        self.last_window = self.rng.normal(1.0 if you else -1.0, 0.7, (16, 96))
        return 0.9 if you else 0.05


def model_file(tmp_path, size=100):
    path = tmp_path / "hey_abdoh.onnx"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def test_it_learns_you_from_your_recordings(tmp_path):
    scorer = FakeScorer()
    model = model_file(tmp_path)
    result = train(scorer, [recording(YOU)] * 10, recording(OTHER, 20), model, 0.4)
    assert (result.passed, result.total, result.woke) == (10, 10, 10)
    you = np.random.default_rng(2).normal(1.0, 0.7, (16, 96))
    other = np.random.default_rng(3).normal(-1.0, 0.7, (16, 96))
    assert result.check.prob(you) > 0.9 and result.check.prob(other) < 0.1
    assert (result.check.model, result.check.model_size) == ("hey_abdoh.onnx", 100)


def test_fit_balances_few_positives_against_many_negatives():
    rng = np.random.default_rng(0)
    x = np.vstack([rng.normal(1, 1, (5, 4)), rng.normal(-1, 1, (200, 4))])
    y = np.concatenate([np.ones(5), np.zeros(200)])
    mean, scale, w, b = fit(x, y)
    probs = 1 / (1 + np.exp(-(((x - mean) / scale) @ w + b)))
    assert probs[:5].mean() > 0.7 and probs[5:].mean() < 0.3


def test_it_needs_recordings():
    with pytest.raises(ValueError):
        train(FakeScorer(), [], recording(OTHER), "model.onnx", 0.4)


def test_saved_and_loaded_for_its_own_model_only(tmp_path):
    model = model_file(tmp_path)
    check = train(FakeScorer(), [recording(YOU)] * 3, recording(OTHER, 5), model, 0.4).check
    check.save(tmp_path / "check.npz")
    loaded = VoiceCheck.load(tmp_path / "check.npz", model)
    window = np.ones((16, 96))
    assert loaded is not None and loaded.prob(window) == pytest.approx(check.prob(window))
    assert VoiceCheck.load(tmp_path / "check.npz", model_file(tmp_path / "other", 99)) is None
    assert VoiceCheck.load(tmp_path / "missing.npz", model) is None
    (tmp_path / "broken.npz").write_bytes(b"not a check")
    assert VoiceCheck.load(tmp_path / "broken.npz", model) is None


def test_features_are_the_mean_and_spread_over_time():
    window = np.vstack([np.zeros(96), np.ones(96) * 2])
    assert np.allclose(features(window), np.concatenate([np.ones(96), np.ones(96)]))


# ----- the wake word engine asks the check -----


class Check:
    def __init__(self, prob):
        self.value = prob
        self.asked = 0

    def prob(self, window):
        self.asked += 1
        return self.value


def loud(oww, seconds=1.0):
    """Quiet first (the engine ignores its first frames), then loud: the fake model fires."""
    quiet = np.zeros(FRAME * 8, dtype=np.int16)
    loud_ = (np.ones(int(16000 * seconds)) * 30000).astype(np.int16)
    oww.detect(quiet.tobytes())
    return oww.detect(loud_.tobytes())


def test_the_wake_word_counts_only_in_your_voice():
    oww, _, _ = fake_oww()
    assert loud(oww)  # no check: any voice
    oww, _, _ = fake_oww()
    oww.voice_check = Check(0.2)
    assert not loud(oww) and oww.voice_check.asked >= 1  # the model fired, but it wasn't you
    oww, _, _ = fake_oww()
    oww.voice_check = Check(0.8)
    assert loud(oww)
    oww, _, _ = fake_oww()
    oww.voice_check, oww.voice_threshold = Check(0.8), 0.9
    assert not loud(oww)


def test_the_engine_uses_a_check_made_for_its_model(tmp_path):
    cfg = Config(app_dir=tmp_path, wake_word_model="models/hey_abdoh.onnx")
    model = model_file(tmp_path / "models")
    check = train(FakeScorer(), [recording(YOU)] * 3, recording(OTHER, 5), model, 0.4).check
    oww, _, _ = fake_oww()
    oww.label = "openWakeWord (hey_abdoh)"
    assert use_voice_check(oww, cfg) is False and oww.voice_check is None
    check.save(tmp_path / FILE)
    assert use_voice_check(oww, cfg) is True
    assert oww.label == "openWakeWord (hey_abdoh), your voice"
    model.write_bytes(b"a new model")  # a new wake word model: the old check doesn't fit
    assert use_voice_check(oww, cfg) is False and oww.label == "openWakeWord (hey_abdoh)"


# ----- recording and training from the window -----


class SpeechMic(FakeMic):
    """Each read gives 100 ms: you talking for a second, then silence."""

    def __init__(self):
        super().__init__([])
        self.reads = 0

    def read(self, timeout=2.0):
        self.reads += 1
        level = YOU if self.reads % 30 <= 10 else 0
        return (np.ones(1600) * level).astype(np.int16).tobytes()


def make_daemon(tmp_path):
    cfg = Config(app_dir=tmp_path, wake_word_model="models/hey_abdoh.onnx")
    model_file(tmp_path / "models")
    oww, _, _ = fake_oww()
    daemon = Daemon(cfg, Router(), FakeSpeaker(), FakeMic, oww, None, bus=Bus())
    daemon.voice_scorer = lambda model: FakeScorer()
    return daemon


def test_teaching_it_your_voice(tmp_path, monkeypatch):
    import threading

    monkeypatch.setattr("abdoh.audio.voicecheck.TALK_SECONDS", 2)
    daemon = make_daemon(tmp_path)
    mic = SpeechMic()
    daemon.mic = mic
    stop = threading.Event()

    def main_loop():  # what Daemon.run does while a recording is asked for
        while not stop.is_set():
            if daemon._capture is not None:
                daemon._record_capture(mic)

    threading.Thread(target=main_loop, daemon=True).start()
    try:
        for number in (1, 2, 3):
            assert daemon.record_voice("phrase", number) == {"ok": True, "heard": True}
        assert daemon.record_voice("talk") == {"ok": True, "heard": True}
    finally:
        stop.set()
    assert daemon.voice_status()["recorded"] == 3
    result = daemon.train_voice()
    assert result["ok"] and result["recorded"] == 3
    assert daemon.engine.voice_check is not None and daemon.voice_status()["active"]
    assert (tmp_path / FILE).exists()
    daemon.forget_voice()
    assert daemon.engine.voice_check is None
    assert not (tmp_path / FILE).exists() and daemon.voice_status()["recorded"] == 0


def test_training_needs_recordings(tmp_path):
    daemon = make_daemon(tmp_path)
    assert daemon.train_voice()["ok"] is False


def test_recording_needs_the_microphone(tmp_path):
    daemon = make_daemon(tmp_path)
    assert daemon.record_voice("phrase") == {"ok": False, "error": "The microphone isn't open."}
