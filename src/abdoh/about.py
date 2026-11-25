"""What Abdoh knows about itself, so Claude can answer "which speech model do you use?",
"is my voice check on?" or "what commands do I have?".

`about(cfg, via)` is the part that only changes with the settings: it goes into Claude's
instructions. `state_line(...)` is what changes all the time (the mode that's on, whether voice
replies are on): it comes with every message instead, so switching a mode doesn't start a new
Claude conversation.
"""

import logging
import sys

from abdoh import __version__
from abdoh.config import Config

log = logging.getLogger(__name__)

ABOUT = """

About you, Abdoh (for when the user asks how you work or how you're set up; don't bring it \
up otherwise):
- Version {version}, on the user's {platform} computer. The window has the pages Home (your \
conversation), Modes, Act as (the user's roles for you, like a German teacher; while one is \
on you keep listening without the wake word until the user says not to), Memory (what you \
remember about the user, which they can edit or switch off), Commands, \
Permissions (what Claude may do, connected services, the user's instructions) and Settings \
(voice, microphone, wake word, conversation, speech recognition, lamps, updates); there's also \
a tray icon. You can't change settings yourself: say where they \
are. You can make and change their commands, modes and roles when they ask (if Permissions \
allows it). Your actions can switch modes, screens, speakers, lamps and the like.
- Waking up: the openWakeWord model "{wake_model}" listens for {wake_words} (sensitivity \
{wake_threshold}; higher means fewer false wake-ups). {voice_check} The hotkey is {hotkey}.
- Hearing: {hearing} Languages the user chose: {languages}.
- Speaking: {speaking} Speed: {rate} words a minute.
- Thinking: {thinking}
- Conversation: {conversation}
{things}"""


def about(cfg: Config, via: str = "code") -> str:
    """Abdoh's settings and parts, in words (see ABOUT). Never raises: a part that can't be
    read is left out."""
    return ABOUT.format(
        version=__version__,
        platform={"win32": "Windows", "darwin": "Mac"}.get(sys.platform, "Linux"),
        wake_model=_safe(lambda: cfg.resolve(cfg.wake_word_model).stem, cfg.wake_word_model),
        wake_words=", ".join(f'"{w}"' for w in cfg.wake_words) or "its wake word",
        wake_threshold=cfg.wake_word_threshold,
        voice_check=_safe(lambda: _voice_check(cfg), ""),
        hotkey=cfg.hotkey or "turned off",
        hearing=_safe(lambda: _hearing(cfg), "offline speech recognition."),
        languages=", ".join(cfg.languages),
        speaking=_safe(lambda: _speaking(cfg), "a text-to-speech voice."),
        rate=cfg.tts_rate,
        thinking=_thinking(cfg, via),
        conversation=_conversation(cfg),
        things=_safe(lambda: _things(cfg), ""),
    )


def state_line(
    mode: str | None = None,
    voice: bool = True,
    paused: bool = False,
    screens: str = "",
    role: str = "",
    lamps: str = "",
) -> str:
    """How Abdoh is right now, for the start of a message: "mode: Work; voice replies on;
    screens: 1 laptop (on); not connected: 2 HP 32f; lamps: Desk lamp (colours and whites)"."""
    parts = [f"mode on: {mode}" if mode else "no mode on"]
    parts.append("voice replies on" if voice else "voice replies off (the user reads)")
    if paused:
        parts.append("not listening for the wake word")
    if screens:
        parts.append(f"screens: {screens}")
    if lamps:
        parts.append(f"lamps: {lamps}")
    if role:
        parts.append(role)  # last: "acting as German teacher: <its instructions>"
    return "; ".join(parts)


def _safe(make, default: str) -> str:
    try:
        return make()
    except Exception:
        log.debug("Couldn't describe part of Abdoh", exc_info=True)
        return default


def _voice_check(cfg: Config) -> str:
    from abdoh.audio.voicecheck import FILE, VoiceCheck

    if VoiceCheck.load(cfg.app_dir / FILE, cfg.resolve(cfg.wake_word_model)) is not None:
        return (
            "Only the user's own voice wakes you: they taught it in Settings → Wake word "
            f"(how sure it must be: {cfg.wake_word_voice_threshold})."
        )
    return "Any voice saying it wakes you; Settings → Wake word → Teach it your voice changes that."


def _hearing(cfg: Config) -> str:
    from abdoh import models
    from abdoh.audio.stt import choose_engine, parakeet_available

    model = models.chosen(cfg)
    if model is not None and models.is_ready(cfg, model) and not model.bundled:
        return (
            f"{model.name}, offline on this computer, chosen by the user in Settings → Advanced "
            f"instead of the recommended model. {model.line}"
        )
    parakeet = parakeet_available(cfg)
    if choose_engine(cfg, parakeet) == "parakeet":
        if parakeet.name.endswith("v2"):
            return "NVIDIA Parakeet TDT 0.6b v2, offline on this computer (English only)."
        return (
            "NVIDIA Parakeet TDT 0.6b v3, offline on this computer: English, German and 23 "
            "other European languages, and it tells by itself which one was spoken."
        )
    return (
        f"OpenAI Whisper ({cfg.whisper_model}) through faster-whisper, offline on this computer "
        "(slower than Parakeet; used for languages Parakeet doesn't have, or when the user "
        "chose the lighter model)."
    )


def _speaking(cfg: Config) -> str:
    from abdoh.speech.piper_voice import piper_available

    windows = cfg.tts_voice or "the default Windows voice"
    if cfg.tts_engine == "piper" and piper_available():
        return (
            f"Piper natural voices made offline on this computer: {cfg.piper_voice_en} for "
            f"English, {cfg.piper_voice_de} for German, others downloaded the first time a "
            f"language is spoken; {windows} speaks while one downloads. Each sentence is read "
            "by the voice for its language."
        )
    return f"the Windows voice ({windows})."


def _thinking(cfg: Config, via: str) -> str:
    c = cfg.claude
    if via == "api":
        how = f"you are Claude through the Anthropic API with the user's own key, model {c.model}"
    elif via == "openrouter":
        model = c.openrouter_model or "openrouter/auto"
        how = (
            f"you run as the model {model} through OpenRouter with the user's own key (no "
            "files, web search or connectors there)"
        )
    else:
        model = c.code_model or "the user's Claude Code default model"
        how = (
            "you are Claude, through Claude Code with the user's own Claude account "
            f"(model: {model})"
        )
    effort = c.effort or "default"
    return f"{how}, effort {effort}. Answers are at most {c.voice_reply_max_sentences} sentences."


def _conversation(cfg: Config) -> str:
    parts = [
        "after something the user asked you to do, a short sound"
        if cfg.confirm_actions == "sound"
        else "after something the user asked you to do, a few words",
        f"listening {cfg.follow_up_seconds:g} more seconds after an answer"
        if cfg.follow_up_seconds
        else "no listening after answers",
        f"in a lesson (a role explaining on the board, the window open) listening without the "
        f"wake word until {cfg.lesson_listen_seconds / 60:g} quiet minutes"
        if cfg.lesson_listen_seconds
        else "always the wake word in lessons too",
        "talking over you stops you" if cfg.voice_interrupts else "only the wake word stops you",
        f"other apps drop to {cfg.duck_percent}% during a conversation"
        if cfg.duck_others
        else "other apps keep their volume",
    ]
    return "; ".join(parts) + "."


def _things(cfg: Config) -> str:
    """The user's modes, commands and lamps, by name."""
    lines = []
    names = _safe(lambda: _modes(cfg), "")
    if names:
        lines.append(f"- The user's modes: {names}.")
    commands = _safe(lambda: _commands(cfg), "")
    if commands:
        lines.append(f"- The user's own commands (run instantly, without you): {commands}.")
    return "\n".join(lines)  # the lamps are in every message's first line (state_line)


def _modes(cfg: Config) -> str:
    from abdoh.modes.store import ModesStore

    return ", ".join(m.name for m in ModesStore(cfg.app_dir / "modes.yaml").load())


def _commands(cfg: Config, limit: int = 30) -> str:
    from abdoh.commands.registry import CommandRegistry

    commands = CommandRegistry(cfg.commands_path).commands
    said = [f'"{c.triggers[0]}"' for c in commands[:limit] if c.triggers]
    more = f" and {len(commands) - limit} more" if len(commands) > limit else ""
    return ", ".join(said) + more


def lamps_text(lamps) -> str:
    """ "Desk lamp (colours and whites), Lamp 2 (whites only)", or "none set up yet"."""
    from abdoh.lights import KIND_NAMES

    named = [
        f"{lamp.name} ({KIND_NAMES[lamp.kind]})" if lamp.kind in KIND_NAMES else lamp.name
        for lamp in lamps
    ]
    return ", ".join(named) if named else "none set up yet"
