"""The natural voice (Piper), with fake voices, a fake sound output and fake downloads: no
model, speakers or network."""

import threading
import time

import numpy as np

from abdoh.config import Config
from abdoh.speech.piper_voice import (
    DEFAULT_VOICES,
    PiperSpeaker,
    download_voice,
    make_voice,
    voice_path,
)
from abdoh.speech.tts import FakeSpeaker

RATE = 1000  # samples a second: 50 per block


class Stream:
    def __init__(self, output):
        self.output = output

    def write(self, block):
        self.output.written.append(np.array(block))
        if self.output.slow:
            time.sleep(0.01)

    def abort(self):
        self.output.events.append("abort")

    def start(self):
        self.output.events.append("start")

    def stop(self):
        self.output.events.append("stop")

    def close(self):
        self.output.events.append("close")


class Output:
    def __init__(self, slow=False):
        self.written = []
        self.events = []
        self.slow = slow

    def open(self, rate):
        self.rate = rate
        return Stream(self)

    def samples(self):
        return np.concatenate(self.written) if self.written else np.zeros(0)


def speaker(installed=("en_US-lessac-medium",), output=None, fallback=None, **kw):
    downloads = []
    loaded = []

    def find(name):
        return f"{name}.onnx" if name in installed else None

    def load(path):
        loaded.append(path)
        return path

    def synthesize(voice, text, length_scale):
        speaker.made.append((voice, text, length_scale))
        return np.arange(len(text) * 100, dtype=np.int16), RATE

    def download(name, folder):
        downloads.append(name)

    speaker = PiperSpeaker(
        find,
        "voices",
        fallback=fallback,
        load=load,
        synthesize=synthesize,
        output=output or Output(),
        download=download,
        **kw,
    )
    speaker.made, speaker.downloads, speaker.loaded = [], downloads, loaded
    return speaker


def wait_for(condition, timeout=2.0):
    for _ in range(int(timeout / 0.005)):
        if condition():
            return True
        time.sleep(0.005)
    return False


def test_it_speaks_a_sentence_with_the_voice_for_its_language():
    output = Output()
    voice = speaker(output=output)
    voice.say("Hello there.")
    assert voice.made == [("en_US-lessac-medium.onnx", "Hello there.", 1.0)]
    assert len(output.samples()) == 1200 and output.events[-2:] == ["stop", "close"]


def test_the_voice_is_loaded_once():
    voice = speaker()
    voice.say("One.")
    voice.say("Two.")
    assert voice.loaded == ["en_US-lessac-medium.onnx"]


def test_a_missing_voice_downloads_while_windows_speaks():
    fallback = FakeSpeaker()
    voice = speaker(installed=(), fallback=fallback)
    voice.language = "de"
    voice.say("Guten Morgen.")
    assert fallback.said == ["Guten Morgen."] and fallback.language == "de"
    assert wait_for(lambda: voice.downloads == ["de_DE-thorsten-medium"])
    voice.say("Noch einmal.")  # still downloading (the fake never finishes): not again
    time.sleep(0.05)
    assert voice.downloads == ["de_DE-thorsten-medium"]


def test_arabic_letters_get_the_arabic_voice():
    voice = speaker(installed=("ar_JO-kareem-medium",))
    voice.say("مرحبا")
    assert voice.made[0][0] == "ar_JO-kareem-medium.onnx"


def test_your_choice_of_voice_and_speed():
    voice = speaker(installed=("en_GB-alan-medium",), voices={"en": "en_GB-alan-medium"}, rate=350)
    voice.say("Hello.")
    assert voice.made[0][0] == "en_GB-alan-medium.onnx" and voice.made[0][2] == 0.5
    voice.configure(rate=175, voices={"en": "en_US-lessac-medium"})
    assert voice.voice_name("en") == "en_US-lessac-medium" and voice._length_scale() == 1.0


def test_a_voice_you_no_longer_use_leaves_memory():
    voice = speaker(installed=("en_US-lessac-medium", "en_US-ryan-medium", "de_DE-thorsten-medium"))
    voice.say("Hello.")
    voice.language = "de"
    voice.say("Hallo.")
    assert set(voice._loaded) == {"en_US-lessac-medium", "de_DE-thorsten-medium"}
    voice.configure(voices={"en": "en_US-ryan-medium"})
    assert "en_US-lessac-medium" not in voice._loaded  # let go of right away
    assert wait_for(lambda: "en_US-ryan-medium" in voice._loaded)  # the new one gets ready
    assert "de_DE-thorsten-medium" in voice._loaded  # German didn't change


def test_choosing_the_same_voices_again_changes_nothing():
    voice = speaker()
    voice.say("Hello.")
    voice.configure(rate=200, voices={})
    voice.configure(voices={"en": "en_US-lessac-medium"})  # the default, chosen by name
    assert voice.loaded == ["en_US-lessac-medium.onnx"]


def test_stop_cuts_it_off():
    output = Output(slow=True)
    voice = speaker(output=output)
    talking = threading.Thread(target=voice.say, args=("A long sentence " * 20,))
    talking.start()
    assert wait_for(lambda: len(output.written) >= 3)
    voice.stop()
    talking.join(1)
    assert not talking.is_alive() and "abort" in output.events
    assert len(output.samples()) < 32000


def test_pause_and_resume_go_on_from_a_little_before():
    output = Output(slow=True)
    voice = speaker(output=output)
    talking = threading.Thread(target=voice.say, args=("Something to say. " * 10,))
    talking.start()
    assert wait_for(lambda: len(output.written) >= 20)
    assert voice.pause() is True
    assert wait_for(lambda: "abort" in output.events)
    before = len(output.written)
    time.sleep(0.05)
    assert len(output.written) == before  # quiet while paused
    voice.resume()
    talking.join(5)
    assert "start" in output.events
    resumed_at = output.written[before][0]
    assert resumed_at < output.written[before - 1][0]  # it went back a little
    assert output.samples()[-1] == 18000 - 1  # and finished


def test_nothing_to_pause_when_quiet():
    assert speaker().pause() is False


def test_the_windows_voice_is_paused_when_it_is_the_one_talking():
    fallback = FakeSpeaker()
    voice = speaker(installed=(), fallback=fallback)
    assert voice.pause() is True and fallback.pauses == 1
    voice.resume()
    assert fallback.resumes == 1


def test_if_piper_fails_windows_speaks():
    fallback = FakeSpeaker()
    voice = speaker(fallback=fallback)

    def broken(voice_, text, scale):
        raise RuntimeError("bad model")

    voice._synthesize = broken
    voice.say("Hello.")
    assert fallback.said == ["Hello."]


def test_warm_up_gets_the_voices_ready():
    voice = speaker(installed=("en_US-lessac-medium",))
    voice.warm_languages = ("en", "de")
    voice.warm_up()
    assert wait_for(lambda: voice.loaded and voice.downloads == ["de_DE-thorsten-medium"])


def test_where_a_voice_is_downloaded_from(tmp_path):
    assert (
        voice_path("en_GB-jenny_dioco-medium")
        == "en/en_GB/jenny_dioco/medium/en_GB-jenny_dioco-medium"
    )
    got = []

    def fetch(url, target):
        got.append(url)
        target.write_bytes(b"model")

    path = download_voice("de_DE-thorsten-medium", tmp_path, fetch)
    assert path == tmp_path / "de_DE-thorsten-medium.onnx" and path.exists()
    assert (tmp_path / "de_DE-thorsten-medium.onnx.json").exists()
    assert got[0].endswith("de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx.json?download=true")
    assert not list(tmp_path.glob("*.part"))


def test_the_model_download_reports_how_far_along_it_is(tmp_path):
    told = []

    def fetch(url, target, progress=None):
        if progress is not None:  # only the model (about 60 MB), not its small settings file
            for done in (20, 40, 60):
                progress(done, 60)
        target.write_bytes(b"x")

    download_voice("fr_FR-siwis-medium", tmp_path, fetch, progress=lambda d, t: told.append(d))
    assert told == [20, 40, 60]


def test_the_window_hears_how_a_voice_download_goes():
    told = []

    def download(name, folder, progress=None):
        for done in (0, 30, 30, 60):  # the same percent twice is told once
            progress(done, 60)

    voice = speaker()
    voice._download = download
    voice.on_download = lambda name, percent: told.append((name, percent))
    voice._voice_for("fr")  # its voice isn't here: it downloads
    assert wait_for(lambda: told and told[-1][1] is None)
    assert told == [
        ("fr_FR-siwis-medium", 0),
        ("fr_FR-siwis-medium", 50),
        ("fr_FR-siwis-medium", 99),
        ("fr_FR-siwis-medium", None),
    ]  # fmt: skip  (each percent once; 99 until the file is in place, then done)


def test_the_daemon_shows_it_in_settings():
    from abdoh.daemon import Daemon
    from abdoh.events import Bus
    from abdoh.ui.api import UiState

    bus = Bus()
    daemon = Daemon.__new__(Daemon)
    daemon.bus = bus
    daemon._voice_download("fr_FR-siwis-medium", 45)
    state = UiState()
    for kind, value in bus.pending_events():
        state.feed(kind, value)
    assert state.snapshot()["voice_download"] == {
        "voice": "fr_FR-siwis-medium", "language": "French", "percent": 45
    }  # fmt: skip
    daemon._voice_download("fr_FR-siwis-medium", None)
    for kind, value in bus.pending_events():
        state.feed(kind, value)
    assert state.snapshot()["voice_download"] is None


def test_every_language_has_a_voice_name_that_parses():
    for language, name in DEFAULT_VOICES.items():
        assert name.startswith(language) and voice_path(name).count("/") == 4


def test_the_settings_choose_the_engine(tmp_path, monkeypatch):
    monkeypatch.setattr("abdoh.speech.tts.make_speaker", lambda *a, **k: FakeSpeaker())
    windows = make_voice(Config(app_dir=tmp_path, tts_engine="windows"))
    assert isinstance(windows, FakeSpeaker)
    natural = make_voice(Config(app_dir=tmp_path, piper_voice_de="de_DE-kerstin-medium"))
    assert isinstance(natural, PiperSpeaker) and isinstance(natural.fallback, FakeSpeaker)
    assert natural.voice_name("de") == "de_DE-kerstin-medium"
    model = tmp_path / "models" / "piper" / "en_US-lessac-medium.onnx"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"x")
    assert natural._find("en_US-lessac-medium") is None  # needs its .json too
    model.with_name(model.name + ".json").write_text("{}")
    assert natural._find("en_US-lessac-medium") == model


def test_the_voice_watch_hears_when_abdoh_starts_and_stops_playing():
    output = Output(slow=True)
    voice = speaker(output=output)
    heard = []
    voice.on_playing = heard.append
    talking = threading.Thread(target=voice.say, args=("Something to say. " * 10,))
    talking.start()
    assert wait_for(lambda: len(output.written) >= 5)
    voice.pause()
    assert wait_for(lambda: heard[-1:] == [False])  # paused: nothing comes out
    voice.resume()
    talking.join(5)
    assert heard[0] is True and heard[-1] is False and heard.count(True) == 2


def test_a_sentence_as_a_wav_file_for_the_phone():
    import io
    import wave

    output = Output()
    voice = speaker(output=output)
    wav = voice.render("Hello there.")
    with wave.open(io.BytesIO(wav)) as read:
        assert (read.getnchannels(), read.getsampwidth(), read.getframerate()) == (1, 2, RATE)
        assert read.getnframes() == len("Hello there.") * 100
    assert voice.render("   ") is None
    assert output.written == []  # nothing on the laptop's speakers


def test_no_wav_without_a_natural_voice_yet():
    voice = speaker(installed=())  # still downloading: the phone's own voice says it
    assert voice.render("Hello there.") is None
