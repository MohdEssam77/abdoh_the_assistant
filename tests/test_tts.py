import threading
import time

from abdoh.speech.tts import (
    SVSF_ASYNC,
    SVSF_IS_NOT_XML,
    SVSF_PURGE_BEFORE_SPEAK,
    FakeSpeaker,
    Pyttsx3Speaker,
    SapiSpeaker,
    Speaker,
    installed_voices,
    make_speaker,
    sapi_rate,
    text_language,
    voice_language,
    windows_voices,
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


DAVID = "Microsoft David Desktop - English (United States)"
ZIRA = "Microsoft Zira Desktop - English (United States)"


NAAYF = "Microsoft Naayf - Arabic (Saudi)"


class FakeToken:
    def __init__(self, name, language="409"):
        self.name, self.language = name, language

    def GetDescription(self):
        return self.name

    def GetAttribute(self, name):
        assert name == "Language"
        return self.language


class FakeTokens:
    def __init__(self, tokens):
        self.tokens = tokens
        self.Count = len(tokens)

    def Item(self, i):
        return self.tokens[i]


DESKTOP = [FakeToken(DAVID), FakeToken(ZIRA)]


class FakeSapiVoice:
    """Like SAPI.SpVoice: Speak() starts speaking, WaitUntilDone() says when it's finished."""

    def __init__(self, polls=3, on_poll=None):
        self.Rate = 0
        self.Voice = None
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

    def GetVoices(self):
        return FakeTokens(DESKTOP)


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


def test_sapi_uses_the_chosen_voice():
    factory = SapiFactory()
    SapiSpeaker(voice=ZIRA, voice_factory=factory).say("hi")
    assert factory.voices[0].Voice.GetDescription() == ZIRA


def test_sapi_keeps_the_default_voice_when_the_chosen_one_is_gone():
    factory = SapiFactory()
    SapiSpeaker(voice="Some Removed Voice", voice_factory=factory).say("hi")
    assert factory.voices[0].Voice is None
    assert factory.voices[0].calls  # still spoke


def test_new_speed_and_voice_apply_to_the_next_text():
    factory = SapiFactory()
    speaker = SapiSpeaker(rate=175, voice_factory=factory)
    speaker.say("one")
    speaker.configure(rate=250, voice=ZIRA)
    speaker.say("two")
    assert len(factory.voices) == 2
    assert factory.voices[1].Rate == sapi_rate(250)
    assert factory.voices[1].Voice.GetDescription() == ZIRA
    assert factory.voices[1].calls[0][0] == "two"


def test_windows_voices_lists_the_names():
    assert windows_voices(SapiFactory()) == [DAVID, ZIRA]

    def broken():
        raise OSError("no SAPI")

    assert windows_voices(broken) == []


def test_sapi_voice_is_recreated_after_an_error():
    factory = SapiFactory()
    speaker = SapiSpeaker(voice_factory=factory)
    speaker.say("boom")  # logged, never raised
    speaker.say("hello")
    assert len(factory.voices) == 2
    assert factory.voices[1].calls == [("hello", SVSF_ASYNC | SVSF_IS_NOT_XML)]


def test_sapi_rate_matches_words_per_minute():
    assert sapi_rate(175) == 1  # Xanthos's default
    assert sapi_rate(157) == 0  # the voice's normal speed
    assert sapi_rate(1000) == 10 and sapi_rate(20) == -10
    assert sapi_rate(0) == -10  # a bad setting doesn't break the voice


def test_make_speaker_picks_the_windows_voice_on_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    assert isinstance(make_speaker(), SapiSpeaker)
    monkeypatch.setattr("sys.platform", "linux")
    assert isinstance(make_speaker(), Pyttsx3Speaker)


# ----- a voice for each language -----


def test_voice_languages_and_text_languages():
    assert voice_language("409") == "en" and voice_language("401;1") == "ar"
    assert voice_language("C0A") == "es" and voice_language("") == ""
    assert text_language("Hello there") == "en"
    assert text_language("نعم، أنا هنا. كيف أقدر أساعدك؟") == "ar"
    assert text_language("نعم", hint="ur") == "ur"  # the same letters: your language wins
    assert text_language("Bonjour, ça va ?", hint="fr") == "fr"
    assert text_language("OK", hint="ar") == "en"  # Latin letters are not Arabic
    assert text_language("Привет") == "ru" and text_language("こんにちは、世界") == "ja"
    assert text_language("12:30") == "en"


def arabic_speaker(**kwargs):
    factory = SapiFactory()
    onecore = [FakeToken(NAAYF, "401")]
    speaker = SapiSpeaker(voice_factory=factory, onecore=lambda: onecore, **kwargs)
    return speaker, factory, onecore[0]


def test_arabic_text_is_read_by_the_arabic_voice_and_english_by_yours():
    speaker, factory, naayf = arabic_speaker(voice=ZIRA)
    speaker.say("نعم، أنا هنا.")
    voice = factory.voices[0]
    assert voice.Voice is naayf
    speaker.say("Back to English.")
    assert voice.Voice.GetDescription() == ZIRA
    assert [text for text, _ in voice.calls] == ["نعم، أنا هنا.", "Back to English."]


def test_without_a_voice_for_the_language_nothing_is_garbled():
    factory = SapiFactory()
    speaker = SapiSpeaker(voice_factory=factory)  # English voices only
    missing = []
    speaker.on_missing_voice = missing.append
    speaker.say("نعم، أنا هنا.")
    speaker.say("كيف أساعدك؟")
    assert factory.voices[0].calls == []  # an English voice can't read Arabic letters
    assert missing == ["ar"]  # said once


def test_latin_text_in_a_language_without_a_voice_is_still_read():
    factory = SapiFactory()
    speaker = SapiSpeaker(voice_factory=factory)
    missing = []
    speaker.on_missing_voice = missing.append
    speaker.language = "fr"
    speaker.say("Bonjour.")
    assert [text for text, _ in factory.voices[0].calls] == ["Bonjour."]
    assert missing == ["fr"]


def test_newer_windows_voices_are_listed_once():
    factory = SapiFactory()
    extra = [FakeToken(NAAYF, "401"), FakeToken(DAVID)]
    names = [name for name, _, _ in installed_voices(factory(), lambda: extra)]
    assert names == [DAVID, ZIRA, NAAYF]

    def broken():
        raise OSError("no OneCore voices")

    assert len(installed_voices(factory(), broken)) == 2


# ----- going quiet when you talk, and going on -----


class Status:
    def __init__(self, voice):
        self.voice = voice

    @property
    def InputWordPosition(self):  # noqa: N802 - SAPI's name
        return self.voice.word


class WordVoice(FakeSapiVoice):
    """Reaches one more word (6 characters) on every poll."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.word = 0
        self.Status = Status(self)

    def Speak(self, text, flags):  # noqa: N802 - SAPI's name
        super().Speak(text, flags)
        self.word = 0

    def WaitUntilDone(self, ms):  # noqa: N802
        time.sleep(0.005)  # like a real voice, a text takes a while
        done = super().WaitUntilDone(ms)
        if not done:
            self.word += 6
        return done


def paused_speaker(**kwargs):
    voices = []

    def factory():
        voice = WordVoice(polls=400, **kwargs)
        voices.append(voice)
        return voice

    speaker = SapiSpeaker(voice_factory=factory)
    return speaker, voices


def say_in_background(speaker, text):

    thread = threading.Thread(target=speaker.say, args=(text,), daemon=True)
    thread.start()
    return thread


def wait_for(condition, seconds=2.0):

    end = time.perf_counter() + seconds
    while not condition():
        assert time.perf_counter() < end, "timed out"
        time.sleep(0.005)


QUIET = ("", SVSF_ASYNC | SVSF_PURGE_BEFORE_SPEAK)


def test_pause_goes_quiet_and_resume_goes_on_from_the_same_word():
    speaker, voices = paused_speaker()
    text = "alpha bravo delta gamma omega sigma kappa theta"  # every word starts 6 apart
    thread = say_in_background(speaker, text)
    wait_for(lambda: voices and voices[0].word >= 12)
    assert speaker.pause() is True
    wait_for(lambda: voices[0].calls[-1] == QUIET)
    heard_up_to = len(voices[0].calls)
    time.sleep(0.15)
    assert len(voices[0].calls) == heard_up_to  # nothing more is said while paused
    assert thread.is_alive()  # say() waits: the reply waits with it
    speaker.resume()
    wait_for(lambda: len(voices[0].calls) > heard_up_to)
    rest, flags = voices[0].calls[-1]
    assert flags == SVSF_ASYNC | SVSF_IS_NOT_XML
    assert text.endswith(rest) and rest.split()[0] in text.split() and len(rest) < len(text)
    speaker.stop()
    thread.join(2)
    assert not thread.is_alive()


def test_stop_while_paused_ends_the_text():
    speaker, voices = paused_speaker()
    thread = say_in_background(speaker, "one two three four five six")
    wait_for(lambda: voices and voices[0].word >= 6)
    speaker.pause()
    wait_for(lambda: voices[0].calls[-1] == QUIET)
    speaker.stop()
    thread.join(2)
    assert not thread.is_alive()
    assert voices[0].calls[-1] == QUIET  # nothing was read after the stop


def test_pause_when_nothing_is_being_said():
    speaker, _ = paused_speaker()
    assert speaker.pause() is False
    speaker.say("hello")  # and a later text isn't held up
    assert FakeSpeaker().pause() is True


def test_a_voice_that_cant_continue_just_stops():
    class Plain(Speaker):
        def __init__(self):
            self.stops = 0

        def say(self, text):
            pass

        def stop(self):
            self.stops += 1

    plain = Plain()
    assert plain.pause() is False and plain.stops == 1
    plain.resume()  # nothing to go on with; no error
