"""Load config.yaml + .env into a typed Config, and set up logging."""

import logging
import logging.handlers
import os
import shutil
from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml
from dotenv import dotenv_values

log = logging.getLogger(__name__)

# The folder holding config.yaml, commands.yaml and .env (the project root by default).
DEFAULT_APP_DIR = Path(os.environ.get("ABDOH_HOME", Path(__file__).resolve().parents[2]))


CLAUDE_BACKENDS = ("auto", "code", "api", "off")


@dataclass
class ClaudeConfig:
    backend: str = "auto"  # auto: Claude Code if installed (subscription), else the API key
    code_path: str = ""  # claude.exe; empty = find it
    code_model: str = ""  # empty = your Claude Code default
    model: str = "claude-opus-5-5"  # API key only
    max_tokens: int = 4000  # API key only
    effort: str = "low"
    allow_web: bool = True  # Claude Code may search the web
    timeout_seconds: float = 60
    followup_seconds: float = 60  # a follow-up within this time gets the last exchange as context
    translate_target: str = "English"
    voice_reply_max_sentences: int = 4


@dataclass
class Config:
    wake_words: list[str] = field(default_factory=lambda: ["abdoh", "hey abdoh"])
    wake_word_aliases: list[str] = field(default_factory=lambda: ["abdo", "ab doe", "abdul"])
    wake_word_model: str = "models/hey_abdoh.onnx"  # openWakeWord; missing -> Vosk fallback
    wake_word_threshold: float = 0.5
    vosk_model: str = "models/vosk-model-small-en-us-0.15"
    whisper_model: str = "base"
    language: str | None = "en"
    match_threshold: int = 85
    silence_seconds: float = 0.6
    max_record_seconds: float = 10
    tts_rate: int = 175
    allow_run: bool = False
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
        """Resolve a path from config relative to the app dir (and expand ~)."""
        p = Path(path).expanduser()
        return p if p.is_absolute() else self.app_dir / p


def _ensure_copy(target: Path, example: Path) -> None:
    if not target.exists() and example.exists():
        shutil.copyfile(example, target)
        log.info("Created %s from %s", target.name, example.name)


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


def load_config(app_dir: Path | None = None) -> Config:
    """Load config.yaml from app_dir; create it and commands.yaml from the examples if missing."""
    app_dir = Path(app_dir or DEFAULT_APP_DIR)
    _ensure_copy(app_dir / "config.yaml", app_dir / "config.example.yaml")
    _ensure_copy(app_dir / "commands.yaml", app_dir / "commands.example.yaml")

    raw: dict = {}
    config_path = app_dir / "config.yaml"
    if config_path.exists():
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

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

    return Config(**kwargs, claude=claude, app_dir=app_dir, anthropic_api_key=read_api_key(app_dir))


def setup_logging(config: Config, console: bool = True, level: int = logging.INFO) -> None:
    """Rotating file log at config.log_file, plus console output when running in the foreground."""
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    for noisy in ("comtypes", "httpx", "httpcore", "anthropic", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    log_path = config.resolve(config.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        root.addHandler(stream)
