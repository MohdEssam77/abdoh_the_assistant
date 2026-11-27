"""One voice at a time (the owner, 2026-11-27: "if Abdoh is talking about something and another
thing is there for it to say, it should wait"): a Codoh notice or where the board's PDF went
waits for the reply being said, and Abdoh's own words heard back aren't a request."""

import threading
import time

from fakes import FakeTranscriber, FakeWakeWord
from test_interrupt import FakeWatch, PacedMic, Router, long_reply, said_at_least

from abdoh.audio.echo_text import likeness, own_words
from abdoh.config import Config
from abdoh.daemon import Daemon
from abdoh.events import Bus
from abdoh.router import OVER_REPLY
from abdoh.speech.tts import FakeSpeaker

# ----- what Abdoh heard is its own words -----

# Real cases from the owner's logs: (heard, what Abdoh was saying then).
OWN = [
    (
        "Each one was",
        "This one accepts words with an odd number of ones: each one flips the state.",
    ),
    ("Take your time.", 'Take your time, I only caught "each one was".'),
]
NOT_OWN = [
    (
        "Can you show me like a bigger example, like draw a bigger tomata, please?",
        "Sure, think of it as a light switch that remembers just one thing: have I seen an even "
        "or odd number of ones? Reading a one flips between these two states.",
    ),
    (
        "Okay, okay, all good, all good, shut up.",
        "Sorry Mo, I still get the George Wassouf video with Brave as the window in front.",
    ),
    (
        "And this might be a problem for him.",
        "Ah, so it's for your friend, with sound from the monitor and the mic on his laptop.",
    ),  # fmt: skip
    ("Thank you.", "I can't see Codoh right now. The screen you're using shows Brave."),
    ("Wait, what is a state?", "Each state remembers how much of the ending we've matched so far."),
]


def test_abdohs_own_words_heard_back():
    for heard, said in OWN:
        assert own_words(heard, [said]), heard
    for heard, said in NOT_OWN:
        assert not own_words(heard, [said]), (heard, likeness(heard, said))
    assert not own_words("Each one was", [])  # nothing said lately
    assert not own_words("", ["anything"])


def test_short_words_must_match_closely():
    assert own_words("Each one", ["each one flips the state"])
    assert not own_words("If I", ["A finite automaton is a tiny machine"])


class Echo(FakeTranscriber):
    """Hears what Abdoh is saying right now, as a microphone too near the speakers does."""

    def __init__(self, daemon):
        super().__init__([])
        self.daemon = daemon

    def transcribe(self, audio, language=None):
        return self.daemon.speaker.said[-1].rstrip(".")


def make(router, watch, heard=(), speaker=None):
    daemon = Daemon(
        Config(),
        router,
        speaker or FakeSpeaker(),
        lambda: PacedMic([]),
        FakeWakeWord(fire_on=10**9),
        FakeTranscriber(list(heard)),
        bus=Bus(),
        voice_watch=watch,
    )
    daemon.mic = PacedMic([])
    return daemon


def explaining(daemon, count=30):
    def sentences():
        for i in range(count):
            if daemon._interrupted.is_set():
                return
            time.sleep(0.003)
            yield f"State number {i} remembers how much of the ending we matched."

    return sentences


def test_its_own_words_heard_back_dont_stop_the_reply():
    router = Router()
    watch = FakeWatch()
    daemon = make(router, watch)
    daemon.transcriber = Echo(daemon)
    router.replies = [explaining(daemon)]
    watch.fire = said_at_least(daemon, 3)
    daemon._handle_spoken("Explain the automaton")
    assert router.requests == ["Explain the automaton"]  # no "request" from its own voice
    assert len(daemon.speaker.said) == 30 and daemon.speaker.resumes == 1


def test_what_you_say_over_a_reply_may_be_ignored_by_claude():
    router = Router()
    watch = FakeWatch()
    daemon = make(router, watch, heard=["What about Paris?"])
    asides = []
    handle = router.handle
    router.handle = lambda text, aside=False, woken=False: (asides.append(aside),
                                                            handle(text))[1]  # fmt: skip
    router.replies = [long_reply(daemon), "Paris is lovely."]
    watch.fire = said_at_least(daemon, 3)
    daemon._handle_spoken("Tell me about London")
    assert asides == [False, OVER_REPLY]


# ----- one voice at a time -----


class SlowSpeaker(FakeSpeaker):
    """Takes a moment for each sentence, and notes whether two ever played at once."""

    def __init__(self):
        super().__init__()
        self.playing = 0
        self.most = 0
        self.lock = threading.Lock()

    def say(self, text):
        with self.lock:
            self.playing += 1
            self.most = max(self.most, self.playing)
        time.sleep(0.02)
        super().say(text)
        with self.lock:
            self.playing -= 1


def test_a_notice_waits_for_the_reply_being_said():
    router = Router()
    speaker = SlowSpeaker()
    daemon = make(router, FakeWatch(), speaker=speaker)
    daemon.HEAR_AFTER_SPEAKING_SECONDS = 0.05
    router.replies = [explaining(daemon, 10)]
    started = threading.Event()

    def notice_during_the_reply():
        started.wait(2)
        daemon.say_later("Codoh wants to change calc.py. Allow it?")

    threading.Thread(target=notice_during_the_reply, daemon=True).start()
    router.replies = [lambda: _signal_after(explaining(daemon, 10)(), started, 2)]
    daemon.handle_text("Explain it")
    for _ in range(200):
        if "Codoh wants to change calc.py. Allow it?" in speaker.said:
            break
        time.sleep(0.01)
    assert speaker.said[-1] == "Codoh wants to change calc.py. Allow it?"  # after the reply
    assert sum(s.startswith("State number") for s in speaker.said) == 10
    assert speaker.most == 1  # never two at once
    daemon.stop_event.set()


def _signal_after(sentences, event, n):
    for i, sentence in enumerate(sentences):
        if i == n:
            event.set()
        yield sentence


def test_a_filler_and_the_answer_never_overlap():
    router = Router()
    speaker = SlowSpeaker()
    daemon = make(router, FakeWatch(), speaker=speaker)
    threads = [threading.Thread(target=daemon._speak, args=(f"Part {i}.",)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(speaker.said) == 5 and speaker.most == 1


def test_a_notice_that_is_no_longer_true_is_left_out():
    router = Router()
    daemon = make(router, FakeWatch())
    daemon.HEAR_AFTER_SPEAKING_SECONDS = 0
    waiting = {"state": "allowed"}  # you allowed it on the page meanwhile
    daemon.say_later(
        "Codoh wants to run a command. Allow it?", lambda: waiting["state"] == "waiting"
    )
    daemon.say_later("Codoh is done: Built.")
    for _ in range(200):
        if daemon.speaker.said:
            break
        time.sleep(0.01)
    assert daemon.speaker.said == ["Codoh is done: Built."]
    assert ("history", "Abdoh: Codoh is done: Built.") in daemon.bus.pending_events()
    daemon.stop_event.set()


def test_a_notice_waits_while_you_talk_or_abdoh_waits_for_your_answer():
    router = Router()
    daemon = make(router, FakeWatch())
    daemon.HEAR_AFTER_SPEAKING_SECONDS = 0
    for busy in ("_recording", "_answer_window", "_awaiting_answer"):
        setattr(daemon, busy, True)
        daemon.say_later(f"Notice while {busy}.")
        time.sleep(0.3)
        assert daemon.speaker.said == [], busy
        setattr(daemon, busy, False)
        for _ in range(200):
            if daemon.speaker.said:
                break
            time.sleep(0.01)
        assert daemon.speaker.said == [f"Notice while {busy}."]
        daemon.speaker.said.clear()
    daemon.stop_event.set()


def test_while_paused_a_notice_is_shown_not_said():
    router = Router()
    daemon = make(router, FakeWatch())
    daemon.HEAR_AFTER_SPEAKING_SECONDS = 0
    daemon.paused = True
    daemon.say_later("Codoh is done: Built.")
    for _ in range(200):
        if ("history", "Abdoh: Codoh is done: Built.") in daemon.bus.pending_events():
            break
        time.sleep(0.01)
    else:
        raise AssertionError("not shown")
    assert daemon.speaker.said == []
    daemon.stop_event.set()
