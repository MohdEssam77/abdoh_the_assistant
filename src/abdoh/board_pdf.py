"""The board as a PDF: what the Act as page shows (text, math, drawings, pictures), printed by
Edge in the background (`msedge --headless --print-to-pdf`, on every Windows 11 PC; checked on
the owner's laptop 2026-11-25) into Documents\\Abdoh\\Boards.

The page sends the board as it shows it (already drawn and cleaned by board.js); Abdoh wraps it
in one printable page with KaTeX's CSS (its fonts load from the app's own folder), takes out
anything that could run (scripts, event attributes) once more, and lets Edge print it. No Edge:
the page opens the print dialog instead ("Microsoft Print to PDF").
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
    return f"{clean[:60]} {when:%Y-%m-%d %H-%M}.pdf"


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
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / file_name(title, when)
    with tempfile.TemporaryDirectory(prefix="abdoh-board-") as work:
        html = Path(work) / "board.html"
        html.write_text(page(cards, title, when), encoding="utf-8")
        profile = Path(work) / "edge-profile"  # its own: never touches the user's Edge
        args = [
            str(edge), "--headless", "--disable-gpu", "--no-pdf-header-footer",
            "--no-first-run", "--disable-extensions", f"--user-data-dir={profile}",
            f"--print-to-pdf={target}", html.as_uri(),
        ]  # fmt: skip
        started = time.monotonic()
        try:
            run(args, capture_output=True, timeout=EDGE_SECONDS, creationflags=NO_WINDOW)
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("Edge couldn't print the board: %s", e)
            raise BoardPdfError("The PDF couldn't be made.") from e
    if not target.exists() or target.stat().st_size == 0:
        raise BoardPdfError("The PDF couldn't be made.")
    log.info("Saved the board as %s in %.1fs", target, time.monotonic() - started)
    return target
