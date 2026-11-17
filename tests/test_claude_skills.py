"""Screen capture and screen-skill parsing (no display, no network)."""

import io

import pytest
from PIL import Image

from abdoh.claude.screen import FrontWindow, ScreenCaptureError, capture_screen, pick_monitor
from abdoh.claude.skills import (
    is_summarize_request,
    is_translate_request,
    parse_target_language,
)


def fake_screenshot(color="white", size=(3200, 1800)):
    return lambda which="active": Image.new("RGB", size, color)


def test_capture_downscales_to_2000():
    png = capture_screen(grab=fake_screenshot())
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG"
    assert img.size == (2000, 1125)


def test_capture_asks_for_the_screen_you_want():
    asked = []

    def grab(which):
        asked.append(which)
        return Image.new("RGB", (100, 100), "white")

    capture_screen(grab=grab)
    capture_screen(grab=grab, which="all")
    assert asked == ["active", "all"]


# The owner's three monitors, as mss lists them (the big one is the primary, at 0,0).
LAPTOP = {"left": -3840, "top": 0, "width": 1920, "height": 1080}
HP = {"left": -1920, "top": 0, "width": 1920, "height": 1080}
WIDE = {"left": 0, "top": 0, "width": 3440, "height": 1440}


def test_the_screen_with_the_window_in_front_is_the_one_you_use():
    monitors = [WIDE, LAPTOP, HP]
    assert pick_monitor(monitors, (-1000, 500)) is HP
    assert pick_monitor(monitors, (-3000, 200)) is LAPTOP
    assert pick_monitor(monitors, (1700, 700)) is WIDE
    assert pick_monitor(monitors, (-1000, 1300)) is HP  # below the HP's bottom edge: nearest
    assert pick_monitor(monitors, None) is WIDE  # no window: the primary


def test_a_window_knows_its_middle():
    assert FrontWindow("Inbox", "chrome", (-1920, 0, 0, 1080)).center == (-960, 540)
    assert FrontWindow().center is None


def test_small_screens_are_not_enlarged():
    img = Image.open(io.BytesIO(capture_screen(grab=fake_screenshot(size=(800, 600)))))
    assert img.size == (800, 600)


def test_black_capture_is_reported():
    with pytest.raises(ScreenCaptureError, match="black"):
        capture_screen(grab=fake_screenshot("black"))


def test_capture_failure_is_reported():
    def broken(which):
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
