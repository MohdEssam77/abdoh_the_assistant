from abdoh.audio.stt import Transcriber, model_name


def test_english_uses_the_english_only_model():
    assert model_name("base", "en") == "base.en"
    assert model_name("small", "en") == "small.en"


def test_other_languages_keep_the_multilingual_model():
    assert model_name("base", None) == "base"
    assert model_name("base", "ar") == "base"
    assert model_name("large-v3", "en") == "large-v3"  # no English-only version


def test_transcriber_does_not_load_the_model_until_needed():
    t = Transcriber("base", "en")
    assert t.model_size == "base.en"
    assert t.transcribe(b"") == ""
    assert t._model is None
