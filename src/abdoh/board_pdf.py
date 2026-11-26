"""The board as a PDF: what the Act as page shows (text, math, drawings, pictures), printed by
Edge in the background (`msedge --headless --print-to-pdf`, on every Windows 11 PC; checked on
the owner's laptop 2026-11-25) into Documents\\Abdoh\\Boards.

The page sends the board as it shows it (already drawn and cleaned by board.js); Abdoh wraps it
in one printable page with KaTeX's CSS (its fonts load from the app's own folder), takes out
anything that could run (scripts, event attributes) once more, and lets Edge print it. No Edge:
the page opens the print dialog instead ("Microsoft Print to PDF"), and when Edge makes no PDF
(twice: a second try after a moment), too. What Edge said goes to the log.

Edge can return before it has written the PDF: in the owner's running Abdoh it handed the print
to a process of its own and exited at once (2026-11-27), so the PDF came a second later and
Abdoh, cleaning up the page and Edge's profile meanwhile, failed. So Abdoh waits for a finished
PDF (it ends with %%EOF) and keeps Edge's files until then; what Edge can't let go of yet is
left in Temp and tidied the next time.
"""

import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

WEB = Path(__file__).resolve().parent / "ui" / "web"
FOLDER_NAME = ("Abdoh", "Boards")
EDGE_SECONDS = 60
TRIES = 2  # Edge made no PDF: once more (it may have been updating, or busy starting)
RETRY_SECONDS = 1.0
# Edge returned: wait this long for the PDF to be there and finished (it may still be writing).
WAIT_SECONDS = 15.0
FAILED_WAIT_SECONDS = 3.0  # ... and this long when Edge said it failed (an exit code)
POLL_SECONDS = 0.2
TEMP_PREFIX = "abdoh-board-"
LEFTOVER_SECONDS = 3600.0  # Edge's files left in Temp are tidied after an hour
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
EDGE_PATHS = (
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe",
)
PRINT_CSS = """
@page { size: A4; margin: 16mm 14mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", Arial, sans-serif; color: #1a1a1a; background: #fff; margin: 0;
  font-size: 11.5pt; line-height: 1.5; }
header { border-bottom: 2px solid #0d9668; padding-bottom: 6px; margin-bottom: 14px; }
header h1 { font-size: 17pt; margin: 0; }
header small { color: #6b7280; }
.board-item { border: 1px solid #d8dbe0; border-radius: 10px; padding: 10px 14px; margin: 0 0 12px;
  break-inside: avoid; }
.board-item p { white-space: pre-wrap; margin: 0 0 6px; }
.board-item h3, .board-item h4 { margin: 2px 0 6px; }
.board-item table { border-collapse: collapse; margin: 4px 0 8px; }
.board-item td, .board-item th { border: 1px solid #d8dbe0; padding: 3px 8px; }
.board-code { border: 1px solid #d8dbe0; border-radius: 8px; overflow: hidden; margin: 0 0 8px; }
.board-code-head { font-size: 9pt; color: #6b7280; padding: 3px 10px;
  border-bottom: 1px solid #d8dbe0; }
.board-code-head button { display: none; }
.board-code pre { margin: 0; padding: 8px 10px; white-space: pre-wrap; font-size: 9.5pt;
  font-family: Consolas, "Cascadia Code", monospace; font-variant-ligatures: none; }
.board-drawing pre[hidden] { display: none; }
.board-paper { display: flex; justify-content: center; padding: 8px; }
.board-paper svg { max-width: 100%; max-height: 120mm; height: auto; }
.board-picture { margin: 0 0 8px; text-align: center; }
.board-picture img { max-width: 100%; max-height: 110mm; border-radius: 8px; }
.board-picture figcaption { font-size: 8.5pt; color: #6b7280; }
.board-note { color: #6b7280; font-size: 9pt; }
.board-math.display { display: block; text-align: center; margin: 4px 0; }
"""


class BoardPdfError(RuntimeError):
    """No PDF: the message is safe to show and say."""


def find_edge(env=os.environ) -> Path | None:
    for pattern in EDGE_PATHS:
        path = Path(re.sub(r"%([^%]+)%", lambda m: env.get(m.group(1), ""), pattern))
        if path.is_file():
            return path
    found = shutil.which("msedge")
    return Path(found) if found else None


def boards_folder(documents: Path | None = None) -> Path:
    """Documents\\Abdoh\\Boards, in the real Documents folder (OneDrive moves it)."""
    if documents is None:
        from abdoh.claude.code import user_folders

        documents = user_folders().get("Documents", Path.home() / "Documents")
    return Path(documents).joinpath(*FOLDER_NAME)


def _safe(html: str) -> str:
    """Once more, nothing that could run: scripts, event attributes, javascript: links."""
    html = re.sub(r"<script\b[^>]*>.*?</script\s*>", "", html, flags=re.I | re.S)
    html = re.sub(r"<(iframe|object|embed|link|meta)\b[^>]*>", "", html, flags=re.I)
    html = re.sub(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", html, flags=re.I)
    return re.sub(r"javascript:", "", html, flags=re.I)


def page(cards: list[str], title: str, when: datetime | None = None, web: Path = WEB) -> str:
    """One printable page: a heading, then each board card as the page showed it."""
    when = when or datetime.now()
    katex = (web / "vendor" / "katex" / "katex.min.css").as_uri()
    name = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    body = "\n".join(_safe(card) for card in cards)
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<title>{name}</title><link rel="stylesheet" href="{katex}">'
        f"<style>{PRINT_CSS}</style></head><body>"
        f"<header><h1>{name}</h1><small>Abdoh's board, {when:%d %B %Y, %H:%M}</small></header>"
        f"{body}</body></html>"
    )


def file_name(title: str, when: datetime | None = None) -> str:
    when = when or datetime.now()
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title).strip(" .") or "Board"
    return f"{clean[:60].rstrip(' .')} {when:%Y-%m-%d %H-%M}.pdf"


def save(cards: list[str], title: str, folder: Path | None = None, edge: Path | None = None,
         run=None, when: datetime | None = None) -> Path:  # fmt: skip
    """Print the board to a PDF and return where it is. Raises BoardPdfError."""
    run = run or subprocess.run
    if not cards:
        raise BoardPdfError("The board is empty.")
    edge = edge or find_edge()
    if edge is None:
        raise BoardPdfError("Edge isn't on this computer, so Abdoh can't make the PDF itself.")
    when = when or datetime.now()
    folder = Path(folder) if folder else boards_folder()
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.warning("Couldn't make the folder for the board's PDF (%s): %s", folder, e)
        raise BoardPdfError("The folder for the PDF couldn't be made.") from e
    target = folder / file_name(title, when)
    _tidy_leftovers()
    started = time.monotonic()
    # Edge's helpers may still hold files in its profile for a moment: never fail on cleanup.
    with tempfile.TemporaryDirectory(prefix=TEMP_PREFIX, ignore_cleanup_errors=True) as work:
        html = Path(work) / "board.html"
        html.write_text(page(cards, title, when), encoding="utf-8")
        for attempt in range(1, TRIES + 1):
            profile = Path(work) / f"edge-profile-{attempt}"  # its own: never the user's Edge
            args = [
                str(edge), "--headless", "--disable-gpu", "--no-pdf-header-footer",
                "--no-first-run", "--disable-extensions", f"--user-data-dir={profile}",
                f"--print-to-pdf={target}", html.as_uri(),
            ]  # fmt: skip
            began = time.monotonic()
            try:
                done = run(args, capture_output=True, timeout=EDGE_SECONDS, creationflags=NO_WINDOW)
            except (OSError, subprocess.SubprocessError) as e:
                log.warning("Edge couldn't print the board (try %d): %s", attempt, e)
                done = None
            code = getattr(done, "returncode", None)
            if not finished(target):
                log.info(
                    "Edge returned after %.1fs (exit code %s) before the PDF was written: "
                    "waiting for it",
                    time.monotonic() - began,
                    code,
                )
            wait = WAIT_SECONDS if done is not None and not code else FAILED_WAIT_SECONDS
            if wait_for(target, wait):
                break
            log.warning(
                "Edge made no PDF of the board (try %d, exit code %s): %s",
                attempt,
                getattr(done, "returncode", "none"),
                _tail(getattr(done, "stderr", b"")) or "it said nothing",
            )
            if attempt < TRIES:
                time.sleep(RETRY_SECONDS)
        else:
            raise BoardPdfError("The PDF couldn't be made.")
    log.info("Saved the board as %s in %.1fs", target, time.monotonic() - started)
    return target


def finished(pdf: Path) -> bool:
    """A whole PDF is there: it ends with %%EOF (Edge writes it last)."""
    try:
        with open(pdf, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 1024))
            return size > 0 and b"%%EOF" in f.read()
    except OSError:
        return False


def wait_for(pdf: Path, seconds: float, sleep=time.sleep, clock=time.monotonic) -> bool:
    """Wait until the PDF is finished (True), or `seconds` passed (False)."""
    end = clock() + seconds
    while True:
        if finished(pdf):
            return True
        if clock() >= end:
            return False
        sleep(POLL_SECONDS)


def _tidy_leftovers(temp: Path | None = None, now: float | None = None) -> None:
    """Edge's files from earlier PDFs that Edge still held then (Temp\\abdoh-board-*), once
    they're an hour old."""
    temp = Path(temp or tempfile.gettempdir())
    now = time.time() if now is None else now
    try:
        old = [p for p in temp.glob(TEMP_PREFIX + "*") if p.is_dir()
               and now - p.stat().st_mtime > LEFTOVER_SECONDS]  # fmt: skip
    except OSError:
        return
    for path in old:
        shutil.rmtree(path, ignore_errors=True)


def _tail(output, chars: int = 400) -> str:
    """The end of what Edge wrote to stderr, on one line (for the log)."""
    if isinstance(output, bytes):
        output = output.decode("utf-8", "replace")
    return " ".join(str(output or "").split())[-chars:]
