"""Settings → Advanced: the model catalog, downloading, switching and deleting what's replaced."""

import functools
import hashlib
import io
import threading
from types import SimpleNamespace

import pytest

from abdoh import download, models
from abdoh.audio.stt import ParakeetTranscriber, WhisperTranscriber, make_transcriber
from abdoh.config import Config
from abdoh.download import Download, DownloadError, Stopped

# ----- the catalog -----


def test_every_model_has_a_line_and_what_it_downloads():
    assert len(models.BY_ID) == len(models.SPEECH_MODELS)
    for model in models.SPEECH_MODELS:
        assert model.name and len(model.line) > 40 and model.line.endswith(".")
        if model.bundled:
            assert model.download_for(["en"]) is None and model.size_mb == 0
        else:
            for spec in model.downloads.values():
                assert spec.revision and len(spec.revision) == 40  # pinned
                assert spec.folder.startswith("models/")
                assert abs(spec.total / 1e6 - model.size_mb) < model.size_mb * 0.1
            big = max(spec.files, key=lambda f: f[1])
            assert len(big[2]) == 64  # the big file is checked


def test_which_models_fit_your_languages():
    v3, v2, small = (
        models.find("parakeet-v3"),
        models.find("parakeet-v2"),
        models.find("whisper-small"),
    )
    assert v3.fits(["en"]) and v3.fits(["de"]) and v3.fits(["en", "de"])
    assert not v3.fits(["en", "fr"])  # it can't tell those two apart
    assert not v3.fits(["ar"]) and small.fits(["ar", "en"])
    assert v2.fits(["en"]) and not v2.fits(["de"])


def test_english_only_gets_the_english_whisper():
    small = models.find("whisper-small")
    assert small.download_for(["en"]).repo == "Systran/faster-whisper-small.en"
    assert small.download_for(["en", "ar"]).repo == "Systran/faster-whisper-small"


def test_the_setting_takes_only_known_models(app_dir):
    from abdoh.settings import SPEECH_MODEL_IDS, SettingsError, save_settings

    assert set(SPEECH_MODEL_IDS) == {"", *models.BY_ID}
    assert save_settings(app_dir, {"speech_model": "parakeet-v2"}).speech_model == "parakeet-v2"
    with pytest.raises(SettingsError):
        save_settings(app_dir, {"speech_model": "whisper-huge"})


# ----- downloading -----

FILES = {"model.bin": b"weights" * 100, "config.json": b"{}"}
TINY = Download(
    "models/tiny",
    "someone/tiny",
    "0" * 40,
    tuple(
        (n, len(b), hashlib.sha256(b).hexdigest() if n == "model.bin" else "")
        for n, b in FILES.items()
    ),
)


class FakeServer:
    """Hugging Face, here: serves FILES, from a byte on (Range), or a damaged copy."""

    def __init__(self, damaged=False, fail=False):
        self.asked = []
        self.damaged, self.fail = damaged, fail

    def __call__(self, url, start):
        self.asked.append((url, start))
        if self.fail:
            raise OSError("no internet")
        body = FILES[url.rsplit("/", 1)[1]]
        if self.damaged:
            body = b"x" * len(body)
        response = io.BytesIO(body[start:])
        response.status = 206 if start else 200
        return response


def fetch(server, **kw):
    return functools.partial(download.fetch, open_url=server, free_space=lambda p: 10**12, **kw)


def test_a_model_downloads_with_progress_and_a_marker(tmp_path):
    seen = []
    server = FakeServer()
    fetch(server)(TINY, tmp_path / "tiny", on_progress=lambda d, t: seen.append(d * 100 // t))
    assert download.ready(tmp_path / "tiny", TINY) and download.downloaded_by_abdoh(
        tmp_path / "tiny"
    )
    assert seen[0] == 0 and seen[-1] == 100
    assert (
        server.asked[0][0]
        == "https://huggingface.co/someone/tiny/resolve/" + "0" * 40 + "/model.bin"
    )


def test_an_interrupted_download_goes_on_where_it_stopped(tmp_path):
    folder = tmp_path / "tiny"
    folder.mkdir()
    (folder / "model.bin.part").write_bytes(FILES["model.bin"][:300])
    server = FakeServer()
    fetch(server)(TINY, folder)
    assert (
        "https://huggingface.co/someone/tiny/resolve/" + "0" * 40 + "/model.bin",
        300,
    ) in server.asked
    assert (folder / "model.bin").read_bytes() == FILES["model.bin"]


@pytest.mark.parametrize(
    "server, free, said",
    [
        (FakeServer(damaged=True), 10**12, "damaged"),
        (FakeServer(fail=True), 10**12, "interrupted"),
        (FakeServer(), 100, "free disk space"),
    ],
    ids=["damaged", "no internet", "full disk"],
)
def test_when_it_cant_download(tmp_path, server, free, said):
    with pytest.raises(DownloadError, match=said):
        download.fetch(TINY, tmp_path / "tiny", open_url=server, free_space=lambda p: free)
    assert not (tmp_path / "tiny" / "model.bin").exists()


def test_a_download_stops_when_asked(tmp_path):
    stop = threading.Event()
    stop.set()
    with pytest.raises(Stopped):
        fetch(FakeServer())(TINY, tmp_path / "tiny", stop=stop)


def test_only_folders_abdoh_downloaded_are_deleted(tmp_path):
    mine, yours = tmp_path / "mine", tmp_path / "yours"
    fetch(FakeServer())(TINY, mine)
    yours.mkdir()
    (yours / "model.bin").write_bytes(b"yours")
    assert download.delete(mine) and not mine.exists()
    assert not download.delete(yours) and (yours / "model.bin").exists()


# ----- choosing a model and switching to it -----


class FakeWhisperModel:
    def __init__(self, *args, **kwargs):
        pass

    def transcribe(self, samples, **kwargs):
        return [], SimpleNamespace(language="en", all_language_probs=[])


class FakeParakeetModel:
    def recognize(self, samples, sample_rate=16000):
        return ""


TINY_MODEL = models.SpeechModel(
    "whisper-tiny", "Whisper tiny", "A tiny one for tests.", "whisper", None, 1, size="tiny",
    downloads={"any": TINY},
)  # fmt: skip


@pytest.fixture
def tiny_catalog(monkeypatch):
    monkeypatch.setattr(models, "BY_ID", {**models.BY_ID, "whisper-tiny": TINY_MODEL})
    monkeypatch.setattr(models, "SPEECH_MODELS", (*models.SPEECH_MODELS, TINY_MODEL))
    monkeypatch.setattr(models, "recommended_id", lambda cfg: "parakeet-v3")


def parakeet(tmp_path):
    return ParakeetTranscriber(tmp_path / "models/parakeet-tdt-0.6b-v3",
                               make_model=lambda *a, **k: FakeParakeetModel())  # fmt: skip


def make_fake(cfg):
    """make_transcriber, with fake models: the chosen tiny Whisper, or Parakeet."""
    model = models.chosen(cfg)
    if model is not None and models.is_ready(cfg, model):
        return WhisperTranscriber("tiny", cfg.languages, models.folder_of(cfg, model),
                                  make_model=FakeWhisperModel)  # fmt: skip
    return parakeet(cfg.app_dir)


def switch_for(tmp_path, cfg, server=None):
    swapped, said = [], []
    switch = models.ModelSwitch(
        cfg, parakeet(tmp_path), swapped.append, said.append,
        fetch=fetch(server or FakeServer()), make=make_fake, wait=0,
    )  # fmt: skip
    return switch, swapped, said


def run(switch):
    switch.apply()
    switch._thread.join(5)


def test_choosing_a_model_downloads_it_then_switches(tmp_path, tiny_catalog):
    cfg = Config(app_dir=tmp_path, speech_model="whisper-tiny")
    switch, swapped, said = switch_for(tmp_path, cfg)
    run(switch)
    assert [models.in_use(t) for t in swapped] == ["whisper-tiny"]
    states = [s["state"] for s in said]
    assert states[0] == "downloading" and states[-2:] == ["switching", "ready"]
    assert said[-1] == {"state": "ready", "id": "whisper-tiny"}
    assert any(s.get("percent") == 100 for s in said)


def test_back_to_recommended_deletes_the_download(tmp_path, tiny_catalog):
    cfg = Config(app_dir=tmp_path, speech_model="whisper-tiny")
    switch, swapped, said = switch_for(tmp_path, cfg)
    run(switch)
    folder = tmp_path / "models/tiny"
    assert folder.exists()  # in use: kept
    cfg.speech_model = ""
    run(switch)
    assert models.in_use(swapped[-1]) == "parakeet-v3" and not folder.exists()


def test_what_is_in_use_or_not_downloaded_by_abdoh_stays(tmp_path, tiny_catalog):
    cfg = Config(app_dir=tmp_path, speech_model="")
    fetch(FakeServer())(TINY, tmp_path / "models/tiny")
    switch, swapped, said = switch_for(tmp_path, cfg)
    switch.transcriber = WhisperTranscriber("tiny", ["en"], tmp_path / "models/tiny")  # in use
    switch._clean()
    assert (tmp_path / "models/tiny").exists()
    (tmp_path / "models/parakeet-tdt-0.6b-v3").mkdir(parents=True)  # inside the app: no marker
    switch.transcriber = parakeet(tmp_path)
    switch._clean()
    assert not (tmp_path / "models/tiny").exists()
    assert (tmp_path / "models/parakeet-tdt-0.6b-v3").exists()


def test_a_failed_download_keeps_the_model_in_use(tmp_path, tiny_catalog):
    cfg = Config(app_dir=tmp_path, speech_model="whisper-tiny")
    switch, swapped, said = switch_for(tmp_path, cfg, FakeServer(fail=True))
    run(switch)
    assert swapped == [] and models.in_use(switch.transcriber) == "parakeet-v3"
    assert said[-1]["state"] == "failed" and "interrupted" in said[-1]["error"]


def test_nothing_happens_when_the_model_is_already_in_use(tmp_path, tiny_catalog):
    switch, swapped, said = switch_for(tmp_path, Config(app_dir=tmp_path))
    run(switch)
    assert swapped == [] and said == [{"state": "ready", "id": "parakeet-v3"}]


def test_a_chosen_model_is_used_once_it_is_there(tmp_path, tiny_catalog):
    cfg = Config(app_dir=tmp_path, speech_model="whisper-tiny")
    assert not isinstance(make_transcriber(cfg), WhisperTranscriber) or (
        make_transcriber(cfg).model_size != "tiny"
    )  # not downloaded yet: the recommended one
    fetch(FakeServer())(TINY, tmp_path / "models/tiny")
    made = make_transcriber(cfg)
    assert isinstance(made, WhisperTranscriber) and made.model_dir == tmp_path / "models/tiny"


def test_a_chosen_model_that_doesnt_fit_the_languages_is_not_used(tmp_path):
    cfg = Config(app_dir=tmp_path, speech_model="parakeet-v2", languages=["de"])
    assert models.chosen(cfg) is None


def test_the_listing_for_the_window(tmp_path):
    cfg = Config(app_dir=tmp_path, speech_model="parakeet-v2", languages=["en"])
    listed = models.listing(cfg, parakeet(tmp_path), {"state": "downloading", "id": "parakeet-v2"})
    ids = [m["id"] for m in listed["speech"]]
    assert ids == ["parakeet-v3", "parakeet-v2", "whisper-base", "whisper-small", "whisper-medium"]
    v2 = listed["speech"][1]
    assert v2["chosen"] and not v2["using"] and not v2["ready"]
    assert listed["using"] == "parakeet-v3" and listed["status"]["state"] == "downloading"
    arabic = models.listing(Config(app_dir=tmp_path, languages=["ar"]), None)
    assert [m["id"] for m in arabic["speech"]] == [
        "whisper-base",
        "whisper-small",
        "whisper-medium",
    ]


def test_the_daemon_swaps_the_recognizer(tmp_path):
    from test_daemon import StubRouter, make_daemon

    daemon = make_daemon(StubRouter([]), cfg=Config(app_dir=tmp_path))
    new = parakeet(tmp_path)
    daemon.use_transcriber(new)
    assert daemon.transcriber is new
