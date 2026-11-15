from abdoh.audio.stt import Transcriber, is_complete, model_folder, model_name
from abdoh.config import Config


class FakeWhisper:
    def __init__(self, source, device, compute_type):
        self.source = source

    def transcribe(self, samples, **kwargs):
        return [], None


def made_from(cfg, tmp_path):
    t = Transcriber.from_config(cfg)
    t._make_model = FakeWhisper
    t.transcribe(b"\0\0" * 1600)
    return t._model.source


def bundle(folder, model_bin=b"weights"):
    folder.mkdir(parents=True)
    (folder / "model.bin").write_bytes(model_bin)
    (folder / "config.json").write_text("{}")
    return folder


def test_the_model_that_ships_with_abdoh_is_used(tmp_path):
    folder = bundle(tmp_path / model_folder("base.en"))
    assert made_from(Config(app_dir=tmp_path), tmp_path) == str(folder)


def test_a_broken_bundled_model_is_skipped(tmp_path):
    bundle(tmp_path / model_folder("base.en"), model_bin=b"")  # an interrupted download
    assert not is_complete(tmp_path / model_folder("base.en"))
    assert made_from(Config(app_dir=tmp_path), tmp_path) == "base.en"  # downloads instead


def test_other_models_are_downloaded_by_name(tmp_path):
    bundle(tmp_path / model_folder("base.en"))
    cfg = Config(app_dir=tmp_path, whisper_model="small")
    assert made_from(cfg, tmp_path) == "small.en"


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
