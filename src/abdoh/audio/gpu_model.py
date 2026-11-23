"""The full-size speech model for the graphics card (see abdoh/gpu.py).

Abdoh ships the compact Parakeet model, which runs on the processor. On a computer with a
suitable graphics card, the full-size one (about 2.4 GB) downloads in the background into
Abdoh's data folder: on the card it's about twice as fast and leaves the RAM and the processor
alone. The files are pinned to one version and checked against their checksums; an interrupted
download continues where it stopped."""

import hashlib
import logging
import shutil
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

FOLDER = "models/parakeet-tdt-0.6b-v3-gpu"
REPO = "istupakov/parakeet-tdt-0.6b-v3-onnx"
REVISION = "8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce"
URL = "https://huggingface.co/{repo}/resolve/{revision}/{name}"
# The full-size files: name -> (bytes, sha256).
FILES = {
    "encoder-model.onnx": (
        41770866,
        "98a74b21b4cc0017c1e7030319a4a96f4a9506e50f0708f3a516d02a77c96bb1",
    ),
    "encoder-model.onnx.data": (
        2435420160,
        "9a22d372c51455c34f13405da2520baefb7125bd16981397561423ed32d24f36",
    ),
    "decoder_joint-model.onnx": (
        72520893,
        "e978ddf6688527182c10fde2eb4b83068421648985ef23f7a86be732be8706c1",
    ),
}
# The same in both models: copied from the compact one that ships with Abdoh.
FROM_COMPACT = ("config.json", "vocab.txt", "nemo128.onnx")
TOTAL = sum(size for size, _ in FILES.values())
SPARE = 2**30  # free disk space left over afterwards
CHUNK = 1 << 20

Progress = Callable[[int, int], None]  # (bytes so far, bytes in all)


class DownloadError(Exception):
    """The model couldn't be downloaded; the message is short and safe to show."""


class Stopped(Exception):
    """Abdoh is closing, or the setting was switched off."""


def ready(folder: Path) -> bool:
    """Is the full model there, complete?"""
    folder = Path(folder)
    if not all((folder / name).is_file() for name in FROM_COMPACT):
        return False
    return all(_size(folder / name) == size for name, (size, _) in FILES.items())


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return -1


def _open(url: str, start: int):
    headers = {"User-Agent": "Abdoh-model-download"}
    if start:
        headers["Range"] = f"bytes={start}-"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60)


def download(
    folder: Path,
    compact: Path,
    on_progress: Progress = lambda done, total: None,
    stop: threading.Event | None = None,
    open_url=_open,
    free_space=lambda path: shutil.disk_usage(path).free,
) -> None:
    """Get the full model into `folder`. Raises DownloadError, or Stopped."""
    folder, compact = Path(folder), Path(compact)
    folder.mkdir(parents=True, exist_ok=True)
    for name in FROM_COMPACT:
        if not (folder / name).is_file():
            shutil.copyfile(compact / name, folder / name)
    have = {
        name: size if _size(folder / name) == size else max(_size(folder / f"{name}.part"), 0)
        for name, (size, _) in FILES.items()
    }
    needed = TOTAL - sum(have.values())
    if needed and free_space(folder) < needed + SPARE:
        gigabytes = (needed + SPARE) / 2**30
        raise DownloadError(f"It needs {gigabytes:.1f} GB of free disk space.")
    done = sum(have.values())
    for name, (size, checksum) in FILES.items():
        if _size(folder / name) == size:
            continue
        done = _fetch(name, size, checksum, folder, done, on_progress, stop, open_url)
    log.info("The speech model for the graphics card is ready in %s", folder)


def _fetch(name, size, checksum, folder, done, on_progress, stop, open_url) -> int:
    part = folder / f"{name}.part"
    start = max(_size(part), 0)
    if start > size:
        part.unlink()
        start = 0
    url = URL.format(repo=REPO, revision=REVISION, name=name)
    if start < size:
        resumed = f" from {start >> 20} MB" if start else ""
        log.info("Downloading %s (%d MB)%s", name, size >> 20, resumed)
        try:
            with open_url(url, start) as response:
                if start and getattr(response, "status", 206) != 206:
                    done -= start  # the server sent it all again: start over
                    start = 0
                with open(part, "ab" if start else "wb") as f:
                    while chunk := response.read(CHUNK):
                        if stop is not None and stop.is_set():
                            raise Stopped
                        f.write(chunk)
                        done += len(chunk)
                        on_progress(done, TOTAL)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            raise DownloadError("The download was interrupted (no internet?).") from e
    if _size(part) != size or _sha256(part, stop) != checksum:
        part.unlink(missing_ok=True)
        raise DownloadError("A downloaded file was damaged, so it was deleted.")
    part.replace(folder / name)
    return done


def _sha256(path: Path, stop: threading.Event | None) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8 * CHUNK):
            if stop is not None and stop.is_set():
                raise Stopped
            digest.update(chunk)
    return digest.hexdigest()
