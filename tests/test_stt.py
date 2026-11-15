import numpy as np
import pytest

from abdoh.audio.stt import (
    MAX_GAIN,
    PARAKEET_DIR,
    PARAKEET_FILES,
    TARGET_PEAK,
    ParakeetTranscriber,
    WhisperTranscriber,
    choose_engine,
    is_complete,
    level,
    load_transcriber,
    make_transcriber,
    model_folder,
    model_name,
)
from abdoh.config import Config


def pcm(peak: int, n: int = 1600) -> bytes:
    return (np.ones(n, dtype=np.int16) * peak).tobytes()


class Info:
    def __init__(self, language, probs=()):
        self.language = language
        self.all_language_probs = list(probs)


class FakeWhisper:
    """Like faster_whisper.WhisperModel: remembers how it was called."""

    def __init__(self, source="", detects="en", probs=()):
        self.source = source
        self.detects, self.probs = detects, probs
        self.calls = []

    def transcribe(self, samples, language=None, **kwargs):
        self.calls.append((language, float(np.abs(samples).max())))
        heard = language or self.detects
        return [type("S", (), {"text": f" said in {heard} "})()], Info(heard, self.probs)


class FakeParakeet:
    def __init__(self, fail=False):
        self.heard = []
        self.fail = fail

    def recognize(self, samples, sample_rate):
        if self.fail:
            raise RuntimeError("out of memory")
        self.heard.append((samples.dtype, sample_rate, float(np.abs(samples).max())))
        return " What time is it? "


def bundle(folder, files=("model.bin", "config.json"), empty=()):
    folder.mkdir(parents=True)
    for name in files:
        (folder / name).write_bytes(b"" if name in empty else b"data")
    return folder


# ----- names and files -----


def test_english_uses_the_english_only_whisper_model():
    assert model_name("base", ["en"]) == "base.en"
    assert model_name("small", ["en"]) == "small.en"
    assert model_name("large-v3", ["en"]) == "large-v3"  # no English-only version


def test_other_languages_keep_the_multilingual_model():
    assert model_name("small", ["en", "ar"]) == "small"
    assert model_name("base", ["ar"]) == "base"


def test_a_model_folder_with_an_empty_file_is_not_complete(tmp_path):
    assert is_complete(bundle(tmp_path / "ok"))
    assert not is_complete(bundle(tmp_path / "broken", empty=("model.bin",)))
    assert not is_complete(tmp_path / "missing")


# ----- levelling -----


def test_quiet_audio_is_brought_up():
    quiet = np.array([0.0, 0.01, -0.02], dtype=np.float32)
    assert float(np.abs(level(quiet)).max()) == pytest.approx(TARGET_PEAK)


def test_near_silence_is_not_amplified_into_noise():
    hiss = np.array([0.0001, -0.0001], dtype=np.float32)
    assert float(np.abs(level(hiss)).max()) == pytest.approx(0.0001 * MAX_GAIN)
    assert not level(np.zeros(4, dtype=np.float32)).any()


# ----- choosing the engine -----


def app(tmp_path, parakeet=True, **settings) -> Config:
    if parakeet:
        bundle(tmp_path / PARAKEET_DIR, PARAKEET_FILES)
    return Config(app_dir=tmp_path, **settings)


def test_english_uses_parakeet_when_its_model_is_there(tmp_path):
    transcriber = make_transcriber(app(tmp_path))
    assert isinstance(transcriber, ParakeetTranscriber)
    assert transcriber.model_dir == tmp_path / PARAKEET_DIR


def test_without_the_parakeet_model_english_falls_back_to_whisper_base(tmp_path):
    transcriber = make_transcriber(app(tmp_path, parakeet=False))
    assert isinstance(transcriber, WhisperTranscriber) and transcriber.model_size == "base.en"


def test_an_incomplete_parakeet_model_is_not_used(tmp_path):
    bundle(tmp_path / PARAKEET_DIR, PARAKEET_FILES, empty=("encoder-model.int8.onnx",))
    assert isinstance(make_transcriber(Config(app_dir=tmp_path)), WhisperTranscriber)


def test_more_languages_use_multilingual_whisper(tmp_path):
    transcriber = make_transcriber(app(tmp_path, languages=["en", "ar"]))
    assert isinstance(transcriber, WhisperTranscriber)
    assert (transcriber.model_size, transcriber.languages) == ("small", ["en", "ar"])


def test_you_can_choose_the_lighter_engine(tmp_path):
    transcriber = make_transcriber(app(tmp_path, speech_engine="whisper", whisper_model="base"))
    assert isinstance(transcriber, WhisperTranscriber) and transcriber.model_size == "base.en"
    assert choose_engine(Config(speech_engine="parakeet"), None) == "whisper"  # no model: can't


# ----- Parakeet -----


def test_parakeet_gets_levelled_float_audio(tmp_path):
    model = FakeParakeet()
    transcriber = ParakeetTranscriber(tmp_path, make_model=lambda name, path, quantization: model)
    assert transcriber.transcribe(pcm(300)) == "What time is it?"
    assert transcriber.transcribe(b"") == ""
    dtype, rate, peak = model.heard[0]
    assert (dtype, rate) == (np.float32, 16000) and peak == pytest.approx(TARGET_PEAK, rel=1e-3)


def test_if_parakeet_cannot_load_whisper_takes_over(tmp_path):
    def broken(cfg):
        return ParakeetTranscriber(tmp_path, make_model=lambda *a, **k: FakeParakeet(fail=True))

    def fallback(cfg, fallback):
        return WhisperTranscriber("base", ["en"], make_model=lambda *a, **k: FakeWhisper())

    transcriber = load_transcriber(Config(app_dir=tmp_path), broken, fallback)
    assert isinstance(transcriber, WhisperTranscriber) and transcriber._model is not None


def test_a_broken_whisper_model_is_an_error(tmp_path):
    def broken(cfg):
        def fail(*a, **k):
            raise RuntimeError("Unable to open file 'model.bin'")

        return WhisperTranscriber("base", ["en"], make_model=fail)

    with pytest.raises(RuntimeError, match="model.bin"):
        load_transcriber(Config(app_dir=tmp_path), broken)


# ----- Whisper -----


def whisper(tmp_path, languages, **model):
    made = []

    def make(source, device, compute_type):
        made.append(FakeWhisper(source, **model))
        return made[-1]

    transcriber = WhisperTranscriber("small", languages, tmp_path / "none", make_model=make)
    return transcriber, made


def test_the_whisper_model_that_ships_with_abdoh_is_used(tmp_path):
    folder = bundle(tmp_path / model_folder("base.en"))
    made = []
    transcriber = WhisperTranscriber(
        "base", ["en"], folder, make_model=lambda source, **k: made.append(source) or FakeWhisper()
    )
    transcriber.warm_up()
    assert made == [str(folder)]


def test_a_missing_whisper_model_is_downloaded_by_name(tmp_path):
    transcriber, made = whisper(tmp_path, ["en", "ar"])
    transcriber.warm_up()
    assert made[0].source == "small"


def test_one_language_is_never_guessed(tmp_path):
    transcriber, made = whisper(tmp_path, ["ar"], detects="ru")
    assert transcriber.transcribe(pcm(3000)) == "said in ar"
    assert [language for language, _ in made[0].calls] == ["ar"]
    assert transcriber.last_language == "ar"


def test_your_languages_are_detected(tmp_path):
    transcriber, made = whisper(tmp_path, ["en", "ar"], detects="ar")
    assert transcriber.transcribe(pcm(3000)) == "said in ar"
    assert transcriber.last_language == "ar"
    assert len(made[0].calls) == 1  # one pass: no second transcription needed


def test_a_language_you_dont_speak_is_heard_as_one_of_yours(tmp_path):
    probs = [("ru", 0.5), ("ar", 0.3), ("en", 0.1)]
    transcriber, made = whisper(tmp_path, ["en", "ar"], detects="ru", probs=probs)
    assert transcriber.transcribe(pcm(3000)) == "said in ar"  # the likeliest of yours
    assert [language for language, _ in made[0].calls] == [None, "ar"]
    assert transcriber.last_language == "ar"


def test_whisper_does_not_load_until_needed(tmp_path):
    transcriber, made = whisper(tmp_path, ["en"])
    assert transcriber.transcribe(b"") == "" and made == []
