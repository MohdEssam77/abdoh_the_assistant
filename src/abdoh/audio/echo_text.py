"""Is what Abdoh heard over its reply just its own words coming back?

The echo canceller takes most of Abdoh's voice out of the microphone, but not all of it, and
not always: with a microphone on another device than the speakers (a webcam's, a laptop's with
a monitor's speakers), loud enough words get through, and Abdoh stopped itself for "each one
was" while saying "each one flips the state" (the owner's webcam, 2026-11-27). So what was
heard is compared, letter by letter, with stretches of what Abdoh said in the last seconds:
words it clearly just said are its own voice, and the reply goes on.

Real cases from the owner's logs: Abdoh's own words scored 0.80 and 1.00 ("each one was",
"take your time"); the user's real interruptions 0.54 at most.
"""

import difflib
import re

LIKE = 0.7  # this alike (0 to 1) to what Abdoh said: its own words, from 3 words heard
LIKE_SHORT = 0.9  # ... for 1 or 2 words, which match by chance more easily
SECONDS = 20.0  # what Abdoh said this long ago still counts (a sentence takes a few seconds)


def words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]+", " ", str(text).lower().replace("’", "'")).split()


def likeness(heard: str, said: str) -> float:
    """How alike (0 to 1) `heard` is to the stretch of `said` it's most like, of about the
    same number of words, letter by letter (speech recognition mishears a word here and
    there: "each thing we're back" for "each state remembers")."""
    h = words(heard)
    s = words(said)
    if not h or not s:
        return 0.0
    text = " ".join(h)
    best = 0.0
    for size in sorted({max(1, len(h) - 1), len(h), len(h) + 1}):
        for i in range(max(1, len(s) - size + 1)):
            window = " ".join(s[i : i + size])
            best = max(best, difflib.SequenceMatcher(None, text, window, autojunk=False).ratio())
            if best == 1.0:
                return best
    return best


def own_words(heard: str, said: list[str]) -> bool:
    """`heard` is Abdoh's own words coming back: very like what it just said (`said`: its
    latest sentences)."""
    count = len(words(heard))
    if not count or not said:
        return False
    needed = LIKE if count >= 3 else LIKE_SHORT
    return likeness(heard, " ".join(said)) >= needed
