import pytest
import yaml

from abdoh.claude.reply import ACTION_HELP
from abdoh.config import CLAUDE_ACTIONS, load_config
from abdoh.settings import (
    SettingsError,
    render_config,
    restart_needed,
    save_settings,
    settings_view,
    yaml_value,
)


def test_claude_actions_match_the_actions_claude_is_told_about():
    assert set(CLAUDE_ACTIONS) == set(ACTION_HELP)


def test_view_has_every_setting_but_not_the_api_key(app_dir):
    (app_dir / ".env").write_text("ANTHROPIC_API_KEY=sk-secret\n")
    view = settings_view(load_config(app_dir))
    assert view["tts_rate"] == 175
    assert view["claude"]["allow_web"] is True
    assert view["claude"]["actions"] == list(CLAUDE_ACTIONS)
    assert view["has_api_key"] is True
    assert "sk-secret" not in str(view)
    assert "app_dir" not in view


def test_save_changes_a_value_and_keeps_the_comments(app_dir):
    cfg = save_settings(app_dir, {"tts_rate": 200, "claude": {"allow_web": False}})
    assert cfg.tts_rate == 200
    assert cfg.claude.allow_web is False
    assert cfg.wake_words == ["abdoh", "hey abdoh", "ya abdoh"]  # untouched
    text = (app_dir / "config.yaml").read_text(encoding="utf-8")
    assert "# Abdoh configuration." in text
    assert "tts_rate: 200" in text and "# speaking speed in words per minute" in text
    assert "# higher = fewer false wake-ups" in text
    assert "  allow_web: false" in text


def test_comments_stay_in_their_column(app_dir):
    save_settings(app_dir, {"wake_word_threshold": 0.6})
    text = (app_dir / "config.yaml").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.startswith("wake_word_threshold:"))
    template = (app_dir / "config.example.yaml").read_text(encoding="utf-8")
    original = next(ln for ln in template.splitlines() if ln.startswith("wake_word_threshold:"))
    assert line.index("#") == original.index("#")


def test_text_lists_and_arabic_round_trip(app_dir):
    instructions = 'Call me "Mo".\nAnswer briefly: no # hashtags, \\ or emojis.'
    cfg = save_settings(
        app_dir,
        {
            "wake_words": ["abdoh", "hey abdoh", "ya abdoh", "يا عبدوه"],
            "claude": {"instructions": instructions, "folders": ["C:\\Users\\me\\Documents"]},
        },
    )
    assert cfg.wake_words == ["abdoh", "hey abdoh", "ya abdoh", "يا عبدوه"]
    assert cfg.claude.instructions == instructions.strip()
    assert cfg.claude.folders == ["C:\\Users\\me\\Documents"]


def test_values_set_by_hand_are_kept(app_dir):
    path = app_dir / "config.yaml"
    load_config(app_dir)  # creates config.yaml from the example
    path.write_text(path.read_text().replace('whisper_model: "base"', 'whisper_model: "small"'))
    cfg = save_settings(app_dir, {"tts_rate": 190})
    assert cfg.whisper_model == "small"


def test_new_settings_are_added_when_the_file_is_old(app_dir):
    (app_dir / "config.yaml").write_text("tts_rate: 150\nclaude:\n  allow_web: false\n")
    cfg = save_settings(app_dir, {"setup_done": True})
    assert (cfg.tts_rate, cfg.claude.allow_web, cfg.setup_done) == (150, False, True)
    assert "instructions:" in (app_dir / "config.yaml").read_text()


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"colour": "red"}, "Unknown setting: colour"),
        ({"claude": {"magic": True}}, "Unknown setting: claude.magic"),
        ({"tts_rate": "fast"}, "Voice speed must be a number"),
        ({"tts_rate": True}, "Voice speed must be a number"),
        ({"tts_rate": 12.5}, "whole number"),
        ({"wake_word_threshold": 2}, "between 0.05 and 0.95"),
        ({"allow_run": "yes"}, "must be on or off"),
        ({"wake_words": "abdoh"}, "must be a list of text"),
        ({"claude": {"actions": ["open_url", "hack"]}}, "unknown choice 'hack'"),
        ({"claude": {"backend": "cloud"}}, "must be one of"),
        ({"claude": "off"}, "group"),
    ],
)
def test_bad_values_are_refused_and_nothing_is_written(app_dir, changes, message):
    load_config(app_dir)
    before = (app_dir / "config.yaml").read_text()
    with pytest.raises(SettingsError, match=message):
        save_settings(app_dir, changes)
    assert (app_dir / "config.yaml").read_text() == before


def test_lists_are_cleaned(app_dir):
    cfg = save_settings(app_dir, {"wake_words": [" abdoh ", "", "abdoh", "hey abdoh"]})
    assert cfg.wake_words == ["abdoh", "hey abdoh"]


def test_languages_are_a_list_of_codes(app_dir):
    assert save_settings(app_dir, {"languages": ["EN", "ar"]}).languages == ["en", "ar"]
    for bad in ([], ["english"], ["e n"]):
        with pytest.raises(SettingsError, match="at least one language"):
            save_settings(app_dir, {"languages": bad})


def test_settings_from_abdoh_0_3_are_upgraded(app_dir):
    old = (
        'wake_words: ["abdoh", "hey abdoh"]\nwake_word_threshold: 0.5\nwhisper_model: "base"\n'
        "language: null\ntts_rate: 190\n"
    )
    (app_dir / "config.yaml").write_text(old)
    cfg = load_config(app_dir)
    assert cfg.languages == ["en", "ar"]  # "detect automatically" became your two languages
    assert (cfg.wake_word_threshold, cfg.whisper_model) == (0.4, "small")  # the new defaults
    assert cfg.wake_words == ["abdoh", "hey abdoh", "ya abdoh"]
    assert cfg.tts_rate == 190  # your own choices stay
    text_before = (app_dir / "config.yaml").read_text()
    assert text_before == old  # nothing is rewritten until you save a setting
    save_settings(app_dir, {"tts_rate": 200})
    text = (app_dir / "config.yaml").read_text()
    assert "config_version: 5" in text and "\nlanguage:" not in text
    assert load_config(app_dir).languages == ["en", "ar"]


def test_your_own_values_survive_the_upgrade(app_dir):
    (app_dir / "config.yaml").write_text(
        'language: "en"\nwake_word_threshold: 0.6\nwhisper_model: "medium"\n'
    )
    cfg = load_config(app_dir)
    assert (cfg.languages, cfg.wake_word_threshold, cfg.whisper_model) == (["en"], 0.6, "medium")


def test_restart_is_needed_only_for_some_settings(app_dir):
    old = load_config(app_dir)
    new = save_settings(app_dir, {"hotkey": "ctrl+shift+a", "tts_rate": 220})
    assert restart_needed(old, new) == ["hotkey"]


def test_render_without_a_template_writes_everything():
    text = render_config({"tts_rate": 175, "claude": {"allow_web": True}}, "")
    assert yaml.safe_load(text) == {"tts_rate": 175, "claude": {"allow_web": True}}


def test_yaml_values():
    assert yaml_value(None) == "null"
    assert yaml_value(False) == "false"
    assert yaml_value(0.5) == "0.5"
    assert yaml_value(["a", 'b"c']) == '["a", "b\\"c"]'
