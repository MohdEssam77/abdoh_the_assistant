from fakes import FakeMic, FakeTranscriber, FakeWakeWord, silent_block, tone_block

from abdoh.audio.listener import listen_for_request
from abdoh.audio.recorder import (
    MIN_THRESHOLD,
    energy_detector,
    estimate_threshold,
    record_until_silence,
    rms,
)
from abdoh.audio.wakeword import contains_phrase, wait_for_wake_word
from abdoh.config import Config
from abdoh.speech.tts import FakeSpeaker


def test_rms():
    assert rms(silent_block()) == 0
    assert rms(tone_block(1000)) == 1000


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


def test_contains_phrase_needs_whole_phrase():
    phrases = ["ab doe", "abdul"]
    assert contains_phrase("[unk] ab doe", phrases)
    assert contains_phrase("abdul", phrases)
    assert not contains_phrase("ab", phrases)
    assert not contains_phrase("hey [unk]", phrases)


def test_wait_for_wake_word():
    assert wait_for_wake_word(FakeMic([]).read, FakeWakeWord(fire_on=3)) is True
    assert wait_for_wake_word(FakeMic([]).read, FakeWakeWord(), should_stop=lambda: True) is False


def test_listen_includes_audio_before_wake_word():
    mic = FakeMic([tone_block()] * 3 + [silent_block()] * 20)
    stt = FakeTranscriber(["Good morning Abdoh."])
    speaker = FakeSpeaker()
    text = listen_for_request(mic, FakeWakeWord(fire_on=3), stt, speaker, Config())
    assert text == "Good morning Abdoh."
    assert speaker.said == []
    assert stt.calls[0].startswith(tone_block() * 3)


def test_listen_ignores_false_wake_up():
    mic = FakeMic([tone_block()] * 3 + [silent_block()] * 20)
    stt = FakeTranscriber(["So, um, yeah."])
    speaker = FakeSpeaker()
    text = listen_for_request(mic, FakeWakeWord(fire_on=3), stt, speaker, Config())
    assert text == ""
    assert speaker.said == []


def test_listen_asks_yes_when_only_wake_word():
    mic = FakeMic([tone_block()] * 2 + [silent_block()] * 12 + [tone_block()] * 5)
    stt = FakeTranscriber(["Hey Abdoh.", "what time is it"])
    speaker = FakeSpeaker()
    text = listen_for_request(mic, FakeWakeWord(fire_on=2), stt, speaker, Config())
    assert speaker.said == ["Yes?"]
    assert text == "what time is it"


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
    stt = FakeTranscriber(["Hey Abdoh what time is it"])
    vad = FakeVad()
    cfg = Config(silence_seconds=0.6)
    text = listen_for_request(mic, FakeWakeWord(fire_on=3), stt, FakeSpeaker(), cfg, vad=vad)
    assert text == "Hey Abdoh what time is it"
    assert vad.resets == 1
    assert vad.warmup and vad.warmup[0] == tone_block() * 3  # audio from before the wake word
    # 3 blocks before the wake word, 4 more speech blocks, then 0.6 s (6 blocks) of silence
    assert len(stt.calls[0]) // 3200 == 3 + 4 + 6


def test_listen_waits_a_little_longer_for_the_first_word():
    mic = FakeMic([tone_block()] * 3 + [silent_block()] * 20)
    stt = FakeTranscriber(["Good morning Abdoh"])
    cfg = Config(silence_seconds=0.6)
    listen_for_request(mic, FakeWakeWord(fire_on=3), stt, FakeSpeaker(), cfg, vad=FakeVad())
    assert len(mic.blocks) == 23 - 3 - 8  # START_WAIT_SECONDS = 0.8 s of no speech
    assert stt.calls[0] == tone_block() * 3  # nothing followed the wake word


def test_vad_resets_before_the_follow_up():
    mic = FakeMic([tone_block()] * 2 + [silent_block()] * 12 + [tone_block()] * 5)
    stt = FakeTranscriber(["Hey Abdoh.", "what time is it"])
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
