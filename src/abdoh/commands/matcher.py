"""Text normalization and wake word stripping."""

import re

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
