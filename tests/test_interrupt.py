"""Talking over Abdoh: it goes quiet, listens, and then goes on, stops, or does what you said.

The voice watch is faked: it "hears you" when the test says so.
"""

import threading
import time

from fakes import FakeMic, FakeTranscriber, FakeWakeWord

from abdoh.config import Config
from abdoh.daemon import Daemon
from abdoh.events import Bus
from abdoh.speech.tts import FakeSpeaker

SENTENCES = 60


class PacedMic(FakeMic):
    """Silence, a block every few milliseconds (an instant one would hog the CPU)."""

    def read(self):
        time.sleep(0.002)
        return super().read()


class Router:
    """Answers each request with the next reply: a string, or a function making sentences."""

    brain = None
    registry = None

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []
        self.closed = []

    def add_builtin(self, name, triggers, handler):
        pass

    def builtin_name(self, text):
        return None

    def handle(self, text):
        self.requests.append(text)
        reply = self.replies.pop(0) if self.replies else "Okay."
        return reply() if callable(reply) else reply


class FakeWatch:
    """Hears you once, when `fire()` turns true."""

    available = True
    canceller = object()
    sensitivity = "medium"

    class tap:  # noqa: N801 - stands in for an object
        available = True

        @staticmethod
        def stop():
            pass

    def __init__(self, fire=lambda: False):
        self.fire = fire
        self.fired = False
        self.shots = 1
        self.fed = self.idles = self.rearms = 0

    def feed(self, block, arrival):
        self.fed += 1
        if not self.fired and self.shots and self.fire():
            self.fired = True
            self.shots -= 1
            return True
        return False

    def clean(self, block, arrival):
        return block

    def pre_roll(self):
        return b""

    def rearm(self):
        self.rearms += 1
        self.fired = False

    def idle(self):
        self.idles += 1


def make_daemon(router, heard, watch=None, cfg=None, engine=None):
    """`heard`: what the transcriber hears you say over the reply."""
    daemon = Daemon(
        cfg or Config(),
        router,
        FakeSpeaker(),
        lambda: PacedMic([]),
        engine or FakeWakeWord(fire_on=10**9),
        FakeTranscriber(heard),
        bus=Bus(),
        voice_watch=watch or FakeWatch(),
    )
    daemon.mic = PacedMic([])
    return daemon


def long_reply(daemon, closed=None):
    """Many short sentences, like a long explanation from Claude."""

    def sentences():
        try:
            for i in range(SENTENCES):
                if daemon._interrupted.is_set():
                    return
                time.sleep(0.003)
                yield f"Sentence {i}."
        finally:
            if closed is not None:
                closed.set()  # the reply stopped being read: Claude is interrupted

    return sentences


def said_at_least(daemon, n):
    return lambda: len(daemon.speaker.said) >= n


# ----- a spoken request's reply -----


def test_saying_something_new_stops_the_reply_and_it_is_next():
    router = Router()
    watch = FakeWatch()
    daemon = make_daemon(router, ["What about Paris?"], watch)
    closed = threading.Event()
    router.replies = [long_reply(daemon, closed), "Paris is lovely."]
    watch.fire = said_at_least(daemon, 3)
    daemon._handle_spoken("Tell me about London")
    assert daemon.speaker.pauses == 1  # quiet as soon as you were heard
    assert closed.is_set()  # Claude was told to stop
    assert router.requests == ["Tell me about London", "What about Paris?"]
    assert daemon.speaker.said[-1] == "Paris is lovely."
    assert sum(s.startswith("Sentence") for s in daemon.speaker.said) < SENTENCES / 2


def test_okay_lets_abdoh_go_on():
    router = Router()
    watch = FakeWatch()
    daemon = make_daemon(router, ["Okay."], watch)
    router.replies = [long_reply(daemon)]
    watch.fire = said_at_least(daemon, 3)
    daemon._handle_spoken("Tell me a story")
    assert (daemon.speaker.pauses, daemon.speaker.resumes, daemon.speaker.stops) == (1, 1, 0)
    assert len(daemon.speaker.said) == SENTENCES  # the whole reply
    assert router.requests == ["Tell me a story"]
    assert watch.rearms == 1  # and you can still interrupt later


def test_a_cough_lets_abdoh_go_on():
    router = Router()
    watch = FakeWatch()
    daemon = make_daemon(router, [""], watch)  # nothing that was words
    router.replies = [long_reply(daemon)]
    watch.fire = said_at_least(daemon, 3)
    daemon._handle_spoken("Tell me a story")
    assert len(daemon.speaker.said) == SENTENCES and daemon.speaker.resumes == 1


def test_wait_stops_the_reply_and_nothing_else_happens():
    router = Router()
    watch = FakeWatch()
    daemon = make_daemon(router, ["Wait."], watch)
    router.replies = [long_reply(daemon)]
    watch.fire = said_at_least(daemon, 3)
    daemon._handle_spoken("Tell me a story")
    assert daemon.speaker.stops >= 1
    assert router.requests == ["Tell me a story"]
    assert len(daemon.speaker.said) < SENTENCES / 2
    assert daemon._awaiting_answer is False  # no "go on" listening after a stop


def test_talking_while_abdoh_still_thinks_is_the_same_request():
    router = Router()
    watch = FakeWatch()
    daemon = make_daemon(router, ["in Paris"], watch)
    thinking = threading.Event()

    def slow():
        thinking.set()
        for _ in range(100):
            if daemon._interrupted.is_set():
                return
            time.sleep(0.01)
        yield "It's sunny."

    router.replies = [slow, "Sunny in Paris."]
    watch.fire = thinking.is_set
    daemon._handle_spoken("What's the weather")
    assert router.requests == ["What's the weather", "What's the weather in Paris"]
    assert daemon.speaker.said == ["Sunny in Paris."]


def test_nothing_is_said_while_you_talk():
    """A sentence that arrives while you're being listened to waits; it's dropped if you then
    ask something else."""
    daemon = make_daemon(Router(), [])
    daemon._floor.clear()  # you have the floor
    done = threading.Event()
    threading.Thread(target=lambda: (daemon._speak("Hello."), done.set()), daemon=True).start()
    time.sleep(0.1)
    assert daemon.speaker.said == [] and not done.is_set()
    daemon.stop_speaking()
    assert done.wait(1)
    assert daemon.speaker.said == []


# ----- a typed request's reply (the main loop is listening meanwhile) -----


def test_a_typed_requests_reply_can_be_talked_over():
    router = Router()
    watch = FakeWatch()
    daemon = make_daemon(router, ["Never mind, open notepad."], watch)
    router.replies = [long_reply(daemon), "Opening Notepad."]
    watch.fire = said_at_least(daemon, 3)
    typed = threading.Thread(target=daemon.handle_text, args=("Tell me a story",), daemon=True)
    typed.start()
    while not daemon._handle_lock.locked():
        time.sleep(0.001)
    daemon._listen_once(daemon.mic)  # hears you over the reply, then answers you
    typed.join(2)
    assert router.requests == ["Tell me a story", "Never mind, open notepad."]
    assert daemon.speaker.said[-1] == "Opening Notepad."


def test_the_watch_only_listens_while_a_reply_runs():
    watch = FakeWatch()
    daemon = make_daemon(Router(), [], watch)
    assert daemon._observe(b"\0" * 3200, daemon.mic) is False
    assert watch.fed == 0
    with daemon._handle_lock:
        daemon._observe(b"\0" * 3200, daemon.mic)
        daemon._observe(b"\0" * 3200, daemon.mic)
    daemon._observe(b"\0" * 3200, daemon.mic)
    assert watch.fed == 2
    assert watch.idles == 2  # fresh at the start of the reply, and forgotten after it


# ----- when it's off -----


def test_turned_off_or_missing_nothing_is_watched():
    router = Router()
    watch = FakeWatch(fire=lambda: True)
    off = make_daemon(router, ["What about Paris?"], watch, Config(voice_interrupts=False))
    router.replies = [long_reply(off)]
    off._handle_spoken("Tell me a story")
    assert watch.fed == 0 and len(off.speaker.said) == SENTENCES

    class Missing(FakeWatch):
        available = False

    missing = Missing(fire=lambda: True)
    daemon = make_daemon(Router(), ["What about Paris?"], missing)
    daemon.router.replies = [long_reply(daemon)]
    daemon._handle_spoken("Tell me a story")
    assert missing.fed == 0 and len(daemon.speaker.said) == SENTENCES


def test_not_while_paused():
    watch = FakeWatch(fire=lambda: True)
    daemon = make_daemon(Router(), [], watch)
    daemon.paused = True
    with daemon._handle_lock:
        assert daemon._observe(b"\0" * 3200, daemon.mic) is False
    assert watch.fed == 0


def test_the_sensitivity_follows_the_settings(tmp_path):
    watch = FakeWatch()
    daemon = make_daemon(Router(), [], watch)
    daemon.cfg.app_dir = tmp_path
    daemon.apply_settings(Config(app_dir=tmp_path, voice_interrupt_sensitivity="high"))
    assert watch.sensitivity == "high"


def test_the_page_is_told_whether_abdoh_can_hear_you_over_itself():
    from abdoh.daemon import NO_ECHO_CANCELLER, NO_SPEAKER_TAP

    daemon = make_daemon(Router(), [])
    assert daemon._hearing_problem() == ""
    daemon.voice_watch = None
    assert daemon._hearing_problem() == NO_ECHO_CANCELLER

    class NoTap(FakeWatch):
        class tap:  # noqa: N801
            available = False

    daemon.voice_watch = NoTap()
    assert daemon._hearing_problem() == NO_SPEAKER_TAP
