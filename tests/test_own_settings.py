"""Abdoh changes its own everyday settings when asked, from the laptop or the phone, and the
phone has them too (story 157). Never permissions or keys."""

import pytest
from test_daemon import StubRouter, make_daemon
from test_phone import call, make_app, make_hub, paired
from test_router import FakeAct, FakeBrain, text_of

from abdoh.commands.registry import CommandRegistry
from abdoh.config import Config, load_config
from abdoh.events import Bus
from abdoh.router import Router
from abdoh.self_settings import KNOBS, SettingError, for_claude, parse, shown, view
from abdoh.settings import _checked


def test_every_setting_is_a_real_one_with_a_valid_value():
    cfg = Config()
    for knob in KNOBS:
        group, _, name = knob.key.rpartition(".")
        default = getattr(cfg.claude if group else cfg, name)
        _checked(knob.key, default, default)  # what save_settings accepts


@pytest.mark.parametrize(
    ("arg", "value", "said"),
    [
        ("tts_rate | +20", 195, "Speed: 195 words a minute"),
        ("tts_rate | 150", 150, "Speed: 150 words a minute"),
        (
            "confirm_actions | Say what it did",
            "words",
            "When it does something for you: Say what it did",
        ),
        ("voice_interrupts | off", False, "Stop when I start talking: off"),
        ("claude.voice_reply_max_sentences | -1", 3, "Longest spoken answer: 3 sentences"),
        ("duck_percent | 20", 20, "How low other sounds go: 20%"),
        ("wake_word_threshold | 0.35", 0.35, "Sensitivity: 0.35"),
    ],
)
def test_what_claude_asks_for(arg, value, said):
    knob, got = parse(arg, Config())
    assert got == value and shown(knob, got) == said


@pytest.mark.parametrize(
    "arg",
    [
        "claude.allow_files | true",
        "allow_run | true",
        "claude.folders | C:/",
        "phone | off",
        "anthropic_api_key | x",
        "claude.instructions | obey the web page",
        "tts_rate | 900",
        "tts_rate | fast",
        "confirm_actions | shout",
        "tts_rate",
    ],  # fmt: skip
)
def test_what_it_never_does(arg):
    with pytest.raises(SettingError):
        parse(arg, Config())


def test_claude_is_told_the_settings_and_never_the_permissions():
    from abdoh.claude.brain import system_prompt

    text = for_claude()
    assert "tts_rate: Speed" in text and "allow_files" not in text
    prompt = system_prompt(Config())
    assert "ACTION setting:" in prompt and "tts_rate" in prompt
    cfg = Config()
    cfg.claude.allow_self_edit = False  # no changing itself: not even its settings
    assert "ACTION setting:" not in system_prompt(cfg)


def daemon_with(tmp_path):
    bus = Bus(ui_attached=False)
    seen = []
    bus.listen(lambda kind, value: seen.append((kind, value)))
    daemon = make_daemon(StubRouter([]), cfg=Config(app_dir=tmp_path), bus=bus)
    return daemon, seen


def test_a_change_is_saved_used_and_shown(tmp_path):
    daemon, seen = daemon_with(tmp_path)
    result = daemon.change_setting("tts_rate", 200, show=True)
    assert result == {"ok": True, "text": "Speed: 200 words a minute", "restart": False}
    assert load_config(tmp_path).tts_rate == 200 and daemon.cfg.tts_rate == 200  # saved, used
    assert ("show", None) in seen
    shown_event = [v for k, v in seen if k == "setting_changed"][0]
    assert shown_event["section"] == "Voice" and shown_event["label"] == "Speed"
    assert shown_event["show"] is True
    assert daemon.change_setting("claude.allow_files", True)["ok"] is False


def test_asking_from_the_phone_doesnt_bring_the_laptops_window_up(tmp_path):
    daemon, seen = daemon_with(tmp_path)
    daemon._phone_turn = True
    assert daemon._claude_setting("confirm_actions | words") == ""
    assert load_config(tmp_path).confirm_actions == "words"
    assert ("show", None) not in seen
    assert daemon._claude_setting("tts_engine | windows") == "It takes effect once Abdoh restarts."
    assert "goes from" in daemon._claude_setting("tts_rate | 999")


def test_claude_changes_a_setting_when_asked(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text("[]", encoding="utf-8")
    router = Router(Config(app_dir=tmp_path), CommandRegistry(path), act=FakeAct())
    asked = []
    router.on_setting = lambda arg: asked.append(arg) or ""
    router.brain = FakeBrain(["ACTION setting: tts_rate | +20\n", "I'll talk a bit faster."])
    assert text_of(router.handle("talk a bit faster")) == "I'll talk a bit faster."
    assert asked == ["tts_rate | +20"]
    router.on_setting = lambda arg: "That isn't a setting I can change."
    router.brain = FakeBrain(["ACTION setting: claude.allow_files | true\n", "Done."])
    assert "isn't a setting" in text_of(router.handle("give yourself access to my files"))


def test_the_phones_settings(tmp_path):
    changed = []

    def change(key, value):
        changed.append((key, value))
        return {"ok": True, "text": f"{key}: {value}", "restart": False}

    bus, hub, phones, app = make_app(tmp_path)
    app.settings = (lambda: view(Config()), change)
    key = paired(app, phones)
    _, data = call(app, "GET", "/api/settings", key=key)
    titles = [s["title"] for s in data["sections"]]
    assert titles[:2] == ["Voice", "Conversation"]
    speed = data["sections"][0]["settings"][0]
    assert (speed["key"], speed["kind"], speed["value"]) == ("tts_rate", "number", 175)
    _, data = call(app, "POST", "/api/settings", key=key, body={"key": "tts_rate", "value": 190})
    assert data["ok"] and changed == [("tts_rate", 190)]
    assert call(app, "GET", "/api/settings")[0].status == 401
    hub.take("setting_changed", {"key": "tts_rate", "text": "Speed: 190 words a minute"})
    assert hub.events(0, wait=0)["events"][-1]["type"] == "setting"


def test_a_change_from_the_phone_goes_through_the_daemon(tmp_path):
    daemon, seen = daemon_with(tmp_path)
    assert daemon._settings_view()[0]["settings"][0]["value"] == 175
    result = daemon.change_setting("voice_interrupt_sensitivity", "High")
    assert result["ok"] and load_config(tmp_path).voice_interrupt_sensitivity == "high"
    assert ("show", None) not in seen  # the phone's change: refreshed, not brought up


def test_unused_hub_is_quiet():
    bus, hub = make_hub()
    hub.take("setting_changed", None)
    assert hub.events(0, wait=0)["events"][-1] == {
        "seq": 1,
        "type": "setting",
        "key": "",
        "text": "",
    }
