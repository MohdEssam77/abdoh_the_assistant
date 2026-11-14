import threading

from abdoh.speech.tts import FakeSpeaker, Pyttsx3Speaker, Speaker


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
