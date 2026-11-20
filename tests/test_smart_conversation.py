"""Thinks before it talks: things you ask it to do are done with a short sound, not words,
and it only listens for more after a real conversation. Speech right after a reply that wasn't
meant for Xanthos is left alone."""

from types import SimpleNamespace

import pytest
from test_daemon import StubRouter, make_daemon
from test_local_skills import FakeComputer
from test_router import FakeBrain, setup  # noqa: F401 - setup is a fixture

from abdoh.config import Config
from abdoh.events import Bus
from abdoh.local_skills import LocalSkills
from abdoh.router import ASIDE
from abdoh.system_skills import Done, Question


class Sounds:
    def __init__(self):
        self.played = []

    def play(self, name):
        self.played.append(name)

    def stop_ticking(self):
        pass

    def start_ticking(self, name="thinking", every=3.0):
        pass


def daemon_for(replies, cfg=None, turn=None):
    router = StubRouter(replies)
    router.last_turn = turn
    bus = Bus()
    daemon = make_daemon(router, cfg=cfg, bus=bus)
    daemon.earcons = Sounds()
    seen = []
    bus.emit = lambda kind, value=None: seen.append((kind, value))
    return daemon, seen


# ----- things you ask it to do -----


def test_a_done_action_plays_a_sound_and_says_nothing():
    daemon, seen = daemon_for([Done("Opening Spotify.")])
    daemon.handle_text("open spotify", voice=True)
    assert daemon.speaker.said == []
    assert daemon.earcons.played == ["done"]
    assert ("history", "Xanthos: Opening Spotify.") in seen  # the window still shows it
    assert daemon._awaiting_answer is False  # and it doesn't listen for more


def test_you_can_ask_for_words_instead():
    daemon, _ = daemon_for([Done("Opening Spotify.")], cfg=Config(confirm_actions="words"))
    daemon.handle_text("open spotify", voice=True)
    assert daemon.speaker.said == ["Opening Spotify."]


def test_answers_and_errors_are_still_spoken():
    daemon, _ = daemon_for(["It's 9:41.", "I couldn't find that app."])
    daemon.handle_text("what time is it", voice=True)
    daemon.handle_text("open the moon", voice=True)
    assert daemon.speaker.said == ["It's 9:41.", "I couldn't find that app."]
    assert daemon.earcons.played == []


def test_with_voice_replies_off_there_is_no_sound_either():
    daemon, _ = daemon_for([Done("")])
    daemon.voice_enabled = False
    daemon.handle_text("pause")
    assert daemon.earcons.played == []


def test_claude_doing_something_without_a_word_is_done():
    turn = SimpleNamespace(actions=[("play_youtube", "jazz")])
    daemon, seen = daemon_for([iter([])], turn=turn)
    daemon.handle_text("play some jazz", voice=True)
    assert daemon.speaker.said == [] and daemon.earcons.played == ["done"]
    assert ("history", "Xanthos: Done: play youtube jazz.") in seen
    assert daemon._awaiting_answer is False


def test_after_claude_did_something_it_doesnt_listen_for_more():
    turn = SimpleNamespace(actions=[("open_app", "Spotify")])
    daemon, _ = daemon_for([iter(["Spotify is open, enjoy."])], turn=turn)
    daemon.handle_text("open spotify and say something nice", voice=True)
    assert daemon._awaiting_answer is False


def test_unless_it_asked_you_something():
    turn = SimpleNamespace(actions=[("open_url", "https://youtube.com")])
    daemon, _ = daemon_for([iter(["I found three. Which one?"])], turn=turn)
    daemon.handle_text("find me a video about cats", voice=True)
    assert daemon._awaiting_answer is True and daemon._soft_chime is False


def test_a_conversation_listens_for_more():
    daemon, _ = daemon_for([iter(["OOP organizes code into objects."])])
    daemon.handle_text("what is oop", voice=True)
    assert daemon._awaiting_answer is True and daemon._soft_chime is True


# ----- the local skills and commands -----


@pytest.fixture
def skills():
    return LocalSkills(FakeComputer())


@pytest.mark.parametrize(
    "said",
    [
        "volume 30",
        "pause",
        "next song",
        "brightness 50",
        "take a screenshot",
        "take a note buy milk",
    ],
)
def test_doing_things_is_done(skills, said):
    assert isinstance(skills.handle(said, said), Done)


@pytest.mark.parametrize("said", ["what time is it", "whats the volume", "battery"])
def test_telling_things_is_said(skills, said):
    reply = skills.handle(said, said)
    assert reply and not isinstance(reply, Done)


@pytest.mark.parametrize(
    "said", ["thanks", "thank you", "okay", "ok thanks", "thats it", "great", "perfect", "bye"]
)
def test_thanks_and_okay_just_end_it(skills, said):
    reply = skills.handle(said, said)
    assert reply == "" and not isinstance(reply, Done)


def test_a_command_without_words_is_done(setup):  # noqa: F811
    router, _, _ = setup
    assert isinstance(router.handle("open my mail"), Done)
    reply = router.handle("good morning")  # its own "say" action: spoken
    assert reply == "Good morning!" and not isinstance(reply, Done)


def test_a_question_stays_a_question(skills):
    assert isinstance(skills.handle("shut down the computer"), Question)


# ----- said right after a reply, maybe to someone else -----


def test_speech_after_a_reply_may_be_ignored(setup):  # noqa: F811
    router, _, _ = setup
    router.brain = FakeBrain(("ACTION ignore: not for me\n",))
    assert " ".join(router.handle("did you feed the cat", aside=True)) == ""
    assert router.brain.asked[0][0].startswith(ASIDE)
    assert router.last_turn.ignored is True


def test_ignoring_is_only_allowed_right_after_a_reply(setup):  # noqa: F811
    router, _, _ = setup
    router.brain = FakeBrain(("ACTION ignore: not for me\n", "The cat was fed."))
    assert " ".join(router.handle("did you feed the cat")) == "The cat was fed."
    assert router.last_turn.ignored is False
    assert not router.brain.asked[0][0].startswith(ASIDE)


def test_meant_for_xanthos_after_all_is_answered(setup):  # noqa: F811
    router, _, _ = setup
    router.brain = FakeBrain(("And tomorrow it rains.",))
    assert " ".join(router.handle("and tomorrow", aside=True)) == "And tomorrow it rains."


def test_the_moment_after_a_reply_is_marked_as_aside():
    daemon, _ = daemon_for([iter(["Sunny."]), iter([])])
    daemon.handle_text("weather", voice=True)
    assert daemon._soft_chime is True  # the follow-up window, not an answer to a question
    daemon._handle_spoken("talking to my brother", aside=True)
    assert daemon.router.requests == ["weather", "talking to my brother"]
