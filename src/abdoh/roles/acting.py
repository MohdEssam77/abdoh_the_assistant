"""The role Abdoh plays right now: none, one of yours (roles.yaml), or one made up on the spot
("act as a chef"). Claude gets it with every message (`state_text`), so starting or stopping a
role never starts a new Claude conversation. A role ends when Abdoh quits."""

import logging
import re
from collections.abc import Callable

from abdoh.roles.model import RESERVED, Role, RolesFileError

log = logging.getLogger(__name__)

_ARTICLE = re.compile(r"^(?:my|a|an|the)\s+", re.IGNORECASE)
# For Claude, while a role is on: Abdoh keeps listening (ACTION listen, see claude/reply.py).
LISTENING = (
    " Abdoh keeps listening while this role is on: the user needn't say the wake word, and what "
    "they say may be meant for someone else in the room. When they want Abdoh to stop listening "
    '(in any words: "you can stop listening", "I\'ll call you when I need you"), add the line '
    "ACTION listen: off (the role stays on)."
)
NOT_LISTENING = (
    " Abdoh listens only after the wake word for now. If the user wants it to keep listening "
    "again (like going on with the lesson), add the line ACTION listen: on."
)
_OFF = {"off", "no", "false", "stop", "0"}


def wants_on(value: str) -> bool:
    """ACTION listen's value: off, or (anything else) on."""
    return value.strip(" .").lower() not in _OFF


# For Claude, while a role that may use the board is on (claude/reply.py reads the markers).
BOARD = (
    " You have a board in Abdoh's window, like a teacher's whiteboard: use it for code, "
    "equations, worked steps, tables, word lists, anything better seen than heard. Write on it "
    "the way a teacher does, a little at a time: one line (or a few short lines that belong "
    "together) between a line [board] and a line [/board], then say what it means or why it's "
    "there, then the next line. Never put a whole program, proof or list of steps up at once. "
    "Abdoh writes each piece out while the user watches and says your next words once it's "
    "written. The pieces of one answer make one board, so a code block can go on across "
    "pieces: open it (```python) in the first and close it (```) in the last. Use Markdown "
    "(headings, lists, tables, code blocks) and LaTeX for math: $...$ inside a line, $$...$$ "
    "on a line of its own for a formula by itself. The board is shown, never read aloud: "
    "speak the explanation and refer to the board, never read it out."
)


class Acting:
    """`roles()` lists your roles (the store's load); `on_change(role or None)` is told when a
    role starts or ends (the voice's speed, the window). While a role is on, Abdoh keeps
    listening without the wake word until you say not to; `on_listening(on)` is told."""

    def __init__(
        self,
        roles: Callable[[], list[Role]],
        on_change: Callable[[Role | None], None] = lambda role: None,
        on_listening: Callable[[bool], None] = lambda on: None,
    ):
        self._roles = roles
        self._on_change = on_change
        self._on_listening = on_listening
        self.current: Role | None = None
        self.listening = False  # keep listening without the wake word (while a role is on)

    @property
    def keeps_listening(self) -> bool:
        return self.current is not None and self.listening

    def set_listening(self, on: bool) -> bool:
        """Keep listening without the wake word (on), or only after it. False with no role on."""
        if self.current is None:
            return False
        if on != self.listening:
            self.listening = on
            log.info("%s listening without the wake word", "Keeps" if on else "Stopped")
            self._on_listening(on)
        return True

    def roles(self) -> list[Role]:
        try:
            return self._roles()
        except RolesFileError as e:
            log.warning("Roles file error: %s", e)
            return []

    def find(self, name: str) -> Role | None:
        wanted = _ARTICLE.sub("", " ".join(name.split())).lower()
        return next((r for r in self.roles() if r.name.lower() == wanted), None)

    def start(self, what: str) -> Role | None:
        """One of your roles by name, or a role made up from this description ("a friendly
        chef"). "off" (and "" ) ends the role instead."""
        what = " ".join(what.split()).strip(" .")
        if not what or what.lower() in RESERVED:
            self.stop()
            return None
        role = self.find(what)
        if role is None:
            description = _ARTICLE.sub("", what)
            name = description[:1].upper() + description[1:60]
            role = Role(name, f"Act as {what}.", board=True, saved=False)
        self.current = role
        self.listening = True  # a lesson: no wake word needed
        log.info("Acting as %s%s", role.name, "" if role.saved else " (made up)")
        self._on_change(role)
        return role

    def stop(self) -> bool:
        """End the role. False if none was on."""
        if self.current is None:
            return False
        log.info("Stopped acting as %s", self.current.name)
        self.current = None
        self.listening = False
        self._on_change(None)
        return True

    def switch(self, what: str) -> str:
        """For ACTION role and the role action: a role, or off. Returns what was done."""
        role = self.start(what)
        return f"Acting as {role.name}." if role else "Stopped acting."

    def state_text(self, usual_sentences: int) -> str:
        """For the line Claude gets with every message ("" with no role on)."""
        role = self.current
        if role is None:
            return ""
        text = f"acting as {role.name}: {role.instructions}"
        sentences = role.sentences(usual_sentences)
        if sentences != usual_sentences:
            text += f" (answers may be up to {sentences} sentences)"
        if role.board:
            text += BOARD
        return text + (LISTENING if self.listening else NOT_LISTENING)
