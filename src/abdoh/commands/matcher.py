"""Text normalization, wake word stripping, and fuzzy matching against command triggers."""

import re

from rapidfuzz import fuzz

from abdoh.commands.registry import Command

_PUNCT = re.compile(r"[^\w\s']")
_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace."""
    text = _PUNCT.sub(" ", text.lower()).replace("'", "")
    return _SPACES.sub(" ", text).strip()


def strip_wake_words(text: str, wake_words: list[str]) -> str:
    """Normalize text and remove wake phrases (whole words, longest first)."""
    text = normalize(text)
    for phrase in sorted({normalize(w) for w in wake_words if w.strip()}, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(phrase)}\b", " ", text)
    return _SPACES.sub(" ", text).strip()


def score(text: str, trigger: str) -> float:
    """Similarity 0-100 between normalized text and a trigger.

    token_set_ratio tolerates extra words and word order, but scores 100 whenever all of a
    short trigger's words appear anywhere ("time" vs "what's the time in tokyo"). Averaging
    with plain ratio keeps typo tolerance while requiring the phrases to be similar overall.
    """
    trigger = normalize(trigger)
    return (fuzz.token_set_ratio(text, trigger) + fuzz.ratio(text, trigger)) / 2


def match(
    text: str, commands: list[Command], threshold: float, wake_words: list[str] = ()
) -> tuple[Command, float] | None:
    """Best matching command for text (wake words stripped), if its score >= threshold."""
    text = strip_wake_words(text, list(wake_words))
    if not text:
        return None
    best: tuple[Command, float] | None = None
    for command in commands:
        for trigger in command.triggers:
            s = score(text, trigger)
            if best is None or s > best[1]:
                best = (command, s)
    return best if best and best[1] >= threshold else None
