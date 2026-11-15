import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def models():
    spec = importlib.util.spec_from_file_location(
        "download_models", ROOT / "scripts" / "download_models.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_whisper_model_is_downloaded_whole(models, tmp_path):
    fetched = []

    def fetch(url, path):
        fetched.append(url)
        Path(path).write_bytes(b"data for " + url.encode())

    folder = tmp_path / "faster-whisper-base.en"
    models.download_whisper(folder, fetch)
    assert sorted(p.name for p in folder.iterdir()) == sorted(models.WHISPER_FILES)
    assert all(url.startswith("https://huggingface.co/Systran/") for url in fetched)
    assert "3d3d5dee26484f91867d81cb899cfcf72b96be6c" in fetched[0]  # a fixed revision
    models.download_whisper(folder, lambda url, path: pytest.fail("downloaded twice"))


def test_parakeet_model_comes_from_a_fixed_revision(models, tmp_path):
    from abdoh.audio.stt import PARAKEET_FILES, is_complete

    fetched = []

    def fetch(url, path):
        fetched.append(url)
        Path(path).write_bytes(b"onnx")

    folder = tmp_path / "parakeet-tdt-0.6b-v2"
    models.download_parakeet(folder, fetch)
    assert is_complete(folder, PARAKEET_FILES)  # exactly the files Abdoh checks for
    assert sorted(models.PARAKEET_FILES) == sorted(PARAKEET_FILES)
    assert all("/resolve/0bbb45a3365852604aef28b538a8f066f4ccaa85/" in url for url in fetched)


def test_the_repos_wake_word_is_copied_unless_you_have_your_own(models, tmp_path):
    assets, target = tmp_path / "assets", tmp_path / "models"
    assets.mkdir()
    (assets / "hey_abdoh.onnx").write_bytes(b"trained")
    models.copy_wake_word(target, assets)
    assert (target / "hey_abdoh.onnx").read_bytes() == b"trained"
    (target / "hey_abdoh.onnx").write_bytes(b"mine")
    models.copy_wake_word(target, assets)
    assert (target / "hey_abdoh.onnx").read_bytes() == b"mine"


def test_the_wake_word_model_is_in_the_repo():
    assert (ROOT / "assets" / "hey_abdoh.onnx").stat().st_size > 100_000


def test_an_empty_download_never_becomes_the_model(models, tmp_path):
    def fetch(url, path):
        Path(path).write_bytes(b"" if url.endswith("model.bin") else b"ok")

    folder = tmp_path / "faster-whisper-base.en"
    with pytest.raises(RuntimeError, match="empty"):
        models.download_whisper(folder, fetch)
    assert not (folder / "model.bin").exists()
    assert not list(folder.glob("*.part"))
