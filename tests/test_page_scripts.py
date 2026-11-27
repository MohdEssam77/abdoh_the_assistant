"""Every script of the window parses (a quote left unclosed once broke a whole page)."""

import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "abdoh" / "ui" / "web"
SCRIPTS = sorted(WEB.glob("*.js"))


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js isn't installed")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_the_page_script_parses(script):
    done = subprocess.run(
        ["node", "--check", str(script)], capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 0, done.stderr
