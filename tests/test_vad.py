import numpy as np
from fakes import silent_block, tone_block

from abdoh.audio.vad import CONTEXT, WINDOW, SileroVad, bundled_model_path, load_vad


class FakeSession:
    """Mimics the Silero ONNX model: probability = loudness of the window."""

    def __init__(self):
        self.inputs = []

    def run(self, outputs, feeds):
        x, h, c = feeds["input"], feeds["h"], feeds["c"]
        self.inputs.append(x.copy())
        prob = 0.9 if np.abs(x[0, CONTEXT:]).mean() > 0.01 else 0.05
        return np.array([prob], dtype=np.float32), h + 1, c + 1


def test_speech_and_silence():
    assert SileroVad(session=FakeSession()).is_speech(tone_block())
    assert not SileroVad(session=FakeSession()).is_speech(silent_block())


def test_speech_ends_after_some_silence():
    vad = SileroVad(session=FakeSession())
    assert vad.is_speech(tone_block())
    vad.is_speech(silent_block())  # its first window still holds the end of the tone
    assert not vad.is_speech(silent_block())


def test_windows_carry_over_between_blocks():
    session = FakeSession()
    vad = SileroVad(session=session)
    vad.speech_prob(silent_block())  # 1600 samples: 3 windows, 64 left over
    assert len(session.inputs) == 3
    assert all(x.shape == (1, WINDOW + CONTEXT) for x in session.inputs)
    vad.speech_prob(silent_block())  # 64 + 1600 = 1664: 3 more windows, 128 left over
    assert len(session.inputs) == 6


def test_context_is_the_end_of_the_previous_window():
    session = FakeSession()
    vad = SileroVad(session=session)
    audio = (np.arange(WINDOW * 2) % 1000).astype(np.int16)
    vad.speech_prob(audio.tobytes())
    first, second = session.inputs
    assert np.all(first[0, :CONTEXT] == 0)
    assert np.allclose(second[0, :CONTEXT], first[0, -CONTEXT:])


def test_state_is_carried_and_reset():
    session = FakeSession()
    vad = SileroVad(session=session)
    vad.speech_prob(silent_block())
    assert vad._h[0, 0, 0] == 3  # three model steps
    vad.reset()
    assert vad._h[0, 0, 0] == 0


def test_short_block_keeps_the_last_probability():
    vad = SileroVad(session=FakeSession())
    assert vad.speech_prob(tone_block()) == np.float32(0.9)
    assert vad.speech_prob(tone_block()[:100]) == np.float32(0.9)  # not a full window yet


def test_bundled_model_is_found():
    path = bundled_model_path()
    assert path is not None and path.name == "silero_vad_v6.onnx"


def test_load_vad_falls_back_to_none(monkeypatch):
    monkeypatch.setattr("abdoh.audio.vad.bundled_model_path", lambda: None)
    assert load_vad() is None
