"""Built-in Claude skills that look at the screen."""

import re

from abdoh.claude.screen import capture_screen

TRANSLATE_PROMPT = (
    "Translate the main text visible in this screenshot into {target}. "
    "If it's long, give the gist in a few sentences."
)
SUMMARIZE_PROMPT = "Summarize the main content of this screenshot in a few spoken sentences."

_TARGET = re.compile(r"\b(?:to|into)\s+([a-z]+)\s*$")


def parse_target_language(request: str) -> str | None:
    """'translate my screen to arabic' -> 'Arabic'."""
    m = _TARGET.search(request.lower().strip())
    return m.group(1).capitalize() if m and m.group(1) != "screen" else None


def is_translate_request(words: set[str]) -> bool:
    return "translate" in words and "screen" in words


def is_summarize_request(words: set[str]) -> bool:
    return bool(words & {"summarize", "summarise", "summary"}) and "screen" in words


def translate_screen(claude, target: str, capture=capture_screen) -> str:
    return claude.ask(TRANSLATE_PROMPT.format(target=target), image_png=capture())


def summarize_screen(claude, capture=capture_screen) -> str:
    return claude.ask(SUMMARIZE_PROMPT, image_png=capture())
