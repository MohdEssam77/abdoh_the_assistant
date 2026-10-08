import threading

from fakes import FakeMic, FakeTranscriber, FakeWakeWord, silent_block, tone_block

from abdoh.audio.mic import MicrophoneError
from abdoh.config import Config
from abdoh.daemon import SORRY, Daemon
from abdoh.speech.tts import FakeSpeaker


class StubRouter:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    def handle(self, text):
        self.requests.append(text)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def make_daemon(router, mic_factory, transcriber):
    return Daemon(
        Config(),
        router,
        FakeSpeaker(),
        mic_factory,
        FakeWakeWord(fire_on=2),
        transcriber,
        mic_retry_seconds=0.01,
    )


def run_until(daemon, condition, timeout=5.0):
    t = threading.Thread(target=daemon.run, daemon=True)
    t.start()
    for _ in range(int(timeout / 0.01)):
        if condition():
            break
        threading.Event().wait(0.01)
    daemon.stop()
    t.join(timeout)
    assert not t.is_alive()


def speech_mic():
    return FakeMic([tone_block()] * 2 + [silent_block()] * 12)


def test_handle_text_speaks_reply():
    daemon = make_daemon(StubRouter(["Hi there"]), speech_mic, FakeTranscriber([]))
    assert daemon.handle_text("hello") == "Hi there"
    assert daemon.speaker.said == ["Hi there"]


def test_router_exception_does_not_crash():
    daemon = make_daemon(StubRouter([RuntimeError("boom")]), speech_mic, FakeTranscriber([]))
    assert daemon.handle_text("hello") == SORRY
    assert daemon.speaker.said == [SORRY]


def test_voice_request_end_to_end():
    router = StubRouter(["Good morning!"])
    daemon = make_daemon(router, speech_mic, FakeTranscriber(["Good morning Abdoh."]))
    run_until(daemon, lambda: daemon.speaker.said)
    assert router.requests == ["Good morning Abdoh."]
    assert daemon.speaker.said == ["Good morning!"]


def test_mic_failure_is_retried():
    attempts = []

    def flaky_mic():
        attempts.append(1)
        if len(attempts) < 3:
            raise MicrophoneError("no mic")
        return speech_mic()

    router = StubRouter(["ok"])
    daemon = make_daemon(router, flaky_mic, FakeTranscriber(["Abdoh time"]))
    run_until(daemon, lambda: daemon.speaker.said)
    assert len(attempts) >= 3
    assert daemon.speaker.said == ["ok"]
