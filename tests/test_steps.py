"""Several things in one request ("stop the music, play arabic music, then open whatsapp"):
done one by one, in order, each the way it would be done alone."""

import pytest
from test_local_skills import FakeComputer
from test_router import COMMANDS, FakeAct, FakeBrain, FakeRun, text_of

from abdoh.commands.registry import CommandRegistry
from abdoh.config import Config
from abdoh.local_skills import LocalSkills
from abdoh.router import STEP, Router
from abdoh.steps import split_steps
from abdoh.system_skills import Done, Question

# ----- where a request splits -----


@pytest.mark.parametrize(
    ("said", "steps"),
    [
        (
            "Stop the current music and play Arabic music, then open WhatsApp.",
            ["Stop the current music", "play Arabic music", "open WhatsApp"],
        ),
        (
            "stop the music. Then play jazz. After that open spotify",
            ["stop the music", "play jazz", "open spotify"],
        ),
        ("set volume to 30 and take a screenshot", ["set volume to 30", "take a screenshot"]),
        ("open WhatsApp, Spotify and Discord", ["open WhatsApp", "open Spotify", "open Discord"]),
        (
            "can you pause the music and then lock the computer",
            ["can you pause the music", "lock the computer"],
        ),
        ("pause the music and what time is it", ["pause the music", "what time is it"]),
    ],
)
def test_things_to_do_one_after_another_are_split(said, steps):
    assert split_steps(said) == steps


@pytest.mark.parametrize(
    "said",
    [
        "play rock and roll",  # a title
        "what's the difference between python and java",  # a question about two things
        "remind me to buy milk and eggs at 5",
        "remind me to call mom and send the email",  # all of it is the reminder
        "search for salt and pepper",
        "tell me a joke and open whatsapp",  # Claude does both, as one request
        "what's the weather and what's the time",  # questions only: Claude answers both
        "Okay, thank you.",
        "Stop the music, please.",
        "open spotify",
        # the owner's, 2026-11-26/27: each was done twice
        "Can you please save this as a PDF? Save the board.",
        "Um I want you to open uh a project of mine in Kodo, so the project is called Unigo.",
        "Stop the music. Play some jazz.",  # two sentences, no "then": Claude does both
        "open chrome and the files of my project",
    ],
)
def test_everything_else_stays_one_request(said):
    assert split_steps(said) == []


@pytest.mark.parametrize(
    "said", ["stop the current music", "stop the arabic music", "pause this song", "stop music"]
)
def test_stopping_whatever_music_is_playing_needs_no_claude(said):
    computer = FakeComputer()
    assert isinstance(LocalSkills(computer).handle(said, said), Done)
    assert computer.calls == [("media", "play_pause")]


def test_playing_some_kind_of_music_is_not_the_play_key():
    assert LocalSkills(FakeComputer()).handle("play jazz music", "play jazz music") is None


# ----- doing them -----

COMMANDS_PLUS = (
    COMMANDS
    + """
- name: arabic_music
  triggers: ["play arabic music"]
  actions:
    - open_url: "https://youtube.com/playlist"
- name: stop_and_mail
  triggers: ["stop the music and open my mail"]
  actions:
    - open_url: "https://mail.google.com"
"""
)


@pytest.fixture
def make(tmp_path):
    """A router with your commands and the built-in skills; `calls`: what was done, in order."""

    def router_with(brain=None):
        path = tmp_path / "commands.yaml"
        path.write_text(COMMANDS_PLUS, encoding="utf-8")
        computer = FakeComputer()
        computer.apps.known["whatsapp"] = "WhatsApp"
        computer.open_app = lambda name: computer.calls.append(("open_app", name)) or name
        run = FakeRun()

        def run_and_note(command, allow_run, computer=None, slots=None):
            calls.append(("command", command.name))
            return run(command, allow_run, computer=computer, slots=slots)

        calls = computer.calls
        router = Router(
            Config(app_dir=tmp_path), CommandRegistry(path), brain=brain, run=run_and_note,
            act=FakeAct(),
        )  # fmt: skip
        router.local = LocalSkills(computer)
        return router, calls

    return router_with


def test_your_example_is_done_in_order_without_claude(make):
    router, calls = make(FakeBrain(["(Claude)"]))
    reply = router.handle("Stop the current music and play Arabic music, then open WhatsApp.")
    assert calls == [("media", "play_pause"), ("command", "arabic_music"), ("open_app", "whatsapp")]
    assert isinstance(reply, Done)  # nothing to say: the done sound
    assert router.brain.asked == []


def test_what_the_steps_say_is_said(make):
    router, calls = make()
    reply = router.handle("set volume to 30 and take a screenshot")
    assert reply == "Volume at 30 percent. Saved a screenshot in your Screenshots folder."
    assert calls == [("volume", 30), ("screenshot",)]


def test_a_command_of_yours_with_and_in_it_runs_as_it_is(make):
    router, calls = make()
    router.handle("stop the music and open my mail")
    assert calls == [("command", "stop_and_mail")]


def test_a_step_only_claude_knows_goes_to_claude_in_its_turn(make):
    router, calls = make(FakeBrain(["ACTION open_url: https://youtube.com/results?q=cats\n"]))
    reply = router.handle("pause the music and find a video about cats then open whatsapp")
    assert calls == [("media", "play_pause")]  # the first step is done at once
    assert text_of(reply) == ""  # Claude's step, then WhatsApp: in order, as the reply is read
    assert calls[-1] == ("open_app", "whatsapp")
    prompt = router.brain.asked[0][0]
    assert prompt == STEP.format(
        request="pause the music and find a video about cats then open whatsapp",
        step="find a video about cats",
    )
    assert router.last_turn.actions == [("open_url", "https://youtube.com/results?q=cats")]


def test_after_the_wake_word_claude_may_still_say_it_wasnt_meant_for_abdoh(make):
    router, calls = make(FakeBrain(["ACTION ignore: not for me\n"]))
    reply = router.handle("find a video about cats and open whatsapp", woken=True)
    assert text_of(reply) == ""
    assert calls == []  # nor was the rest
    assert router.last_turn.ignored


def test_a_question_stops_the_steps_until_you_answer(make):
    router, calls = make()
    reply = router.handle("shut down the computer and open whatsapp")
    assert isinstance(reply, Question)
    assert ("open_app", "whatsapp") not in calls


def test_claude_is_told_to_do_every_step_it_gets():
    from abdoh.claude.brain import ACTIONS

    assert "several things, do every one, in the order they asked" in ACTIONS


def test_tell_me_if_belongs_to_what_it_watches():
    assert split_steps("watch me fill this in and tell me if I get it wrong") == []
    assert split_steps("run the tests and let me know when they pass") == []
    assert split_steps("open spotify and tell me if it's raining") == [
        "open spotify",
        "tell me if it's raining",
    ]


@pytest.mark.parametrize(
    "said",
    [
        "watch the screen while I shop and give me suggestions",
        "watch me shop and give me any tips",
        "look at my screen while I shop and suggest better options",
        "watch me cook and point out anything I miss",
    ],
)
def test_suggestions_belong_to_what_it_watches(said):
    assert split_steps(said) == []


def test_suggestions_alone_are_still_a_step():
    assert split_steps("open amazon and give me some gift ideas") == [
        "open amazon",
        "give me some gift ideas",
    ]
