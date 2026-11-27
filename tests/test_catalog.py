"""The Catalog (abdoh/catalog.py): complete, and naming only pages and settings that exist."""

import re
from pathlib import Path

from abdoh import catalog
from abdoh.config import Config

WEB = Path(__file__).resolve().parents[1] / "src" / "abdoh" / "ui" / "web"
PAGES = set(re.findall(r'data-page="([a-z]+)"', (WEB / "index.html").read_text("utf-8")))
FIELDS = ("id", "section", "title", "icon", "line", "what", "say", "steps", "where", "tips")
# Phrases the page may send to Abdoh with "Try it": nothing that changes anything.
HARMLESS = re.compile(r"^(what|which|how|what's)\b", re.I)


def test_every_feature_is_complete():
    sections = {s["id"] for s in catalog.SECTIONS}
    ids = [f["id"] for f in catalog.FEATURES]
    assert len(ids) == len(set(ids))
    for f in catalog.FEATURES:
        assert all(f.get(k) is not None for k in FIELDS), f["id"]
        assert f["section"] in sections, f["id"]
        assert f["line"].endswith((".", "?", "”")), f["id"]
        assert len(f["line"]) <= 110, f["id"]
    assert {f["section"] for f in catalog.FEATURES} == sections  # no empty section


def test_pages_and_settings_exist():
    cfg = Config()
    for f in catalog.FEATURES:
        assert f["where"]["page"] in PAGES, (f["id"], f["where"]["page"])
        if f.get("setting"):
            catalog.setting_value(cfg, f["setting"])  # raises for a name that isn't there
        if f.get("needs"):
            assert f["needs"] in catalog.NEEDS_TEXT, f["id"]
    for step in catalog.START:
        assert step["page"] in PAGES


def test_the_new_features_are_in_it():
    ids = {f["id"] for f in catalog.FEATURES}
    assert {"codoh", "watch", "fallback", "logs", "quiet", "memory", "lamps"} <= ids


def test_try_it_phrases_are_harmless():
    for f in catalog.FEATURES:
        if f.get("try"):
            assert HARMLESS.match(f["try"]), f["try"]


def test_status_follows_the_settings(tmp_path):
    cfg = Config(app_dir=tmp_path)
    cfg.claude.backend = "off"
    found = {f["id"]: f["status"] for f in catalog.catalog(cfg)["features"]}
    assert found["claude"]["state"] == "needs" and found["claude"]["text"] == "Connect an AI"
    assert found["wake-word"]["state"] == "on"
    cfg.memory = False
    cfg.voice_interrupts = False
    found = {f["id"]: f["status"] for f in catalog.catalog(cfg)["features"]}
    assert found["memory"]["state"] == "off" and found["interrupt"]["state"] == "off"
    assert found["fallback"]["state"] == "needs"  # no ChatGPT plan here
    assert found["lamps"]["state"] == "needs"


def test_what_claude_reads_about_a_log_question():
    text = catalog.for_log(["stop", "talking", "reply"])
    assert "Talk over a reply" in text
    assert catalog.for_log(["zzzz"]) == ""


def test_the_log_follow_up_has_the_features(tmp_path):
    from test_logs import Brain, recent_log

    from abdoh.commands.registry import CommandRegistry
    from abdoh.router import Router

    cfg = Config(app_dir=tmp_path, log_file=str(recent_log(tmp_path)))
    brain = Brain("ACTION logs: why it stopped talking over my reply | just now\n", "Okay.")
    router = Router(cfg, CommandRegistry(tmp_path / "commands.yaml"), brain=brain)
    " ".join(router.handle("why did you stop talking?"))
    assert "Talk over a reply" in brain.prompts[1]


def test_abdoh_knows_the_catalog_and_codoh():
    from abdoh.about import about

    text = about(Config())
    assert "Catalog" in text and "Codoh" in text


def test_the_window_api(tmp_path):
    from abdoh.events import Bus
    from abdoh.ui.api import AppApi, UiState

    found = AppApi(Bus(), UiState(), Config(app_dir=tmp_path)).catalog()
    assert len(found["features"]) == len(catalog.FEATURES) and found["start"]
