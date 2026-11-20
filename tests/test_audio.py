from fakes import FakeMic, FakeTranscriber, FakeWakeWord, silent_block, tone_block

from abdoh.audio.listener import listen_for_request
from abdoh.audio.recorder import (
    MIN_THRESHOLD,
    energy_detector,
    estimate_threshold,
    peak,
    record_until_silence,
    rms,
)
from abdoh.audio.wakeword import wait_for_wake_word
from abdoh.config import Config
from abdoh.speech.tts import FakeSpeaker


def test_rms():
    assert rms(silent_block()) == 0
    assert rms(tone_block(1000)) == 1000


def test_peak():
    assert peak(silent_block()) == 0 and peak(b"") == 0
    assert peak(tone_block(1000)) == 1000
    assert peak(tone_block(-32768)) == 32768  # no int16 overflow


def test_estimate_threshold_has_a_floor():
    assert estimate_threshold(silent_block() * 10) == MIN_THRESHOLD
    assert estimate_threshold(b"") == MIN_THRESHOLD


def test_record_stops_after_silence():
    mic = FakeMic([tone_block()] * 5 + [silent_block()] * 50)
    audio = record_until_silence(
        mic.read, energy_detector(500), silence_seconds=1.0, max_seconds=10
    )
    assert len(mic.history) == 15  # 5 speech + 10 silent blocks
    assert len(audio) == 15 * 3200


def test_record_stops_at_max():
    mic = FakeMic([tone_block()] * 500)
    record_until_silence(mic.read, energy_detector(500), silence_seconds=1.0, max_seconds=2.0)
    assert len(mic.history) == 20


def test_record_returns_empty_without_speech():
    mic = FakeMic([])
    assert (
        record_until_silence(mic.read, energy_detector(500), silence_seconds=1.0, wait_seconds=0.5)
        == b""
    )
    assert len(mic.history) == 5


def test_wait_for_wake_word():
    assert wait_for_wake_word(FakeMic([]).read, FakeWakeWord(fire_on=3)) is True
    assert wait_for_wake_word(FakeMic([]).read, FakeWakeWord(), should_stop=lambda: True) is False


def test_after_the_wake_word_the_request_is_what_follows():
    wake = [tone_block(2000)] * 2  # "hey abdoh" (and whatever was said before it)
    mic = FakeMic(wake + [tone_block()] * 4 + [silent_block()] * 20)
    stt = FakeTranscriber(["What time is it?"])
    chimes = []
    text = listen_for_request(
        mic,
        FakeWakeWord(fire_on=2),
        stt,
        FakeSpeaker(),
        Config(),
        on_listen=lambda: chimes.append("listening"),
    )
    assert text == "What time is it?"
    assert chimes == ["listening"]  # you hear that it woke up
    assert tone_block(2000) not in stt.calls[0]  # the wake word itself isn't transcribed
    assert stt.calls[0].startswith(tone_block() * 4)


def test_after_the_wake_word_abdoh_waits_for_you_to_go_on():
    pause = [silent_block()] * 20  # two seconds of thinking after "Hey Xanthos"
    mic = FakeMic([silent_block()] * 2 + pause + [tone_block()] * 4 + [silent_block()] * 20)
    speaker = FakeSpeaker()
    stt = FakeTranscriber(["open my mail"])
    text = listen_for_request(mic, FakeWakeWord(fire_on=2), stt, speaker, Config())
    assert text == "open my mail" and speaker.said == []


def test_nothing_after_the_wake_word_gets_a_yes():
    mic = FakeMic([silent_block()] * 2 + [silent_block()] * 35 + [tone_block()] * 4)
    speaker = FakeSpeaker()
    stt = FakeTranscriber(["what time is it"])
    text = listen_for_request(mic, FakeWakeWord(fire_on=2), stt, speaker, Config())
    assert speaker.said == ["Yes?"] and text == "what time is it"


def test_the_wake_word_and_then_nothing_is_nothing():
    mic = FakeMic([])
    stt = FakeTranscriber(["should not be used"])
    speaker = FakeSpeaker()
    assert listen_for_request(mic, FakeWakeWord(fire_on=2), stt, speaker, Config()) == ""
    assert stt.calls == [] and speaker.said == ["Yes?"]


class FakeVad:
    """Speech = loud block. Records resets and the warm-up audio it was given."""

    def __init__(self):
        self.resets = 0
        self.warmup: list[bytes] = []

    def reset(self):
        self.resets += 1

    def speech_prob(self, audio):
        self.warmup.append(audio)
        return 0.0

    def is_speech(self, block):
        return rms(block) > 100


def test_listen_uses_the_vad_when_given():
    mic = FakeMic([tone_block()] * 3 + [tone_block()] * 4 + [silent_block()] * 20)
    stt = FakeTranscriber(["what time is it"])
    vad = FakeVad()
    cfg = Config(silence_seconds=0.6)
    text = listen_for_request(mic, FakeWakeWord(fire_on=3), stt, FakeSpeaker(), cfg, vad=vad)
    assert text == "what time is it"
    assert vad.resets == 1
    assert vad.warmup and vad.warmup[0] == tone_block() * 3  # audio from before the wake word
    # 4 speech blocks after the wake word, then 0.6 s (6 blocks) of silence
    assert len(stt.calls[0]) // 3200 == 4 + 6


def test_vad_resets_before_the_follow_up():
    mic = FakeMic([silent_block()] * 2 + [silent_block()] * 35 + [tone_block()] * 4)
    stt = FakeTranscriber(["what time is it"])
    vad = FakeVad()
    listen_for_request(mic, FakeWakeWord(fire_on=2), stt, FakeSpeaker(), Config(), vad=vad)
    assert vad.resets == 2


def test_hotkey_records_without_a_wake_word(monkeypatch):
    monkeypatch.setattr("abdoh.audio.listener.CHIME_SECONDS", 0)
    mic = FakeMic([silent_block()] * 3 + [tone_block()] * 4 + [silent_block()] * 20)
    stt = FakeTranscriber(["what time is it"])
    chimes = []
    presses = iter([True])
    text = listen_for_request(
        mic,
        FakeWakeWord(fire_on=99),
        stt,
        FakeSpeaker(),
        Config(silence_seconds=0.6),
        pressed=lambda: next(presses, False),
        on_listen=lambda: chimes.append("listening"),
    )
    assert text == "what time is it"  # no wake word needed, and no "Yes?"
    assert chimes == ["listening"]
    assert stt.calls[0].count(tone_block()) == 4  # only what was said after the key press


def test_answer_is_recorded_without_the_wake_word(monkeypatch):
    monkeypatch.setattr("abdoh.audio.listener.CHIME_SECONDS", 0)
    mic = FakeMic([silent_block()] * 30 + [tone_block()] * 4 + [silent_block()] * 20)
    stt = FakeTranscriber(["Cairo."])
    engine = FakeWakeWord(fire_on=1)
    chimes = []
    text = listen_for_request(
        mic,
        engine,
        stt,
        FakeSpeaker(),
        Config(silence_seconds=0.6),
        on_listen=lambda: chimes.append("listening"),
        answer=True,
    )
    assert text == "Cairo."
    assert engine.count == 0  # the wake word engine wasn't needed
    assert chimes == ["listening"]
    assert stt.calls[0].count(tone_block()) == 4  # 3 s of thinking is fine (up to 5 s)


def test_no_answer_means_nothing(monkeypatch):
    monkeypatch.setattr("abdoh.audio.listener.CHIME_SECONDS", 0)
    stt = FakeTranscriber(["should not be used"])
    text = listen_for_request(
        FakeMic([]), FakeWakeWord(fire_on=99), stt, FakeSpeaker(), Config(), answer=True
    )
    assert text == "" and stt.calls == []


def test_hotkey_with_nothing_said(monkeypatch):
    monkeypatch.setattr("abdoh.audio.listener.CHIME_SECONDS", 0)
    stt = FakeTranscriber(["should not be used"])
    presses = iter([True])
    text = listen_for_request(
        FakeMic([]),
        FakeWakeWord(fire_on=99),
        stt,
        FakeSpeaker(),
        Config(),
        pressed=lambda: next(presses, False),
    )
    assert text == "" and stt.calls == []


def test_nothing_said_reports_how_loud_the_mic_was(monkeypatch):
    monkeypatch.setattr("abdoh.audio.listener.CHIME_SECONDS", 0)
    heard = []
    presses = iter([True])
    text = listen_for_request(
        FakeMic([tone_block(150)] * 5),  # some sound, quieter than speech
        FakeWakeWord(fire_on=99),
        FakeTranscriber(["should not be used"]),
        FakeSpeaker(),
        Config(),
        pressed=lambda: next(presses, False),
        on_nothing=heard.append,
    )
    assert text == "" and heard == [150]


def test_speech_is_not_reported_as_nothing(monkeypatch):
    monkeypatch.setattr("abdoh.audio.listener.CHIME_SECONDS", 0)
    heard = []
    text = listen_for_request(
        FakeMic([tone_block()] * 4 + [silent_block()] * 20),
        FakeWakeWord(fire_on=99),
        FakeTranscriber(["Cairo."]),
        FakeSpeaker(),
        Config(silence_seconds=0.6),
        answer=True,
        on_nothing=heard.append,
    )
    assert text == "Cairo." and heard == []


def test_the_microphone_stamps_each_block_with_when_it_arrived():
    """sounddevice calls the callback from its own thread with (indata, frames, time, status)."""
    import time

    from abdoh.audio.mic import Microphone

    mic = Microphone()
    before = time.perf_counter()
    mic._callback(tone_block(1000), 1600, object(), None)
    assert mic.read() == tone_block(1000)
    assert before <= mic.last_time <= time.perf_counter()
    assert mic.level == 1000
