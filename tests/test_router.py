import os

import pytest

from abdoh.claude.brain import NOT_CONNECTED, BrainError
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


def text_of(reply):
    """A reply is a string, or Claude's sentences as they arrive."""
    return reply if isinstance(reply, str) else " ".join(reply)


class FakeRun:
    def __init__(self, fail=False):
        self.ran = []
        self.fail = fail

    def __call__(self, command, allow_run):
        if self.fail:
            raise ActionError("I couldn't open that link.")
        self.ran.append(command.name)
        return [text for kind, text in command.actions if kind == "say"]


class FakeBrain:
    def __init__(self, chunks=("Tokyo is the capital of Japan.",), error=None):
        self.chunks = chunks
        self.error = error
        self.asked = []
        self.closed = False

    def stream(self, prompt, image_png=None):
        self.asked.append((prompt, image_png))
        if self.error:
            raise self.error
        try:
            yield from self.chunks
        finally:
            self.closed = True


class FakeAct:
    def __init__(self, fail=None):
        self.done = []
        self.fail = fail

    def __call__(self, kind, arg):
        if self.fail:
            raise ActionError(self.fail)
        self.done.append((kind, arg))


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text(COMMANDS, encoding="utf-8")
    run = FakeRun()
    router = Router(Config(app_dir=tmp_path), CommandRegistry(path), run=run, act=FakeAct())
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


def test_question_goes_to_claude_in_your_own_words(setup):
    router, run, _ = setup
    router.brain = FakeBrain()
    reply = router.handle("Hey Abdoh, what's the capital of Japan?")
    assert not isinstance(reply, str)  # streamed
    assert text_of(reply) == "Tokyo is the capital of Japan."
    assert router.brain.asked == [("what's the capital of Japan?", None)]


def test_claude_reply_is_streamed_sentence_by_sentence(setup):
    router, _, _ = setup
    router.brain = FakeBrain(["Tokyo is the capital. ", "It's big."])
    assert list(router.handle("capital of japan")) == ["Tokyo is the capital.", "It's big."]


def test_claude_actions_run_and_are_remembered(setup):
    router, _, _ = setup
    router.brain = FakeBrain(["ACTION open_url: https://www.python.org\n", "Opening it now."])
    assert text_of(router.handle("Abdoh, open the Python website")) == "Opening it now."
    assert router._act.done == [("open_url", "https://www.python.org")]
    turn = router.last_turn
    assert turn.request == "open the Python website"
    assert turn.actions == [("open_url", "https://www.python.org")]
    assert turn.answer == "Opening it now."


def test_failed_claude_action_is_spoken(setup):
    router, _, _ = setup
    router._act = FakeAct(fail="I couldn't find an app called Foo.")
    router.brain = FakeBrain(["ACTION open_app: Foo\n", "Opening Foo."])
    assert text_of(router.handle("open foo please")) == (
        "I couldn't find an app called Foo. Opening Foo."
    )


def test_thinking_is_signalled_before_claude(setup):
    router, _, _ = setup
    notes = []
    router.on_thinking = lambda: notes.append("thinking")
    router.brain = FakeBrain()
    reply = router.handle("capital of japan")
    assert notes == ["thinking"]  # right away, before the answer is read
    text_of(reply)


def test_commands_win_over_claude(setup):
    router, _, _ = setup
    router.brain = FakeBrain()
    assert router.handle("good morning abdoh") == "Good morning!"
    assert router.brain.asked == []


@pytest.fixture
def screen_router(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text(COMMANDS, encoding="utf-8")
    notes = []
    router = Router(
        Config(app_dir=tmp_path),
        CommandRegistry(path),
        brain=FakeBrain(["Here is the text."]),
        run=FakeRun(),
        act=FakeAct(),
        capture=lambda: b"PNG",
        on_thinking=lambda: notes.append("thinking"),
    )
    return router, notes


def test_translate_screen_default_target(screen_router):
    router, notes = screen_router
    assert text_of(router.handle("Abdoh, translate what's on my screen")) == "Here is the text."
    prompt, image = router.brain.asked[0]
    assert "into English" in prompt and image == b"PNG"
    assert notes == ["thinking"]


def test_translate_screen_to_language(screen_router):
    router, _ = screen_router
    text_of(router.handle("Hey Abdoh, translate my screen to Arabic"))
    assert "into Arabic" in router.brain.asked[0][0]


def test_summarize_screen(screen_router):
    router, _ = screen_router
    text_of(router.handle("Abdoh, summarize my screen"))
    assert "Summarize" in router.brain.asked[0][0]
    assert router.brain.asked[0][1] == b"PNG"


def test_screen_skill_without_claude(screen_router):
    router, notes = screen_router
    router.brain = None
    assert router.handle("summarize my screen") == NOT_CONNECTED
    assert notes == []


def test_screen_capture_error_is_spoken(screen_router):
    router, _ = screen_router

    def broken():
        raise ScreenCaptureError("Your screenshot came out completely black.")

    router._capture = broken
    assert "black" in text_of(router.handle("summarize my screen"))


def test_claude_error_is_spoken(setup):
    router, _, _ = setup
    router.brain = FakeBrain(error=BrainError("I couldn't reach Claude right now."))
    assert text_of(router.handle("capital of japan")) == "I couldn't reach Claude right now."


def test_stopping_early_closes_claude(setup):
    router, _, _ = setup
    brain = FakeBrain(["One. ", "Two. ", "Three."])
    router.brain = brain
    reply = router.handle("count to three")
    assert next(reply) == "One."
    reply.close()
    assert brain.closed
    assert router.last_turn.answer == "One."


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


def test_commands_file_error_before_a_claude_answer(setup):
    router, _, path = setup
    router.brain = FakeBrain(["Tokyo."])
    path.write_text("- name: [broken", encoding="utf-8")
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 5))
    assert list(router.handle("capital of japan")) == [COMMANDS_FILE_ERROR, "Tokyo."]
