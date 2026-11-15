import threading

from abdoh.speech.tts import (
    SVSF_ASYNC,
    SVSF_IS_NOT_XML,
    SVSF_PURGE_BEFORE_SPEAK,
    FakeSpeaker,
    Pyttsx3Speaker,
    SapiSpeaker,
    Speaker,
    make_speaker,
    sapi_rate,
)


def test_fake_speaker_records_calls():
    s = FakeSpeaker()
    s.say("hello")
    s.say("world")
    s.stop()
    assert isinstance(s, Speaker)
    assert s.said == ["hello", "world"]
    assert s.stops == 1


class FakeEngine:
    """Speaks word by word, firing the 'started-word' callback like pyttsx3 does."""

    def __init__(self, on_word=None):
        self.props = {}
        self.callbacks = {}
        self.spoken: list[str] = []
        self.pending = ""
        self.stopped = False
        self.on_word = on_word  # test hook, called after each spoken word

    def setProperty(self, name, value):
        self.props[name] = value

    def connect(self, name, callback):
        self.callbacks[name] = callback

    def say(self, text):
        self.pending = text

    def runAndWait(self):
        if self.pending == "boom":
            raise RuntimeError("driver error")
        self.stopped = False
        for i, word in enumerate(self.pending.split()):
            self.callbacks["started-word"]("utterance", i, len(word))
            if self.stopped:
                return
            self.spoken.append(word)
            if self.on_word:
                self.on_word()

    def stop(self):
        self.stopped = True


class Factory:
    def __init__(self, on_word=None):
        self.engines: list[FakeEngine] = []
        self.on_word = on_word

    def __call__(self):
        engine = FakeEngine(self.on_word)
        self.engines.append(engine)
        return engine


def test_engine_is_created_once_and_reused():
    factory = Factory()
    speaker = Pyttsx3Speaker(rate=150, engine_factory=factory)
    speaker.say("hello there")
    speaker.say("good morning")
    assert len(factory.engines) == 1
    engine = factory.engines[0]
    assert engine.spoken == ["hello", "there", "good", "morning"]
    assert engine.props["rate"] == 150


def test_blank_text_is_not_spoken():
    factory = Factory()
    speaker = Pyttsx3Speaker(engine_factory=factory)
    speaker.say("   ")
    speaker.say("hi")
    assert factory.engines[0].spoken == ["hi"]


def test_stop_interrupts_at_the_next_word():
    holder = {}
    factory = Factory(on_word=lambda: holder["speaker"].stop())
    speaker = Pyttsx3Speaker(engine_factory=factory)
    holder["speaker"] = speaker
    speaker.say("one two three four")
    assert factory.engines[0].spoken == ["one"]


def test_speaks_normally_after_a_stop():
    factory = Factory()
    speaker = Pyttsx3Speaker(engine_factory=factory)
    speaker.stop()
    speaker.say("still here")
    assert factory.engines[0].spoken == ["still", "here"]


def test_engine_is_recreated_after_an_error():
    factory = Factory()
    speaker = Pyttsx3Speaker(engine_factory=factory)
    speaker.say("boom")  # logged, never raised
    speaker.say("hello")
    assert len(factory.engines) == 2
    assert factory.engines[1].spoken == ["hello"]


def test_warm_up_creates_the_engine_before_the_first_reply():
    created = threading.Event()
    factory = Factory()

    def make():
        engine = factory()
        created.set()
        return engine

    speaker = Pyttsx3Speaker(engine_factory=make)
    speaker.warm_up()
    assert created.wait(2)
    speaker.say("hi")
    assert len(factory.engines) == 1


# ----- the Windows voice (SAPI) -----


class FakeSapiVoice:
    """Like SAPI.SpVoice: Speak() starts speaking, WaitUntilDone() says when it's finished."""

    def __init__(self, polls=3, on_poll=None):
        self.Rate = 0
        self.calls: list[tuple[str, int]] = []
        self.polls = polls  # each text takes this many WaitUntilDone() calls to finish
        self.left = 0
        self.on_poll = on_poll  # test hook, called on every WaitUntilDone()

    def Speak(self, text, flags):
        if text == "boom":
            raise OSError("COM error")
        self.calls.append((text, flags))
        self.left = 0 if flags & SVSF_PURGE_BEFORE_SPEAK else self.polls

    def WaitUntilDone(self, ms):
        if self.on_poll:
            self.on_poll()
        if self.left == 0:
            return True
        self.left -= 1
        return False


class SapiFactory:
    def __init__(self, **kwargs):
        self.voices: list[FakeSapiVoice] = []
        self.kwargs = kwargs

    def __call__(self):
        voice = FakeSapiVoice(**self.kwargs)
        self.voices.append(voice)
        return voice


def test_sapi_speaks_until_done_with_one_voice():
    factory = SapiFactory()
    speaker = SapiSpeaker(rate=175, voice_factory=factory)
    speaker.say("hello there")
    speaker.say("good morning")
    assert len(factory.voices) == 1
    voice = factory.voices[0]
    flags = SVSF_ASYNC | SVSF_IS_NOT_XML  # never read "<" in a reply as voice markup
    assert voice.calls == [("hello there", flags), ("good morning", flags)]
    assert voice.left == 0  # say() returned only when the voice had finished
    assert voice.Rate == 1


def test_sapi_stop_cuts_the_voice_off():
    holder = {}
    factory = SapiFactory(polls=100, on_poll=lambda: holder["speaker"].stop())
    speaker = SapiSpeaker(voice_factory=factory)
    holder["speaker"] = speaker
    speaker.say("a very long answer")
    assert factory.voices[0].calls[-1] == ("", SVSF_ASYNC | SVSF_PURGE_BEFORE_SPEAK)


def test_sapi_speaks_normally_after_a_stop():
    factory = SapiFactory()
    speaker = SapiSpeaker(voice_factory=factory)
    speaker.stop()
    speaker.say("still here")
    assert factory.voices[0].calls == [("still here", SVSF_ASYNC | SVSF_IS_NOT_XML)]


def test_sapi_voice_is_recreated_after_an_error():
    factory = SapiFactory()
    speaker = SapiSpeaker(voice_factory=factory)
    speaker.say("boom")  # logged, never raised
    speaker.say("hello")
    assert len(factory.voices) == 2
    assert factory.voices[1].calls == [("hello", SVSF_ASYNC | SVSF_IS_NOT_XML)]


def test_sapi_rate_matches_words_per_minute():
    assert sapi_rate(175) == 1  # Abdoh's default
    assert sapi_rate(157) == 0  # the voice's normal speed
    assert sapi_rate(1000) == 10 and sapi_rate(20) == -10
    assert sapi_rate(0) == -10  # a bad setting doesn't break the voice


def test_make_speaker_picks_the_windows_voice_on_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    assert isinstance(make_speaker(), SapiSpeaker)
    monkeypatch.setattr("sys.platform", "linux")
    assert isinstance(make_speaker(), Pyttsx3Speaker)
