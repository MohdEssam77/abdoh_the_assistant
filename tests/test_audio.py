from fakes import FakeMic, FakeTranscriber, FakeWakeWord, silent_block, tone_block

from abdoh.audio.listener import listen_for_request
from abdoh.audio.recorder import MIN_THRESHOLD, estimate_threshold, record_until_silence, rms
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
    audio = record_until_silence(mic.read, 500, silence_seconds=1.0, max_seconds=10)
    assert len(mic.history) == 15  # 5 speech + 10 silent blocks
    assert len(audio) == 15 * 3200


def test_record_stops_at_max():
    mic = FakeMic([tone_block()] * 500)
    record_until_silence(mic.read, 500, silence_seconds=1.0, max_seconds=2.0)
    assert len(mic.history) == 20


def test_record_returns_empty_without_speech():
    mic = FakeMic([])
    assert record_until_silence(mic.read, 500, silence_seconds=1.0, wait_seconds=0.5) == b""
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


def test_listen_asks_yes_when_only_wake_word():
    mic = FakeMic([tone_block()] * 2 + [silent_block()] * 12 + [tone_block()] * 5)
    stt = FakeTranscriber(["Hey Abdoh.", "what time is it"])
    speaker = FakeSpeaker()
    text = listen_for_request(mic, FakeWakeWord(fire_on=2), stt, speaker, Config())
    assert speaker.said == ["Yes?"]
    assert text == "what time is it"
