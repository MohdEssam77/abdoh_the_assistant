import threading

from fakes import FakeMic, FakeTranscriber, FakeWakeWord, silent_block, tone_block

from abdoh.audio.mic import MicrophoneError
from abdoh.commands.registry import CommandRegistry
from abdoh.config import ClaudeConfig, Config
from abdoh.daemon import MIC_TOO_QUIET, SORRY, Daemon
from abdoh.events import Bus
from abdoh.router import Router
from abdoh.speech.tts import FakeSpeaker


class StubRouter:
    def __init__(self, replies, builtin=None):
        self.replies = list(replies)
        self.requests = []
        self.builtin = builtin
        self.brain = None
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


def test_commands_saved_in_the_app_are_used_right_away(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text('- name: a\n  triggers: ["hello"]\n  actions:\n    - say: "hi"\n')
    registry = CommandRegistry(path)
    bus = Bus()
    daemon = make_daemon(Router(Config(), registry), bus=bus)
    path.write_text('- name: b\n  triggers: ["bye"]\n  actions:\n    - say: "bye"\n')
    daemon.handle_request("commands_changed")
    assert [c.name for c in registry.commands] == ["b"]
    path.write_text("- name: [broken\n")
    daemon.handle_request("commands_changed")
    assert "Commands file error" in bus.pending_events()[-1][1]


def test_talk_button_listens_like_the_hotkey():
    daemon = make_daemon(StubRouter([]))
    daemon.handle_request("listen")
    assert daemon._take_listen_now() is True


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
    cfg.claude = ClaudeConfig(backend="api")  # don't depend on Claude Code being installed
    (tmp_path / ".env").write_text("OTHER=1\nANTHROPIC_API_KEY=old\n")
    bus = Bus()
    daemon = make_daemon(router, cfg=cfg, bus=bus)
    daemon.handle_request("set_key", "sk-new")
    assert (tmp_path / ".env").read_text() == "OTHER=1\nANTHROPIC_API_KEY=sk-new\n"
    assert cfg.has_api_key and router.brain is not None
    assert ("claude", "API key") in bus.pending_events()


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


class StreamingRouter(StubRouter):
    """Returns Claude-style streamed replies (generators of sentences)."""

    def __init__(self, sentences):
        super().__init__([])
        self.sentences = sentences
        self.closed = False
        self.read = 0

    def handle(self, text):
        self.requests.append(text)
        return self._gen()

    def _gen(self):
        try:
            for s in self.sentences:
                self.read += 1
                yield s
        finally:
            self.closed = True


def test_streamed_reply_is_spoken_sentence_by_sentence():
    bus = Bus()
    router = StreamingRouter(["Tokyo is the capital.", "It's big."])
    daemon = make_daemon(router, bus=bus)
    assert daemon.handle_text("capital of japan") == "Tokyo is the capital. It's big."
    assert daemon.speaker.said == ["Tokyo is the capital.", "It's big."]
    history = [v for k, v in bus.pending_events() if k == "history"]
    assert history == ["You: capital of japan", "Abdoh: Tokyo is the capital. It's big."]
    assert router.closed


class StoppingSpeaker(FakeSpeaker):
    """Simulates the user pressing Stop while the first sentence is spoken."""

    def __init__(self):
        super().__init__()
        self.daemon = None

    def say(self, text):
        super().say(text)
        self.daemon.stop_speaking()


def test_stop_during_a_streamed_reply_stops_reading_claude():
    speaker = StoppingSpeaker()
    router = StreamingRouter(["One.", "Two.", "Three."])
    daemon = Daemon(Config(), router, speaker, None, None, None)
    speaker.daemon = daemon
    assert daemon.handle_text("count") == "One."
    assert speaker.said == ["One."]
    assert router.read == 1 and router.closed


def test_error_while_streaming_is_spoken():
    class Broken(StubRouter):
        def handle(self, text):
            def gen():
                yield "Starting."
                raise RuntimeError("boom")

            return gen()

    daemon = make_daemon(Broken([]))
    assert daemon.handle_text("x") == f"Starting. {SORRY}"
    assert daemon.speaker.said == ["Starting.", SORRY]


class FakeStatusBrain:
    name = "Claude Code"

    def status(self):
        return "Pro subscription (Claude Code)"


def test_claude_status_is_reported_then_refined():
    bus = Bus()
    router = StubRouter([])
    router.brain = FakeStatusBrain()
    daemon = make_daemon(router, bus=bus)
    daemon._report_claude()
    events = []
    for _ in range(200):
        events += bus.pending_events()
        if ("claude", "Pro subscription (Claude Code)") in events:
            break
        threading.Event().wait(0.01)
    assert events[0] == ("claude", "Claude Code")
    assert ("claude", "Pro subscription (Claude Code)") in events


def test_no_claude_is_reported():
    bus = Bus()
    daemon = make_daemon(StubRouter([]), bus=bus)
    daemon._report_claude()
    assert ("claude", "not connected") in bus.pending_events()


def test_timer_announcement_plays_the_alarm_then_speaks(monkeypatch):
    monkeypatch.setattr(Daemon, "ALARM_SECONDS", 0)
    earcons = RecordingEarcons()
    daemon = Daemon(Config(), StubRouter([]), FakeSpeaker(), None, None, None, earcons=earcons)
    daemon.handle_request("voice", False)  # the alarm still sounds with voice replies off
    daemon.announce("Your 5 minute timer is done.")
    assert ("play", "alarm") in earcons.events
    daemon.handle_request("voice", True)
    daemon.announce("Your 1 minute timer is done.")
    assert daemon.speaker.said == ["Your 1 minute timer is done."]


def test_hotkey_while_idle_listens_once():
    daemon = make_daemon(StubRouter([]))
    daemon.push_to_talk()
    assert daemon._take_listen_now() is True
    assert daemon._take_listen_now() is False  # one press, one request


def test_hotkey_while_replying_stops_speaking():
    speaker = BlockingSpeaker()
    daemon = Daemon(Config(), StubRouter(["a long answer"]), speaker, None, None, None)
    t = threading.Thread(target=daemon.handle_text, args=("story",), daemon=True)
    t.start()
    assert speaker.speaking.wait(2)
    daemon.push_to_talk()
    t.join(2)
    assert speaker.stops == 1
    assert daemon._take_listen_now() is False


def test_hotkey_request_works_while_paused(monkeypatch):
    monkeypatch.setattr("abdoh.audio.listener.CHIME_SECONDS", 0)
    router = StubRouter(["It is noon."])
    mic = FakeMic([tone_block()] * 3 + [silent_block()] * 20)
    daemon = Daemon(
        Config(),
        router,
        FakeSpeaker(),
        lambda: mic,
        FakeWakeWord(fire_on=999),
        FakeTranscriber(["what time is it"]),
        mic_retry_seconds=0.01,
    )
    daemon.set_paused(True)
    daemon.push_to_talk()
    run_until(daemon, lambda: daemon.speaker.said)
    assert router.requests == ["what time is it"]
    assert daemon.speaker.said == ["It is noon."]


def question_daemon(replies, texts, cfg=None):
    """A daemon whose mic hears: a request (with the wake word), a pause, then an answer."""
    mic = FakeMic(
        [tone_block()] * 2 + [silent_block()] * 12 + [tone_block()] * 3 + [silent_block()] * 20
    )
    return Daemon(
        cfg or Config(),
        StubRouter(replies),
        FakeSpeaker(),
        lambda: mic,
        FakeWakeWord(fire_on=2),  # fires once, for the first request only
        FakeTranscriber(texts),
        mic_retry_seconds=0.01,
    )


def test_claude_question_is_answered_without_the_wake_word(monkeypatch):
    monkeypatch.setattr("abdoh.audio.listener.CHIME_SECONDS", 0)
    daemon = question_daemon(
        [["Sure.", "Which city?"], ["It's sunny in Cairo."]],  # streamed, like Claude
        ["Abdoh, what's the weather?", "Cairo."],
    )
    run_until(daemon, lambda: len(daemon.speaker.said) >= 3)
    assert daemon.router.requests == ["Abdoh, what's the weather?", "Cairo."]
    assert daemon.speaker.said == ["Sure.", "Which city?", "It's sunny in Cairo."]


def test_after_a_reply_abdoh_keeps_listening_for_a_moment(monkeypatch):
    monkeypatch.setattr("abdoh.audio.listener.CHIME_SECONDS", 0)
    daemon = question_daemon(
        [["It's sunny."], ["Rain tomorrow."]], ["Abdoh, weather?", "And tomorrow?"]
    )
    sounds = []
    daemon.earcons.play = sounds.append
    run_until(daemon, lambda: len(daemon.speaker.said) >= 2)
    assert daemon.router.requests == ["Abdoh, weather?", "And tomorrow?"]  # no wake word needed
    assert "ready" in sounds and "listening" not in sounds  # the softer "go on" sound


def test_no_extra_listening_after_a_statement_when_follow_up_is_off(monkeypatch):
    monkeypatch.setattr("abdoh.audio.listener.CHIME_SECONDS", 0)
    cfg = Config(follow_up_seconds=0)
    daemon = question_daemon([["It's sunny."], ["should not run"]], ["Abdoh, weather?", "x"], cfg)
    run_until(daemon, lambda: daemon.engine.count > 80)  # long past where an answer would be
    assert daemon.router.requests == ["Abdoh, weather?"]


def test_no_extra_listening_when_everything_is_turned_off(monkeypatch):
    monkeypatch.setattr("abdoh.audio.listener.CHIME_SECONDS", 0)
    cfg = Config(follow_up_seconds=0, claude=ClaudeConfig(listen_after_question=False))
    daemon = question_daemon([["Which city?"], ["should not run"]], ["Abdoh, weather?", "x"], cfg)
    run_until(daemon, lambda: daemon.engine.count > 80)
    assert daemon.router.requests == ["Abdoh, weather?"]


def test_a_question_waits_at_least_as_long_as_a_follow_up():
    daemon = make_daemon(StubRouter([["Which city?"], ["Sunny."]]), cfg=Config(follow_up_seconds=2))
    daemon.handle_text("weather", voice=True)
    assert (daemon._awaiting_answer, daemon._answer_wait, daemon._soft_chime) == (True, 5.0, False)
    daemon._awaiting_answer = False
    daemon.handle_text("cairo", voice=True)
    assert (daemon._awaiting_answer, daemon._answer_wait, daemon._soft_chime) == (True, 2.0, True)


def test_typed_requests_and_fixed_replies_dont_listen_for_an_answer():
    daemon = make_daemon(StubRouter([["Which city?"], "Which city?", ["Which city?"]]))
    daemon.handle_request("text", "what's the weather")  # typed: answer by typing
    assert daemon._awaiting_answer is False
    daemon.handle_text("weather", voice=True)  # not Claude (a command's say: text)
    assert daemon._awaiting_answer is False
    daemon.handle_text("weather", voice=True)
    assert daemon._awaiting_answer is True


def test_a_stopped_question_isnt_waited_for():
    speaker = StoppingSpeaker()
    daemon = Daemon(Config(), StreamingRouter(["Which city?"]), speaker, None, None, None)
    speaker.daemon = daemon
    daemon.handle_text("weather", voice=True)
    assert daemon._awaiting_answer is False


def test_hotkey_without_voice_input_says_why():
    bus = Bus()
    daemon = Daemon(Config(), StubRouter([]), FakeSpeaker(), None, None, None, bus,
                    listen_error="no model")  # fmt: skip
    daemon.push_to_talk()
    assert ("history", "Abdoh: Voice input isn't available (no model).") in bus.pending_events()


def test_voice_toggle_is_announced_to_the_ui():
    bus = Bus()
    daemon = make_daemon(StubRouter([]), bus=bus)
    daemon.handle_request("voice", False)
    assert ("voice", False) in bus.pending_events()


def test_hotkey_with_a_silent_mic_says_it_may_be_muted(monkeypatch):
    monkeypatch.setattr("abdoh.audio.listener.CHIME_SECONDS", 0)
    daemon = Daemon(
        Config(),
        StubRouter([]),
        FakeSpeaker(),
        lambda: FakeMic([]),  # a muted mic: nothing but zeros
        FakeWakeWord(fire_on=999),
        FakeTranscriber([]),
        mic_retry_seconds=0.01,
    )
    daemon.push_to_talk()
    run_until(daemon, lambda: daemon.speaker.said)
    assert daemon.speaker.said == [MIC_TOO_QUIET]


def test_only_a_silent_mic_after_the_hotkey_is_reported():
    daemon = make_daemon(StubRouter([]))
    daemon._via_hotkey = True
    daemon._heard_nothing(2000)  # there was sound, just no speech
    daemon._via_hotkey = False
    daemon._heard_nothing(0)  # not answering Claude's question is fine
    assert daemon.speaker.said == []
    daemon._via_hotkey = True
    daemon._heard_nothing(5)
    assert daemon.speaker.said == [MIC_TOO_QUIET]
