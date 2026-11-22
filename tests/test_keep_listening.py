"""Keeps listening: an answer that came out as no words is listened for again, and while a role
is on Abdoh hears you without the wake word (you just talk) until you tell it not to."""

from fakes import FakeMic, FakeTranscriber, FakeWakeWord, silent_block, tone_block
from test_router import FakeAct, FakeBrain

from abdoh.audio.listener import listen_for_request
from abdoh.audio.vad import SileroVad
from abdoh.audio.wakeword import wait_for_trigger
from abdoh.commands.registry import CommandRegistry
from abdoh.config import Config
from abdoh.daemon import Daemon
from abdoh.events import Bus
from abdoh.roles.acting import Acting, wants_on
from abdoh.roles.model import parse_roles
from abdoh.router import Router
from abdoh.speech.tts import FakeSpeaker
from abdoh.ui.api import AppApi, UiState

TEACHER = {"name": "Math teacher", "instructions": "Explain step by step.", "board": True}
TONE, QUIET = tone_block(), silent_block()


class FakeVad:
    """Speech is the loud test tone."""

    def __init__(self):
        self.resets = 0

    def reset(self):
        self.resets += 1

    def speech_prob(self, block):
        return 1.0 if block == TONE else 0.0

    def is_speech(self, block):
        return block == TONE

    def fresh(self):
        return FakeVad()


# ----- an answer with no words in it -----


def test_an_answer_with_no_words_is_listened_for_again(monkeypatch):
    """The math lesson: an "um" (or a breath, or Abdoh's own echo) and a pause to think ended
    the recording, no words came out, and the real answer went unheard."""
    monkeypatch.setattr("abdoh.audio.listener.CHIME_SECONDS", 0)
    mic = FakeMic([TONE] * 2 + [QUIET] * 10 + [TONE] * 4 + [QUIET] * 20)
    stt = FakeTranscriber(["", "The right half."])
    text = listen_for_request(
        mic, FakeWakeWord(fire_on=99), stt, FakeSpeaker(), Config(silence_seconds=0.6), answer=True
    )
    assert text == "The right half." and len(stt.calls) == 2


def test_no_words_again_and_again_ends_it(monkeypatch):
    monkeypatch.setattr("abdoh.audio.listener.CHIME_SECONDS", 0)
    stt = FakeTranscriber(["", "", "", "never asked"])
    text = listen_for_request(
        FakeMic(([TONE] * 2 + [QUIET] * 8) * 5),
        FakeWakeWord(fire_on=99),
        stt,
        FakeSpeaker(),
        Config(silence_seconds=0.6),
        answer=True,
    )
    assert text == "" and len(stt.calls) == 3


# ----- you just talk (a role is on) -----


def test_speech_can_be_the_trigger():
    blocks = iter([QUIET, TONE, TONE])
    said = wait_for_trigger(
        lambda: next(blocks), FakeWakeWord(fire_on=99), hear=lambda block: block == TONE
    )
    assert said == "speech"


def test_what_you_say_is_the_request_from_its_first_word():
    noticed = iter([False, False, True])  # after a moment of speech
    started = []
    stt = FakeTranscriber(["Twelve is smaller, so the right half."])
    text = listen_for_request(
        FakeMic([QUIET, TONE, TONE] + [TONE] * 3 + [QUIET] * 15),
        FakeWakeWord(fire_on=99),
        stt,
        FakeSpeaker(),
        Config(silence_seconds=0.6),
        hear=lambda block: next(noticed, False),
        on_speech=lambda: started.append(True),
    )
    assert text == "Twelve is smaller, so the right half." and started == [True]
    assert stt.calls[0].count(TONE) == 5  # with what came before it was noticed


def test_a_pause_to_think_doesnt_end_it():
    stt = FakeTranscriber(["Twelve is... smaller."])
    listen_for_request(
        FakeMic([TONE] * 3 + [QUIET] * 9 + [TONE] * 2 + [QUIET] * 15),  # 0.9 s to think
        FakeWakeWord(fire_on=99),
        stt,
        FakeSpeaker(),
        Config(silence_seconds=0.6),
        hear=lambda block: block == TONE,
    )
    assert stt.calls[0].count(TONE) == 5  # both parts, though 0.9 s > the usual 0.6 s


# ----- the daemon: when Abdoh hears you -----


def make_daemon(tmp_path):
    router = Router(Config(app_dir=tmp_path), CommandRegistry(tmp_path / "none.yaml"))
    bus = Bus()
    daemon = Daemon(
        Config(app_dir=tmp_path), router, FakeSpeaker(), None, FakeWakeWord(10_000),
        FakeTranscriber([]), bus=bus, vad=FakeVad(),
    )  # fmt: skip
    daemon.use_roles(
        Acting(
            lambda: parse_roles([TEACHER]),
            on_change=daemon._role_changed,
            on_listening=daemon._listening_changed,
        )
    )
    return daemon, bus


def test_abdoh_hears_you_start_talking_while_a_role_is_on(tmp_path):
    daemon, _ = make_daemon(tmp_path)
    assert [daemon._hear(TONE) for _ in range(3)] == [False] * 3  # no role: the wake word
    daemon.acting.start("Math teacher")
    daemon._hear_from = 0  # Abdoh hasn't just spoken
    assert [daemon._hear(TONE) for _ in range(3)] == [False, False, True]  # 0.3 s in a row


def test_a_click_or_a_cough_is_not_talking(tmp_path):
    daemon, _ = make_daemon(tmp_path)
    daemon.acting.start("Math teacher")
    daemon._hear_from = 0
    heard = [daemon._hear(block) for block in (TONE, TONE, QUIET, TONE, QUIET, TONE, TONE, TONE)]
    assert heard == [False] * 7 + [True]


def test_never_while_abdoh_talks_nor_just_after(tmp_path):
    daemon, _ = make_daemon(tmp_path)
    daemon.acting.start("Math teacher")
    daemon._hear_from = 0
    with daemon._handle_lock:  # answering (a typed request, a reminder)
        assert not any(daemon._hear(TONE) for _ in range(5))
    assert not any(daemon._hear(TONE) for _ in range(5))  # its own voice dies away first
    daemon._quiet_for_hearing()  # it just answered something you said
    assert not any(daemon._hear(TONE) for _ in range(5))
    daemon._hear_from = 0
    assert [daemon._hear(TONE) for _ in range(3)] == [False, False, True]


def test_not_after_you_said_to_stop_listening(tmp_path):
    daemon, bus = make_daemon(tmp_path)
    daemon.acting.start("Math teacher")
    daemon.acting.set_listening(False)
    daemon._hear_from = 0
    assert not any(daemon._hear(TONE) for _ in range(5))
    assert ("listening", True) in bus.pending_events()  # the role started: listening
    daemon.acting.set_listening(True)
    assert bus.pending_events()[-1] == ("listening", True)


def test_no_answer_window_or_chime_while_it_keeps_listening(tmp_path):
    daemon, _ = make_daemon(tmp_path)
    daemon.acting.start("Math teacher")
    daemon._listen_for_more("Which half do we keep?")
    assert daemon._awaiting_answer is False  # it hears you anyway
    daemon.acting.set_listening(False)
    daemon._listen_for_more("Which half do we keep?")
    assert daemon._awaiting_answer is True  # as usual: the answer after a question


def test_what_you_say_goes_to_claude_as_maybe_for_someone_else(tmp_path):
    daemon, _ = make_daemon(tmp_path)
    daemon.acting.start("Math teacher")
    daemon._hear_from = 0
    daemon.transcriber = FakeTranscriber(["Twelve is smaller."])
    handled = []
    daemon.handle_text = lambda text, voice=False, aside=False, woken=False: handled.append(
        (text, aside)
    )
    daemon._listen_and_answer(FakeMic([TONE] * 6 + [QUIET] * 15))
    assert handled == [("Twelve is smaller.", True)]  # Claude may ignore it (ACTION ignore)


# ----- stopping it: in any words (Claude), or the button -----


def test_a_role_listens_until_told_not_to():
    told = []
    acting = Acting(lambda: parse_roles([TEACHER]), on_listening=told.append)
    assert not acting.keeps_listening and not acting.set_listening(True)  # no role on
    acting.start("Math teacher")
    assert acting.keeps_listening and "ACTION listen: off" in acting.state_text(4)
    assert acting.set_listening(False) and told == [False]
    assert not acting.keeps_listening and "ACTION listen: on" in acting.state_text(4)
    acting.start("a pirate")  # a new role: listening again
    assert acting.keeps_listening
    acting.stop()
    assert not acting.keeps_listening


def test_listen_off_in_any_words():
    assert not wants_on("off") and not wants_on(" OFF.") and wants_on("on") and wants_on("yes")


def test_claude_stops_the_listening_and_the_role_stays(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text("[]", encoding="utf-8")
    router = Router(Config(app_dir=tmp_path), CommandRegistry(path), act=FakeAct())
    router.acting = Acting(lambda: parse_roles([TEACHER]))
    router.brain = FakeBrain(("Sure.\nACTION listen: on",))
    list(router.handle("keep listening to me"))  # no role: not allowed, nothing changes
    assert router.acting.current is None and not router.acting.listening
    router.acting.start("Math teacher")
    router.brain = FakeBrain(("Sure, call me when you need me.\nACTION listen: off",))
    assert " ".join(router.handle("you can stop listening now")) == (
        "Sure, call me when you need me."
    )
    assert router.acting.current is not None and not router.acting.listening


def test_the_window_shows_it_and_its_button_switches_it(tmp_path):
    state = UiState()
    state.feed("listening", True)
    assert state.snapshot()["listening"] is True
    bus = Bus()
    AppApi(bus, state, Config(app_dir=tmp_path)).keep_listening(False)
    requests = iter(lambda: bus.next_request(0), None)
    assert [r for r in requests if r[0] == "keep_listening"] == [("keep_listening", False)]


def test_the_button_reaches_the_role(tmp_path):
    daemon, _ = make_daemon(tmp_path)
    daemon.acting.start("Math teacher")
    daemon.handle_request("keep_listening", False)
    assert not daemon.keeps_listening()


def test_the_hearing_detector_has_its_own_state():
    model = object()
    vad = SileroVad(session=model)
    other = vad.fresh()
    assert other is not vad and other._session is model and other._h is not vad._h
