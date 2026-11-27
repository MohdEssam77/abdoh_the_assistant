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


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js isn't installed")
def test_the_phone_turns_its_recording_into_16_khz_audio():
    """phone.js's toPcm16k: a 48 kHz recording becomes the 16 kHz 16-bit audio that speech
    recognition reads (a third as many samples, the same tone, loud parts clipped)."""
    import json
    import re

    source = (SRC / "phone" / "web" / "phone.js").read_text(encoding="utf-8")
    function = re.search(r"function toPcm16k\(.*?\n}\n", source, re.S).group(0)
    script = (
        function
        + """
const rate = 48000, n = 48000;
const tone = new Float32Array(n);
for (let i = 0; i < n; i++) tone[i] = 0.5 * Math.sin(2 * Math.PI * 440 * i / rate);
const loud = new Float32Array(300).fill(3);
const out = new Int16Array(toPcm16k([tone.slice(0, 20000), tone.slice(20000), loud], rate));
const peak = Math.max(...out.slice(0, 16000));
console.log(JSON.stringify({ length: out.length, peak, last: out[out.length - 1] }));
"""
    )
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert result["length"] == 16100  # (48000 + 300) / 3
    assert 15000 < result["peak"] < 16500  # 0.5 of full scale, a little lower from averaging
    assert result["last"] == 32767  # too loud: clipped, not wrapped around
