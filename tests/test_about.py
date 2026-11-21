"""Krekos knows about itself: its parts and settings go to Claude, and how it is right now (the
mode that's on) comes with every message."""

from datetime import datetime
from pathlib import Path

from abdoh import __version__
from abdoh.about import about, state_line
from abdoh.claude.brain import stamp
from abdoh.config import ClaudeConfig, Config


def setup_files(app_dir: Path) -> Config:
    (app_dir / "modes.yaml").write_text(
        "- name: Work\n  icon: briefcase\n  actions:\n    - say: Go\n"
        "- name: Movie\n  icon: film\n  actions:\n    - say: Enjoy\n",
        encoding="utf-8",
    )
    (app_dir / "commands.yaml").write_text(
        '- name: hi\n  triggers: ["good morning"]\n  actions:\n    - say: "Morning!"\n',
        encoding="utf-8",
    )
    (app_dir / "lamps.json").write_text('[{"name": "Desk lamp", "mac": "aa", "ip": "1.2.3.4"}]')
    return Config(
        app_dir=app_dir,
        piper_voice_en="en_US-ryan-medium",
        confirm_actions="words",
        duck_others=False,
        claude=ClaudeConfig(code_model="sonnet", effort="high"),
    )


def test_it_describes_its_parts_and_settings(tmp_path):
    text = about(setup_files(tmp_path), "code")
    assert f"Version {__version__}" in text
    assert '"hey krekos"' in text and "hey_krekos" in text  # the wake word model
    assert "Any voice saying it wakes you" in text  # no voice check taught yet
    assert "Whisper" in text  # no Parakeet model in this test folder
    assert "en_US-ryan-medium for English" in text or "Windows voice" in text
    assert "Claude Code" in text and "model: sonnet" in text and "effort high" in text
    assert "a few words" in text and "other apps keep their volume" in text
    assert "Work, Movie" in text and "Desk lamp" in text
    assert '"good morning"' in text  # a command from the example commands file


def test_through_the_api_it_names_the_model(tmp_path):
    text = about(Config(app_dir=tmp_path, claude=ClaudeConfig(model="claude-opus-5-5")), "api")
    assert "Anthropic API" in text and "claude-opus-5-5" in text


def test_parakeet_v3_is_described_when_it_is_there(tmp_path):
    from abdoh.audio.stt import PARAKEET_DIR, PARAKEET_FILES

    folder = tmp_path / PARAKEET_DIR
    folder.mkdir(parents=True)
    for name in PARAKEET_FILES:
        (folder / name).write_bytes(b"x")
    assert "Parakeet TDT 0.6b v3" in about(Config(app_dir=tmp_path))


def test_a_broken_part_is_left_out_not_an_error(tmp_path):
    (tmp_path / "modes.yaml").write_text(": not yaml [", encoding="utf-8")
    (tmp_path / "lamps.json").write_text("{broken")
    text = about(Config(app_dir=tmp_path))
    assert "Smart lamps: none set up yet." in text


def test_how_it_is_right_now():
    assert state_line("Work") == "mode on: Work; voice replies on"
    assert state_line(None, voice=False, paused=True) == (
        "no mode on; voice replies off (the user reads); not listening for the wake word"
    )
    now = datetime(2026, 11, 21, 9, 5)
    assert stamp("hi", now, "mode on: Work").startswith(
        "[Saturday, November 21, 2026, 9:05 AM; mode on: Work]"
    )
    assert stamp("hi", now) == "[Saturday, November 21, 2026, 9:05 AM]\nhi"


def test_claude_code_gets_it_in_its_instructions_and_with_each_message(tmp_path):
    from test_claude_code import FakePopen, make_brain

    brain = make_brain(tmp_path, FakePopen())
    assert "About you, Krekos" in brain.instructions()
    brain.state = lambda: "mode on: Movie; voice replies on"
    sent = []

    class Pipe:
        def write(self, text):
            sent.append(text)

        def flush(self):
            pass

    session = type("S", (), {"proc": type("P", (), {"stdin": Pipe()})()})()
    brain._send(session, "what mode is on")
    assert "mode on: Movie" in sent[0] and "what mode is on" in sent[0]


def test_the_api_gets_it_too(tmp_path):
    from abdoh.claude.api import ApiBrain

    brain = ApiBrain(Config(app_dir=tmp_path, anthropic_api_key="sk-test"))
    brain.state = lambda: "mode on: Work; voice replies on"
    params = brain.request("which mode is on")
    assert "About you, Krekos" in params["system"]
    assert params["messages"][0]["content"][-1]["text"].startswith("[Krekos now: mode on: Work")


def test_a_broken_state_is_left_out(tmp_path):
    from abdoh.claude.api import ApiBrain

    brain = ApiBrain(Config(app_dir=tmp_path, anthropic_api_key="sk-test"))

    def broken():
        raise RuntimeError("modes went away")

    brain.state = broken
    assert brain.request("hi")["messages"][0]["content"][-1]["text"] == "hi"


def test_the_daemon_tells_claude_the_mode():
    from test_daemon import StubRouter, make_daemon

    daemon = make_daemon(StubRouter([]))
    assert daemon._state_line() == "no mode on; voice replies on"
    daemon.modes = type("Modes", (), {"current": "Work"})()
    daemon.voice_enabled = False
    assert daemon._state_line() == "mode on: Work; voice replies off (the user reads)"
