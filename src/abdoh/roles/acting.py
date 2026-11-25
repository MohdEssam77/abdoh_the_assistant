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
    " While you explain on the board and the user talks with you, Abdoh keeps listening: the "
    "user needn't say the wake word, and what they say may be meant for someone else in the "
    "room. When they want Abdoh to stop listening "
    '(in any words: "you can stop listening", "I\'ll call you when I need you"), add the line '
    "ACTION listen: off (the role stays on)."
)
NOT_LISTENING = (
    " Abdoh listens only after the wake word for now. If the user wants it to keep listening "
    "again (like going on with the lesson), add the line ACTION listen: on."
)
_OFF = {"off", "no", "false", "stop", "0"}
NAME_LENGTH = 60


def _role_name(description: str) -> str:
    """A made-up role's name: its description up to the first full stop or comma
    ("theoretical computer science professor. Sharp, patient..." -> "Theoretical computer
    science professor"), cut at a word if it's still long."""
    name = re.split(r"[.,;:!?](?:\s|$)", description, maxsplit=1)[0].strip()
    if len(name) > NAME_LENGTH:
        name = name[:NAME_LENGTH].rsplit(" ", 1)[0]
    return name[:1].upper() + name[1:]


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
    "speak the explanation and refer to the board, never read it out. You can draw on it too, "
    "never in ASCII: a state machine, automaton, graph or tree in Graphviz DOT (```dot; for an "
    "automaton: rankdir=LR, doublecircle for accepting states, and an arrow from an invisible "
    "point node to the start state), a flowchart, sequence diagram, timeline or simple chart in "
    "Mermaid (```mermaid), anything else (geometry, a sketch, a function's graph) as SVG "
    "(```svg with a viewBox; shapes, paths and text only), and chemistry in LaTeX with "
    "\\ce{...}. A drawing goes in one piece of its own, opened and closed there, then you "
    "explain it. To show a real photo (a dish, a plant, an animal, a place, a tool), write a "
    "line [picture: the thing, in two to four English words, like spaghetti carbonara] on the "
    "board, or "
    "[picture: https://...] for a picture you found with web search; Abdoh finds it and shows "
    "it with its credit. Never ask for pictures of real private people. When the first "
    "line of a message says AI pictures are on, you can also ask for a picture made by AI "
    "where no real photo would do (a scene, an idea, an illustration): [picture: draw: a "
    "detailed description in English]. It costs the user a little, so only when it helps; "
    "Abdoh checks their credit and says so if it's too low. When it says AI pictures are off, "
    "draw it yourself (SVG) or show a photo, and if they ask for an AI picture, say it needs an "
    "OpenRouter key. When the user wants to keep the board (save it, as a PDF), write the line "
    "ACTION board_pdf: now (Abdoh saves it and says where); at the end of a long lesson you may "
    "offer it once."
)


class Acting:
    """`roles()` lists your roles (the store's load); `on_change(role or None)` is told when a
    role starts or ends (the voice's speed, the window). While a role is on, Abdoh keeps
    listening without the wake word in a lesson (see Daemon.keeps_listening) unless you said not
    to; `on_listening(on)` is told when you switch that."""

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
            name = _role_name(_ARTICLE.sub("", what))
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

    def state_text(self, usual_sentences: int, lessons: bool = True) -> str:
        """For the line Claude gets with every message ("" with no role on). `lessons`: Abdoh
        may keep listening in a lesson (the lesson_listen_seconds setting isn't 0)."""
        role = self.current
        if role is None:
            return ""
        text = f"acting as {role.name}: {role.instructions}"
        sentences = role.sentences(usual_sentences)
        if sentences != usual_sentences:
            text += f" (answers may be up to {sentences} sentences)"
        if role.board:
            text += BOARD
        if not lessons:  # keeping listening in lessons is off (Settings): the wake word always
            return text
        return text + (LISTENING if self.listening else NOT_LISTENING)
