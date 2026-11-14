"""Screen capture and screen-skill parsing (no display, no network)."""

import io

import pytest
from PIL import Image

from abdoh.claude.screen import ScreenCaptureError, capture_screen
from abdoh.claude.skills import (
    is_summarize_request,
    is_translate_request,
    parse_target_language,
)


def fake_screenshot(color="white", size=(3200, 1800)):
    return lambda: Image.new("RGB", size, color)


def test_capture_downscales_to_1600():
    png = capture_screen(grab=fake_screenshot())
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG"
    assert img.size == (1600, 900)


def test_small_screens_are_not_enlarged():
    img = Image.open(io.BytesIO(capture_screen(grab=fake_screenshot(size=(800, 600)))))
    assert img.size == (800, 600)


def test_black_capture_is_reported():
    with pytest.raises(ScreenCaptureError, match="black"):
        capture_screen(grab=fake_screenshot("black"))


def test_capture_failure_is_reported():
    def broken():
        raise OSError("no display")

    with pytest.raises(ScreenCaptureError, match="couldn't capture"):
        capture_screen(grab=broken)


@pytest.mark.parametrize(
    "request_text, target",
    [
        ("translate my screen to arabic", "Arabic"),
        ("translate whats on my screen into french", "French"),
        ("translate whats on my screen", None),
        ("translate my screen", None),
    ],
)
def test_parse_target_language(request_text, target):
    assert parse_target_language(request_text) == target


def test_screen_skill_keywords():
    assert is_translate_request({"translate", "my", "screen"})
    assert not is_translate_request({"translate", "hello"})
    assert is_summarize_request({"summarise", "the", "screen"})
    assert not is_summarize_request({"summarize", "this", "article"})
