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


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js isn't installed")
def test_a_call_hears_when_you_start_and_stop_talking():
    """phone.js's earStep, the call's ear (story 145), with made-up loudness: a quiet room,
    then two seconds of talking; a knock; a room that slowly gets louder (a fan), then talking
    over it; and someone who never stops (sent after 45 s)."""
    import json
    import re

    source = (SRC / "phone" / "web" / "phone.js").read_text(encoding="utf-8")
    parts = [
        re.search(r"const CALL = \{.*?\n\};\n", source, re.S).group(0),
        re.search(r"function newEar\(.*?\n}\n", source, re.S).group(0),
        re.search(r"function earStep\(.*?\n}\n", source, re.S).group(0),
    ]
    script = (
        "\n".join(parts)
        + """
const MS = 2048 / 48000 * 1000;
function run(ear, levels, over = false) {
  const out = [];
  levels.forEach((rms, i) => {
    const got = earStep(ear, rms, MS, over);
    if (got) out.push([got, Math.round(i * MS)]);
  });
  return out;
}
const blocks = (seconds, rms) => Array(Math.round(seconds * 1000 / MS)).fill(rms);
// words, with short dips between them
const talk = (seconds) => blocks(seconds, 0).map((_, i) => (i % 9 === 4 ? 0.02 : 0.12));
const fan = newEar();
const result = {
  talk: run(newEar(), [...blocks(1, 0.003), ...talk(2), ...blocks(2, 0.003)]),
  knock: run(newEar(), [...blocks(1, 0.003), ...blocks(0.15, 0.3), ...blocks(2, 0.003)]),
  fan: run(fan, [...blocks(1, 0.003), ...blocks(30, 0.012), ...blocks(30, 0.03)]),
  floor: fan.floor,
  overFan: run(fan, [...talk(1.5), ...blocks(2, 0.03)]),
  endless: run(newEar(), [...blocks(0.5, 0.003), ...blocks(50, 0.1)]),
  // While Abdoh talks (story 146): what's left of its voice after the echo canceller...
  echo: run(newEar(), blocks(10, 0).map((_, i) => 0.005 + 0.02 * Math.abs(Math.sin(i))), true),
  knockOver: run(newEar(), [...blocks(1, 0.01), ...blocks(0.15, 0.3), ...blocks(2, 0.01)], true),
  talkOver: run(newEar(), [...blocks(1, 0.01), ...talk(2), ...blocks(2, 0.01)], true),
};
console.log(JSON.stringify(result));
"""
    )
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout)
    (start, began), (end, ended) = got["talk"]
    assert start == "start" and 1000 <= began <= 1200  # 120 ms into your words
    assert end == "end" and 4150 <= ended <= 4300  # 1.2 s after you stopped
    assert [kind for kind, _ in got["knock"]] == ["start", "drop"]  # a knock isn't words
    assert got["fan"] == [] and got["floor"] > 0.02  # a hum that comes up slowly isn't you
    assert [kind for kind, _ in got["overFan"]] == ["start", "end"]  # talking over it is
    (start, began), (end, ended) = got["endless"][:2]
    assert end == "end" and 44800 <= ended - began <= 45000  # sent at 45 s
    assert got["echo"] == []  # Abdoh's own voice, what the phone leaves of it, isn't you
    assert got["knockOver"] == []  # over Abdoh, a knock doesn't even start a turn
    (start, began), (end, ended) = got["talkOver"]
    assert start == "start" and 1250 <= began <= 1500  # about 0.3 s into your words
    assert end == "end" and 4150 <= ended <= 4300
