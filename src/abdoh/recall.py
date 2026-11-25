"""Remembering earlier conversations: Claude writes `ACTION recall: <what> | <when>`, Abdoh
finds the exchanges kept (conversations.py) that match best, each with the one before and after
it, at most about 4,000 characters, and asks Claude again with them, like a look at the screen.
When no exchange uses the words Claude wrote (it said "automaton", the lesson said "DFA"), Claude
gets the latest ones of those days instead and judges itself.

`<when>` is what the user said (yesterday, on Monday, this morning, last week, 3 days ago, in
English or German), a date (2026-11-23), two dates, or nothing (every day kept). Claude needn't
work out dates: when it did, it said its sums aloud.
"""

import re
from datetime import date, timedelta

from abdoh.conversations import WEEKDAYS, Conversations, Exchange, day_label

MAX_CHARS = 4_000
# Per exchange, what Claude gets of each part (the files keep more).
CUT_YOU, CUT_ABDOH, CUT_BOARD = 300, 600, 400
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_AGO = re.compile(r"\b(\d{1,2})\s+days?\s+ago\b|\bvor\s+(\d{1,2})\s+tagen\b")
_GERMAN_DAYS = ("montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag")
_DAY_NAMES = [(en.lower(), de) for en, de in zip(WEEKDAYS, _GERMAN_DAYS, strict=True)]
_WORD = re.compile(r"\w+", re.UNICODE)
# Words that say nothing about what was talked about (English and German).
_FILLER = set(
    "a an the and or of to in on at for with about from by is are was were be been it its this "
    "that these those what which who how when where why did do does we i you me my our your us "
    "he she they them his her their there here some any all everything anything something "
    "talk talked talking discuss discussed say said tell told ask asked speak spoke conversation "
    "conversations chat chatted earlier before again last yesterday today week day time "
    "der die das ein eine und oder von zu im in am an auf mit über was wir ich du mir mein "
    "haben hat hatten gestern heute woche gesagt gefragt gesprochen".split()
)
FOLLOW_UP = (
    "Here is what was said in earlier conversations kept on this computer ({where}), {about}:"
    '\n{found}\n\nTheir request was: "{request}". Answer it now from this, in a few spoken '
    "sentences, like someone who remembers: don't read it out, don't mention files or searching. "
    "If what they mean isn't there, say in one sentence that you don't remember talking about "
    "that{kept}, then help with it if you can. Don't ask to recall again."
)
MATCHED = 'the exchanges that best match "{what}"'
UNMATCHED = 'the latest ones (none uses the words "{what}", but it may be there in other words)'
LATEST = "the latest ones"
NONE_KEPT = (
    'No conversations are kept from {where}. Their request was: "{request}". Tell them in one '
    "sentence that you don't remember that conversation{kept}. Don't ask to recall again."
)


def parse_when(when: str, today: date, days: int = 7) -> tuple[date, date]:
    """The first and last day `when` means, within the days kept (nothing: all of them)."""
    oldest = today - timedelta(days=days)
    text = (when or "").strip().lower()
    dates = [date.fromisoformat(d) for d in _DATE.findall(text) if _valid(d)]
    if dates:
        first, last = min(dates), max(dates)
    elif "day before yesterday" in text or "vorgestern" in text:
        first = last = today - timedelta(days=2)
    elif any(w in text for w in ("yesterday", "gestern", "last night")):
        first = last = today - timedelta(days=1)
    elif any(w in text for w in ("today", "heute", "this morning", "tonight", "this afternoon")):
        first = last = today
    elif ago := _AGO.search(text):
        first = last = today - timedelta(days=int(ago[1] or ago[2]))
    elif "week" in text or "woche" in text:
        first, last = oldest, today - timedelta(days=1) if "last" in text else today
    else:
        day = next((i for i, names in enumerate(_DAY_NAMES) if any(n in text for n in names)), None)
        if day is not None:  # the last one before today
            first = last = today - timedelta(days=(today.weekday() - day - 1) % 7 + 1)
        else:
            first, last = oldest, today
    if last < oldest:
        return first, last  # older than what's kept: nothing is found, and Claude says why
    return max(first, oldest), min(last, today)


def _valid(text: str) -> bool:
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def describe(first: date, last: date, today: date) -> str:
    """'yesterday', 'Monday 23 November', 'from Saturday 21 November to today'."""
    one = day_label(first, today)
    if first == last:
        return one.lower() if one in ("Today", "Yesterday") else one
    two = day_label(last, today)
    return f"from {one} to {two.lower() if two in ('Today', 'Yesterday') else two}"


def words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _FILLER and len(w) > 1}


def _alike(a: str, b: str) -> bool:
    """The same word, or nearly (lamp and lamps, automata and automaton)."""
    if a == b:
        return True
    shared = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        shared += 1
    return shared >= max(4, min(len(a), len(b)) - 2)


def score(exchange: Exchange, wanted: set[str]) -> int:
    """How many of the wanted words the exchange has."""
    have = words(" ".join((exchange.you, exchange.abdoh, exchange.board, exchange.role)))
    return sum(1 for w in wanted if any(_alike(w, h) for h in have))


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def line(exchange: Exchange, today: date) -> str:
    when = f"{day_label(exchange.at.date(), today)}, {exchange.at:%H:%M}"
    if exchange.role:
        when += f", acting as {exchange.role}"
    you, abdoh = _short(exchange.you, CUT_YOU), _short(exchange.abdoh, CUT_ABDOH)
    text = f"[{when}] User: {you} | Abdoh: {abdoh}"
    if exchange.board:
        text += f" | On the board: {_short(exchange.board, CUT_BOARD)}"
    return text


def find(kept: list[Exchange], what: str, today: date, limit: int = MAX_CHARS) -> list[Exchange]:
    """The exchanges about `what` (each with the one before and after it), best first until
    `limit` characters, returned in the order they happened ([] when none uses its words).
    `what` that names nothing in particular ("everything"): the latest ones."""
    wanted = words(what)
    if not wanted:
        return latest(kept, today, limit)
    scores = [score(e, wanted) for e in kept]
    hits = sorted((i for i, s in enumerate(scores) if s), key=lambda i: (-scores[i], -i))
    chosen = []
    for i in hits:
        chosen += [j for j in (i, i - 1, i + 1) if 0 <= j < len(kept)]
    return _fit(kept, chosen, today, limit)


def latest(kept: list[Exchange], today: date, limit: int = MAX_CHARS) -> list[Exchange]:
    """The latest exchanges that fit in `limit` characters, in the order they happened."""
    return _fit(kept, list(range(len(kept) - 1, -1, -1)), today, limit)


def _fit(kept: list[Exchange], chosen: list[int], today: date, limit: int) -> list[Exchange]:
    picked: list[int] = []
    size = 0
    for i in dict.fromkeys(chosen):
        length = len(line(kept[i], today)) + 1
        if size + length > limit and picked:
            break
        picked.append(i)
        size += length
    return [kept[i] for i in sorted(picked)]


def follow_up(conversations: Conversations, what: str, when: str, request: str) -> str:
    """The message that asks Claude again, with what was found (or that nothing was)."""
    today = conversations.today()
    first, last = parse_when(when, today, conversations.days)
    where = describe(first, last, today)
    kept = conversations.exchanges(first, last)
    older = first <= conversations.oldest_kept()
    note = f" (conversations are kept for {conversations.days} days)" if older else ""
    if not kept:
        return NONE_KEPT.format(where=where, request=request, kept=note)
    found = find(kept, what, today)
    if found:
        about = MATCHED.format(what=what) if words(what) else LATEST
    else:  # not in those words: Claude reads the latest and judges
        found, about = latest(kept, today), UNMATCHED.format(what=what)
    lines = "\n".join(line(e, today) for e in found)
    return FOLLOW_UP.format(where=where, about=about, found=lines, request=request, kept=note)


def split(arg: str) -> tuple[str, str]:
    """'carbonara | 2026-11-24' -> ('carbonara', '2026-11-24')."""
    what, _, when = arg.partition("|")
    return what.strip(), when.strip()
