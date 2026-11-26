"""Several things in one request: "stop the music, play arabic music, then open whatsapp".

A request is split where "and", "then", "after that" or a comma joins things to do, and only
when every part is one on its own: it starts with a verb of doing ("stop", "play", "open"), or
a question, or is a bare name after "open" or "close" ("open whatsapp and spotify"). Anything
else stays one request: "play rock and roll", "what's the difference between python and java".
After a verb that takes free text ("remind me to call mom and send the email"), the rest
belongs to it, and "tell me if..." is about the step before it ("watch me fill this in and tell
me if I get it wrong" is one request).
"""

import re

from abdoh.commands.matcher import normalize

_JOINS = r"and then|and after that|after that|and also|also|then|and"
SEPARATOR = re.compile(rf"(\s*[,;.!?]+\s*(?:(?:{_JOINS})\s+)?|\s+(?:{_JOINS})\s+)", re.IGNORECASE)
DOING = frozenset(
    "play pause stop resume continue skip next previous mute unmute open close launch quit exit "
    "start turn switch set put make increase decrease raise lower dim brighten take lock "
    "minimize minimise maximize maximise show hide search google find go check enable disable "
    "change activate deactivate restart translate summarize summarise copy paste move snap "
    "volume brightness shut empty save create delete remove cancel clear run watch listen "
    "visit bring give read".split()
)
QUESTIONS = frozenset("what whats how hows when where who whos why which is are do does".split())
# Their text runs on: what follows belongs to them.
FREE_TEXT = frozenset("remind note write type dictate send tell say text message email".split())
# "... and tell me if I get it wrong", "... and let me know when it's done": about the step
# before, when that one watches or tries something ("open spotify and tell me if it's raining"
# is still two).
OBSERVING = frozenset(
    "watch check run read listen look see monitor follow observe try test".split()
)
_ABOUT_IT = re.compile(
    r"^(?:(?:please|just|also|and|then|now) )*(?:tell me|let me know|say|warn me|stop me"
    r"|correct me|show me) (?:if|whether|when|what|how|why|where|which|as soon as|once)\b"
)
# "open whatsapp and spotify": the bare name borrows the verb.
SHARED = frozenset("open close launch quit".split())
_FILLER = re.compile(
    r"^(?:(?:please|can you|could you|would you|will you|i want you to|i need you to"
    r"|go ahead and|also|and|now|just|then|uh|um|okay|ok) )+"
)


def first_word(text: str) -> str:
    words = _FILLER.sub("", normalize(text) + " ").split()
    return words[0] if words else ""


def split_steps(text: str) -> list[str]:
    """The things to do one by one, in order, or [] when `text` is one request."""
    pieces = SEPARATOR.split(text.strip())
    steps: list[str] = []
    verb = ""  # the verb of the step being built
    for i in range(0, len(pieces), 2):
        piece = pieces[i].strip()
        if not piece:
            continue
        about_it = verb in OBSERVING and _ABOUT_IT.match(normalize(piece))
        if steps and (verb in FREE_TEXT or about_it):
            steps[-1] += pieces[i - 1] + piece  # "remind me to call mom and send the email"
            continue
        word = first_word(piece)
        if word in DOING or word in QUESTIONS or word in FREE_TEXT:
            steps.append(piece)
            verb = word
        elif steps and verb in SHARED:
            steps.append(f"{verb} {piece}")  # "open whatsapp and spotify"
        else:
            return []  # not a list of things to do
    if len(steps) < 2 or not any(first_word(s) in DOING for s in steps):
        return []
    return [s.strip(" ,;.!?") for s in steps]
