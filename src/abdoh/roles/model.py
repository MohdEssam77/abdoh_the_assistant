"""What a role is ("act as my German teacher"), and reading roles.yaml.

A role is a way for Abdoh to talk: instructions Claude follows while it's on, how fast Piper
speaks, how long the answers may be, and whether Claude may put things on the board (code,
equations, steps: anything better seen than heard).
"""

from dataclasses import dataclass

SPEEDS = ("slow", "normal", "fast")
SPEED_FACTORS = {"slow": 0.8, "normal": 1.0, "fast": 1.2}  # times your own voice speed
ANSWERS = ("short", "normal", "long")
ANSWER_SENTENCES = {"normal": 5, "long": 10}  # short: your usual limit
MAX_INSTRUCTIONS = 1500
RESERVED = ("off", "normal", "none", "nothing")  # "ACTION role: off" ends a role
FIELDS = ("name", "phrases", "instructions", "speed", "answers", "board")


class RolesFileError(ValueError):
    """roles.yaml (or a role from the app) isn't valid; the message is safe to show."""


@dataclass(frozen=True)
class Role:
    name: str
    instructions: str
    phrases: tuple[str, ...] = ()
    speed: str = "normal"
    answers: str = "normal"
    board: bool = False
    saved: bool = True  # False: made up on the spot ("act as a chef"), not in roles.yaml

    def sentences(self, usual: int) -> int:
        """How many sentences an answer may have in this role."""
        return max(usual, ANSWER_SENTENCES.get(self.answers, usual))


def parse_roles(data) -> list[Role]:
    """Parsed YAML -> Roles. Raises RolesFileError."""
    if data is None:
        return []
    if not isinstance(data, list):
        raise RolesFileError("The roles file must be a list of roles.")
    roles, names = [], set()
    for i, item in enumerate(data, start=1):
        role = parse_role(item, f"role #{i}")
        if role.name.lower() in names:
            raise RolesFileError(f"There are two roles called {role.name}.")
        names.add(role.name.lower())
        roles.append(role)
    return roles


def parse_role(item, where: str = "the role") -> Role:
    if not isinstance(item, dict):
        raise RolesFileError(f"{where} must be a mapping with a name and instructions.")
    name = " ".join(str(item.get("name") or "").split())
    if not name:
        raise RolesFileError(f"{where} needs a name.")
    if name.lower() in RESERVED:
        raise RolesFileError(f"A role can't be called {name}.")
    where = f"role '{name}'"
    unknown = set(item) - set(FIELDS)
    if unknown:
        raise RolesFileError(f"{where}: unknown field '{sorted(unknown)[0]}'.")
    instructions = " ".join(str(item.get("instructions") or "").split())
    if not instructions:
        raise RolesFileError(f"{where}: say how Abdoh should act (instructions).")
    if len(instructions) > MAX_INSTRUCTIONS:
        raise RolesFileError(f"{where}: instructions can be at most {MAX_INSTRUCTIONS} characters.")
    phrases = item.get("phrases") or []
    if isinstance(phrases, str):
        phrases = [phrases]
    if not isinstance(phrases, list) or not all(isinstance(p, str) and p.strip() for p in phrases):
        raise RolesFileError(f"{where}: phrases must be a list of words.")
    speed = str(item.get("speed") or "normal")
    if speed not in SPEEDS:
        raise RolesFileError(f"{where}: speed is slow, normal or fast.")
    answers = str(item.get("answers") or "normal")
    if answers not in ANSWERS:
        raise RolesFileError(f"{where}: answers are short, normal or long.")
    board = item.get("board", False)
    if not isinstance(board, bool):
        raise RolesFileError(f"{where}: board is true or false.")
    return Role(name, instructions, tuple(p.strip() for p in phrases), speed, answers, board)


def as_form(role: Role) -> dict:
    """A role as the app's form data (and as a roles.yaml item, through store.to_item)."""
    return {
        "name": role.name,
        "phrases": list(role.phrases),
        "instructions": role.instructions,
        "speed": role.speed,
        "answers": role.answers,
        "board": role.board,
        "saved": role.saved,
    }
