"""Load config.yaml + .env into a typed Config, and set up logging."""

import logging
import logging.handlers
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml
from dotenv import dotenv_values

log = logging.getLogger(__name__)

# Files that ship with Abdoh (example files, bundled models): the project folder, or the
# inside of the built Abdoh.exe.
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def _default_app_dir() -> Path:
    """The folder holding config.yaml, commands.yaml, .env and models/."""
    if os.environ.get("ABDOH_HOME"):
        return Path(os.environ["ABDOH_HOME"])
    if getattr(sys, "frozen", False):  # the built Abdoh.exe keeps your files in your profile
        return Path(os.environ.get("APPDATA", Path.home())) / "Abdoh"
    return Path(__file__).resolve().parents[2]  # the project folder


DEFAULT_APP_DIR = _default_app_dir()


CLAUDE_BACKENDS = ("auto", "code", "api", "openrouter", "off")
SPEECH_ENGINES = ("auto", "parakeet", "whisper")
# 2: `languages` replaced `language`. 3: Claude got more actions. (Both Abdoh 0.4.)
# 6: Abdoh became Xanthos (new wake words and wake word model). 7: Claude can switch lamps.
# 8: Xanthos became Krekos (new wake words and wake word model again).
# 9: Krekos became Abdoh again (Abdoh's wake words and wake word model). 10: Claude can move
# windows. 11: Claude can lock the computer and turn the screens off.
CONFIG_VERSION = 11
# Things Claude can do on the computer (abdoh.claude.reply.ACTION_HELP has the same names).
CLAUDE_ACTIONS = (
    "open_url",
    "open_app",
    "play_youtube",
    "media",
    "timer",
    "volume",
    "brightness",
    "app_volume",
    "remind",
    "note",
    "mode",
    "displays",
    "audio_output",
    "dark_mode",
    "lamp",
    "window",
    "power",
)
# Settings older versions wrote that no longer do anything (vosk_model: the old wake word;
# mic_raw: 0.7.1-0.7.3's raw microphone).
REMOVED_KEYS = {"vosk_model", "mic_raw"}
WAKE_WORDS = ("abdoh", "hey abdoh", "ya abdoh")
# How speech recognition writes "Abdoh" (left out of your requests).
WAKE_WORD_ALIASES = ("abdo", "abdu", "abdou", "abdoo", "ab doe", "abdul")
WAKE_WORD_MODEL = "models/hey_abdoh.onnx"
LOG_FILE = "~/.abdoh/abdoh.log"
# The names it had for a while and how speech recognition wrote them: Krekos ("krecos",
# "cricos", "creekos", "yakrecos") and Xanthos ("zanthos", "xantos", "santos", "xanthus").
_OLD_NAME = re.compile(
    r"\b(?:ya ?)?[ckgp]r[aeiouy]{1,2}(?:ck|c|k)[aou]{1,2}(?:e?s|ze?)?\b|\b[xzs]anth?[ou]s\b"
)
_OLD_MODELS = ("hey_xanthos.onnx", "hey_krekos.onnx")
_OLD_LOGS = ("~/.xanthos/xanthos.log", "~/.krekos/krekos.log")
# By the config version that added them: switched on for people upgrading from before it.
NEW_ACTIONS = {
    3: ("volume", "brightness", "remind", "note"),
    4: ("app_volume",),
    5: ("mode", "displays", "audio_output", "dark_mode"),
    7: ("lamp",),
    10: ("window",),
    11: ("power",),
}


@dataclass
class ClaudeConfig:
    # auto: Claude Code if installed (subscription), else the API key, else OpenRouter
    backend: str = "auto"
    code_path: str = ""  # claude.exe; empty = find it
    code_model: str = ""  # empty = your Claude Code default
    model: str = "claude-opus-5-5"  # API key only
    max_tokens: int = 4000  # API key and OpenRouter only
    openrouter_model: str = "openrouter/auto"  # OpenRouter only: any model there
    # Pictures made by AI on the board (with an OpenRouter key): the model that makes them
    openrouter_image_model: str = "black-forest-labs/flux-3-image-klein"
    effort: str = "low"
    allow_web: bool = True  # Claude Code may search the web
    allow_files: bool = True  # Claude Code may work with your files and run commands
    allow_screen: bool = True  # Claude may look at the screen you're using when you ask about it
    allow_self_edit: bool = True  # Claude may change your commands, modes and roles when you ask
    actions: list[str] = field(default_factory=lambda: list(CLAUDE_ACTIONS))  # it may do these
    folders: list[str] = field(default_factory=list)  # where it may work with files; [] = home
    instructions: str = ""  # your own instructions, sent with every request
    # claude.ai connectors Claude Code may use (connect them at claude.ai → Settings → Connectors)
    connectors: list[str] = field(default_factory=lambda: ["Gmail", "Google Calendar"])
    timeout_seconds: float = 120
    followup_seconds: float = 60  # a follow-up within this time gets the last exchange as context
    listen_after_question: bool = True  # answer Claude's questions without the wake word
    translate_target: str = "English"
    voice_reply_max_sentences: int = 4


@dataclass
class Config:
    config_version: int = CONFIG_VERSION  # for upgrading settings files from older versions
    wake_words: list[str] = field(default_factory=lambda: list(WAKE_WORDS))
    # Other spellings speech recognition may write for "Abdoh", left out of your requests.
    wake_word_aliases: list[str] = field(default_factory=lambda: list(WAKE_WORD_ALIASES))
    wake_word_model: str = WAKE_WORD_MODEL  # openWakeWord; missing -> hotkey only
    wake_word_threshold: float = 0.4
    wake_word_voice_threshold: float = 0.5  # with your voice check: how sure it must be it's you
    hotkey: str = "ctrl+alt+space"  # push-to-talk / stop speaking; "" turns it off
    languages: list[str] = field(default_factory=lambda: ["en"])  # what you speak to Abdoh
    speech_engine: str = "auto"  # auto | parakeet (English, most accurate) | whisper
    use_gpu: bool = True  # speech recognition on a suitable graphics card (abdoh/gpu.py)
    whisper_model: str = "small"  # Whisper size, used for languages other than English
    match_threshold: int = 85
    silence_seconds: float = 0.6
    confirm_actions: str = "sound"  # sound: a short sound after "open Spotify"; words: say it
    follow_up_seconds: float = 6.0  # after a reply, keep listening this long (0 = off)
    # In a lesson (a role explaining on the board, the window open), listen without the wake word
    # until this long passes with no word from either side (0 = off: always the wake word).
    lesson_listen_seconds: float = 120.0
    wake_word_interrupts: bool = True  # saying the wake word stops a reply
    keep_unclear_clips: bool = False  # keep "heard you but no words" recordings for a day
    voice_interrupts: bool = True  # just start talking to stop a reply (no wake word)
    voice_interrupt_sensitivity: str = "medium"  # low | medium | high
    duck_others: bool = True  # other apps go quieter while Abdoh listens and answers
    duck_percent: int = 30  # ... to this share of their volume
    allow_power: bool = True  # Abdoh may put the computer to sleep, shut it down, restart it
    memory: bool = True  # Abdoh remembers things about you (memory.yaml); off: nothing is sent
    # Your conversations are kept this many days (conversations/), for "what did we discuss
    # yesterday?". Off, or memory off: nothing new is kept.
    keep_conversations: bool = True
    conversation_days: int = 7
    max_record_seconds: float = 10
    tts_engine: str = "piper"  # piper: natural voices; windows: the Windows voice
    piper_voice_en: str = "en_US-lessac-medium"  # Piper's voice for English ...
    piper_voice_de: str = "de_DE-thorsten-medium"  # ... and for German
    tts_rate: int = 175
    tts_voice: str = ""  # a voice's name; "" = the system's default voice
    mic_device: str = ""  # a microphone's name; "" = the system's default microphone
    allow_run: bool = False
    check_updates: bool = True  # look for a new version once a day
    setup_done: bool = False  # the first-start setup was finished (or skipped)
    claude: ClaudeConfig = field(default_factory=ClaudeConfig)
    log_file: str = LOG_FILE
    # Not read from config.yaml:
    app_dir: Path = DEFAULT_APP_DIR
    anthropic_api_key: str | None = None
    openrouter_api_key: str | None = None  # OpenRouter: Claude, GPT, Gemini... with one key

    @property
    def has_api_key(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def has_openrouter_key(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def commands_path(self) -> Path:
        return self.app_dir / "commands.yaml"

    @property
    def env_path(self) -> Path:
        return self.app_dir / ".env"

    def resolve(self, path: str) -> Path:
        """Resolve a path from config relative to the app dir (and expand ~). If it isn't
        there, a copy that ships with Abdoh (e.g. models bundled in Abdoh.exe) is used."""
        p = Path(path).expanduser()
        if p.is_absolute():
            return p
        own, bundled = self.app_dir / p, BUNDLE_DIR / p
        return bundled if not own.exists() and bundled.exists() else own


def _ensure_copy(target: Path, example_name: str) -> None:
    example = target.parent / example_name
    if not example.exists():
        example = BUNDLE_DIR / example_name
    if not target.exists() and example.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(example, target)
        log.info("Created %s from %s", target, example)


def write_atomic(path: Path, text: str) -> None:
    """Write a text file so it's never left half-written (write a temp file, then swap)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


ANTHROPIC_KEY = "ANTHROPIC_API_KEY"
OPENROUTER_KEY = "OPENROUTER_API_KEY"


def read_api_key(app_dir: Path, name: str = ANTHROPIC_KEY) -> str | None:
    """A key from .env in app_dir, falling back to the environment."""
    values = dotenv_values(app_dir / ".env") if (app_dir / ".env").exists() else {}
    key = values.get(name) or os.environ.get(name)
    return key.strip() if key and key.strip() else None


def save_api_key(env_path: Path, key: str, name: str = ANTHROPIC_KEY) -> None:
    """Write a key (ANTHROPIC_API_KEY, OPENROUTER_API_KEY) into the .env file, keeping any
    other lines."""
    env_path = Path(env_path)
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    lines = [ln for ln in lines if not ln.strip().startswith(name)]
    lines.append(f"{name}={key.strip()}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def upgrade(raw: dict) -> dict:
    """Settings from an older Abdoh, brought up to date (the file itself is rewritten the next
    time settings are saved). Only values still at their old default are changed."""
    version = raw.get("config_version", 1)
    if version >= CONFIG_VERSION:
        return raw
    raw = dict(raw)
    claude = raw.get("claude")
    if isinstance(claude, dict) and isinstance(claude.get("actions"), list):
        # New things Claude can do are allowed until you turn them off, like the others.
        added = [a for v, names in NEW_ACTIONS.items() if version < v for a in names]
        actions = [*claude["actions"], *(a for a in added if a not in claude["actions"])]
        raw["claude"] = {**claude, "actions": actions}
    raw["config_version"] = CONFIG_VERSION
    if version < 2:
        _upgrade_from_1(raw)
    if version < 9:
        _rename(raw)
    return raw


def _upgrade_from_1(raw: dict) -> None:
    if "languages" not in raw:  # `language: null` meant "detect it": English and Arabic now
        language = raw.pop("language", "en")
        raw["languages"] = [language] if language else ["en", "ar"]
    raw.pop("language", None)
    if raw.get("wake_word_threshold") == 0.5:
        raw["wake_word_threshold"] = 0.4
    if raw.get("whisper_model") == "base":
        raw["whisper_model"] = "small"
    words = raw.get("wake_words")  # "ya abdoh" came with Arabic (0.4)
    if isinstance(words, list) and "hey abdoh" in words and "ya abdoh" not in words:
        raw["wake_words"] = [*words, "ya abdoh"]


def _rename(raw: dict) -> None:
    """Abdoh became Xanthos, then Krekos, and Abdoh again: those names' wake words, spellings,
    model and log go (Abdoh's own stay as they are). Your own other wake words stay, and a list
    without the old names is left alone."""
    for key, new in (("wake_words", WAKE_WORDS), ("wake_word_aliases", WAKE_WORD_ALIASES)):
        words = raw.get(key)
        if isinstance(words, list):
            own = [w for w in words if not (isinstance(w, str) and _OLD_NAME.search(w.lower()))]
            if len(own) < len(words):
                raw[key] = [*new, *(w for w in own if w not in new)]
    if str(raw.get("wake_word_model", "")).endswith(_OLD_MODELS):
        raw["wake_word_model"] = WAKE_WORD_MODEL
    if raw.get("log_file") in _OLD_LOGS:
        raw["log_file"] = LOG_FILE


def load_config(app_dir: Path | None = None) -> Config:
    """Load config.yaml from app_dir; create it and commands.yaml from the examples if missing."""
    app_dir = Path(app_dir or DEFAULT_APP_DIR)
    _ensure_copy(app_dir / "config.yaml", "config.example.yaml")
    _ensure_copy(app_dir / "commands.yaml", "commands.example.yaml")

    raw: dict = {}
    config_path = app_dir / "config.yaml"
    if config_path.exists():
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    raw = upgrade(raw)
    known = {f.name for f in fields(Config)} - {
        "app_dir", "anthropic_api_key", "openrouter_api_key", "claude"
    }  # fmt: skip
    kwargs = {k: v for k, v in raw.items() if k in known}
    for k in raw.keys() - known - {"claude"} - REMOVED_KEYS:
        log.warning("Unknown config key ignored: %s", k)

    claude_raw = raw.get("claude") or {}
    claude_known = {f.name for f in fields(ClaudeConfig)}
    claude = ClaudeConfig(**{k: v for k, v in claude_raw.items() if k in claude_known})
    if claude.backend not in CLAUDE_BACKENDS:
        log.warning("Unknown claude.backend %r; using 'auto'", claude.backend)
        claude.backend = "auto"

    cfg = Config(
        **kwargs,
        claude=claude,
        app_dir=app_dir,
        anthropic_api_key=read_api_key(app_dir),
        openrouter_api_key=read_api_key(app_dir, OPENROUTER_KEY),
    )
    if cfg.speech_engine not in SPEECH_ENGINES:
        log.warning("Unknown speech_engine %r; using 'auto'", cfg.speech_engine)
        cfg.speech_engine = "auto"
    if not cfg.languages:
        cfg.languages = ["en"]
    return cfg


def setup_logging(config: Config, console: bool = True, level: int = logging.INFO) -> None:
    """Rotating file log at config.log_file, plus console output when running in the foreground."""
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    for noisy in ("comtypes", "httpx", "httpx2", "httpcore", "anthropic", "faster_whisper", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    log_path = config.resolve(config.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # The log has what you said in it: keep today's and yesterday's only. (Abdoh 0.4 kept
    # numbered backups of any age: remove them.)
    for number in (1, 2, 3):
        log_path.with_name(f"{log_path.name}.{number}").unlink(missing_ok=True)
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_path, when="midnight", backupCount=1, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        root.addHandler(stream)
