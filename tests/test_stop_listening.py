"""Being told to stop, in any words: Abdoh goes quiet at once and says nothing. "Stop
listening" also pauses it: then only "Abdoh, start listening" counts, and a wake word set off
by talk in the room makes no sound (story 107, from a friend's test with people in the room)."""

from types import SimpleNamespace

import pytest
from fakes import FakeMic, FakeTranscriber, FakeWakeWord, silent_block, tone_block
from test_daemon import RecordingEarcons, StubRouter, real_router, run_until
from test_interrupt import FakeWatch, Router, long_reply, make_daemon, said_at_least

from abdoh.config import Config
from abdoh.daemon import STOPPED_LISTENING, Daemon
from abdoh.events import Bus
from abdoh.local_skills import interruption_kind, start_request, stop_request
from abdoh.speech.tts import FakeSpeaker

# ----- what counts (said over a reply: mostly the friend's own words, from the log) -----


@pytest.mark.parametrize(
    "said",
    [
        "Um you can stop listening.",
        "Hey Abdoh, you can stop listening now",
        "please stop listening",
        "Okay, stop listening for now.",
        "I'll call you when I need you",
        "Yeah, it should stop listening then.",  # anywhere in what was said over a reply
    ],
)
def test_stop_listening_in_any_words(said):
    assert interruption_kind(said) == "stop_listening"


@pytest.mark.parametrize(
    "said",
    [
        "Uh okay you can stop now.",
        "Yeah, just shut up, shut up, I told you to shut up.",
        "Shut up.",
        "Shut up bitch.",
        "Okay. Thank you. Stop.",
        "stop stop",
        "just stop please",
    ],
)
def test_shut_up_in_any_words(said):
    assert interruption_kind(said) == "stop"


@pytest.mark.parametrize("said", ["Well.", "pain", "Sorry.", "LinkedIn.", "Do you", "See it."])
def test_a_stray_word_or_two_is_a_fragment(said):
    assert interruption_kind(said) == "fragment"  # Abdoh goes on


@pytest.mark.parametrize(
    "said",
    [
        "Stop, what about tomorrow?",  # asks something: that's what to do
        "stop the music",
        "open notepad",
        "what time",
        "Okay, just make a fifty word essay about India.",
    ],
)
def test_requests_stay_requests(said):
    assert interruption_kind(said) == "request"


def test_laughing_is_nothing():
    assert interruption_kind("Heh heh heh.") == "nothing"


def test_after_the_wake_word_all_of_it_must_be_a_stop():
    assert stop_request("you can stop listening now") == "stop_listening"
    assert stop_request("how do I make my laptop stop listening to the mic") == ""
    assert stop_request("Yeah, it should stop listening then.") == ""  # only when loose
    assert stop_request("why did you tell me to shut up") == ""
    assert stop_request("okay you can stop now") == "stop"


@pytest.mark.parametrize(
    "said", ["start listening", "you can listen again", "wake up", "Abdoh, I need you", "im back"]
)
def test_start_listening_in_any_words(said):
    assert start_request(said)


# ----- over a reply -----


def test_stop_listening_over_a_reply_pauses_without_a_word():
    router = Router()
    watch = FakeWatch()
    daemon = make_daemon(router, ["Um, you can stop listening."], watch)
    router.replies = [long_reply(daemon)]
    watch.fire = said_at_least(daemon, 3)
    daemon._handle_spoken("Tell me a story")
    assert daemon.paused and daemon.speaker.stops >= 1
    assert router.requests == ["Tell me a story"]  # nothing went to Claude
    assert not any("listening" in s for s in daemon.speaker.said)  # not a word about it
    assert daemon._awaiting_answer is False
    assert ("history", "Abdoh: " + STOPPED_LISTENING) in daemon.bus.pending_events()


def test_shut_up_in_many_words_over_a_reply_ends_it():
    router = Router()
    watch = FakeWatch()
    daemon = make_daemon(router, ["Yeah, just shut up, shut up, I told you to shut up."], watch)
    router.replies = [long_reply(daemon)]
    watch.fire = said_at_least(daemon, 3)
    daemon._handle_spoken("Tell me a story")
    assert router.requests == ["Tell me a story"] and not daemon.paused
    assert daemon._awaiting_answer is False


def test_a_stray_word_over_a_reply_lets_abdoh_go_on():
    router = Router()
    watch = FakeWatch()
    daemon = make_daemon(router, ["Well."], watch)
    router.replies = [long_reply(daemon)]
    watch.fire = said_at_least(daemon, 3)
    daemon._handle_spoken("Tell me a story")
    assert daemon.speaker.resumes == 1 and router.requests == ["Tell me a story"]


class StoppingTranscriber(FakeTranscriber):
    """Hears someone in the room over the reply; meanwhile you stop Abdoh (or pause it)."""

    def __init__(self, texts, meanwhile):
        super().__init__(texts)
        self.meanwhile = meanwhile

    def transcribe(self, audio):
        self.meanwhile()
        return super().transcribe(audio)


@pytest.mark.parametrize("how", ["stop_speaking", "pause"])
def test_what_was_heard_when_you_stopped_abdoh_is_dropped(how):
    router = Router()
    watch = FakeWatch()
    daemon = make_daemon(router, [], watch)
    heard = "That's why the laptop is working now."
    daemon.transcriber = StoppingTranscriber([heard], lambda: daemon.handle_request(how))
    router.replies = [long_reply(daemon)]
    watch.fire = said_at_least(daemon, 3)
    daemon._handle_spoken("Tell me a story")
    assert router.requests == ["Tell me a story"]  # not answered


def test_nothing_queued_is_answered_once_paused():
    router = Router()
    daemon = make_daemon(router, [])

    def pause_and_queue():
        daemon.set_paused(True)
        daemon._next_request = "Uh policy lesson."
        return iter(["Okay."])

    router.replies = [pause_and_queue]
    daemon._handle_spoken("first")
    assert router.requests == ["first"]


# ----- no "go on" listening after Claude couldn't answer -----


class FailingRouter(StubRouter):
    def __init__(self, failed):
        super().__init__([iter(["You've reached your Claude usage limit for now."])])
        self.last_turn = SimpleNamespace(actions=[], ignored=False, failed=failed)


@pytest.mark.parametrize("failed", [True, False])
def test_no_listening_for_more_after_claude_failed(failed):
    daemon = Daemon(Config(), FailingRouter(failed), FakeSpeaker(), None, None, None)
    daemon.handle_text("how much is left", voice=True)
    assert daemon._awaiting_answer is (not failed)


# ----- paused: the wake word makes no sound -----


def paused_daemon(heard, tmp_path):
    cfg, router = real_router(tmp_path)
    earcons = RecordingEarcons()
    daemon = Daemon(
        cfg,
        router,
        FakeSpeaker(),
        lambda: FakeMic([tone_block()] * 5 + [silent_block()] * 12),
        FakeWakeWord(fire_on=2),
        FakeTranscriber(heard),
        Bus(),
        earcons=earcons,
        mic_retry_seconds=0.01,
    )
    daemon.set_paused(True)
    return daemon, earcons


def test_a_wake_word_while_paused_makes_no_sound(tmp_path):
    daemon, earcons = paused_daemon(["And then you will have to get it."], tmp_path)
    run_until(daemon, lambda: len(daemon.transcriber.calls) >= 1)
    assert daemon.paused and daemon.speaker.said == []
    assert not [e for e in earcons.events if e[0] == "play"]  # no chime, no "unclear"


def test_start_listening_in_other_words_while_paused(tmp_path):
    daemon, _ = paused_daemon(["Abdoh, you can listen again"], tmp_path)
    run_until(daemon, lambda: not daemon.paused)
    assert not daemon.paused and daemon.speaker.said == ["I'm listening again."]


def test_the_wake_word_chimes_again_once_listening(tmp_path):
    daemon, earcons = paused_daemon(["What time is it"], tmp_path)
    daemon.set_paused(False)
    run_until(daemon, lambda: len(daemon.transcriber.calls) >= 1)
    assert ("play", "listening") in earcons.events
