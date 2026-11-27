"""Hearing a request (abdoh/audio/listener.py)."""


def test_slow_transcription_is_judged_by_how_long_you_spoke(monkeypatch, caplog):
    """0.7 s for 15 s of speech is normal (it was warned about); 3 s for 2 s isn't."""
    from abdoh.audio import listener
    from abdoh.audio.mic import BYTES_PER_SECOND

    class Took:
        def __init__(self, seconds):
            self.seconds = seconds

        def transcribe(self, audio):
            return "hi"

    for spoke, took, slow in ((15.0, 0.7, False), (2.0, 3.0, True), (1.0, 0.5, False)):
        clock = iter([100.0, 100.0 + took])
        monkeypatch.setattr(listener.time, "perf_counter", lambda clock=clock: next(clock))
        caplog.clear()
        listener._transcribe(Took(took), b"\0" * int(spoke * BYTES_PER_SECOND))
        warned = any("Slow transcription" in r.getMessage() for r in caplog.records)
        assert warned is slow, (spoke, took)
