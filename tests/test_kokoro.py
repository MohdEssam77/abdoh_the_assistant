"""Kokoro's English voices: phonemes, making the audio (a fake model), and their place among the
natural voices (download, settings). No model, speakers or network."""

import json

import numpy as np
from test_piper_voice import Output, speaker

from abdoh.config import Config
from abdoh.speech import kokoro_voice as kokoro
from abdoh.speech.kokoro_voice import KokoroModel, KokoroVoice, phonemes
from abdoh.speech.piper_voice import ENGLISH_VOICES, make_voice
from abdoh.speech.tts import FakeSpeaker


def fake_espeak(language, text):
    """espeak-ng's IPA, decomposed per character, one list per sentence (like Piper's)."""
    return [list("ðə kˈæt sˈæt ɑːn ðə mˈæt."), list("ɡˈʊd.")]


def test_phonemes_are_adjusted_as_kokoro_expects():
    assert phonemes("The cat.", phonemize=fake_espeak) == "ðə kˈæt sˈæt ɑːn ðə mˈæt.ɡˈʊd."
    r_sound = phonemes("x", phonemize=lambda lang, text: [list("ræx")])
    assert r_sound == "ɹæk"  # espeak's r and x: Kokoro knows ɹ and k


class FakeSession:
    def __init__(self):
        self.feeds = []

    def run(self, outputs, feed):
        self.feeds.append(feed)
        return [np.full((1, 2400), 0.5, dtype=np.float32)]


def model(tmp_path):
    vocab = {c: i for i, c in enumerate("ðəkˈætsɑːnmɡʊd. ", start=1)}
    (tmp_path / "tokenizer.json").write_text(json.dumps({"model": {"vocab": vocab}}), "utf-8")
    return KokoroModel(tmp_path, session=FakeSession())


def test_a_sentence_becomes_audio(tmp_path):
    styles = np.arange(40 * 256, dtype=np.float32).reshape(40, 1, 256)
    voice = KokoroVoice(model(tmp_path), styles, "en-us", phonemize=fake_espeak)
    audio, rate = voice.synthesize_audio("The cat sat on the mat. Good.", length_scale=0.8)
    assert rate == 24000 and audio.dtype == np.int16 and len(audio) == 2400
    assert audio[0] == int(0.5 * 32767)
    feed = voice.model.session.feeds[0]
    ids = feed["input_ids"][0]
    tokens = len(phonemes("", phonemize=fake_espeak))  # 30: every one of them is known
    assert ids[0] == 0 and ids[-1] == 0 and len(ids) == 2 + tokens
    assert np.array_equal(feed["style"], styles[tokens])  # the style for that many tokens
    assert feed["speed"][0] == 1.25  # faster speech: Piper's length 0.8


def test_nothing_to_say_is_silence(tmp_path):
    voice = KokoroVoice(model(tmp_path), np.zeros((5, 1, 256), np.float32), "en-us",
                        phonemize=lambda lang, text: [])  # fmt: skip
    audio, rate = voice.synthesize_audio("")
    assert len(audio) == 0 and voice.model.session.feeds == []


class KokoroLike:
    def __init__(self):
        self.said = []

    def synthesize_audio(self, text, length_scale):
        self.said.append((text, length_scale))
        return np.ones(500, dtype=np.int16), 1000


def test_the_natural_voice_plays_a_kokoro_voice():
    output = Output()
    kokoro_voice = KokoroLike()
    voice = speaker(installed=("kokoro:af_heart",), output=output, voices={"en": "kokoro:af_heart"})
    voice._load = lambda path: kokoro_voice
    voice.say("Hello there.")
    assert kokoro_voice.said == [("Hello there.", 1.0)] and voice.made == []  # not Piper
    assert len(output.samples()) == 500 and output.rate == 1000


def test_kokoro_voices_are_english_choices():
    assert set(kokoro.NAMES) <= set(ENGLISH_VOICES)
    assert kokoro.label("kokoro:bf_emma") == "Emma (British, Kokoro)"
    assert kokoro.VOICES["bm_george"][1] == "en-gb" and kokoro.VOICES["af_heart"][1] == "en-us"
    files = [name for name, _, _ in kokoro.DOWNLOAD.files]
    assert files[-1] == "onnx/model.onnx" and len(files) == 2 + len(kokoro.VOICES)


def test_a_kokoro_voice_is_found_once_downloaded(tmp_path, monkeypatch):
    monkeypatch.setattr("abdoh.speech.tts.make_speaker", lambda *a, **k: FakeSpeaker())
    natural = make_voice(Config(app_dir=tmp_path, piper_voice_en="kokoro:af_heart"))
    assert natural.voice_name("en") == "kokoro:af_heart"
    assert natural._find("kokoro:af_heart") is None  # not downloaded: it downloads
    fetched = []

    def fetch(download, folder, on_progress=None, stop=None):
        fetched.append(folder)
        for name, size, _ in download.files:
            (folder / name).parent.mkdir(parents=True, exist_ok=True)
            (folder / name).write_bytes(b"x" * size if size < 10**6 else b"")

    monkeypatch.setattr("abdoh.download.fetch", fetch)
    monkeypatch.setattr("abdoh.speech.kokoro_voice.ready", lambda folder: True)
    path = natural._download(
        "kokoro:af_heart", tmp_path / "models/piper", progress=lambda d, t: None
    )
    assert fetched == [tmp_path / "models/kokoro"]
    assert path == tmp_path / "models/kokoro/voices/af_heart.bin"
    assert natural._find("kokoro:af_heart") == path


def test_the_download_bar_says_english(tmp_path):
    from abdoh.daemon import Daemon
    from abdoh.events import Bus

    daemon = Daemon.__new__(Daemon)
    daemon.bus = Bus()
    daemon._voice_download("kokoro:af_heart", 12)
    assert daemon.bus.pending_events()[-1][1]["language"] == "English"


def test_the_setting_takes_kokoro_voices(app_dir):
    from abdoh.settings import save_settings

    assert save_settings(app_dir, {"piper_voice_en": "kokoro:bm_george"}).piper_voice_en == (
        "kokoro:bm_george"
    )
