"""Speech recognition on the graphics card, when there's a suitable one (use_gpu, on by default).

In the background: find the card (abdoh/gpu.py), download the full model the first time
(abdoh/audio/gpu_model.py), then move the recognizer there. Meanwhile, and on any computer
without such a card, speech recognition runs on the processor as before. `status` says how
it's going, for the Settings page."""

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from abdoh.audio import gpu_model

log = logging.getLogger(__name__)

LOOKING = "Looking for a graphics card…"
OFF = "Off: speech recognition runs on the processor."
NO_CARD = (
    "This computer has no graphics card with 4 GB or more of its own, so speech recognition runs "
    "on the processor."
)
DOWNLOADING = (
    "Downloading the speech model for your {card}: {percent}% of 2.4 GB. Speech recognition "
    "works as usual meanwhile."
)
NOT_DOWNLOADED = "Couldn't download the speech model for your graphics card. {why} Abdoh tries \
again when it next starts."
MOVING = "Moving speech recognition to your {card}…"
ON = "Speech recognition runs on your {card}: about twice as fast, with less memory."
FAILED = (
    "Your graphics card didn't work for speech recognition, so it runs on the processor until "
    "Abdoh restarts."
)
WAIT_BEFORE_DOWNLOAD = 30.0  # seconds: Abdoh has started and settled first


class GpuSpeech:
    def __init__(
        self,
        cfg,
        transcriber,
        on_status: Callable[[str], None] = lambda text: None,
        find_gpu=None,
        download=gpu_model.download,
        wait: float = WAIT_BEFORE_DOWNLOAD,
    ):
        self.cfg = cfg
        self.transcriber = transcriber
        self.on_status = on_status
        self._find_gpu = find_gpu
        self._download = download
        self._wait = wait
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.status = ""

    @property
    def folder(self) -> Path:
        return self.cfg.app_dir / gpu_model.FOLDER

    def usable(self) -> bool:
        """Is speech recognition the kind that can run on a card (Parakeet v3)?"""
        return bool(getattr(self.transcriber, "v3", False)) and hasattr(self.transcriber, "use_gpu")

    def _say(self, text: str) -> None:
        if text != self.status:
            self.status = text
            self.on_status(text)

    def start(self) -> None:
        """Check, download and move (in the background), as the setting says."""
        if not self.usable():
            return
        if not self.cfg.use_gpu:
            self._say(OFF)
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="abdoh-gpu-speech", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Abdoh is closing: stop downloading (it continues next time)."""
        self._stop.set()

    def apply(self) -> None:
        """The setting changed: on, start; off, stop and go back to the processor."""
        if not self.usable():
            return
        if self.cfg.use_gpu:
            self.start()
            return
        self._stop.set()
        self._say(OFF)
        if self.transcriber.on_gpu:
            threading.Thread(
                target=self.transcriber.use_gpu, args=(None,), name="abdoh-cpu-speech", daemon=True
            ).start()

    def _run(self) -> None:
        try:
            self._move()
        except Exception:
            log.exception("Couldn't set up speech recognition on the graphics card")
            self._say(FAILED)

    def _move(self) -> None:
        stt = self.transcriber
        if stt.gpu_failed:
            self._say(FAILED)
            return
        if not stt.on_gpu:
            self._say(LOOKING)
        find = self._find_gpu
        if find is None:
            from abdoh.gpu import find_gpu as find
        card = find()
        if card is None:
            log.info("No suitable graphics card: speech recognition stays on the processor")
            self._say(NO_CARD)
            return
        name = card.describe()
        if not gpu_model.ready(self.folder):
            self._say(DOWNLOADING.format(card=name, percent=0))
            if self._stop.wait(self._wait):
                return
            shown = [-1]

            def progress(done: int, total: int) -> None:
                percent = int(done * 100 / total)
                if percent != shown[0]:
                    shown[0] = percent
                    self._say(DOWNLOADING.format(card=name, percent=percent))

            try:
                self._download(self.folder, stt.model_dir, on_progress=progress, stop=self._stop)
            except gpu_model.Stopped:
                return
            except gpu_model.DownloadError as e:
                log.warning("Couldn't download the model for the graphics card: %s", e)
                self._say(NOT_DOWNLOADED.format(why=e))
                return
        if self._stop.is_set() or not self.cfg.use_gpu:
            return
        if not stt.on_gpu:
            self._say(MOVING.format(card=name))
        self._say(ON.format(card=name) if stt.use_gpu(self.folder) else FAILED)
