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


def remove_wake_words(text: str, wake_words: list[str]) -> str:
    """Remove wake phrases but keep the original case and punctuation (for Claude).

    "Hey Abdoh, what's 15% of 80?" -> "what's 15% of 80?"
    """
    phrases = sorted({normalize(w) for w in wake_words if w.strip()}, key=len, reverse=True)
    for phrase in phrases:
        words = r"[\s,.!?-]+".join(re.escape(w) for w in phrase.split())
        text = re.sub(rf"\b{words}\b,?", " ", text, flags=re.I)
    text = re.sub(r"\s+([,.!?])", r"\1", _SPACES.sub(" ", text))
    text = re.sub(r",([.!?])", r"\1", text)  # "pain, Abdoh?" -> "pain?"
    return text.strip().lstrip(",.!?- ").strip()


def has_wake_word(text: str, wake_words: list[str], threshold: float = 75) -> bool:
    """True if the transcript contains a wake word, allowing near spellings ("Abdo", "Abdou")."""
    words = normalize(text).split()
    for phrase in {normalize(w) for w in wake_words if w.strip()}:
        n = len(phrase.split())
        for i in range(len(words) - n + 1):
            if fuzz.ratio(" ".join(words[i : i + n]), phrase) >= threshold:
                return True
    return False


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
