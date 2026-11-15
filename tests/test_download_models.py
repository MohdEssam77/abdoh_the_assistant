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


def test_an_empty_download_never_becomes_the_model(models, tmp_path):
    def fetch(url, path):
        Path(path).write_bytes(b"" if url.endswith("model.bin") else b"ok")

    folder = tmp_path / "faster-whisper-base.en"
    with pytest.raises(RuntimeError, match="empty"):
        models.download_whisper(folder, fetch)
    assert not (folder / "model.bin").exists()
    assert not list(folder.glob("*.part"))
