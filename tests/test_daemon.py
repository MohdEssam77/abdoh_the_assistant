import threading

from fakes import FakeMic, FakeTranscriber, FakeWakeWord, silent_block, tone_block

from abdoh.audio.mic import MicrophoneError
from abdoh.commands.registry import CommandRegistry
from abdoh.config import Config
from abdoh.daemon import SORRY, Daemon
from abdoh.events import Bus
from abdoh.router import Router
from abdoh.speech.tts import FakeSpeaker


class StubRouter:
    def __init__(self, replies, builtin=None):
        self.replies = list(replies)
        self.requests = []
        self.builtin = builtin
        self.claude = None
        self.registry = None

    def add_builtin(self, name, triggers, handler):
        pass

    def builtin_name(self, text):
        return self.builtin

    def handle(self, text):
        self.requests.append(text)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def make_daemon(router, mic_factory=None, transcriber=None, cfg=None, bus=None):
    return Daemon(
        cfg or Config(),
        router,
        FakeSpeaker(),
        mic_factory or speech_mic,
        FakeWakeWord(fire_on=2),
        transcriber or FakeTranscriber([]),
        bus=bus,
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
    daemon = make_daemon(StubRouter(["Hi there"]))
    assert daemon.handle_text("hello") == "Hi there"
    assert daemon.speaker.said == ["Hi there"]


def test_router_exception_does_not_crash():
    daemon = make_daemon(StubRouter([RuntimeError("boom")]))
    assert daemon.handle_text("hello") == SORRY
    assert daemon.speaker.said == [SORRY]


def test_voice_request_end_to_end():
    router = StubRouter(["Good morning!"])
    daemon = make_daemon(router, transcriber=FakeTranscriber(["Good morning Abdoh."]))
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


def test_paused_ignores_voice_requests():
    router = StubRouter(["should not run"])
    daemon = make_daemon(router, transcriber=FakeTranscriber(["Abdoh good morning"]))
    daemon.set_paused(True)
    done = threading.Event()
    original = daemon.engine.reset
    daemon.engine.reset = lambda: (original(), done.set())
    run_until(daemon, done.is_set)
    assert router.requests == []


def test_events_and_history():
    bus = Bus()
    daemon = make_daemon(StubRouter(["Hi"]), bus=bus)
    daemon.handle_request("text", "hello")
    events = bus.pending_events()
    assert ("history", "You: hello") in events
    assert ("history", "Abdoh: Hi") in events
    assert ("status", "Thinking...") in events
    assert events[-1] == ("status", "Listening")


def test_voice_toggle_off_only_shows_text():
    bus = Bus()
    daemon = make_daemon(StubRouter(["Hi"]), bus=bus)
    daemon.handle_request("voice", False)
    daemon.handle_request("text", "hello")
    assert daemon.speaker.said == []
    assert ("history", "Abdoh: Hi") in bus.pending_events()


def test_pause_and_resume_requests():
    bus = Bus()
    daemon = make_daemon(StubRouter([]), bus=bus)
    daemon.handle_request("pause")
    assert daemon.paused and bus.pending_events()[-1] == ("status", "Paused")
    daemon.handle_request("resume")
    assert not daemon.paused and bus.pending_events()[-1] == ("status", "Listening")


def real_router(tmp_path):
    (tmp_path / "commands.yaml").write_text(
        '- name: hi\n  triggers: ["good morning"]\n  actions:\n    - say: "Morning!"\n'
    )
    cfg = Config(app_dir=tmp_path)
    return cfg, Router(cfg, CommandRegistry(cfg.commands_path))


def test_typed_text_uses_same_router(tmp_path):
    cfg, router = real_router(tmp_path)
    daemon = make_daemon(router, cfg=cfg)
    daemon.handle_request("text", "good morning")
    assert daemon.speaker.said == ["Morning!"]


def test_set_key_saves_env_and_connects(tmp_path):
    cfg, router = real_router(tmp_path)
    (tmp_path / ".env").write_text("OTHER=1\nANTHROPIC_API_KEY=old\n")
    bus = Bus()
    daemon = make_daemon(router, cfg=cfg, bus=bus)
    daemon.handle_request("set_key", "sk-new")
    assert (tmp_path / ".env").read_text() == "OTHER=1\nANTHROPIC_API_KEY=sk-new\n"
    assert cfg.claude_enabled and router.claude is not None
    assert ("claude", True) in bus.pending_events()


def test_show_window_by_voice(tmp_path):
    cfg, router = real_router(tmp_path)
    bus = Bus()
    daemon = make_daemon(router, cfg=cfg, bus=bus)
    assert daemon.handle_text("Abdoh, show window") == ""
    assert ("show", None) in bus.pending_events()


def test_stop_and_start_listening_by_voice(tmp_path):
    cfg, router = real_router(tmp_path)
    daemon = make_daemon(router, cfg=cfg)
    assert "stop listening" in daemon.handle_text("Abdoh, stop listening")
    assert daemon.paused
    assert router.builtin_name("Hey Abdoh, start listening") == "start_listening"
    assert router.builtin_name("Abdoh, good morning") is None
    assert daemon.handle_text("Abdoh, start listening") == "I'm listening again."
    assert not daemon.paused


def test_paused_honors_start_listening_by_voice(tmp_path):
    cfg, router = real_router(tmp_path)
    daemon = make_daemon(router, cfg=cfg, transcriber=FakeTranscriber(["Abdoh, start listening"]))
    daemon.set_paused(True)
    run_until(daemon, lambda: not daemon.paused)
    assert not daemon.paused
    assert daemon.speaker.said == ["I'm listening again."]


def test_reload_commands_by_voice(tmp_path):
    cfg, router = real_router(tmp_path)
    daemon = make_daemon(router, cfg=cfg)
    assert daemon.handle_text("Abdoh, reload commands") == "Reloaded 1 commands."


def test_reload_request(tmp_path):
    cfg, router = real_router(tmp_path)
    bus = Bus()
    daemon = make_daemon(router, cfg=cfg, bus=bus)
    daemon.handle_request("reload")
    assert ("history", "Abdoh: Loaded 1 commands.") in bus.pending_events()


def test_quit_request():
    bus = Bus()
    daemon = make_daemon(StubRouter([]), bus=bus)
    daemon.handle_request("quit")
    assert daemon.stop_event.is_set()
    assert ("quit", None) in bus.pending_events()


def test_headless_bus_drops_events():
    bus = Bus(ui_attached=False)
    bus.emit("status", "Listening")
    assert bus.pending_events() == []


class RecordingEarcons:
    def __init__(self):
        self.events = []

    def play(self, name):
        self.events.append(("play", name))

    def start_ticking(self, name="thinking", every=3.0):
        self.events.append(("tick", name))

    def stop_ticking(self):
        self.events.append(("stop", None))


class ThinkingRouter(StubRouter):
    """Calls on_thinking like the real router does before a Claude request."""

    def handle(self, text):
        self.on_thinking()
        return super().handle(text)


def test_thinking_ticks_until_the_reply():
    earcons = RecordingEarcons()
    bus = Bus()
    daemon = Daemon(
        Config(), ThinkingRouter(["Tokyo."]), FakeSpeaker(), None, None, None, bus, earcons=earcons
    )
    daemon.handle_text("capital of japan")
    assert earcons.events[0] == ("tick", "thinking")
    assert ("stop", None) in earcons.events
    assert daemon.speaker.said == ["Tokyo."]
    assert ("status", "Thinking...") in bus.pending_events()


def test_no_ticking_when_voice_replies_are_off():
    earcons = RecordingEarcons()
    daemon = Daemon(
        Config(), ThinkingRouter(["Tokyo."]), FakeSpeaker(), None, None, None, earcons=earcons
    )
    daemon.handle_request("voice", False)
    daemon.handle_text("capital of japan")
    assert ("tick", "thinking") not in earcons.events


def test_stop_speaking_silences_the_rest_of_the_reply():
    bus = Bus()
    daemon = make_daemon(StubRouter([]), bus=bus)
    daemon._interrupted.clear()
    daemon.stop_speaking()
    daemon.say("this is not spoken")
    assert daemon.speaker.stops == 1
    assert daemon.speaker.said == []
    assert ("history", "Abdoh: this is not spoken") in bus.pending_events()


def test_new_request_speaks_again_after_a_stop():
    daemon = make_daemon(StubRouter(["Hi"]))
    daemon.stop_speaking()
    daemon.handle_text("hello")
    assert daemon.speaker.said == ["Hi"]


class BlockingSpeaker(FakeSpeaker):
    """say() blocks until stop() is called, like a long reply being spoken."""

    def __init__(self):
        super().__init__()
        self.speaking = threading.Event()
        self.released = threading.Event()

    def say(self, text):
        super().say(text)
        self.speaking.set()
        self.released.wait(5)

    def stop(self):
        super().stop()
        self.released.set()


def test_stop_request_is_handled_while_a_typed_reply_is_spoken():
    bus = Bus()
    speaker = BlockingSpeaker()
    daemon = Daemon(Config(), StubRouter(["a long answer"]), speaker, None, None, None, bus)
    server = threading.Thread(target=daemon.serve_requests, daemon=True)
    server.start()
    bus.request("text", "tell me a story")
    assert speaker.speaking.wait(2)
    bus.request("stop_speaking")
    assert speaker.released.wait(2)
    daemon.stop()
    server.join(2)
    assert speaker.stops == 1
