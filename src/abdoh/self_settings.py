"""The settings Abdoh may change itself when you ask, and the phone's Settings (story 157).

"Talk a bit faster", "stop playing a sound when you do something, say it", "remember less":
Claude writes `ACTION setting: <key> | <value>` (or `+20` / `-1` for "a bit more" or "less"),
from the laptop or the phone; the phone's Settings change the same ones directly. Both go
through `save_settings` (its checks, config.yaml) and Abdoh uses the change at once.

Only everyday settings are here. Never: what Abdoh and Claude may do (the permissions, the
folders, running commands, the power), keys, your own instructions for Claude, the phone switch,
the speech models. Something Claude read (a web page) can't make Abdoh trust itself more.
"""

from dataclasses import dataclass

from abdoh.config import Config


class SettingError(ValueError):
    """Not one of these settings, or not a value it can have; the message is for people."""


@dataclass(frozen=True)
class Knob:
    key: str  # in config.yaml; "claude.voice_reply_max_sentences" for the claude group's
    label: str  # as the window's row calls it
    section: str  # the window's card ("Voice", "Conversation"...)
    help: str
    kind: str  # "bool", "number" or "choice"
    choices: tuple[tuple[str, str], ...] = ()  # (value, what it's called)
    low: float = 0
    high: float = 0
    step: float = 1
    unit: str = ""
    page: str = "settings"  # the window's page the card is on
    restart: bool = False  # used once Abdoh restarts


def _voice_name(name: str) -> str:
    """ "en_GB-jenny_dioco-medium" -> "Jenny Dioco (British)", like the window says it."""
    if name.startswith("kokoro:"):
        who = name.split(":", 1)[1]
        accent = {"a": "American", "b": "British"}.get(who[:1], "")
        return f"{who[3:].replace('_', ' ').title()} ({accent}, Kokoro)"
    code, _, rest = name.partition("-")
    who = rest.rsplit("-", 1)[0]
    accent = {"en_US": "American", "en_GB": "British", "de_DE": "German"}.get(code, code)
    return f"{who.replace('_', ' ').title()} ({accent})"


def _voices():
    from abdoh.speech.piper_voice import ENGLISH_VOICES, GERMAN_VOICES

    english = tuple((v, _voice_name(v)) for v in ENGLISH_VOICES)
    german = tuple((v, _voice_name(v)) for v in GERMAN_VOICES)
    return english, german


_ENGLISH, _GERMAN = _voices()

KNOBS: tuple[Knob, ...] = (
    Knob("tts_rate", "Speed", "Voice", "How fast Abdoh talks.", "number", low=120, high=260,
         step=5, unit="words a minute"),
    Knob("piper_voice_en", "English voice", "Voice", "Abdoh's voice in English.", "choice",
         _ENGLISH),
    Knob("piper_voice_de", "German voice", "Voice", "Abdoh's voice in German.", "choice", _GERMAN),
    Knob("tts_engine", "Kind of voice", "Voice", "A natural voice, or the Windows one.", "choice",
         (("piper", "Natural voice"), ("windows", "Windows voice")), restart=True),
    Knob("confirm_actions", "When it does something for you", "Conversation",
         "After “open Spotify”: a short sound, or it says what it did.", "choice",
         (("sound", "A short sound"), ("words", "Say what it did"))),
    Knob("claude.voice_reply_max_sentences", "Longest spoken answer", "Conversation",
         "How many sentences an answer may have, at most.", "number", low=1, high=20,
         unit="sentences"),
    Knob("follow_up_seconds", "Keep listening after a reply", "Conversation",
         "How long Abdoh listens after answering, so you can go on without the wake word "
         "(0: not at all).", "number", low=0, high=30, unit="seconds"),
    Knob("claude.listen_after_question", "Answer questions right away", "Conversation",
         "When Abdoh asks you something, just answer.", "bool"),
    Knob("voice_interrupts", "Stop when I start talking", "Conversation",
         "Abdoh goes quiet as soon as it hears you.", "bool"),
    Knob("voice_interrupt_sensitivity", "How easily your voice stops Abdoh", "Conversation",
         "Higher reacts sooner; lower is for loud rooms.", "choice",
         (("low", "Low"), ("medium", "Medium"), ("high", "High"))),
    Knob("wake_word_interrupts", "Interrupt with the wake word", "Conversation",
         "Say “Hey Abdoh” while it talks to stop it.", "bool"),
    Knob("duck_others", "Lower other sounds while I talk to Abdoh", "Conversation",
         "Music and videos go quieter while Abdoh listens and answers.", "bool"),
    Knob("duck_percent", "How low other sounds go", "Conversation",
         "Their share of their volume while Abdoh listens.", "number", low=0, high=90, step=5,
         unit="%"),
    Knob("lesson_listen_seconds", "Keep listening in a lesson", "Conversation",
         "In a lesson, how long Abdoh listens without the wake word (0: always the wake word).",
         "number", low=0, high=3600, step=30, unit="seconds"),
    Knob("watch_seconds", "Watching your screen", "Conversation",
         "While it watches your screen, how often it looks at most.", "number", low=2, high=60,
         unit="seconds"),
    Knob("wake_word_threshold", "Sensitivity", "Wake word and hotkey",
         "How sure Abdoh must be it heard its name: lower reacts more easily, higher wakes up "
         "by mistake less.", "number", low=0.3, high=0.8, step=0.05),
    Knob("max_record_seconds", "Longest request", "Wake word and hotkey",
         "How long one request may be.", "number", low=3, high=60, unit="seconds"),
    Knob("memory", "Remember things about me", "Memory", "Abdoh remembers what you tell it.",
         "bool", page="memory"),
    Knob("keep_conversations", "Keep conversations", "Memory",
         "Abdoh keeps your conversations, to look back at them.", "bool", page="memory"),
    Knob("conversation_days", "How long conversations are kept", "Memory", "", "number", low=1,
         high=30, unit="days", page="memory"),
    Knob("check_updates", "Updates", "General", "Look for a new version once a day.", "bool"),
)  # fmt: skip
_BY_KEY = {k.key: k for k in KNOBS}
SECTIONS = ("Voice", "Conversation", "Wake word and hotkey", "Memory", "General")
_ON = {"on", "true", "yes", "1", "enable", "enabled"}
_OFF = {"off", "false", "no", "0", "disable", "disabled"}


def find(key: str) -> Knob:
    knob = _BY_KEY.get(str(key or "").strip())
    if knob is None:
        raise SettingError("That isn't a setting I can change (permissions and keys stay yours).")
    return knob


def current(knob: Knob, cfg: Config):
    group, _, name = knob.key.rpartition(".")
    return getattr(cfg.claude if group == "claude" else cfg, name)


def value_of(knob: Knob, raw, cfg: Config):
    """What `raw` means for this setting (on/off, a number or "+20", a choice by its value or
    its name), checked. Raises SettingError."""
    if knob.kind == "bool":
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in _ON:
            return True
        if text in _OFF:
            return False
        raise SettingError(f"{knob.label} is on or off.")
    if knob.kind == "number":
        text = str(raw).strip().lower().removesuffix(knob.unit.lower()).strip()
        try:
            number = float(text)
        except ValueError:
            raise SettingError(f"{knob.label} must be a number.") from None
        if text.startswith(("+", "-")) and not isinstance(raw, int | float):
            number += float(current(knob, cfg))  # "+20": 20 more than now
        number = round(number / knob.step) * knob.step if knob.step else number
        if not knob.low <= number <= knob.high:
            unit = f" {knob.unit}" if knob.unit else ""
            low, high = _num(knob.low), _num(knob.high)
            raise SettingError(f"{knob.label} goes from {low} to {high}{unit}.")
        default = current(knob, Config())
        whole = isinstance(default, int) and not isinstance(default, bool)
        return int(round(number)) if whole else round(number, 2)
    wanted = str(raw).strip().lower()
    for value, name in knob.choices:
        if wanted in (value.lower(), name.lower()):
            return value
    names = ", ".join(name for _, name in knob.choices)
    raise SettingError(f"{knob.label} can be: {names}.")


def parse(arg: str, cfg: Config) -> tuple[Knob, object]:
    """Claude's `ACTION setting: <key> | <value>`."""
    key, _, raw = str(arg or "").partition("|")
    knob = find(key)
    if not raw.strip():
        raise SettingError(f"What should {knob.label.lower()} be?")
    return knob, value_of(knob, raw.strip(), cfg)


def changes(knob: Knob, value) -> dict:
    """For save_settings: {"tts_rate": 200} or {"claude": {"listen_after_question": True}}."""
    group, _, name = knob.key.rpartition(".")
    return {"claude": {name: value}} if group == "claude" else {name: value}


def shown(knob: Knob, value) -> str:
    """ "Speed: 200 words a minute", "Stop when I start talking: on"."""
    if knob.kind == "bool":
        text = "on" if value else "off"
    elif knob.kind == "choice":
        text = dict(knob.choices).get(value, str(value))
    else:
        text = f"{_num(value)} {knob.unit}".strip() if knob.unit != "%" else f"{_num(value)}%"
    return f"{knob.label}: {text}"


def describe_arg(arg: str) -> str:
    """A step's words for `ACTION setting: <key> | <value>` (without the settings at hand)."""
    key, _, raw = str(arg or "").partition("|")
    knob = _BY_KEY.get(key.strip())
    return f"Setting: {knob.label} → {raw.strip()}" if knob else f"Setting: {arg}"


def view(cfg: Config) -> list[dict]:
    """The phone's Settings: each section and its settings, with what they are now."""
    out = []
    for section in SECTIONS:
        knobs = [k for k in KNOBS if k.section == section]
        out.append({
            "title": section,
            "settings": [{
                "key": k.key, "label": k.label, "help": k.help, "kind": k.kind,
                "value": current(k, cfg), "choices": [list(c) for c in k.choices],
                "low": k.low, "high": k.high, "step": k.step, "unit": k.unit,
                "restart": k.restart,
            } for k in knobs],
        })  # fmt: skip
    return out


def for_claude() -> str:
    """The lines that tell Claude what it may change."""
    lines = []
    for k in KNOBS:
        if k.kind == "bool":
            what = "on or off"
        elif k.kind == "number":
            what = f"{_num(k.low)} to {_num(k.high)}" + (f" {k.unit}" if k.unit else "")
            what += ", or +N / -N for more or less"
        else:
            what = " | ".join(value for value, _ in k.choices[:12])
        about = f" ({k.help.rstrip('.')})" if k.help else ""
        lines.append(f"{k.key}: {k.label}{about}: {what}")
    return "\n".join(lines)


def _num(value) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)
