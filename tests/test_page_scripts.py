"""Every script of the window and the phone page parses (a quote left unclosed once broke a
whole page)."""

import shutil
import subprocess
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "abdoh"
SCRIPTS = sorted([*(SRC / "ui" / "web").glob("*.js"), *(SRC / "phone" / "web").glob("*.js")])


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js isn't installed")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_the_page_script_parses(script):
    done = subprocess.run(
        ["node", "--check", str(script)], capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 0, done.stderr
