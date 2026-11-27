"""Pictures made by AI with the owner's OpenRouter key: the price, the credit check, and what
Abdoh says when it can't. A fake OpenRouter (httpx.MockTransport): no key, no internet."""

import base64
import json

import httpx
import pytest

from abdoh.claude import openrouter
from abdoh.claude.openrouter import (
    PictureRefused,
    credit_left,
    image_models,
    make_picture,
    picture_price,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"p" * 100
FLUX = "black-forest-labs/flux-3-image-klein"
FLUX_ENDPOINTS = {
    "endpoints": [{
        "supported_parameters": {"resolution": {"values": ["768", "1K", "2K"]}},
        "pricing": [
            {"billable": "output_image", "unit": "image", "cost_usd": 0.008, "variant": "768"},
            {"billable": "output_image", "unit": "image", "cost_usd": 0.009, "variant": "1k"},
            {"billable": "output_image", "unit": "image", "cost_usd": 0.014, "variant": "2k"},
        ],
    }]
}  # fmt: skip


@pytest.fixture(autouse=True)
def fresh():
    openrouter._prices.clear()
    openrouter._one_k.clear()
    openrouter._credit.update(at=-1e9, left=None, key=None)


def fake(limit_remaining=None, credits=None, image_status=200, endpoints=FLUX_ENDPOINTS):
    asked = []

    def handle(request: httpx.Request):
        path = request.url.path
        asked.append((request.method, path, request.content and json.loads(request.content)))
        if path.endswith("/endpoints"):
            return httpx.Response(200, json=endpoints)
        if path == "/api/v1/images/models":
            return httpx.Response(200, json={"data": [
                {"id": "recraft/recraft-v4.1-flash-v2:free", "name": "Recraft V4.1 Flash V2"},
                {"id": FLUX, "name": "Black Forest Labs: FLUX 3 Image Klein"},
            ]})  # fmt: skip
        if path == "/api/v1/key":
            return httpx.Response(200, json={"data": {"limit_remaining": limit_remaining}})
        if path == "/api/v1/credits":
            if credits is None:
                return httpx.Response(403, json={"error": {"code": 403, "message": "management"}})
            return httpx.Response(200, json={"data": {"total_credits": credits[0],
                                                      "total_usage": credits[1]}})  # fmt: skip
        if path == "/api/v1/images":
            if image_status != 200:
                return httpx.Response(image_status, json={"error": {"code": image_status}})
            return httpx.Response(200, json={
                "data": [{"b64_json": base64.b64encode(PNG).decode(), "media_type": "image/png"}],
                "usage": {"cost": 0.009},
            })  # fmt: skip
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handle)), asked


def test_the_models_and_a_pictures_price():
    http, _ = fake()
    assert [m["id"] for m in image_models(http)] == [FLUX, "recraft/recraft-v4.1-flash-v2:free"]
    assert image_models(http)[1]["free"] is True
    assert picture_price(FLUX, http) == 0.009  # the 1K size, which Abdoh asks for


def test_a_price_per_token_is_about_a_pictures_worth():
    per_token = {"endpoints": [{"pricing": [
        {"billable": "output_image", "unit": "token", "cost_usd": 3e-05}]}]}  # fmt: skip
    http, _ = fake(endpoints=per_token)
    assert picture_price("google/gemini-3.1-flash-lite-image", http) == pytest.approx(0.0387)


def test_a_picture_is_made_and_paid_from_the_credit():
    http, asked = fake(limit_remaining=4.37)
    data, mime, cost = make_picture("sk-or-test", FLUX, "a cozy kitchen at night", http)
    assert (data, mime, cost) == (PNG, "image/png", 0.009)
    request = next(body for method, path, body in asked if path == "/api/v1/images")
    assert request == {"model": FLUX, "prompt": "a cozy kitchen at night", "n": 1,
                       "response_format": "b64_json", "resolution": "1K"}  # fmt: skip


def test_too_little_credit_is_said_before_trying():
    http, asked = fake(limit_remaining=0.004)
    with pytest.raises(
        PictureRefused, match=r"too low for a picture: about \$0.01 .* \$0.00 is left"
    ):
        make_picture("sk-or-test", FLUX, "a kitchen", http)
    assert not any(path == "/api/v1/images" for _, path, _ in asked)  # nothing spent


def test_the_account_balance_counts_when_openrouter_tells_it():
    http, _ = fake(limit_remaining=None, credits=(5.0, 4.995))
    assert credit_left("sk-or-test", http) == pytest.approx(0.005)
    http, _ = fake()  # a normal key with no limit: unknown, only trying tells
    assert credit_left("sk-or-other", http) is None


@pytest.mark.parametrize(
    "status, said",
    [(402, "credit has run out"), (403, "spending limit is used up"), (401, "rejected your key"),
     (502, "Nothing was charged")],
)  # fmt: skip
def test_what_openrouter_says_no_with(status, said):
    http, _ = fake(image_status=status)
    with pytest.raises(PictureRefused, match=said):
        make_picture("sk-or-test", FLUX, "a kitchen", http)


def test_no_key():
    with pytest.raises(PictureRefused, match="needs an OpenRouter key"):
        make_picture(None, FLUX, "a kitchen")


def test_the_board_asks_once_and_keeps_it(tmp_path):
    from abdoh.pictures import PictureError, Pictures

    made = []

    def ai(description):
        made.append(description)
        return PNG, "image/png", "Made by AI (flux 3 image klein), $0.009"

    pictures = Pictures(tmp_path, ai=ai)
    first = pictures.find("draw: a cozy kitchen at night")
    again = pictures.find("draw: a cozy kitchen at night")
    assert first.ai and first.credit.startswith("Made by AI") and again.path == first.path
    assert made == ["a cozy kitchen at night"]  # asked (and paid) once
    with pytest.raises(PictureError, match="can't make pictures with AI"):
        Pictures(tmp_path / "other").find("draw: a dog")


def test_abdoh_says_why_it_cant(tmp_path):
    import time

    from abdoh.config import Config
    from abdoh.daemon import Daemon
    from abdoh.events import Bus
    from abdoh.pictures import Pictures

    daemon = Daemon.__new__(Daemon)
    daemon.bus, daemon.cfg = Bus(), Config(app_dir=tmp_path)  # no OpenRouter key
    daemon._pictures, daemon._pictures_asked = None, set()
    said = []
    daemon.say_later = lambda text, still=None: said.append(text)
    daemon._pictures = Pictures(tmp_path, ai=daemon._ai_picture)
    daemon._find_pictures("[picture: draw: a cozy kitchen]")
    for _ in range(100):
        if said:
            break
        time.sleep(0.02)
    assert said == [
        "I can't make pictures with AI: that needs an OpenRouter key (Settings, Claude card)."
    ]
    assert daemon._ai_pictures_now() == "AI pictures: off (they need an OpenRouter key)"
    daemon.cfg.openrouter_api_key = "sk-or-test"
    openrouter._credit.update(at=openrouter.time.monotonic(), left=4.37, key="sk-or-test")
    assert daemon._ai_pictures_now() == "AI pictures: on (flux-3-image-klein, credit left $4.37)"


def test_claude_hears_when_it_may_ask_for_one():
    from abdoh.roles.acting import BOARD

    assert "[picture: draw:" in BOARD and "AI pictures are off" in BOARD
