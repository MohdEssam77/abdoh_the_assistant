"""The role Abdoh plays right now: none, one of yours (roles.yaml), or one made up on the spot
("act as a chef"). Claude gets it with every message (`state_text`), so starting or stopping a
role never starts a new Claude conversation. A role ends when Abdoh quits."""

import logging
import re
from collections.abc import Callable

from abdoh.roles.model import RESERVED, Role, RolesFileError

log = logging.getLogger(__name__)

_ARTICLE = re.compile(r"^(?:my|a|an|the)\s+", re.IGNORECASE)
# For Claude, while a role that may use the board is on (claude/reply.py reads the markers).
BOARD = (
    " You can show things on Abdoh's board (the user sees it in Abdoh's window): code, "
    "equations, worked steps, tables, word lists, anything better seen than heard. Put it "
    "between a line [board] and a line [/board]; inside, use Markdown (headings, lists, tables, "
    "code blocks) and write math with plain symbols (x², √, ½, ×, ÷, ≤). The board is shown, "
    "never read aloud: speak the explanation and refer to the board, never read it out."
)


class Acting:
    """`roles()` lists your roles (the store's load); `on_change(role or None)` is told when a
    role starts or ends (the voice's speed, the window)."""

    def __init__(
        self,
        roles: Callable[[], list[Role]],
        on_change: Callable[[Role | None], None] = lambda role: None,
    ):
        self._roles = roles
        self._on_change = on_change
        self.current: Role | None = None

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
        log.info("Acting as %s%s", role.name, "" if role.saved else " (made up)")
        self._on_change(role)
        return role

    def stop(self) -> bool:
        """End the role. False if none was on."""
        if self.current is None:
            return False
        log.info("Stopped acting as %s", self.current.name)
        self.current = None
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
        return text
