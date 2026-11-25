"""Downloading a model's files into a folder: pinned to one revision, resumed where an interrupted
download stopped, checked against their sizes (and checksums, where known), with progress.

A folder this downloaded gets a marker file (MARKER): Abdoh may delete such a folder later (a
model replaced in Settings → Advanced), never one it didn't download itself.
"""

import hashlib
import logging
import shutil
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

MARKER = ".abdoh-download"
HF_URL = "https://huggingface.co/{repo}/resolve/{revision}/{name}"
SPARE = 2**30  # free disk space left over afterwards
CHUNK = 1 << 20

Progress = Callable[[int, int], None]  # (bytes so far, bytes in all)


class DownloadError(Exception):
    """The model couldn't be downloaded; the message is short and safe to show."""


class Stopped(Exception):
    """Abdoh is closing, or the download was cancelled."""


@dataclass(frozen=True)
class Download:
    """A model's files on Hugging Face: (name, bytes, sha256 or "") at one revision."""

    folder: str  # where it goes, relative to Abdoh's folder
    repo: str
    revision: str
    files: tuple[tuple[str, int, str], ...]

    @property
    def total(self) -> int:
        return sum(size for _, size, _ in self.files)

    def url(self, name: str) -> str:
        return HF_URL.format(repo=self.repo, revision=self.revision, name=name)


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return -1


def ready(folder: Path, download: Download) -> bool:
    """Is every file there, at its size?"""
    return all(_size(Path(folder) / name) == size for name, size, _ in download.files)


def downloaded_by_abdoh(folder: Path) -> bool:
    return (Path(folder) / MARKER).is_file()


def _open(url: str, start: int):
    headers = {"User-Agent": "Abdoh-model-download"}
    if start:
        headers["Range"] = f"bytes={start}-"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60)


def fetch(
    download: Download,
    folder: Path,
    on_progress: Progress = lambda done, total: None,
    stop: threading.Event | None = None,
    open_url=_open,
    free_space=lambda path: shutil.disk_usage(path).free,
) -> None:
    """Get the files into `folder`. Raises DownloadError, or Stopped."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / MARKER).write_text(f"{download.repo}@{download.revision}\n", encoding="utf-8")
    have = {
        name: size if _size(folder / name) == size else max(_size(folder / f"{name}.part"), 0)
        for name, size, _ in download.files
    }
    total = download.total
    needed = total - sum(have.values())
    if needed and free_space(folder) < needed + SPARE:
        raise DownloadError(f"It needs {(needed + SPARE) / 2**30:.1f} GB of free disk space.")
    done = sum(have.values())
    on_progress(done, total)
    for name, size, checksum in download.files:
        if _size(folder / name) != size:
            done = _fetch(download, name, size, checksum, folder, done, on_progress, stop, open_url)
    log.info("Downloaded %s into %s", download.repo, folder)


def _fetch(download, name, size, checksum, folder, done, on_progress, stop, open_url) -> int:
    part = folder / f"{name}.part"
    start = max(_size(part), 0)
    if start > size:
        part.unlink()
        done -= start
        start = 0
    if start < size:
        resumed = f" from {start >> 20} MB" if start else ""
        log.info("Downloading %s (%d MB)%s", name, size >> 20, resumed)
        try:
            with open_url(download.url(name), start) as response:
                if start and getattr(response, "status", 206) != 206:
                    done -= start  # the server sent it all again: start over
                    start = 0
                with open(part, "ab" if start else "wb") as f:
                    while chunk := response.read(CHUNK):
                        if stop is not None and stop.is_set():
                            raise Stopped
                        f.write(chunk)
                        done += len(chunk)
                        on_progress(done, download.total)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            raise DownloadError("The download was interrupted (no internet?).") from e
    if _size(part) != size or (checksum and _sha256(part, stop) != checksum):
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


def delete(folder: Path) -> bool:
    """Delete a folder Abdoh downloaded (and only such a folder). Returns whether it did."""
    folder = Path(folder)
    if not downloaded_by_abdoh(folder):
        return False
    shutil.rmtree(folder, ignore_errors=True)
    log.info("Deleted the model in %s", folder)
    return not folder.exists()
