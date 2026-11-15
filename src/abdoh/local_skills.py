"""Things Abdoh does instantly by itself, without Claude: timers, volume and media keys, locking
the computer, and opening any installed app. Your own commands in commands.yaml come first."""

import logging
import re

from abdoh.commands.actions import ActionError
from abdoh.computer import parse_duration

log = logging.getLogger(__name__)

_POLITE = re.compile(r"^(?:(?:can|could|would) you |please )|(?: please| for me)$")

_MEDIA = {
    "volume_up": r"(?:turn )?(?:the )?volume up|turn it up|louder|(?:increase|raise) the volume",
    "volume_down": r"(?:turn )?(?:the )?volume down|turn it down|quieter"
    r"|(?:decrease|lower) the volume",
    "mute": r"(?:un)?mute(?: the)?(?: sound| audio| volume)?",
    "play_pause": r"pause|play|resume|(?:pause|play|resume|stop) (?:the )?"
    r"(?:music|song|video|track)",
    "next": r"next(?: song| track| one)?|skip(?: this| it)?(?: song| track)?",
    "previous": r"previous(?: song| track)?|(?:go )?back a (?:song|track)|last (?:song|track)",
}
_MEDIA_PATTERNS = {key: re.compile(rf"(?:{pattern})") for key, pattern in _MEDIA.items()}
_CANCEL_TIMER = re.compile(r"\b(?:cancel|stop|delete|clear|remove)\b.*\btimers?\b")
_TIMER = re.compile(r"\btimers?\b")
# Ways to end the conversation after a reply: nothing to do, and nothing more to listen for.
_DONE = re.compile(
    r"(?:no |okay |ok )?(?:thanks|thank you|thanks a lot|thank you very much|thats all|thats it"
    r"|never mind|nevermind|nothing|no|nope|stop|cancel|goodbye|bye)(?: abdoh)?"
)
_LOCK = re.compile(r"lock (?:my |the )?(?:computer|pc|laptop|screen|workstation)")
_OPEN = re.compile(r"(?:open|launch|start) (?P<app>.+)")


class LocalSkills:
    def __init__(self, computer):
        self.computer = computer

    def handle(self, request: str) -> str | None:
        """The reply ("" = done quietly) if this is a local skill, or None to let Claude try.

        `request` is normalized text (lowercase, no punctuation, wake words removed).
        """
        request = _POLITE.sub("", request).strip()
        try:
            return self._handle(request)
        except ActionError as e:
            return str(e)

    def _handle(self, request: str) -> str | None:
        if _DONE.fullmatch(request):
            return ""
        if _CANCEL_TIMER.search(request):
            return self.computer.timers.cancel_all()
        if _TIMER.search(request) and parse_duration(request):
            return self.computer.timer(request)
        for key, pattern in _MEDIA_PATTERNS.items():
            if pattern.fullmatch(request):
                self.computer.media(key)
                return ""
        if _LOCK.fullmatch(request):
            self.computer.lock()
            return ""
        found = _OPEN.fullmatch(request)
        if found and self.computer.apps.find(found.group("app")):
            return f"Opening {self.computer.open_app(found.group('app'))}."
        return None
