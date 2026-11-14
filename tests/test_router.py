import os

import pytest

from abdoh.claude.client import NOT_CONNECTED, ClaudeError
from abdoh.claude.screen import ScreenCaptureError
from abdoh.commands.actions import ActionError
from abdoh.commands.registry import CommandRegistry
from abdoh.config import Config
from abdoh.router import COMMANDS_FILE_ERROR, UNKNOWN, Router

COMMANDS = """
- name: good_morning
  triggers: ["good morning"]
  actions:
    - say: "Good morning!"
    - open_url: "https://youtube.com/x"
- name: open_mail
  triggers: ["open my mail"]
  actions:
    - open_url: "https://mail.google.com"
"""


class FakeRun:
    def __init__(self, fail=False):
        self.ran = []
        self.fail = fail

    def __call__(self, command, allow_run):
        if self.fail:
            raise ActionError("I couldn't open that link.")
        self.ran.append(command.name)
        return [text for kind, text in command.actions if kind == "say"]


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text(COMMANDS, encoding="utf-8")
    run = FakeRun()
    router = Router(Config(app_dir=tmp_path), CommandRegistry(path), run=run)
    return router, run, path


def test_command_by_voice_phrase(setup):
    router, run, _ = setup
    assert router.handle("Good morning, Abdoh.") == "Good morning!"
    assert run.ran == ["good_morning"]


def test_silent_command(setup):
    router, run, _ = setup
    assert router.handle("Hey Abdoh, open my mail") == ""
    assert run.ran == ["open_mail"]


def test_unknown_phrase_without_claude(setup):
    router, run, _ = setup
    reply = router.handle("Abdoh, juggle three oranges")
    assert reply == f"{UNKNOWN} {NOT_CONNECTED}"
    assert run.ran == []


class FakeClaude:
    def __init__(self, reply="Tokyo is the capital of Japan.", error=None):
        self.reply = reply
        self.error = error
        self.asked = []

    def ask(self, text, image_png=None):
        self.asked.append((text, image_png))
        if self.error:
            raise self.error
        return self.reply


def test_question_goes_to_claude(setup):
    router, run, _ = setup
    router.claude = FakeClaude()
    assert router.handle("Abdoh, what's the capital of Japan?") == "Tokyo is the capital of Japan."
    assert router.claude.asked == [("whats the capital of japan", None)]


def test_commands_win_over_claude(setup):
    router, run, _ = setup
    router.claude = FakeClaude()
    assert router.handle("good morning abdoh") == "Good morning!"
    assert router.claude.asked == []


@pytest.fixture
def screen_router(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text(COMMANDS, encoding="utf-8")
    notes = []
    router = Router(
        Config(app_dir=tmp_path),
        CommandRegistry(path),
        claude=FakeClaude("Here is the text."),
        run=FakeRun(),
        capture=lambda: b"PNG",
        on_thinking=lambda: notes.append("thinking"),
    )
    return router, notes


def test_translate_screen_default_target(screen_router):
    router, notes = screen_router
    assert router.handle("Abdoh, translate what's on my screen") == "Here is the text."
    prompt, image = router.claude.asked[0]
    assert "into English" in prompt and image == b"PNG"
    assert notes == ["thinking"]


def test_translate_screen_to_language(screen_router):
    router, _ = screen_router
    router.handle("Hey Abdoh, translate my screen to Arabic")
    assert "into Arabic" in router.claude.asked[0][0]


def test_summarize_screen(screen_router):
    router, _ = screen_router
    router.handle("Abdoh, summarize my screen")
    assert "Summarize" in router.claude.asked[0][0]
    assert router.claude.asked[0][1] == b"PNG"


def test_screen_skill_without_claude(screen_router):
    router, notes = screen_router
    router.claude = None
    assert router.handle("summarize my screen") == NOT_CONNECTED
    assert notes == []


def test_screen_capture_error_is_spoken(screen_router):
    router, _ = screen_router

    def broken():
        raise ScreenCaptureError("Your screenshot came out completely black.")

    router._capture = broken
    assert "black" in router.handle("summarize my screen")


def test_claude_error_is_spoken(setup):
    router, _, _ = setup
    router.claude = FakeClaude(error=ClaudeError("I couldn't reach Claude right now."))
    assert router.handle("what's the capital of japan") == "I couldn't reach Claude right now."


def test_only_wake_word(setup):
    router, _, _ = setup
    assert router.handle("Hey Abdoh.") == ""


def test_action_error_is_spoken(tmp_path, setup):
    _, _, path = setup
    router = Router(Config(app_dir=tmp_path), CommandRegistry(path), run=FakeRun(fail=True))
    assert router.handle("good morning") == "I couldn't open that link."


def test_commands_file_error_is_reported_once(setup):
    router, run, path = setup
    path.write_text("- name: [broken", encoding="utf-8")
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 5))
    assert router.handle("good morning") == f"{COMMANDS_FILE_ERROR} Good morning!"
    assert router.handle("good morning") == "Good morning!"
