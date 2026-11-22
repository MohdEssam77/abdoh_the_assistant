"""An answer that came out as no words is listened for again (it used to end the listening
without a word, and the real answer went unheard)."""

from fakes import FakeMic, FakeTranscriber, FakeWakeWord, silent_block, tone_block

from abdoh.audio.listener import listen_for_request
from abdoh.config import Config
from abdoh.speech.tts import FakeSpeaker

TONE, QUIET = tone_block(), silent_block()


def test_an_answer_with_no_words_is_listened_for_again(monkeypatch):
    """The math lesson: an "um" (or a breath, or Abdoh's own echo) and a pause to think ended
    the recording, no words came out, and the real answer went unheard."""
    monkeypatch.setattr("abdoh.audio.listener.CHIME_SECONDS", 0)
    mic = FakeMic([TONE] * 2 + [QUIET] * 10 + [TONE] * 4 + [QUIET] * 20)
    stt = FakeTranscriber(["", "The right half."])
    text = listen_for_request(
        mic, FakeWakeWord(fire_on=99), stt, FakeSpeaker(), Config(silence_seconds=0.6), answer=True
    )
    assert text == "The right half." and len(stt.calls) == 2


def test_no_words_again_and_again_ends_it(monkeypatch):
    monkeypatch.setattr("abdoh.audio.listener.CHIME_SECONDS", 0)
    stt = FakeTranscriber(["", "", "", "never asked"])
    text = listen_for_request(
        FakeMic(([TONE] * 2 + [QUIET] * 8) * 5),
        FakeWakeWord(fire_on=99),
        stt,
        FakeSpeaker(),
        Config(silence_seconds=0.6),
        answer=True,
    )
    assert text == "" and len(stt.calls) == 3
