"""Pictures for the board: `[picture: margherita pizza]` (a search) or `[picture: https://...]`
(a link Claude found).

A search asks Wikimedia Commons first (free licenses, fast: 0.9 s on 2026-11-25) and Openverse
when Commons has nothing (slower, 15 s that day, and 20 searches a minute). The picture is
downloaded by Abdoh (https only, an image, at most MAX_BYTES), kept in <app_dir>/board/ for a
week, and given to the page as a data: URL, so the page never loads anything from the internet.
Each picture has a credit line: who made it and its license.
"""

import base64
import hashlib
import html
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from abdoh import __version__

log = logging.getLogger(__name__)

FOLDER = "board"
MAX_BYTES = 5_000_000
KEEP_DAYS = 7
TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}
COMMONS = "https://commons.wikimedia.org/w/api.php"
OPENVERSE = "https://api.openverse.org/v1/images/"
# Wikimedia asks automated clients to say who they are: the app, never the user.
HEADERS = {
    "User-Agent": f"Abdoh/{__version__} (https://github.com/MohdEssam77/abdoh_the_assistant)"
}
WIDTH = 1024  # Commons scales the picture down for us
# A picture line on the board: [picture: what]
LINE = re.compile(r"^[ \t]*\[picture:[ \t]*(.+?)[ \t]*\][ \t]*$", re.IGNORECASE | re.MULTILINE)
LICENSES = {
    "by": "CC BY", "by-sa": "CC BY-SA", "by-nd": "CC BY-ND", "by-nc": "CC BY-NC",
    "by-nc-sa": "CC BY-NC-SA", "by-nc-nd": "CC BY-NC-ND", "cc0": "CC0", "pdm": "Public domain",
}  # fmt: skip


class PictureError(RuntimeError):
    """No picture: the message is safe to show and say."""


@dataclass
class Picture:
    path: Path
    mime: str
    credit: str  # "Photo: Shisma, CC BY 4.0, Wikimedia Commons"
    title: str = ""

    def data_url(self) -> str:
        data = base64.b64encode(self.path.read_bytes()).decode("ascii")
        return f"data:{self.mime};base64,{data}"


def picture_lines(text: str) -> list[str]:
    """What the board asks pictures of, in order: ["margherita pizza", "https://..."]."""
    return [m.group(1) for m in LINE.finditer(text or "")]


# Words a picture search does better without ("authentic Roman spaghetti carbonara with
# guanciale" found nothing on Commons; "spaghetti carbonara" does).
_FILLER = {
    "a", "an", "the", "with", "and", "of", "in", "on", "for", "at", "to", "from", "by", "some",
    "very", "real", "authentic", "traditional", "classic", "typical", "fresh", "delicious",
    "beautiful", "nice", "good", "proper", "photo", "picture", "image", "closeup", "close-up",
}  # fmt: skip
MAX_SEARCHES = 6


def searches(what: str) -> list[str]:
    """What to search for, best first: the words as given, without filler words, then shorter
    runs of them (three words, then two, from the end: the thing is usually last)."""
    words = what.split()
    content = [w for w in words if w.lower().strip(",.") not in _FILLER]
    tries = [" ".join(words), " ".join(content)]
    for size in (3, 2):
        tries += [" ".join(content[i : i + size]) for i in range(len(content) - size, -1, -1)]
    unique = [t for i, t in enumerate(tries) if t and t not in tries[:i]]
    return unique[:MAX_SEARCHES]


def _plain(markup: str) -> str:
    """Commons' artist field is HTML: just its words."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup or "")).split())


class Pictures:
    """Finds and keeps pictures. `http` is an httpx.Client (a fake one in tests)."""

    def __init__(self, folder: Path, http=None):
        self.folder = Path(folder)
        self._http = http

    def _client(self):
        if self._http is None:
            import httpx

            self._http = httpx.Client(timeout=20.0, follow_redirects=True, headers=HEADERS)
        return self._http

    def find(self, what: str) -> Picture:
        """A picture for `what`: a link, or a search. Raises PictureError."""
        what = " ".join(str(what or "").split())
        if not what:
            raise PictureError("There's nothing to look for.")
        if what.lower().startswith("http://"):
            raise PictureError("I only open pictures from secure (https) links.")
        if what.lower().startswith("https://"):
            host = urlparse(what).hostname or "the web"
            return self._keep(what, f"From {host}", what)
        tries = searches(what)
        # Commons with each wording (fast), then Openverse once (slow, few searches a minute)
        for search, words in [(self._commons, t) for t in tries] + [(self._openverse, tries[-1])]:
            try:
                found = search(words)
            except PictureError:
                raise
            except Exception as e:  # one source down: try the next
                log.info("Picture search failed (%s): %s", search.__name__, e)
                continue
            for url, credit, title in found:
                try:
                    return self._keep(url, credit, title)
                except PictureError as e:
                    log.info("Skipped a picture of %r: %s", what, e)
        raise PictureError(f"I couldn't find a picture of {what}.")

    def _commons(self, what: str) -> list[tuple[str, str, str]]:
        r = self._client().get(COMMONS, params={
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": f"{what} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 5,
            "prop": "imageinfo", "iiprop": "url|extmetadata|mime", "iiurlwidth": WIDTH,
        })  # fmt: skip
        r.raise_for_status()
        pages = sorted(((r.json().get("query") or {}).get("pages") or {}).values(),
                       key=lambda p: p.get("index", 0))  # fmt: skip
        found = []
        for page in pages:
            info = (page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata") or {}
            url = info.get("thumburl") or info.get("url")
            if not url or info.get("mime") not in TYPES:
                continue
            artist = _plain((meta.get("Artist") or {}).get("value", "")) or "unknown"
            license_ = (meta.get("LicenseShortName") or {}).get("value") or "see Wikimedia Commons"
            title = re.sub(r"^File:|\.\w+$", "", page.get("title", ""))
            found.append((url, f"Photo: {artist}, {license_}, Wikimedia Commons", title))
        return found

    def _openverse(self, what: str) -> list[tuple[str, str, str]]:
        r = self._client().get(OPENVERSE, params={"q": what, "page_size": 5, "mature": "false"})
        if r.status_code == 429:
            raise PictureError("The picture search is busy. Try again in a minute.")
        r.raise_for_status()
        found = []
        for item in r.json().get("results") or []:
            if not item.get("url"):
                continue
            license_ = LICENSES.get(item.get("license", ""), str(item.get("license", "")).upper())
            version = item.get("license_version") or ""
            credit = f"Photo: {item.get('creator') or 'unknown'}, {license_} {version}".strip()
            found.append((item["url"], f"{credit}, {item.get('source') or 'Openverse'}",
                          item.get("title") or ""))  # fmt: skip
        return found

    def _keep(self, url: str, credit: str, title: str) -> Picture:
        """Download a picture (once: kept by its address), checking it really is one."""
        name = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
        for mime, ext in TYPES.items():
            kept = self.folder / f"{name}{ext}"
            if kept.exists():
                return Picture(kept, mime, credit, title)
        if not url.lower().startswith("https://"):
            raise PictureError("I only open pictures from secure (https) links.")
        try:
            with self._client().stream("GET", url) as r:
                if r.status_code != 200:
                    raise PictureError(f"That picture didn't load ({r.status_code}).")
                mime = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if mime not in TYPES:
                    raise PictureError("That link isn't a picture.")
                size = int(r.headers.get("content-length") or 0)
                if size > MAX_BYTES:
                    raise PictureError("That picture is too big.")
                data = b""
                for chunk in r.iter_bytes():
                    data += chunk
                    if len(data) > MAX_BYTES:
                        raise PictureError("That picture is too big.")
        except PictureError:
            raise
        except Exception as e:
            log.info("Couldn't download %s: %s", url, e)
            raise PictureError("That picture didn't load.") from e
        self.folder.mkdir(parents=True, exist_ok=True)
        kept = self.folder / f"{name}{TYPES[mime]}"
        kept.write_bytes(data)
        return Picture(kept, mime, credit, title)

    def clean(self, days: int = KEEP_DAYS, now: float | None = None) -> int:
        """Delete pictures older than `days`. Returns how many."""
        cutoff = (now or time.time()) - days * 86400
        gone = 0
        for path in self.folder.glob("*") if self.folder.exists() else []:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                gone += 1
        return gone
