from abdoh.speech.tts import FakeSpeaker, Speaker


def test_fake_speaker_records_calls():
    s = FakeSpeaker()
    s.say("hello")
    s.say("world")
    assert isinstance(s, Speaker)
    assert s.said == ["hello", "world"]
