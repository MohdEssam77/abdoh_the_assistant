import shutil
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
