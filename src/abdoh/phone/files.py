"""Files between the computer and the phone (ABDOH_EPIC_11.md, 2.3 and 2.6).

To the phone: Claude finds a file and writes `ACTION send_file: <full path>`; it goes only if
it's a file inside the folders Claude may work in (Settings → AI: the ones chosen there, else
the home folder and the user's main folders), never one of Abdoh's own (keys, paired phones),
and at most MAX_SEND bytes.

From the phone: saved under `<Downloads>\\From your phone` (or the first folder Claude may use
when Downloads isn't one of them), with a clean name that never overwrites anything.
"""

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

MAX_SEND = 1024**3  # 1 GB
MAX_UPLOAD = 100 * 1024**2  # 100 MB
FOLDER = "From your phone"
PIECE = 256 * 1024
NOT_FOUND = "I couldn't find that file on the computer."
NOT_A_FILE = "That's a folder, not a file: I can only send files."
NOT_ALLOWED = (
    "I can only send files from the folders I may use (Settings → AI → Files), and that one "
    "isn't in them."
)
ABDOHS_OWN = "That's one of Abdoh's own files, with your keys and settings: I won't send it."
TOO_BIG = "That file is too big to send to the phone (1 GB at most)."
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


class FileProblem(Exception):
    """Why a file can't be sent or saved; the message is for people."""


def roots(cfg, home: Path | None = None, folders: dict | None = None) -> list[Path]:
    """Where Claude may work with files: the folders chosen in Settings, else the home folder
    and the main folders (Documents, Downloads...) wherever they really are."""
    chosen = [Path(f).expanduser() for f in cfg.claude.folders if str(f).strip()]
    if chosen:
        return chosen
    home = Path(home or Path.home())
    if folders is None:
        from abdoh.claude.code import user_folders

        folders = user_folders(home)
    found = [home]
    for folder in folders.values():
        if folder not in found:
            found.append(Path(folder))
    return found


def _inside(path: Path, folder: Path) -> bool:
    try:
        return path.is_relative_to(folder.resolve())
    except OSError:
        return False


def file_to_send(text: str, cfg, home: Path | None = None, folders: dict | None = None) -> Path:
    """The file Claude asked to send (its full path), checked. Raises FileProblem."""
    raw = str(text or "").strip().strip("\"'")
    if not raw:
        raise FileProblem(NOT_FOUND)
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise FileProblem(NOT_FOUND)
    try:
        path = path.resolve(strict=True)
    except OSError:
        raise FileProblem(NOT_FOUND) from None
    if path.is_dir():
        raise FileProblem(NOT_A_FILE)
    if not path.is_file():
        raise FileProblem(NOT_FOUND)
    if not cfg.claude.allow_files or not any(_inside(path, r) for r in roots(cfg, home, folders)):
        raise FileProblem(NOT_ALLOWED)
    if _inside(path, Path(cfg.app_dir)):
        raise FileProblem(ABDOHS_OWN)
    if path.stat().st_size > MAX_SEND:
        raise FileProblem(TOO_BIG)
    return path


def upload_folder(cfg, home: Path | None = None, folders: dict | None = None) -> Path:
    """Where files from the phone go."""
    if folders is None:
        from abdoh.claude.code import user_folders

        folders = user_folders(Path(home or Path.home()))
    allowed = roots(cfg, home, folders)
    downloads = folders.get("Downloads")
    if downloads is not None and any(_inside(Path(downloads), r) for r in allowed):
        return Path(downloads) / FOLDER
    return allowed[0] / FOLDER


def clean_name(name: str) -> str:
    """A file name that's safe on Windows and stays in its folder ("../x" -> "x")."""
    name = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = _UNSAFE.sub(" ", name).strip(" .")
    name = " ".join(name.split())
    if len(name) > 100:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: 95 - len(ext)] + dot + ext) if dot and len(ext) <= 8 else name[:100]
    reserved = name.split(".")[0].upper()
    if reserved in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(COM|LPT)\d", reserved):
        name = "_" + name
    return name or "file"


def free_path(folder: Path, name: str) -> Path:
    """`folder/name`, or `name (2)`, `name (3)`... when it's taken."""
    path = folder / name
    stem, suffix = path.stem, path.suffix
    number = 2
    while path.exists():
        path = folder / f"{stem} ({number}){suffix}"
        number += 1
    return path


def save_upload(folder: Path, name: str, reader, length: int, limit: int = MAX_UPLOAD) -> Path:
    """Write `length` bytes from `reader` to a new file in `folder`, a piece at a time. Raises
    FileProblem (too big, or cut short)."""
    if length > limit:
        raise FileProblem("That file is too big to send to the computer (100 MB at most).")
    if length <= 0:
        raise FileProblem("That file is empty.")
    folder.mkdir(parents=True, exist_ok=True)
    path = free_path(folder, clean_name(name))
    part = path.with_name(path.name + ".part")
    left = length
    try:
        with open(part, "wb") as out:
            while left > 0:
                piece = reader.read(min(PIECE, left))
                if not piece:
                    raise FileProblem("The file didn't arrive whole. Try again.")
                out.write(piece)
                left -= len(piece)
        path = free_path(folder, path.name)  # taken meanwhile: the next free name
        part.replace(path)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    log.info("Saved a file from the phone: %s (%d KB)", path.name, length // 1024)
    return path
