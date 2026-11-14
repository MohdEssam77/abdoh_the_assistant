"""Find the top YouTube video for a search, so "play X on YouTube" starts the video itself.

One request for YouTube's results page, read only until the first video result shows up. YouTube
serves two page formats: video results are "videoRenderer" entries, or "lockupViewModel" entries
whose single thumbnail's address holds the video id. Mixes and playlists (a stack of thumbnails),
ads and Shorts are marked differently, so they are skipped. No API key or extra library needed.
"""

import http.client
import logging
import re
import urllib.request
from collections.abc import Iterable, Iterator
from urllib.parse import quote_plus

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.youtube.com/results?search_query={}"
WATCH_URL = "https://www.youtube.com/watch?v={}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Cookie": "SOCS=CAI",  # skips the cookie-consent page YouTube shows in Europe
}
CHUNK_BYTES = 64 * 1024
MAX_BYTES = 3_000_000  # the first result is normally within the first megabyte
_VIDEO = re.compile(
    rb'"videoRenderer":\{"videoId":"([\w-]{11})"'
    rb'|"lockupViewModel":\{"contentImage":\{"thumbnailViewModel":\{"image":\{"sources":\[\{'
    rb'"url":"[^"]{0,100}?/vi(?:_webp)?/([\w-]{11})/'
)


def search_url(query: str) -> str:
    return SEARCH_URL.format(quote_plus(query))


def watch_url(video_id: str) -> str:
    return WATCH_URL.format(video_id)


def first_video_id(chunks: Iterable[bytes]) -> str | None:
    """The first search result's video id in a results page, read chunk by chunk."""
    tail = b""
    for chunk in chunks:
        text = tail + chunk
        found = _VIDEO.search(text)
        if found:
            return (found.group(1) or found.group(2)).decode()
        tail = text[-512:]  # a match can straddle two chunks
    return None


def find_video(query: str, urlopen=urllib.request.urlopen, timeout: float = 4.0) -> str | None:
    """The top video's id for a search, or None if YouTube can't be reached or shows none."""
    request = urllib.request.Request(search_url(query), headers=HEADERS)
    try:
        with urlopen(request, timeout=timeout) as response:
            return first_video_id(_chunks(response))
    except (OSError, ValueError, http.client.HTTPException) as e:  # timeouts are OSErrors
        log.warning("Couldn't search YouTube for %r: %s", query, e)
        return None


def _chunks(response) -> Iterator[bytes]:
    read = 0
    while read < MAX_BYTES:
        chunk = response.read(CHUNK_BYTES)
        if not chunk:
            return
        read += len(chunk)
        yield chunk
