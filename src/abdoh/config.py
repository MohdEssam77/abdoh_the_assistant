"""Load config.yaml + .env into a typed Config, and set up logging."""

import logging
import logging.handlers
import os
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


CLAUDE_BACKENDS = ("auto", "code", "api", "off")
SPEECH_ENGINES = ("auto", "parakeet", "whisper")
# 2: `languages` replaced `language`. 3: Claude got more actions. (Both Abdoh 0.4.)
CONFIG_VERSION = 5
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
)
# By the config version that added them: switched on for people upgrading from before it.
NEW_ACTIONS = {
    3: ("volume", "brightness", "remind", "note"),
    4: ("app_volume",),
    5: ("mode", "displays", "audio_output", "dark_mode"),
}


@dataclass
class ClaudeConfig:
    backend: str = "auto"  # auto: Claude Code if installed (subscription), else the API key
    code_path: str = ""  # claude.exe; empty = find it
    code_model: str = ""  # empty = your Claude Code default
    model: str = "claude-opus-5-5"  # API key only
    max_tokens: int = 4000  # API key only
    effort: str = "low"
    allow_web: bool = True  # Claude Code may search the web
    allow_files: bool = True  # Claude Code may work with your files and run commands
    allow_screen: bool = True  # Claude may look at the screen you're using when you ask about it
    actions: list[str] = field(default_factory=lambda: list(CLAUDE_ACTIONS))  # it may do these
    folders: list[str] = field(default_factory=list)  # where it may work with files; [] = home
    instructions: str = ""  # your own instructions, sent with every request
    timeout_seconds: float = 120
    followup_seconds: float = 60  # a follow-up within this time gets the last exchange as context
    listen_after_question: bool = True  # answer Claude's questions without the wake word
    translate_target: str = "English"
    voice_reply_max_sentences: int = 4


@dataclass
class Config:
    config_version: int = CONFIG_VERSION  # for upgrading settings files from older versions
    wake_words: list[str] = field(default_factory=lambda: ["abdoh", "hey abdoh", "ya abdoh"])
    wake_word_aliases: list[str] = field(default_factory=lambda: ["abdo", "ab doe", "abdul"])
    wake_word_model: str = "models/hey_abdoh.onnx"  # openWakeWord; missing -> Vosk fallback
    wake_word_threshold: float = 0.4
    hotkey: str = "ctrl+alt+space"  # push-to-talk / stop speaking; "" turns it off
    vosk_model: str = "models/vosk-model-small-en-us-0.15"
    languages: list[str] = field(default_factory=lambda: ["en"])  # what you speak to Abdoh
    speech_engine: str = "auto"  # auto | parakeet (English, most accurate) | whisper
    whisper_model: str = "small"  # Whisper size, used for languages other than English
    match_threshold: int = 85
    silence_seconds: float = 0.6
    follow_up_seconds: float = 6.0  # after a reply, keep listening this long (0 = off)
    wake_word_interrupts: bool = True  # saying the wake word stops a reply
    voice_interrupts: bool = True  # just start talking to stop a reply (no wake word)
    voice_interrupt_sensitivity: str = "medium"  # low | medium | high
    duck_others: bool = True  # other apps go quieter while Abdoh listens and answers
    duck_percent: int = 30  # ... to this share of their volume
    allow_power: bool = True  # Abdoh may put the computer to sleep, shut it down, restart it
    max_record_seconds: float = 10
    tts_rate: int = 175
    tts_voice: str = ""  # a voice's name; "" = the system's default voice
    mic_device: str = ""  # a microphone's name; "" = the system's default microphone
    allow_run: bool = False
    check_updates: bool = True  # look for a new version once a day
    setup_done: bool = False  # the first-start setup was finished (or skipped)
    claude: ClaudeConfig = field(default_factory=ClaudeConfig)
    log_file: str = "~/.abdoh/abdoh.log"
    # Not read from config.yaml:
    app_dir: Path = DEFAULT_APP_DIR
    anthropic_api_key: str | None = None

    @property
    def has_api_key(self) -> bool:
        return bool(self.anthropic_api_key)

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


def read_api_key(app_dir: Path) -> str | None:
    """API key from .env in app_dir, falling back to the environment."""
    values = dotenv_values(app_dir / ".env") if (app_dir / ".env").exists() else {}
    key = values.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    return key.strip() if key and key.strip() else None


def save_api_key(env_path: Path, key: str) -> None:
    """Write ANTHROPIC_API_KEY into the .env file, keeping any other lines."""
    env_path = Path(env_path)
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    lines = [ln for ln in lines if not ln.strip().startswith("ANTHROPIC_API_KEY")]
    lines.append(f"ANTHROPIC_API_KEY={key.strip()}")
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
    if version >= 2:
        return raw
    if "languages" not in raw:  # `language: null` meant "detect it": English and Arabic now
        language = raw.pop("language", "en")
        raw["languages"] = [language] if language else ["en", "ar"]
    raw.pop("language", None)
    if raw.get("wake_word_threshold") == 0.5:
        raw["wake_word_threshold"] = 0.4
    if raw.get("whisper_model") == "base":
        raw["whisper_model"] = "small"
    words = raw.get("wake_words")
    if isinstance(words, list) and "hey abdoh" in words and "ya abdoh" not in words:
        raw["wake_words"] = [*words, "ya abdoh"]
    return raw


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
    known = {f.name for f in fields(Config)} - {"app_dir", "anthropic_api_key", "claude"}
    kwargs = {k: v for k, v in raw.items() if k in known}
    for k in raw.keys() - known - {"claude"}:
        log.warning("Unknown config key ignored: %s", k)

    claude_raw = raw.get("claude") or {}
    claude_known = {f.name for f in fields(ClaudeConfig)}
    claude = ClaudeConfig(**{k: v for k, v in claude_raw.items() if k in claude_known})
    if claude.backend not in CLAUDE_BACKENDS:
        log.warning("Unknown claude.backend %r; using 'auto'", claude.backend)
        claude.backend = "auto"

    cfg = Config(**kwargs, claude=claude, app_dir=app_dir, anthropic_api_key=read_api_key(app_dir))
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
