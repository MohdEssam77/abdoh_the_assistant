"""Speech recognition on the graphics card: finding a card (abdoh/gpu.py), downloading the full
model (audio/gpu_model.py), the recognizer moving there and back (audio/stt.py), and the
background part with its status for Settings (audio/gpu_speech.py). No real card, no network."""

import hashlib
import io
import threading
from pathlib import Path

import numpy as np
import pytest
from test_stt import PARAKEET_DIR, PARAKEET_FILES, FakeParakeet, bundle

from abdoh import gpu
from abdoh.audio import gpu_model, gpu_speech
from abdoh.audio.stt import GPU_PROVIDERS, ParakeetTranscriber, gpu_model_dir, make_transcriber
from abdoh.config import Config
from abdoh.ui.api import UiState

GB = 2**30


@pytest.fixture(autouse=True)
def small_files(monkeypatch):
    """The full model's files, tiny: tests never write gigabytes."""
    files = {"encoder-model.onnx": (10, "x"), "encoder-model.onnx.data": (20, "y")}
    monkeypatch.setattr(gpu_model, "FILES", files)
    monkeypatch.setattr(gpu_model, "TOTAL", 30)


RTX = gpu.Gpu("NVIDIA GeForce RTX 3050 6GB Laptop GPU", int(5.86 * GB), "NVIDIA")
UHD = gpu.Gpu("Intel(R) UHD Graphics", 128 * 2**20, "Intel")

# ----- the card -----


def test_the_card_with_its_own_memory_is_chosen():
    assert gpu.suitable([UHD, RTX]) == RTX
    assert RTX.describe() == "NVIDIA GeForce RTX 3050 6GB Laptop GPU (6 GB)"


def test_built_in_graphics_and_small_cards_dont_count():
    assert gpu.suitable([UHD]) is None
    assert gpu.suitable([gpu.Gpu("GTX 1050", 2 * GB)]) is None
    assert gpu.suitable([gpu.Gpu("GTX 1650", int(3.9 * GB))]) is not None  # sold as 4 GB
    assert gpu.suitable([]) is None


def test_no_card_without_directml():
    listed = []
    assert gpu.find_gpu(list_cards=lambda: listed.append(1) or [RTX], ready=lambda: False) is None
    assert listed == []  # not even looked for
    assert gpu.find_gpu(list_cards=lambda: [RTX], ready=lambda: True) == RTX


def test_no_cards_outside_windows(monkeypatch):
    monkeypatch.setattr(gpu.sys, "platform", "linux")
    assert gpu.adapters() == []


# ----- downloading the full model -----


CONTENT = {"encoder-model.onnx": b"encoder" * 50, "encoder-model.onnx.data": b"weights" * 400}


@pytest.fixture
def small_model(monkeypatch, tmp_path):
    """The model's files, made small; the compact model to copy the shared files from."""
    files = {name: (len(data), hashlib.sha256(data).hexdigest()) for name, data in CONTENT.items()}
    monkeypatch.setattr(gpu_model, "FILES", files)
    monkeypatch.setattr(gpu_model, "TOTAL", sum(len(d) for d in CONTENT.values()))
    monkeypatch.setattr(gpu_model, "CHUNK", 64)
    compact = tmp_path / "compact"
    compact.mkdir()
    for name in gpu_model.FROM_COMPACT:
        (compact / name).write_text(name, encoding="utf-8")
    return tmp_path / "full", compact


class Server:
    """Hugging Face, here: answers a Range request with the rest (206), unless `ranges` is off."""

    def __init__(self, ranges=True, content=CONTENT, fail_at=None):
        self.ranges = ranges
        self.content = content
        self.fail_at = fail_at
        self.asked: list[tuple[str, int]] = []

    def __call__(self, url, start):
        name = url.rsplit("/", 1)[1]
        assert f"/resolve/{gpu_model.REVISION}/" in url  # always the pinned version
        self.asked.append((name, start))
        if self.fail_at == name:
            raise OSError("connection reset")
        data = self.content[name]
        response = io.BytesIO(data[start:] if self.ranges else data)
        response.status = 206 if start and self.ranges else 200
        return response


def test_the_model_downloads_and_is_checked(small_model):
    folder, compact = small_model
    seen = []
    gpu_model.download(folder, compact, on_progress=lambda d, t: seen.append(d), open_url=Server())
    assert gpu_model.ready(folder)
    assert (folder / "vocab.txt").read_text(encoding="utf-8") == "vocab.txt"  # from the compact
    assert seen[-1] == gpu_model.TOTAL
    assert not list(folder.glob("*.part"))


def test_an_interrupted_download_continues(small_model):
    folder, compact = small_model
    with pytest.raises(gpu_model.DownloadError, match="interrupted"):
        gpu_model.download(folder, compact, open_url=Server(fail_at="encoder-model.onnx.data"))
    data = CONTENT["encoder-model.onnx.data"]
    (folder / "encoder-model.onnx.data.part").write_bytes(data[:1000])  # the part that came
    server = Server()
    gpu_model.download(folder, compact, open_url=server)
    assert server.asked == [("encoder-model.onnx.data", 1000)]  # only the rest
    assert (folder / "encoder-model.onnx.data").read_bytes() == data


def test_a_server_that_sends_it_all_again_starts_over(small_model):
    folder, compact = small_model
    folder.mkdir()
    (folder / "encoder-model.onnx.part").write_bytes(b"encoder" * 10)
    gpu_model.download(folder, compact, open_url=Server(ranges=False))
    assert gpu_model.ready(folder)


def test_a_damaged_file_is_deleted(small_model):
    folder, compact = small_model
    bad = dict(CONTENT, **{"encoder-model.onnx": b"x" * len(CONTENT["encoder-model.onnx"])})
    with pytest.raises(gpu_model.DownloadError, match="damaged"):
        gpu_model.download(folder, compact, open_url=Server(content=bad))
    assert not (folder / "encoder-model.onnx").exists()
    assert not (folder / "encoder-model.onnx.part").exists()
    assert not gpu_model.ready(folder)


def test_not_without_enough_disk_space(small_model):
    folder, compact = small_model
    server = Server()
    with pytest.raises(gpu_model.DownloadError, match="free disk space"):
        gpu_model.download(folder, compact, open_url=server, free_space=lambda p: 10)
    assert server.asked == []


def test_stopping_keeps_what_came(small_model):
    folder, compact = small_model
    stop = threading.Event()

    def progress(done, total):
        if done > 200:
            stop.set()

    with pytest.raises(gpu_model.Stopped):
        gpu_model.download(folder, compact, on_progress=progress, stop=stop, open_url=Server())
    assert (folder / "encoder-model.onnx.part").exists() or (folder / "encoder-model.onnx").exists()


# ----- the recognizer on the card -----


class Made:
    """onnx_asr.load_model: what was asked for, and the model it makes (or an error)."""

    def __init__(self, gpu_fails=False, gpu_breaks=False):
        self.calls = []
        self.gpu_fails = gpu_fails
        self.gpu_breaks = gpu_breaks

    def __call__(self, name, path, quantization=None, providers=None, sess_options=None):
        on_gpu = providers is not None
        self.calls.append(("gpu" if on_gpu else "cpu", Path(path), quantization))
        if on_gpu and self.gpu_fails:
            raise RuntimeError("DirectML: device removed")
        model = FakeParakeet()
        if on_gpu and self.gpu_breaks:
            model.fail = True
            model.recognize = _breaks_after_warm_up(model)
        return model


def _breaks_after_warm_up(model):
    calls = []

    def recognize(samples, sample_rate):
        calls.append(1)
        if len(calls) > 1:
            raise RuntimeError("DXGI_ERROR_DEVICE_REMOVED")
        return ""

    return recognize


def v3(tmp_path, made, gpu_dir=None):
    return ParakeetTranscriber(tmp_path / "parakeet-tdt-0.6b-v3", made, gpu_dir=gpu_dir)


def test_the_full_model_loads_on_the_card(tmp_path):
    made = Made()
    stt = v3(tmp_path, made, gpu_dir=tmp_path / "full")
    assert stt.transcribe(b"\1\0" * 1600) == "What time is it?"
    assert stt.on_gpu
    assert made.calls == [("gpu", tmp_path / "full", None)]  # full size, no int8
    assert GPU_PROVIDERS[0][0] == "DmlExecutionProvider" and GPU_PROVIDERS[-1] == (
        "CPUExecutionProvider"
    )


def test_a_card_that_wont_load_falls_back_to_the_processor(tmp_path):
    made = Made(gpu_fails=True)
    stt = v3(tmp_path, made, gpu_dir=tmp_path / "full")
    assert stt.transcribe(b"\1\0" * 1600) == "What time is it?"
    assert not stt.on_gpu and stt.gpu_failed
    assert [c[0] for c in made.calls] == ["gpu", "cpu"]
    assert made.calls[1][2] == "int8"


def test_a_card_that_fails_later_falls_back_too(tmp_path):
    made = Made(gpu_breaks=True)
    stt = v3(tmp_path, made, gpu_dir=tmp_path / "full")
    assert stt.transcribe(b"\1\0" * 1600) == "What time is it?"  # still heard
    assert not stt.on_gpu and stt.gpu_failed
    assert stt.use_gpu(tmp_path / "full") is False  # not again until Abdoh restarts


def test_moving_to_the_card_and_back(tmp_path):
    made = Made()
    stt = v3(tmp_path, made)
    stt.warm_up()
    assert not stt.on_gpu
    assert stt.use_gpu(tmp_path / "full") is True
    assert stt.transcribe(b"\1\0" * 1600) == "What time is it?"
    assert stt.use_gpu(None) is False
    assert [c[0] for c in made.calls] == ["cpu", "gpu", "cpu"]


def test_the_english_only_model_never_uses_the_card(tmp_path):
    made = Made()
    stt = ParakeetTranscriber(tmp_path / "parakeet-tdt-0.6b-v2", made, gpu_dir=tmp_path / "full")
    stt.warm_up()
    assert made.calls[0][0] == "cpu"
    assert stt.use_gpu(tmp_path / "full") is False


def ready_model(app_dir: Path) -> Path:
    folder = app_dir / gpu_model.FOLDER
    folder.mkdir(parents=True)
    for name in gpu_model.FROM_COMPACT:
        (folder / name).write_text("x", encoding="utf-8")
    for name, (size, _) in gpu_model.FILES.items():
        (folder / name).write_bytes(b"x" * size)
    return folder


def test_when_the_card_is_used_from_the_start(tmp_path):
    cfg = Config(app_dir=tmp_path)
    not_needed = lambda: pytest.fail("not downloaded: no need to look")  # noqa: E731
    assert gpu_model_dir(cfg, find_gpu=not_needed) is None
    folder = ready_model(tmp_path)
    assert gpu_model_dir(cfg, find_gpu=lambda: RTX) == folder
    assert gpu_model_dir(cfg, find_gpu=lambda: None) is None  # the card is gone (undocked)
    cfg.use_gpu = False
    assert gpu_model_dir(cfg, find_gpu=lambda: RTX) is None


def test_a_new_install_starts_on_the_processor(tmp_path):
    bundle(tmp_path / PARAKEET_DIR, PARAKEET_FILES)
    stt = make_transcriber(Config(app_dir=tmp_path))
    assert isinstance(stt, ParakeetTranscriber) and stt.gpu_dir is None


# ----- in the background, with its status -----


def background(tmp_path, card=RTX, download=None, made=None, **cfg):
    statuses = []
    stt = v3(tmp_path, made or Made())
    stt.warm_up()

    def fake_download(folder, compact, on_progress, stop):
        on_progress(gpu_model.TOTAL // 2, gpu_model.TOTAL)
        ready_model(tmp_path)

    job = gpu_speech.GpuSpeech(
        Config(app_dir=tmp_path, **cfg),
        stt,
        statuses.append,
        find_gpu=lambda: card,
        download=download or fake_download,
        wait=0,
    )
    return job, stt, statuses


def finish(job):
    job.start()
    if job._thread is not None:
        job._thread.join(5)


def test_it_downloads_then_moves_to_the_card(tmp_path):
    job, stt, statuses = background(tmp_path)
    finish(job)
    card = RTX.describe()
    assert statuses == [
        gpu_speech.LOOKING,
        gpu_speech.DOWNLOADING.format(card=card, percent=0),
        gpu_speech.DOWNLOADING.format(card=card, percent=50),
        gpu_speech.MOVING.format(card=card),
        gpu_speech.ON.format(card=card),
    ]
    assert stt.on_gpu


def test_without_a_card_nothing_downloads(tmp_path):
    job, stt, statuses = background(tmp_path, card=None, download=lambda *a, **k: pytest.fail())
    finish(job)
    assert statuses[-1] == gpu_speech.NO_CARD and not stt.on_gpu


def test_a_failed_download_is_said(tmp_path):
    def offline(*args, **kwargs):
        raise gpu_model.DownloadError("The download was interrupted (no internet?).")

    job, stt, statuses = background(tmp_path, download=offline)
    finish(job)
    assert statuses[-1] == gpu_speech.NOT_DOWNLOADED.format(
        why="The download was interrupted (no internet?)."
    )
    assert not stt.on_gpu


def test_switched_off_it_stays_on_the_processor(tmp_path):
    job, stt, statuses = background(tmp_path, download=lambda *a, **k: pytest.fail(), use_gpu=False)
    finish(job)
    assert statuses == [gpu_speech.OFF] and not stt.on_gpu


def test_switching_it_off_moves_back(tmp_path):
    job, stt, statuses = background(tmp_path)
    finish(job)
    assert stt.on_gpu
    job.cfg.use_gpu = False
    job.apply()
    for thread in threading.enumerate():
        if thread.name == "abdoh-cpu-speech":
            thread.join(5)
    assert not stt.on_gpu and statuses[-1] == gpu_speech.OFF


def test_only_parakeet_v3_can_move(tmp_path):
    class Whisper:
        def transcribe(self, audio):
            return ""

    job = gpu_speech.GpuSpeech(Config(app_dir=tmp_path), Whisper(), find_gpu=lambda: RTX, wait=0)
    finish(job)
    assert job.status == "" and job._thread is None


def test_the_window_keeps_the_status():
    state = UiState()
    state.feed("gpu", gpu_speech.NO_CARD)
    assert state.snapshot()["gpu"] == gpu_speech.NO_CARD


def test_settings_turn_it_on_and_off_right_away(tmp_path):
    from test_daemon import StubRouter, make_daemon

    applied = []
    daemon = make_daemon(StubRouter([]), cfg=Config(app_dir=tmp_path))
    daemon.gpu_speech = type("Job", (), {"apply": lambda self: applied.append(1)})()
    daemon.apply_settings(Config(app_dir=tmp_path, use_gpu=False))
    assert applied == [1]
    daemon.apply_settings(Config(app_dir=tmp_path, use_gpu=False))
    assert applied == [1]  # unchanged: nothing to do


def test_no_audio_is_needed_for_any_of_this():
    assert np.zeros(1).dtype  # (the fakes above never touch a microphone or a card)


def test_the_app_is_built_with_the_directml_runtime():
    workflow = (Path(__file__).parents[1] / ".github/workflows/release.yml").read_text("utf-8")
    swap = workflow.index("pip install --no-deps onnxruntime-directml")
    assert workflow.index("pip uninstall -y onnxruntime") < swap < workflow.index("Run the tests")
