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
sentences: no markdown, lists, headings, code, emojis, and never read out links. Talk like a \
friendly, capable assistant: natural, warm and to the point. Answer in the language the user \
speaks to you. The user's words reach you through speech recognition, so if a word looks wrong, \
go by what they most likely meant; ask only when you really can't tell.

{actions}
{files}{web}{tools}If you need more information, ask one short question. Don't end with a \
question otherwise.
{clock}{instructions}"""

CLOCK = "Today is {date}, and the time is {time}."
# For a conversation that stays open: the time comes with every message instead.
STAMPED = (
    "Each message starts with the current date and time in square brackets. Use it when it "
    "matters, and never read it out unless the user asks for the time or the date."
)

ACTIONS = """You can do things on the computer. To do one, write an action line before your \
spoken answer, one action per line, exactly in this form:
{actions}
Use only these actions, and only when the user asks you to do something. {limits}After an \
action, say in a few words what you did."""
NO_ACTIONS = """You can't do things on the computer here: the user turned that off in Abdoh's \
permissions. {limits}If they ask you to do something, say so in one sentence."""
NO_COMMANDS = "You cannot run commands, type or click. "
FILES = """When the user asks, you can also work with their files and run {shell} commands \
with your tools. {where} Before deleting files or overwriting existing ones, say in one short \
sentence what you will do and ask whether to go ahead; do it only after they say yes. Delete by \
moving files to the {trash}, never permanently. To open things, press media keys or set \
timers, use the action lines above, not commands.
"""
HOME = "Their home folder is {home}{folders}."
ONLY = "Only work with files in these folders, never anywhere else: {folders}."
WEB_LINE = "You can search the web when you need current information.\n"
# The user hears nothing while a tool runs, so Claude says what it's doing first.
TOOLS_LINE = """Before you use a tool (a web search, anything with files), first say one very \
short sentence about what you're about to do, like "Let me look that up." Then use the tool.
"""
INSTRUCTIONS = """

The user's own instructions for you (follow them unless they ask for something unsafe):
{text}"""


def _platform() -> str:
    return {"win32": "Windows", "darwin": "Mac"}.get(sys.platform, "Linux")


def _date(now: datetime) -> str:
    return f"{now:%A}, {now:%B} {now.day}, {now.year}"


def _time(now: datetime) -> str:
    return f"{now.hour % 12 or 12}:{now.minute:02d} {'AM' if now.hour < 12 else 'PM'}"


def stamp(prompt: str, now: datetime | None = None) -> str:
    """A message with the current date and time in front (see STAMPED)."""
    now = now or datetime.now()
    return f"[{_date(now)}, {_time(now)}]\n{prompt}"


def system_prompt(
    cfg: Config,
    web: bool = False,
    now: datetime | None = None,
    home: Path | None = None,
    folders: dict[str, Path] | None = None,
    only: list[Path] | None = None,
    stamped: bool = False,
) -> str:
    """Abdoh's instructions for Claude, following your permissions (claude.actions and
    claude.instructions). With `home`, Claude may work with your files: anywhere in your home
    folder, or with `only`, just in those folders."""
    now = now or datetime.now()
    files = ""
    if home is not None:
        windows = sys.platform == "win32"
        if only:
            where = ONLY.format(folders=", ".join(str(p) for p in only))
        else:
            named = ", ".join(f"{name}: {path}" for name, path in (folders or {}).items())
            where = HOME.format(home=home, folders=f" ({named})" if named else "")
        files = FILES.format(
            shell="PowerShell" if windows else "shell",
            where=where,
            trash="Recycle Bin" if windows else "Trash",
        )
    limits = "" if files else NO_COMMANDS
    allowed = [ACTION_HELP[name] for name in ACTION_HELP if name in cfg.claude.actions]
    if allowed:
        actions = ACTIONS.format(actions="\n".join(allowed), limits=limits)
    else:
        actions = NO_ACTIONS.format(limits=limits)
    instructions = cfg.claude.instructions.strip()
    return SYSTEM_PROMPT.format(
        platform=_platform(),
        sentences=cfg.claude.voice_reply_max_sentences,
        actions=actions,
        files=files,
        web=WEB_LINE if web else "",
        tools=TOOLS_LINE if web or files else "",
        clock=STAMPED if stamped else CLOCK.format(date=_date(now), time=_time(now)),
        instructions=INSTRUCTIONS.format(text=instructions) if instructions else "",
    )


class BrainError(RuntimeError):
    """A Claude request failed; the message is safe to speak."""


class Brain(ABC):
    name = "Claude"
    # Keeps the conversation itself, so Abdoh needn't repeat the last exchange.
    remembers = False
    # Called with a few words when Claude starts something slow ("Searching the web").
    on_activity = None

    def close(self) -> None:  # noqa: B027 - optional hook
        """Let go of anything kept open (a Claude Code process)."""

    def same_setup(self, other) -> bool:
        """Would `other` (a brain made from changed settings) behave exactly like this one?"""
        return False

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
