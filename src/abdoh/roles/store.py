"""roles.yaml: read it, and add, change or delete roles from the app. Every change is checked
before it's written, so a mistake in the app can never break the file."""

from pathlib import Path

import yaml

from abdoh.config import write_atomic
from abdoh.roles.model import Role, RolesFileError, as_form, parse_role, parse_roles

HEADER = """\
# Your roles: make them in the Abdoh app (Act as), or here by hand.
# Say "act as my <name>" to start one, and stop it in any words ("you can stop acting").
#
# - name: German teacher
#   phrases: ["german lesson"]  # more ways to start it ("act as <name>" always works)
#   instructions: >             # how Abdoh acts while the role is on
#     You are my German teacher. I'm a beginner. Speak German slowly and simply, explain new
#     words in English, correct my mistakes kindly, and ask me to repeat.
#   speed: slow                 # slow, normal or fast: how fast Abdoh speaks
#   answers: long               # short (as usual), normal (5 sentences) or long (10)
#   board: true                 # may show code, equations and steps on the board
"""

# Roles to start from on the Act as page.
SUGGESTIONS: list[dict] = [
    {
        "name": "German teacher",
        "description": "Teaches you German slowly, in German, and corrects you kindly.",
        "phrases": ["german lesson"],
        "instructions": (
            "You are my German teacher, and I'm a beginner. Speak German slowly and simply, "
            "explain new words in English, correct my mistakes kindly, and ask me to repeat "
            "new phrases. Put new words and their meaning on the board."
        ),
        "speed": "slow",
        "answers": "long",
        "board": True,
    },
    {
        "name": "Math teacher",
        "description": "Explains step by step, and guides you to the answer.",
        "phrases": ["math lesson"],
        "instructions": (
            "You are my patient math teacher. Explain step by step and check that I follow "
            "before going on. When I show you a problem, guide me to the answer instead of just "
            "giving it. Put the worked steps on the board."
        ),
        "speed": "normal",
        "answers": "long",
        "board": True,
    },
    {
        "name": "Programming teacher",
        "description": "Explains ideas simply, and shows the code on the board.",
        "phrases": ["coding lesson"],
        "instructions": (
            "You are my programming teacher. Explain ideas simply with short examples, show "
            "the code on the board, and walk me through it line by line. Ask me small questions "
            "to check that I understood."
        ),
        "speed": "normal",
        "answers": "long",
        "board": True,
    },
]


def to_item(form) -> dict:
    """The app's form data -> a roles.yaml item. Raises RolesFileError."""
    if not isinstance(form, dict):
        raise RolesFileError("A role needs a name and instructions.")
    item: dict = {"name": " ".join(str(form.get("name") or "").split())}
    phrases = [str(p).strip() for p in form.get("phrases") or [] if str(p).strip()]
    if phrases:
        item["phrases"] = list(dict.fromkeys(phrases))
    item["instructions"] = " ".join(str(form.get("instructions") or "").split())
    for key in ("speed", "answers"):
        if form.get(key):
            item[key] = str(form[key])
    item["board"] = bool(form.get("board"))
    parse_role(item)  # raises RolesFileError with a readable message
    return item


def dump(items: list[dict]) -> str:
    body = yaml.safe_dump(items, sort_keys=False, allow_unicode=True, width=96)
    return HEADER + "\n" + (body if items else "[]\n")


class RoleStore:
    """Your roles file. All methods raise RolesFileError with a message that's safe to show."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _items(self) -> list[dict]:
        data = self._read()
        parse_roles(data)
        return data or []

    def _read(self):
        if not self.path.exists():
            return None
        try:
            return yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise RolesFileError(f"Your roles file isn't valid: {e}") from e

    def load(self) -> list[Role]:
        return parse_roles(self._read())

    def forms(self) -> list[dict]:
        return [as_form(role) for role in self.load()]

    def save(self, form, old_name: str | None = None) -> Role:
        """Add a role, or replace the one called `old_name`. Returns the saved role."""
        item = to_item(form)
        items = self._items()
        old = (old_name or item["name"]).lower()
        index = next((i for i, it in enumerate(items) if it["name"].lower() == old), None)
        clash = next(
            (i for i, it in enumerate(items) if it["name"].lower() == item["name"].lower()), None
        )
        if clash is not None and clash != index:
            raise RolesFileError(f"You already have a role called {items[clash]['name']}.")
        if index is None:
            items.append(item)
        else:
            items[index] = item
        self._write(items)
        return parse_role(item)

    def delete(self, name: str) -> None:
        self._write([it for it in self._items() if it["name"].lower() != name.lower()])

    def _write(self, items: list[dict]) -> None:
        text = dump(items)
        parse_roles(yaml.safe_load(text))  # what's written must read back
        write_atomic(self.path, text)
