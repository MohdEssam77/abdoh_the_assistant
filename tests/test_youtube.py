import io
import urllib.error

from abdoh import youtube

# A trimmed-down results page: an ad and a Short come before the first real search result.
PAGE = (
    b'<html><script>var ytInitialData = {"adSlotRenderer":{"videoId":"AAAAAAAAAAA"},'
    b'"reelItemRenderer":{"videoId":"BBBBBBBBBBB"},'
    b'"videoRenderer":{"videoId":"fJ9rUzIMcZQ","thumbnail":{}},'
    b'"videoRenderer":{"videoId":"CCCCCCCCCCC"}};</script></html>'
)


def test_first_search_result_is_picked_not_ads_or_shorts():
    assert youtube.first_video_id([PAGE]) == "fJ9rUzIMcZQ"


def test_result_split_across_chunks_is_found():
    at = PAGE.index(b"fJ9r")
    for cut in range(at - 30, at + 12):
        assert youtube.first_video_id([PAGE[:cut], PAGE[cut:]]) == "fJ9rUzIMcZQ"


def test_no_results():
    assert youtube.first_video_id([b"<html>nothing here</html>"]) is None
    assert youtube.first_video_id([]) is None


def test_find_video_reads_the_results_page():
    seen = {}

    def urlopen(request, timeout):
        seen.update(url=request.full_url, headers=dict(request.header_items()), timeout=timeout)
        return io.BytesIO(PAGE)

    assert youtube.find_video("bohemian rhapsody", urlopen=urlopen) == "fJ9rUzIMcZQ"
    assert seen["url"] == "https://www.youtube.com/results?search_query=bohemian+rhapsody"
    assert seen["headers"]["Cookie"] == "SOCS=CAI"  # no cookie-consent page in Europe
    assert "Mozilla" in seen["headers"]["User-agent"]
    assert seen["timeout"] > 0


def test_find_video_stops_reading_at_the_first_result():
    reads = []

    class Counting(io.BytesIO):
        def read(self, n=-1):
            reads.append(n)
            return super().read(n)

    big = PAGE + b"x" * (youtube.CHUNK_BYTES * 5)
    assert youtube.find_video("q", urlopen=lambda r, timeout: Counting(big)) == "fJ9rUzIMcZQ"
    assert len(reads) == 1


def test_network_problems_mean_no_video():
    def offline(request, timeout):
        raise urllib.error.URLError("no network")

    def slow(request, timeout):
        raise TimeoutError("timed out")

    assert youtube.find_video("anything", urlopen=offline) is None
    assert youtube.find_video("anything", urlopen=slow) is None


def test_urls():
    assert youtube.search_url("lo-fi & jazz") == (
        "https://www.youtube.com/results?search_query=lo-fi+%26+jazz"
    )
    assert youtube.watch_url("fJ9rUzIMcZQ") == "https://www.youtube.com/watch?v=fJ9rUzIMcZQ"
