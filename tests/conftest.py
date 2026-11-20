import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    """A temp app dir containing the example files, with no API key in the environment."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for name in ("config.example.yaml", "commands.example.yaml"):
        shutil.copyfile(REPO / name, tmp_path / name)
    return tmp_path


@pytest.fixture(autouse=True)
def no_real_key_presses(monkeypatch):
    """Tests never press real keys: a media key changes this computer's volume."""
    if sys.platform == "win32":
        import ctypes

        def refuse(*args):
            raise AssertionError("a test pressed a real key")

        monkeypatch.setattr(ctypes.windll.user32, "keybd_event", refuse)


@pytest.fixture(autouse=True)
def no_bundled_models(tmp_path_factory, monkeypatch):
    """Tests never see the models in this checkout's models/ folder: only the example files
    ship with the (pretend) app, so results are the same on every machine."""
    bundle = tmp_path_factory.mktemp("bundle")
    for name in ("config.example.yaml", "commands.example.yaml"):
        shutil.copyfile(REPO / name, bundle / name)
    monkeypatch.setattr("abdoh.config.BUNDLE_DIR", bundle)
    monkeypatch.setattr("abdoh.settings.BUNDLE_DIR", bundle)


@pytest.fixture(autouse=True)
def no_real_folder_moves(monkeypatch):
    """Tests that start the app never move this computer's real Abdoh folders to Xanthos's
    (tests/test_rename.py tests the real function on temporary folders)."""
    monkeypatch.setattr("abdoh.rename.move_old_folders", lambda *a, **k: [])
