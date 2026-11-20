"""Read and change Xanthos's settings from the app.

config.yaml is rewritten from config.example.yaml used as a template, so the comments that
explain each setting stay in the file for people who still edit it by hand.
"""

import json
import re
from dataclasses import fields
from pathlib import Path

import yaml

from abdoh.config import (
    BUNDLE_DIR,
    CLAUDE_ACTIONS,
    CLAUDE_BACKENDS,
    SPEECH_ENGINES,
    ClaudeConfig,
    Config,
    load_config,
    write_atomic,
)
from abdoh.speech.piper_voice import ENGLISH_VOICES, GERMAN_VOICES

TEMPLATE = "config.example.yaml"
# Config fields that aren't settings: where the files live, the API key (kept in .env), and the
# claude group (handled as its own section).
_NOT_SETTINGS = {"app_dir", "anthropic_api_key", "claude"}
# Settings that only take effect after Xanthos restarts.
RESTART_KEYS = (
    "hotkey",
    "wake_words",
    "wake_word_aliases",
    "wake_word_model",
    "whisper_model",
    "languages",
    "speech_engine",
    "log_file",
    "tts_engine",
)
_RANGES = {
    "wake_word_threshold": (0.05, 0.95),
    "wake_word_voice_threshold": (0.1, 0.9),
    "match_threshold": (50, 100),
    "silence_seconds": (0.2, 5),
    "follow_up_seconds": (0, 30),
    "duck_percent": (0, 90),
    "max_record_seconds": (3, 60),
    "tts_rate": (80, 400),
    "claude.max_tokens": (100, 64000),
    "claude.timeout_seconds": (10, 900),
    "claude.followup_seconds": (0, 3600),
    "claude.voice_reply_max_sentences": (1, 20),
}
_CHOICES = {
    "claude.backend": CLAUDE_BACKENDS,
    "speech_engine": SPEECH_ENGINES,
    "voice_interrupt_sensitivity": ("low", "medium", "high"),
    "confirm_actions": ("sound", "words"),
    "tts_engine": ("piper", "windows"),
    "piper_voice_en": ENGLISH_VOICES,
    "piper_voice_de": GERMAN_VOICES,
}
_LIST_CHOICES = {"claude.actions": CLAUDE_ACTIONS}
_NULLABLE: set[str] = set()
LABELS = {
    "wake_words": "Wake words",
    "wake_word_threshold": "Wake word sensitivity",
    "wake_word_voice_threshold": "How sure it must be that it's you",
    "confirm_actions": "When it does something for you",
    "tts_engine": "Voice",
    "piper_voice_en": "English voice",
    "piper_voice_de": "German voice",
    "hotkey": "Hotkey",
    "match_threshold": "Command matching",
    "silence_seconds": "Pause that ends a request",
    "max_record_seconds": "Longest request",
    "tts_rate": "Voice speed",
    "tts_voice": "Voice",
    "mic_device": "Microphone",
    "whisper_model": "Speech recognition model",
    "languages": "Languages",
    "speech_engine": "Speech recognition",
    "voice_interrupt_sensitivity": "How easily your voice stops Xanthos",
    "duck_percent": "Other sounds while Xanthos listens",
    "claude.actions": "Things Claude may do",
    "claude.folders": "Folders Claude may use",
    "claude.instructions": "Your instructions",
    "claude.backend": "How Xanthos connects to Claude",
}


class SettingsError(ValueError):
    """A setting's name or value isn't valid; the message is safe to show."""


def settings_view(cfg: Config) -> dict:
    """The settings as plain data for the app: no API key, only whether there is one."""
    view = {f.name: _plain(getattr(cfg, f.name)) for f in fields(Config)}
    for name in _NOT_SETTINGS:
        view.pop(name)
    view["claude"] = {f.name: _plain(getattr(cfg.claude, f.name)) for f in fields(ClaudeConfig)}
    view["has_api_key"] = cfg.has_api_key
    return view


def _plain(value):
    return list(value) if isinstance(value, list | tuple) else value


def restart_needed(old: Config, new: Config) -> list[str]:
    """The changed settings that only take effect after a restart."""
    return [key for key in RESTART_KEYS if getattr(old, key) != getattr(new, key)]


def save_settings(app_dir: Path, changes: dict) -> Config:
    """Apply `changes` (shaped like config.yaml, e.g. {"tts_rate": 190, "claude": {...}}) to
    the saved settings and rewrite config.yaml. Returns the new Config.

    Raises SettingsError, leaving the file as it was.
    """
    app_dir = Path(app_dir)
    values = settings_view(load_config(app_dir))
    values.pop("has_api_key")
    defaults = Config()
    if not isinstance(changes, dict):
        raise SettingsError("Settings must be a group of names and values.")
    for key, value in changes.items():
        if key == "claude":
            if not isinstance(value, dict):
                raise SettingsError("The Claude settings must be a group of names and values.")
            for sub, sub_value in value.items():
                if sub not in values["claude"]:
                    raise SettingsError(f"Unknown setting: claude.{sub}")
                default = getattr(defaults.claude, sub)
                values["claude"][sub] = _checked(f"claude.{sub}", sub_value, default)
        elif key in values:
            values[key] = _checked(key, value, getattr(defaults, key))
        else:
            raise SettingsError(f"Unknown setting: {key}")
    text = render_config(values, _template(app_dir))
    written = yaml.safe_load(text) or {}
    if any(written.get(k) != v for k, v in values.items()):  # it must read back the same
        raise SettingsError("Couldn't write the settings file safely.")
    write_atomic(app_dir / "config.yaml", text)
    return load_config(app_dir)


def _label(key: str) -> str:
    return LABELS.get(key, key.split(".")[-1].replace("_", " ").capitalize())


def _checked(key: str, value, default):
    """The value converted to the setting's type. Raises SettingsError."""
    label = _label(key)
    if value is None and key in _NULLABLE:
        return None
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise SettingsError(f"{label} must be on or off.")
        return value
    if isinstance(default, int | float):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise SettingsError(f"{label} must be a number.")
        if isinstance(default, int):
            if value != int(value):
                raise SettingsError(f"{label} must be a whole number.")
            value = int(value)
        else:
            value = float(value)
        low, high = _RANGES.get(key, (None, None))
        if low is not None and not low <= value <= high:
            raise SettingsError(f"{label} must be between {low} and {high}.")
        return value
    if isinstance(default, str):
        if not isinstance(value, str):
            raise SettingsError(f"{label} must be text.")
        value = value.strip()
        choices = _CHOICES.get(key)
        if choices and value not in choices:
            raise SettingsError(f"{label} must be one of: {', '.join(choices)}.")
        return value
    if isinstance(default, list):
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise SettingsError(f"{label} must be a list of text.")
        items = list(dict.fromkeys(v.strip() for v in value if v.strip()))
        if key == "languages":
            items = [v.lower() for v in items]
            if not items or not all(re.fullmatch(r"[a-z]{2,3}", v) for v in items):
                raise SettingsError("Choose at least one language (codes like en or ar).")
        allowed = _LIST_CHOICES.get(key)
        bad = [v for v in items if allowed and v not in allowed]
        if bad:
            raise SettingsError(f"{label}: unknown choice '{bad[0]}'.")
        return items
    raise SettingsError(f"{label} can't be changed here.")


def _template(app_dir: Path) -> str:
    for path in (Path(app_dir) / TEMPLATE, BUNDLE_DIR / TEMPLATE):
        if path.exists():
            return path.read_text(encoding="utf-8")
    return ""


_KEY_LINE = re.compile(r"^(?P<indent> *)(?P<key>[A-Za-z_][A-Za-z0-9_]*):(?P<rest>.*)$")


def render_config(values: dict, template: str) -> str:
    """config.yaml text for `values`, laid out like `template` with its comments kept.

    Settings the template doesn't mention are added at the end of their section.
    """
    out: list[str] = []
    written: dict[str | None, set[str]] = {None: set()}
    section_end: dict[str, int] = {}  # section -> index in `out` after its last setting
    section: str | None = None
    for line in template.splitlines():
        match = _KEY_LINE.match(line)
        if not match:
            out.append(line)  # comments, blank lines
            continue
        indent, key, rest = match["indent"], match["key"], match["rest"]
        value, comment = _split_comment(rest)
        if not indent:
            section = None
            if not value.strip() and isinstance(values.get(key), dict):
                section = key  # e.g. "claude:"
                written[section] = set()
                out.append(line)
                section_end[section] = len(out)
                continue
        mapping = values if not indent else values.get(section) if section else None
        if not isinstance(mapping, dict) or key not in mapping or isinstance(mapping[key], dict):
            out.append(line)  # not a setting we know: keep it as it is
            continue
        new = f"{indent}{key}: {yaml_value(mapping[key])}"
        if comment:
            column = len(line) - len(comment)
            new += " " * max(1, column - len(new)) + comment
        out.append(new)
        written[section if indent else None].add(key)
        if indent and section:
            section_end[section] = len(out)
    for name, mapping in values.items():
        if not isinstance(mapping, dict):
            continue
        missing = [k for k in mapping if k not in written.get(name, set())]
        lines = [f"  {k}: {yaml_value(mapping[k])}" for k in missing]
        if name in section_end:
            at = section_end[name]
            out[at:at] = lines
            for other, end in section_end.items():  # later sections moved down
                if end > at and other != name:
                    section_end[other] = end + len(lines)
        elif lines:
            out += [f"{name}:", *lines]
    for key, value in values.items():
        if not isinstance(value, dict) and key not in written[None]:
            out.append(f"{key}: {yaml_value(value)}")
    return "\n".join(out).rstrip("\n") + "\n"


def _split_comment(rest: str) -> tuple[str, str]:
    """' 0.5   # higher = ...' -> (' 0.5   ', '# higher = ...'). Ignores # inside quotes."""
    quote = None
    i = 0
    while i < len(rest):
        ch = rest[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2  # skip the escaped character
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or rest[i - 1].isspace()):
            return rest[:i], rest[i:]
        i += 1
    return rest, ""


def yaml_value(value) -> str:
    """A value as one line of YAML (strings double-quoted, lists in [brackets])."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list | tuple):
        return "[" + ", ".join(yaml_value(v) for v in value) + "]"
    raise TypeError(f"Can't write {type(value).__name__} to config.yaml")
