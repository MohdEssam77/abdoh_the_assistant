import os

import pytest

from abdoh.claude.brain import NOT_CONNECTED, BrainError
from abdoh.claude.screen import ScreenCaptureError
from abdoh.commands.actions import ActionError
from abdoh.commands.registry import CommandRegistry
from abdoh.config import Config
from abdoh.router import COMMANDS_FILE_ERROR, NOTHING_TO_REMEMBER, UNKNOWN, Router

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

    def __call__(self, command, allow_run, computer=None, slots=None):
        if self.fail:
            raise ActionError("I couldn't open that link.")
        self.ran.append(command.name)
        self.slots = slots
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

    def __call__(self, kind, arg, computer=None):
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
    assert router.handle("Good morning, Krekos.") == "Good morning!"
    assert run.ran == ["good_morning"]


def test_silent_command(setup):
    router, run, _ = setup
    assert router.handle("Hey Krekos, open my mail") == ""
    assert run.ran == ["open_mail"]


def test_unknown_phrase_without_claude(setup):
    router, run, _ = setup
    reply = router.handle("Krekos, juggle three oranges")
    assert reply == f"{UNKNOWN} {NOT_CONNECTED}"
    assert run.ran == []


def test_question_goes_to_claude_in_your_own_words(setup):
    router, run, _ = setup
    router.brain = FakeBrain()
    reply = router.handle("Hey Krekos, what's the capital of Japan?")
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
    assert text_of(router.handle("Krekos, open the Python website")) == "Opening it now."
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
    assert text_of(router.handle("Krekos, translate what's on my screen")) == "Here is the text."
    prompt, image = router.brain.asked[0]
    assert "into English" in prompt and image == b"PNG"
    assert notes == ["thinking"]


def test_translate_screen_to_language(screen_router):
    router, _ = screen_router
    text_of(router.handle("Hey Krekos, translate my screen to Arabic"))
    assert "into Arabic" in router.brain.asked[0][0]


def test_summarize_screen(screen_router):
    router, _ = screen_router
    text_of(router.handle("Krekos, summarize my screen"))
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
    assert router.handle("Hey Krekos.") == ""


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


def test_command_with_slots(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text(
        '- name: yt\n  triggers: ["search youtube for {query}"]\n'
        '  actions:\n    - open_url: "https://youtube.com/results?search_query={query}"\n',
        encoding="utf-8",
    )
    run = FakeRun()
    router = Router(Config(app_dir=tmp_path), CommandRegistry(path), run=run)
    assert router.handle("Krekos, search YouTube for lo-fi beats") == ""
    assert run.ran == ["yt"] and run.slots == {"query": "lo fi beats"}


class FakeLocalComputer:
    class Apps:
        @staticmethod
        def find(name):
            return None

    def __init__(self):
        self.pressed = []
        self.apps = self.Apps()

    def media(self, key):
        self.pressed.append(key)


def test_local_skills_before_claude(setup):
    router, _, _ = setup
    router.brain = FakeBrain()
    router.computer = FakeLocalComputer()
    assert router.handle("Krekos, next song") == ""
    assert router.computer.pressed == ["next"]
    assert router.brain.asked == []


def test_local_skill_that_cant_help_falls_through_to_claude(setup):
    router, _, _ = setup
    router.brain = FakeBrain(["Opening YouTube."])
    router.computer = FakeLocalComputer()
    assert text_of(router.handle("open youtube")) == "Opening YouTube."
    assert router.brain.asked == [("open youtube", None)]


def test_your_commands_win_over_local_skills(setup):
    router, _, _ = setup
    router.computer = FakeLocalComputer()
    assert router.handle("good morning") == "Good morning!"
    assert router.computer.pressed == []


@pytest.fixture
def learning(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text(COMMANDS, encoding="utf-8")
    run = FakeRun()
    brain = FakeBrain(["ACTION open_url: https://www.python.org\n", "Opening it."])
    router = Router(
        Config(app_dir=tmp_path), CommandRegistry(path), brain=brain, run=run, act=FakeAct()
    )
    return router, run, path


def test_remember_that_saves_what_claude_did(learning):
    router, run, path = learning
    text_of(router.handle("Krekos, open the Python website"))
    reply = router.handle("Krekos, remember that")
    assert reply == "Saved. Next time just say: open the python website."
    assert "learned_open_the_python_website" in path.read_text(encoding="utf-8")
    # Now it's an instant command: no Claude
    router.brain.asked.clear()
    assert router.handle("open the Python website") == ""
    assert run.ran == ["learned_open_the_python_website"]
    assert router.brain.asked == []


def test_remember_that_as_a_phrase(learning):
    router, run, _ = learning
    text_of(router.handle("open the Python website"))
    assert router.handle("remember that as python time") == (
        "Saved. Next time just say: python time."
    )
    router.handle("python time")
    assert run.ran == ["learned_python_time"]


def test_remember_needs_something_claude_did(learning):
    router, _, _ = learning
    assert router.handle("remember that") == NOTHING_TO_REMEMBER
    router.brain = FakeBrain(["Tokyo is the capital."])  # an answer, but no action
    text_of(router.handle("capital of japan"))
    assert router.handle("remember that") == NOTHING_TO_REMEMBER


def test_failed_actions_are_not_remembered(learning):
    router, _, _ = learning
    router._act = FakeAct(fail="I couldn't open that link.")
    text_of(router.handle("open the Python website"))
    assert router.handle("remember that") == NOTHING_TO_REMEMBER


def test_remember_twice_does_not_duplicate(learning):
    router, _, path = learning
    text_of(router.handle("open the Python website"))
    router.handle("remember that")
    assert router.handle("save that") == NOTHING_TO_REMEMBER
    assert path.read_text(encoding="utf-8").count("- name: learned_") == 1


def test_remember_refuses_when_the_file_has_an_error(learning):
    router, _, path = learning
    text_of(router.handle("open the Python website"))
    path.write_text("- name: [broken", encoding="utf-8")
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 5))
    router.registry.refresh()
    assert "Fix it first" in router.handle("remember that")
    assert path.read_text(encoding="utf-8") == "- name: [broken"


def test_follow_up_gets_the_previous_exchange(learning):
    router, _, _ = learning
    router.brain = FakeBrain(["It's sunny in Cairo."])
    text_of(router.handle("what's the weather in Cairo?"))
    text_of(router.handle("and what about tomorrow?"))
    prompt = router.brain.asked[1][0]
    assert "User: what's the weather in Cairo?" in prompt
    assert "Krekos: It's sunny in Cairo." in prompt
    assert prompt.endswith("The user now says: and what about tomorrow?")


def test_follow_up_context_expires(learning, monkeypatch):
    router, _, _ = learning
    router.brain = FakeBrain(["It's sunny in Cairo."])
    text_of(router.handle("what's the weather in Cairo?"))
    router.last_turn.finished_at -= router.cfg.claude.followup_seconds + 1
    text_of(router.handle("tell me a joke"))
    assert router.brain.asked[1][0] == "tell me a joke"


# ----- Claude asks to look at the screen -----


class LookingBrain:
    """First reply: asks to look. The next one answers from the picture."""

    def __init__(self, first=("Let me look.\n", "ACTION look: the error\n"), second=("It says ",
                 "the file is missing.")):  # fmt: skip
        self.replies = [first, second]
        self.asked = []
        self.closed = 0

    def stream(self, prompt, image_png=None):
        self.asked.append((prompt, image_png))
        reply = self.replies.pop(0) if self.replies else ("ACTION look: again\n", "Done.")
        try:
            yield from reply
        finally:
            self.closed += 1


def looking_router(tmp_path, brain, **claude):
    from abdoh.claude.screen import FrontWindow
    from abdoh.config import ClaudeConfig

    path = tmp_path / "commands.yaml"
    path.write_text("[]", encoding="utf-8")
    router = Router(
        Config(app_dir=tmp_path, claude=ClaudeConfig(**claude)),
        CommandRegistry(path),
        brain=brain,
        act=FakeAct(),
        capture=lambda: b"PNG",
        window=lambda: FrontWindow("Build failed - Visual Studio Code", "Code", (0, 0, 10, 10)),
    )
    seen = []
    router.on_activity = seen.append
    return router, seen


def test_claude_looks_when_it_needs_to_and_then_answers(tmp_path):
    brain = LookingBrain()
    router, seen = looking_router(tmp_path, brain)
    said = list(router.handle("what does this error mean"))
    assert said == ["Let me look.", "It says the file is missing."]
    assert seen == ["Looking at your screen"]
    (first, no_image), (follow_up, image) = brain.asked
    assert no_image is None and image == b"PNG"
    assert '"what does this error mean"' in follow_up  # the request goes with the picture
    assert 'The window in front is "Build failed - Visual Studio Code" (Code)' in follow_up
    assert brain.closed == 2


def test_no_look_without_asking(tmp_path):
    brain = LookingBrain(first=("Tokyo.",))
    router, seen = looking_router(tmp_path, brain)
    assert list(router.handle("capital of japan")) == ["Tokyo."]
    assert len(brain.asked) == 1 and seen == []


def test_only_one_look_per_request(tmp_path):
    brain = LookingBrain(second=("ACTION look: more\n", "Still can't tell."))
    router, seen = looking_router(tmp_path, brain)
    assert list(router.handle("what's this")) == ["Let me look.", "Still can't tell."]
    assert len(brain.asked) == 2 and seen == ["Looking at your screen"]


def test_no_look_when_the_screen_is_off(tmp_path):
    brain = LookingBrain()
    router, seen = looking_router(tmp_path, brain, allow_screen=False)
    assert list(router.handle("what does this error mean")) == ["Let me look."]
    assert len(brain.asked) == 1 and seen == []


def test_a_look_is_never_remembered_as_a_command(tmp_path):
    router, _ = looking_router(tmp_path, LookingBrain())
    list(router.handle("what does this error mean"))
    assert router.last_turn.actions == []


def test_a_failed_look_is_said(tmp_path):
    brain = LookingBrain()
    router, _ = looking_router(tmp_path, brain)

    def broken():
        raise ScreenCaptureError("I couldn't capture your screen.")

    router._capture = broken
    assert list(router.handle("what's this")) == ["Let me look.", "I couldn't capture your screen."]
