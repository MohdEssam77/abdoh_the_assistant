"""The Claude "brain": one interface for Claude Code (subscription) and the API (key)."""

import logging
import sys
from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from abdoh.claude.reply import ACTION_HELP
from abdoh.config import Config

log = logging.getLogger(__name__)

NOT_CONNECTED = (
    "Claude isn't connected. Install Claude Code and sign in with your Claude account, "
    "or add an Anthropic API key in Abdoh's window."
)

SYSTEM_PROMPT = """You are Abdoh, a voice assistant on the user's {platform} computer. Everything \
you write is read aloud by a text-to-speech voice, so answer in at most {sentences} short spoken \
sentences: no markdown, lists, headings, code, emojis, and never read out links.

You can do things on the computer. To do one, write an action line before your spoken answer, \
one action per line, exactly in this form:
{actions}
Use only these actions, and only when the user asks you to do something. {limits}After an \
action, say in a few words what you did.
{files}{web}If you need more information, ask one short question.
Today is {date}, and the time is {time}."""

NO_COMMANDS = "You cannot run commands, type or click. "
FILES = """When the user asks, you can also work with their files and run {shell} commands \
with your tools. Their home folder is {home}{folders}. Before deleting files or overwriting \
existing ones, say in one short sentence what you will do and ask whether to go ahead; do it \
only after they say yes. Delete by moving files to the {trash}, never permanently. To open \
things, press media keys or set timers, use the action lines above, not commands.
"""
WEB_LINE = "You can search the web when you need current information.\n"


def _platform() -> str:
    return {"win32": "Windows", "darwin": "Mac"}.get(sys.platform, "Linux")


def system_prompt(
    cfg: Config,
    web: bool = False,
    now: datetime | None = None,
    home: Path | None = None,
    folders: dict[str, Path] | None = None,
) -> str:
    """Abdoh's instructions for Claude. With `home`, Claude may work with files there."""
    now = now or datetime.now()
    files = ""
    if home is not None:
        windows = sys.platform == "win32"
        where = ", ".join(f"{name}: {path}" for name, path in (folders or {}).items())
        files = FILES.format(
            shell="PowerShell" if windows else "shell",
            home=home,
            folders=f" ({where})" if where else "",
            trash="Recycle Bin" if windows else "Trash",
        )
    return SYSTEM_PROMPT.format(
        platform=_platform(),
        sentences=cfg.claude.voice_reply_max_sentences,
        actions="\n".join(ACTION_HELP.values()),
        limits="" if files else NO_COMMANDS,
        files=files,
        web=WEB_LINE if web else "",
        date=f"{now:%A}, {now:%B} {now.day}, {now.year}",
        time=f"{now.hour % 12 or 12}:{now.minute:02d} {'AM' if now.hour < 12 else 'PM'}",
    )


class BrainError(RuntimeError):
    """A Claude request failed; the message is safe to speak."""


class Brain(ABC):
    name = "Claude"

    @abstractmethod
    def stream(self, prompt: str, image_png: bytes | None = None) -> Iterator[str]:
        """Yield the reply text in chunks as it arrives. Raises BrainError."""

    def status(self) -> str:
        """Short description for the window, e.g. "Pro subscription (Claude Code)".

        May be slow (Claude Code checks its sign-in), so call it off the UI thread.
        """
        return self.name


def make_brain(cfg: Config, find_code=None) -> Brain | None:
    """Claude Code if it's installed (paid by your subscription), else the API if a key is set."""
    from abdoh.claude.code import ClaudeCodeBrain, find_claude_code

    backend = cfg.claude.backend
    if backend == "off":
        return None
    if backend in ("auto", "code"):
        exe = (find_code or find_claude_code)(cfg.claude.code_path)
        if exe:
            return ClaudeCodeBrain(cfg, exe)
        if backend == "code":
            log.warning("claude.backend is 'code' but Claude Code wasn't found")
            return None
    if backend in ("auto", "api") and cfg.anthropic_api_key:
        from abdoh.claude.api import ApiBrain

        return ApiBrain(cfg)
    return None
