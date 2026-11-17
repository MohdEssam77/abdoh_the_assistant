"""Built-in Claude skills that look at the screen: how to recognize them and what to ask."""

import re

TRANSLATE_PROMPT = (
    "Translate the main text visible in this screenshot into {target}. "
    "If it's long, give the gist in a few sentences."
)
SUMMARIZE_PROMPT = "Summarize the main content of this screenshot in a few spoken sentences."
# After Claude asked to look (ACTION look): the picture, and the request again (the API brain
# doesn't keep the conversation).
LOOK_FOLLOW_UP = (
    "Here is the screenshot you asked for: the screen the user is using.{window} Their request "
    'was: "{request}". Answer it now from what you see, in a few spoken sentences. Quote short '
    "pieces of text exactly when they matter. If they asked you to read something, read it as "
    "written, up to twelve sentences. Don't ask to look again."
)
LOOK_WINDOW = ' The window in front is "{title}"{program}.'


def look_follow_up(request: str, title: str = "", program: str = "") -> str:
    window = ""
    if title:
        window = LOOK_WINDOW.format(title=title, program=f" ({program})" if program else "")
    return LOOK_FOLLOW_UP.format(window=window, request=request)


_TARGET = re.compile(r"\b(?:to|into)\s+([a-z]+)\s*$")


def parse_target_language(request: str) -> str | None:
    """'translate my screen to arabic' -> 'Arabic'."""
    m = _TARGET.search(request.lower().strip())
    return m.group(1).capitalize() if m and m.group(1) != "screen" else None


def is_translate_request(words: set[str]) -> bool:
    return "translate" in words and "screen" in words


def is_summarize_request(words: set[str]) -> bool:
    return bool(words & {"summarize", "summarise", "summary"}) and "screen" in words
