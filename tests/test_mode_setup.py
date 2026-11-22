"""Modes know your setup: a mode that needs screens or speakers that aren't connected asks
first, and runs with what's there on a yes (fakes for the screens and speakers)."""

import pytest
import yaml
from test_router import FakeAct, FakeBrain

from abdoh.commands.actions import ActionError, claude_action
from abdoh.commands.registry import CommandRegistry
from abdoh.config import Config
from abdoh.displays import Displays, Monitor
from abdoh.modes.controls import ModeControls
from abdoh.modes.engine import WONT, ModeEngine
from abdoh.modes.model import parse_modes
from abdoh.router import ANSWER_NOTE, Router
from abdoh.system_skills import Done, Question

MODES = """
- name: Study
  settings:
    displays: ['2', '3']
    audio_output: C34H89x
  actions:
    - say: Focus time.
    - window: Brave to 3 maximized
    - window: Discord to 2 left
  schedule: ["weekdays 09:00"]
- name: Work
  settings:
    displays: all
  actions:
    - window: Code to 1 maximized
"""

LAPTOP = Monitor("laptop-id", "", True, True, True, gdi=r"\\.\DISPLAY1")
HP = Monitor("hp-id", "HP 32f", False, True, gdi=r"\\.\DISPLAY2")
WIDE = Monitor("wide-id", "C34H89x", False, True, gdi=r"\\.\DISPLAY3")


class Backend:
    def __init__(self, monitors):
        self.monitors_now = list(monitors)
        self.set_to = None

    def monitors(self):
        return list(self.monitors_now)

    def set_active(self, ids):
        self.set_to = set(ids)


class Output:
    def __init__(self, name, default=False):
        self.id, self.name, self.default = name, name, default


class Computer:
    def __init__(self, tmp_path, monitors, speakers=("Speakers (Realtek(R) Audio)",)):
        self.displays = Displays(tmp_path / "displays.json", Backend([LAPTOP, HP, WIDE]))
        self.displays.all()  # numbered 1, 2, 3 while docked
        self.displays.backend.monitors_now = list(monitors)
        self.outputs = [Output(name, i == 0) for i, name in enumerate(speakers)]
        self.calls = []

    def audio_outputs(self):
        return self.outputs

    def screens(self, spec):
        self.calls.append(("screens", spec))

    def set_audio_output(self, name):
        self.calls.append(("audio_output", name))

    def restore_audio_output(self, snapshot):
        self.calls.append(("restore audio_output", snapshot))


def make(tmp_path, monitors, speakers=("Speakers (Realtek(R) Audio)",), clock=None):
    computer = Computer(tmp_path, monitors, speakers)
    ran = []

    def run(actions):
        ran.extend(actions)
        return [value for kind, value in actions if kind == "say"]

    engine = ModeEngine(
        lambda: parse_modes(yaml.safe_load(MODES)),
        ModeControls(computer, daemon=None),
        run,
        tmp_path / "mode_state.json",
        **({"clock": clock} if clock else {}),
    )
    computer.modes = engine
    return engine, computer, ran


# ----- what a mode needs -----


def test_with_everything_connected_a_mode_runs_as_before(tmp_path):
    engine, computer, ran = make(tmp_path, [LAPTOP, HP, WIDE], ("C34H89x", "Speakers"))
    assert engine.activate("Study") == "Focus time."
    assert ("screens", "only 2, 3") in computer.calls
    assert ("window", "Brave to 3 maximized") in ran


def test_undocked_a_mode_asks_first_and_changes_nothing(tmp_path):
    engine, computer, ran = make(tmp_path, [LAPTOP])
    reply = engine.activate("Study")
    assert isinstance(reply, Question)
    assert reply == (
        "Study mode wants screens 2 and 3 and the C34H89x speakers, but only screen 1, "
        "Laptop screen, is connected. Run it on what's connected?"
    )
    assert computer.calls == [] and ran == [] and engine.current is None


def test_yes_runs_it_with_what_is_connected(tmp_path):
    engine, computer, ran = make(tmp_path, [LAPTOP])
    engine.activate("Study")
    assert engine.answer("yes") == "Focus time."
    assert not any(kind == "screens" for kind, _ in computer.calls)  # never zero screens
    assert not any(kind == "audio_output" for kind, _ in computer.calls)  # not there: skipped
    assert ("window", "brave to 1 maximized") in ran  # windows go to the main screen
    assert ("window", "discord to 1 left") in ran
    assert engine.current == "Study"


def test_some_screens_connected_are_used(tmp_path):
    engine, computer, ran = make(tmp_path, [LAPTOP, HP])
    question = engine.activate("Study")
    assert "wants screen 3 and the C34H89x speakers" in question
    assert "only screens 1 and 2 are connected" in question
    engine.answer("yeah")
    assert ("screens", "only 2") in computer.calls
    assert ("window", "Discord to 2 left") in ran  # its screen is there: as it was


def test_no_leaves_everything_as_it_is(tmp_path):
    engine, computer, ran = make(tmp_path, [LAPTOP])
    engine.activate("Study")
    assert engine.answer("no") == WONT
    assert computer.calls == [] and ran == [] and engine.current is None
    assert engine.answer("yes") is None  # the question is gone


def test_something_else_leaves_the_question_to_claude_once(tmp_path):
    engine, computer, ran = make(tmp_path, [LAPTOP])
    engine.activate("Study")
    assert engine.answer("just use the laptop then") is None
    assert engine.open_question().startswith("Study mode wants")
    assert engine.asked_mode() == "Study"
    assert engine.answer_from_claude("yes") == "Focus time."
    assert engine.current == "Study"
    engine.activate("Study")  # already fits now? no: still undocked, so it asks again
    engine.answer("what time is it")  # the next request isn't an answer...
    assert engine.answer("yes") is None  # ...and after it the question is gone
    assert engine.open_question() is None


def test_the_question_expires(tmp_path):
    now = [0.0]
    engine, computer, ran = make(tmp_path, [LAPTOP], clock=lambda: now[0])
    engine.activate("Study")
    now[0] = 61.0
    assert engine.answer("yes") is None and engine.current is None


def test_a_schedule_runs_with_what_is_there_and_says_what_it_left_out(tmp_path):
    from datetime import datetime

    engine, computer, ran = make(tmp_path, [LAPTOP])
    said = engine.tick(datetime(2026, 11, 23, 9, 0))  # a Monday
    assert engine.current == "Study"
    assert said.startswith("Study mode. But screens 2 and 3 and the C34H89x speakers aren't")
    assert "so I left them out" in said


def test_work_mode_with_all_screens_needs_nothing(tmp_path):
    engine, computer, ran = make(tmp_path, [LAPTOP])
    assert engine.activate("Work") == Done("Work mode.")
    assert ("screens", "all") in computer.calls


# ----- by voice, from commands and from Claude -----


@pytest.fixture
def router(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text(
        '- name: evening\n  triggers: ["time to study"]\n  actions:\n    - mode: Study\n',
        encoding="utf-8",
    )
    router = Router(Config(app_dir=tmp_path), CommandRegistry(path), act=FakeAct())
    engine, computer, ran = make(tmp_path, [LAPTOP])
    router.modes = engine
    router.computer = computer
    return router


def test_by_voice_it_asks_and_yes_runs_it(router):
    reply = router.handle("study mode")
    assert isinstance(reply, Question)  # Abdoh listens for the answer
    assert router.handle("yes") == "Focus time."
    assert router.modes.current == "Study"


def test_by_voice_no_cancels(router):
    router.handle("study mode")
    assert router.handle("no") == WONT
    assert router.modes.current is None


def test_claude_decides_about_other_answers(router):
    router.brain = FakeBrain(("ACTION answer: yes\n",))
    router.handle("study mode")
    reply = router.handle("ok just put everything on this screen")
    assert " ".join(reply) == "Focus time."  # the mode's own words
    prompt = router.brain.asked[0][0]
    question = router.modes.open_question() or "Study mode wants"
    assert prompt.startswith(ANSWER_NOTE.split("{question}")[0])
    assert question.startswith("Study mode wants")
    assert router.modes.current == "Study"
    assert router.last_turn.actions == [("mode", "Study")]


def test_claude_can_say_no_too(router):
    router.brain = FakeBrain(("ACTION answer: no\n",))
    router.handle("study mode")
    assert " ".join(router.handle("hmm actually leave it")) == WONT
    assert router.modes.current is None


def test_without_a_question_claude_cant_answer(router):
    router.brain = FakeBrain(("ACTION answer: yes\n", "Sure."))
    assert " ".join(router.handle("tell me a joke")) == "Sure."
    assert "Abdoh just asked" not in router.brain.asked[0][0]


def test_a_command_that_switches_the_mode_asks_too(router):
    reply = router.handle("time to study")
    assert isinstance(reply, Question) and "Study mode wants" in reply


def test_claude_switching_the_mode_gets_the_question_spoken(tmp_path):
    engine, computer, ran = make(tmp_path, [LAPTOP])
    with pytest.raises(ActionError) as e:
        claude_action("mode", "Study", computer)
    assert str(e.value).endswith("Run it on what's connected?")
    assert engine.answer("yes") == "Focus time."


def test_screens_are_named_in_order():
    from abdoh.modes.controls import _screens_text

    assert _screens_text(["3", "2"]) == "screens 2 and 3"
    assert _screens_text(["2"]) == "screen 2"
    assert _screens_text(["tv", "1", "3", "2"]) == "screens 1, 2 and 3 and the tv"


def test_from_the_window_or_tray_the_question_is_spoken_and_answered(tmp_path):
    from fakes import FakeTranscriber, FakeWakeWord

    from abdoh.daemon import Daemon
    from abdoh.speech.tts import FakeSpeaker

    engine, computer, ran = make(tmp_path, [LAPTOP])
    router = Router(Config(app_dir=tmp_path), CommandRegistry(tmp_path / "none.yaml"))
    daemon = Daemon(
        Config(app_dir=tmp_path), router, FakeSpeaker(), None, FakeWakeWord(10_000),
        FakeTranscriber([]),
    )  # fmt: skip
    daemon.use_modes(engine)
    daemon._switch_mode("Study")
    assert daemon.speaker.said[0].startswith("Study mode wants screens 2 and 3")
    assert daemon._take_listen_now() is True  # it listens for your answer
