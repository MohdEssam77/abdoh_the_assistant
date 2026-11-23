"""Hearing you right: speech after the wake word with no words in it, unclear clips, the speech
model kept warm, how clearly the name was heard, and which screens are connected."""

import os
import threading
import time
import wave

from fakes import FakeMic, FakeTranscriber, FakeWakeWord, silent_block, tone_block

from abdoh.about import state_line
from abdoh.audio import unclear
from abdoh.audio.listener import listen_for_request
from abdoh.audio.stt import Transcriber
from abdoh.config import Config
from abdoh.daemon import HOUSEKEEPING_SECONDS, WARM_EVERY_SECONDS, Daemon
from abdoh.displays import Displays, Monitor
from abdoh.speech.tts import FakeSpeaker

# ----- the listener -----


def test_talk_after_the_wake_word_with_no_words_is_reported():
    heard = []
    mic = FakeMic([silent_block()] * 2 + [tone_block()] * 12 + [silent_block()] * 20)
    stt = FakeTranscriber([""])  # the recognizer made nothing of it
    text = listen_for_request(
        mic, FakeWakeWord(fire_on=2), stt, FakeSpeaker(), Config(), on_unclear=heard.append
    )
    assert text == "" and len(heard) == 1 and len(heard[0]) >= 1.2 * 32000


def test_a_short_noise_with_no_words_is_not():
    heard = []
    mic = FakeMic([silent_block()] * 2 + [tone_block()] * 3 + [silent_block()] * 20)
    stt = FakeTranscriber([""])
    listen_for_request(
        mic, FakeWakeWord(fire_on=2), stt, FakeSpeaker(), Config(), on_unclear=heard.append
    )
    assert heard == []


def test_words_are_not_unclear():
    heard = []
    mic = FakeMic([silent_block()] * 2 + [tone_block()] * 12 + [silent_block()] * 20)
    stt = FakeTranscriber(["what time is it"])
    text = listen_for_request(
        mic, FakeWakeWord(fire_on=2), stt, FakeSpeaker(), Config(), on_unclear=heard.append
    )
    assert text == "what time is it" and heard == []


class NoSpeech:
    """A voice detector that hears no speech in anything (a quiet or late "act as ...")."""

    def reset(self):
        pass

    def speech_prob(self, audio):
        return 0.0

    def is_speech(self, block):
        return False


def missed_after_wake(blocks):
    missed = []
    text = listen_for_request(
        FakeMic([silent_block()] * 2 + blocks),
        FakeWakeWord(fire_on=2),
        FakeTranscriber([]),
        FakeSpeaker(),
        Config(),
        vad=NoSpeech(),
        on_missed=missed.append,
    )
    return text, missed


def test_a_sound_after_the_wake_word_that_wasnt_speech_is_reported(caplog):
    caplog.set_level("INFO")
    text, missed = missed_after_wake([tone_block(2000)] * 10)
    assert text == "" and len(missed) == 1
    assert len(missed[0]) >= 10 * len(tone_block())  # the seconds it waited, sound and all
    assert "Nothing said after the wake word (loudest sound 2000 of 32768, -24 dB)" in caplog.text


def test_silence_after_the_wake_word_is_not(caplog):
    caplog.set_level("INFO")
    text, missed = missed_after_wake([tone_block(150)] * 10)  # a room's hum
    assert text == "" and missed == []
    assert "loudest sound 150 of 32768" in caplog.text


# ----- the daemon -----


class RecordingEarcons:
    def __init__(self):
        self.played = []

    def play(self, name):
        self.played.append(name)

    def start_ticking(self, name="thinking", every=3.0):
        pass

    def stop_ticking(self):
        pass


class Router:
    brain = None
    computer = None
    modes = None

    def __init__(self, replies=()):
        self.on_thinking = self.on_activity = None
        self.unclear = 0
        self.replies = list(replies)
        self.last_turn = None
        self.woken = []

    def add_builtin(self, *args):
        pass

    def heard_unclear(self):
        self.unclear += 1

    def handle(self, text, aside=False, woken=False):
        self.woken.append(woken)
        return self.replies.pop(0)


def make_daemon(app_dir, router=None, transcriber=None, **settings):
    cfg = Config(app_dir=app_dir, **settings)
    return Daemon(
        cfg,
        router or Router(),
        FakeSpeaker(),
        None,
        FakeWakeWord(fire_on=10_000),
        transcriber or FakeTranscriber([]),
        earcons=RecordingEarcons(),
    )


def test_no_words_plays_the_unclear_sound_and_says_nothing(tmp_path):
    daemon = make_daemon(tmp_path)
    daemon._heard_unclear(tone_block() * 15)
    assert daemon.earcons.played == ["unclear"]
    assert daemon.speaker.said == []
    assert daemon._awaiting_answer is False  # no listening afterwards
    assert daemon.router.unclear == 1  # the next Claude request is told
    assert unclear.clips(tmp_path / "voice") == []  # the switch is off


def test_with_the_switch_on_the_recording_is_kept(tmp_path):
    daemon = make_daemon(tmp_path, keep_unclear_clips=True)
    daemon._heard_unclear(tone_block() * 15)
    [clip] = unclear.clips(tmp_path / "voice")
    with wave.open(str(clip)) as wav:
        assert (wav.getframerate(), wav.getnframes()) == (16000, 15 * 1600)


def test_a_missed_request_is_kept_and_claude_hears_of_it(tmp_path):
    daemon = make_daemon(tmp_path, keep_unclear_clips=True)
    daemon._missed_after_wake(tone_block() * 50)
    assert len(unclear.clips(tmp_path / "voice")) == 1
    assert daemon.router.unclear == 1  # "did you hear me?" gets an honest answer
    assert daemon.earcons.played == []  # no sound: it may have been the TV


def test_a_missed_request_isnt_kept_with_the_switch_off(tmp_path):
    daemon = make_daemon(tmp_path)
    daemon._missed_after_wake(tone_block() * 50)
    assert unclear.clips(tmp_path / "voice") == [] and daemon.router.unclear == 1


def test_turning_the_switch_off_deletes_the_recordings(tmp_path):
    daemon = make_daemon(tmp_path, keep_unclear_clips=True)
    daemon._heard_unclear(tone_block() * 15)
    daemon._use_brain = lambda brain: None
    daemon.apply_settings(Config(app_dir=tmp_path, keep_unclear_clips=False))
    assert unclear.clips(tmp_path / "voice") == []


class Turn:
    actions = ()
    ignored = True


def test_claude_ignoring_a_wake_up_plays_the_unclear_sound(tmp_path):
    router = Router([iter(())])
    router.last_turn = Turn()
    daemon = make_daemon(tmp_path, router)
    daemon.handle_text("so then she said", voice=True, woken=(0.4, 0.95))
    assert router.woken == [(0.4, 0.95)]  # Claude hears how clearly its name was said
    assert daemon.earcons.played == ["unclear"]


def test_ignoring_talk_after_a_reply_stays_silent(tmp_path):
    router = Router([iter(())])
    router.last_turn = Turn()
    daemon = make_daemon(tmp_path, router)
    daemon.handle_text("so then she said", voice=True, aside=True)
    assert daemon.earcons.played == []


# ----- unclear clips -----


def test_clips_are_deleted_after_a_day(tmp_path):
    old = unclear.save_clip(tmp_path, b"\0\0" * 1600)
    new = unclear.save_clip(tmp_path, b"\0\0" * 1600)  # same second: a second name
    assert old != new
    day_ago = time.time() - 25 * 3600
    os.utime(old, (day_ago, day_ago))
    assert unclear.prune(tmp_path) == 1
    assert unclear.clips(tmp_path) == [new]
    assert unclear.delete_all(tmp_path) == 1 and unclear.clips(tmp_path) == []
    assert unclear.prune(tmp_path / "missing") == 0


def test_voice_training_never_reads_unclear_clips(tmp_path):
    from abdoh.audio.voicecheck import Recordings

    unclear.save_clip(tmp_path, b"\0\0" * 1600)
    assert Recordings(tmp_path).count() == 0 and Recordings(tmp_path).phrases() == []


# ----- the speech model kept warm -----


class FakeModel(Transcriber):
    def __init__(self):
        super().__init__()
        self._model = object()
        self.runs = 0

    def _recognize(self, model, samples):
        self.runs += 1
        self.last_language = "de"
        return ""


def test_keeping_warm_runs_the_model_and_leaves_the_language_alone():
    model = FakeModel()
    model.last_language = "en"
    model.keep_warm()
    assert model.runs == 1 and model.last_language == "en"


def test_keeping_warm_never_waits_for_a_real_transcription():
    model = FakeModel()
    with model._lock:
        model.keep_warm()  # one is running: skipped at once
    assert model.runs == 0
    unloaded = FakeModel()
    unloaded._model = None
    unloaded.keep_warm()
    assert unloaded.runs == 0


class WarmTranscriber(FakeTranscriber):
    def __init__(self):
        super().__init__([])
        self.warmed = threading.Event()
        self.warm_count = 0

    def keep_warm(self):
        self.warm_count += 1
        self.warmed.set()


def test_the_wake_word_warms_the_speech_model(tmp_path):
    stt = WarmTranscriber()
    daemon = make_daemon(tmp_path, transcriber=stt)
    daemon._on_wake()
    assert stt.warmed.wait(2)


def test_housekeeping_warms_every_few_minutes_and_after_sleep(tmp_path):
    stt = WarmTranscriber()
    daemon = make_daemon(tmp_path, transcriber=stt)
    daemon._warm_speech = lambda: setattr(stt, "warm_count", stt.warm_count + 1)
    daemon._housekeeping_tick(wall=1000.0, now=0.0)
    assert stt.warm_count == 1  # at start
    daemon._housekeeping_tick(wall=1030.0, now=30.0)
    assert stt.warm_count == 1
    daemon._housekeeping_tick(wall=1000.0 + WARM_EVERY_SECONDS, now=WARM_EVERY_SECONDS)
    assert stt.warm_count == 2  # every few minutes
    later = 1000.0 + WARM_EVERY_SECONDS + 4 * HOUSEKEEPING_SECONDS
    daemon._housekeeping_tick(wall=later + 3600, now=WARM_EVERY_SECONDS + 31)
    assert stt.warm_count == 3  # the computer slept in between


def test_housekeeping_deletes_old_clips(tmp_path):
    daemon = make_daemon(tmp_path)
    clip = unclear.save_clip(tmp_path / "voice", b"\0\0" * 1600)
    day_ago = time.time() - 25 * 3600
    os.utime(clip, (day_ago, day_ago))
    daemon._housekeeping_tick(wall=1000.0, now=0.0)
    assert unclear.clips(tmp_path / "voice") == []


# ----- which screens are connected -----


class FakeBackend:
    def __init__(self, monitors):
        self._monitors = monitors

    def monitors(self):
        return list(self._monitors)


def test_claude_hears_which_screens_are_connected(tmp_path):
    laptop = Monitor("laptop-id", "", True, True, True, gdi=r"\\.\DISPLAY1")
    hp = Monitor("hp-id", "HP 32f", False, True, gdi=r"\\.\DISPLAY2")
    samsung = Monitor("sam-id", "C34H89x", False, True, gdi=r"\\.\DISPLAY3")
    displays = Displays(tmp_path / "displays.json", FakeBackend([laptop, hp, samsung]))
    displays.all()  # numbered 1, 2, 3 while docked
    displays.rename("hp-id", "mid screen")
    displays.backend = FakeBackend([laptop])  # undocked
    summary = displays.summary()
    assert summary == "1 Laptop screen (on); not connected: 2 mid screen, 3 C34H89x"
    line = state_line("Work", True, False, summary)
    assert line.endswith("screens: 1 Laptop screen (on); not connected: 2 mid screen, 3 C34H89x")
    assert state_line() == "no mode on; voice replies on"
