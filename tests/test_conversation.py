"""Talking with Abdoh: it says what it's doing, and the wake word interrupts a reply."""

import time

from fakes import FakeMic, FakeTranscriber, FakeWakeWord

from abdoh.claude.brain import system_prompt
from abdoh.config import Config
from abdoh.daemon import FILLERS, Daemon
from abdoh.events import Bus
from abdoh.speech.tts import FakeSpeaker


class Router:
    """Answers with whatever the test put in `reply` (a string, or a function making sentences)."""

    brain = None
    registry = None

    def __init__(self, reply):
        self.reply = reply

    def add_builtin(self, name, triggers, handler):
        pass

    def builtin_name(self, text):
        return None

    def handle(self, text):
        return self.reply() if callable(self.reply) else self.reply


def make_daemon(reply, engine=None, cfg=None):
    bus = Bus()
    daemon = Daemon(
        cfg or Config(),
        Router(reply),
        FakeSpeaker(),
        lambda: FakeMic([]),
        engine or FakeWakeWord(fire_on=10**9),
        FakeTranscriber([]),
        bus=bus,
    )
    return daemon, bus


def events(bus, kind):
    return [value for k, value in bus.pending_events() if k == kind]


# ----- saying what it's doing -----


def test_a_tool_is_announced_when_claude_didnt_say_anything_first():
    daemon, bus = make_daemon("")
    daemon._activity("Searching the web")
    assert daemon.speaker.said == ["Searching the web."]
    assert events(bus, "activity") == ["Searching the web"]


def test_a_tool_is_only_shown_when_claude_already_spoke():
    daemon, bus = make_daemon("")
    daemon._speak("Let me look that up.")
    daemon._activity("Searching the web")
    assert daemon.speaker.said == ["Let me look that up."]
    assert events(bus, "activity") == ["Searching the web"]


def test_asides_respect_voice_off_and_other_languages():
    daemon, _ = make_daemon("")
    daemon.voice_enabled = False
    daemon._activity("Searching the web")
    daemon.voice_enabled = True
    daemon.speaker.language = "ar"  # the asides are English; an Arabic chat just hears the tick
    daemon._activity("Searching the web")
    assert daemon.speaker.said == []


def test_a_slow_answer_gets_a_one_moment(monkeypatch):
    monkeypatch.setattr("abdoh.daemon.FILLER_SECONDS", 0.02)

    def slow():
        time.sleep(0.3)
        yield "Here you go."

    daemon, bus = make_daemon(slow)
    daemon.handle_text("something hard")
    assert daemon.speaker.said[0] in FILLERS and daemon.speaker.said[1:] == ["Here you go."]
    history = events(bus, "history")
    assert history == ["You: something hard", "Abdoh: Here you go."]  # the aside isn't shown


def test_a_quick_answer_gets_no_filler(monkeypatch):
    monkeypatch.setattr("abdoh.daemon.FILLER_SECONDS", 0.2)
    daemon, _ = make_daemon(lambda: iter(["Tokyo."]))
    daemon.handle_text("capital of japan")
    time.sleep(0.3)
    assert daemon.speaker.said == ["Tokyo."]


def test_claude_is_told_to_speak_before_slow_work_and_in_your_language():
    text = system_prompt(Config(), web=True)
    assert "Before you use a tool" in text and "Let me look that up." in text
    assert "Answer in the language the user speaks" in text
    assert "Before you use a tool" not in system_prompt(Config(), web=False)  # no tools: no need


# ----- interrupting with the wake word -----


def long_reply(daemon):
    def sentences():
        for i in range(200):
            if daemon._interrupted.is_set():
                return
            time.sleep(0.005)
            yield f"Sentence {i}."

    return sentences


def test_the_wake_word_stops_a_reply_and_abdoh_listens():
    engine = FakeWakeWord(fire_on=30)  # "Hey Abdoh", a moment into the reply
    daemon, _ = make_daemon(None, engine)
    daemon.router.reply = long_reply(daemon)
    daemon.mic = FakeMic([])
    daemon.handle_text("tell me a long story", voice=True)
    assert daemon.speaker.stops == 1
    assert len(daemon.speaker.said) < 200  # cut short
    assert daemon._take_listen_now() is True  # next: listen to you, no wake word needed
    assert daemon._awaiting_answer is False  # not a follow-up to a reply you cut off


def test_the_watch_ends_with_the_reply():
    engine = FakeWakeWord(fire_on=10**9)
    daemon, _ = make_daemon(lambda: iter(["Short."]), engine)
    daemon.mic = FakeMic([])
    daemon.handle_text("hi", voice=True)
    count = engine.count
    time.sleep(0.05)
    assert engine.count == count  # nobody is reading the microphone behind the main loop's back
    assert daemon.speaker.stops == 0


def test_no_watch_when_turned_off():
    off, _ = make_daemon("", FakeWakeWord(), Config(wake_word_interrupts=False))
    off.mic = FakeMic([])
    assert off._watch_reply() is None


def test_the_wake_word_also_stops_a_typed_requests_reply():
    daemon, _ = make_daemon("")
    with daemon._handle_lock:  # a typed request is being answered
        daemon._on_wake()
    assert daemon.speaker.stops == 1
    daemon._on_wake()  # nothing being said: nothing to stop
    assert daemon.speaker.stops == 1


# ----- a voice for your language -----


def test_a_missing_voice_is_explained_once_in_the_window():
    class Speaker(FakeSpeaker):
        on_missing_voice = None

    bus = Bus()
    speaker = Speaker()
    Daemon(Config(), Router(""), speaker, None, None, None, bus=bus)
    speaker.on_missing_voice("ar")
    (note,) = events(bus, "history")
    assert "Arabic voice" in note and "Time & language" in note


def test_the_speaker_learns_which_language_you_spoke():
    from fakes import silent_block, tone_block

    mic = FakeMic([tone_block()] * 2 + [tone_block()] * 4 + [silent_block()] * 30)
    transcriber = FakeTranscriber(["ما الوقت الآن؟"])
    transcriber.last_language = "ar"
    daemon = Daemon(
        Config(), Router(""), FakeSpeaker(), lambda: mic, FakeWakeWord(fire_on=2), transcriber
    )
    daemon._listen_once(mic)
    assert daemon.speaker.language == "ar"


def test_what_claude_says_before_a_search_is_spoken_before_the_search():
    """The whole chain: Claude Code's events -> sentences -> speech, in the order you hear it."""
    import json

    from abdoh.claude.code import read_events
    from abdoh.claude.reply import speakable

    def event(inner):
        return json.dumps({"type": "stream_event", "event": inner})

    def text(words):
        return event(
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": words}}
        )

    tool = {
        "type": "content_block_start",
        "content_block": {"type": "tool_use", "name": "WebSearch"},
    }
    lines = [
        text("Let me look that up."),
        event(tool),
        event({"type": "message_start"}),
        text("It's sunny."),
        json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": ""}),
    ]
    heard = []
    daemon, _ = make_daemon("")
    daemon.speaker.say = heard.append

    def on_tool(name):
        heard.append("(search starts)")
        daemon._activity("Searching the web")

    for sentence in speakable(read_events(lines, on_tool), lambda kind, arg: None):
        daemon._speak(sentence)
    assert heard == ["Let me look that up.", "(search starts)", "It's sunny."]
