"""Abdoh drives Codoh (ACTION codoh): "make a chat in my portfolio folder and tell it to add a
dark mode", "tell Codoh to run the tests too", "open the abdoh folder in Codoh", "allow it".

Claude writes one line, `ACTION codoh: <verb> | <folder> | <message>`:
  new | <folder> | <message>      a new chat in the folder (the message is optional)
  create | <full path> | <message> the same in a new folder, made first
  open | <folder>                 the folder in Codoh's list, no chat
  send | <message>                to the chat open on the page (else the latest)
  set | <model, mode or effort>   for that chat ("opus", "full access", "high")
  allow | always | deny          what that chat waits for the user to allow
  answer | <words>               the question it asked
  stop                            its reply stops

A folder is a full path, or a name as the user said it ("my portfolio", "abdoh the
assistant"), found among Codoh's folders and the folders in the usual places. Chats started or
sent to this way are the voice's: Abdoh says out loud when they need the user and when they're
done (manager.on_notice).
"""

import difflib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from abdoh.codoh import EFFORTS

log = logging.getLogger(__name__)

STOP_WORDS = {"the", "my", "a", "folder", "project", "directory", "repo", "repository", "called"}
MATCH = 0.82  # how alike a spoken name and a folder's name must be (0 to 1)
MAX_CHILDREN = 400  # folders looked at in each place
MODE_WORDS = {
    "full": ("full access", "full", "bypass", "no questions", "everything"),
    "auto_edit": ("auto edit", "auto-edit", "autoedit", "edits", "accept edits"),
    "plan": ("plan only", "plan", "planning"),
    "ask": ("ask first", "ask", "default"),
}
NO_CHAT = "There's no Codoh chat yet: say which folder it should work in."
QUEUED = "Codoh is still working on something: it gets that as soon as it's done."
NOTHING_WAITING = "Codoh isn't waiting for anything right now."
UNKNOWN = "I didn't understand what to do in Codoh."


@dataclass
class Result:
    said: str = ""  # what went wrong, to say ("" when it worked)
    chat: str = ""  # the chat to show on the page
    show: bool = False  # bring up the Codoh page


def normalize(name: str) -> str:
    words = re.sub(r"[^a-z0-9]+", " ", str(name).lower()).split()
    return "".join(w for w in words if w not in STOP_WORDS) or "".join(words)


def places(
    known: list[Path], home: Path | None = None, documents: dict | None = None
) -> list[Path]:
    """Where folders usually are: next to Codoh's folders, the home folder, Documents,
    Desktop and the usual code folders."""
    home = Path(home or Path.home())
    if documents is None:
        try:
            from abdoh.claude.code import user_folders

            documents = user_folders()
        except Exception:
            documents = {}
    found = [p.parent for p in known]
    found += [home, *(Path(documents[k]) for k in ("Documents", "Desktop") if k in documents)]
    found += [home / n for n in ("source/repos", "repos", "code", "projects", "dev", "src")]
    unique = []
    for p in found:
        if p not in unique and p.is_dir():
            unique.append(p)
    return unique


def find_folder(name: str, known: list[Path], roots: list[Path]) -> Path | None:
    """The folder the user means: a full path as it is, else the closest name among Codoh's
    folders, then among the folders in `roots`."""
    name = str(name or "").strip().strip("\"'")
    if not name:
        return None
    path = Path(name).expanduser()
    if path.is_absolute() and path.is_dir():
        return path
    wanted = normalize(name)
    best, score = None, 0.0
    candidates = [(p, 0.05) for p in known if p.is_dir()]
    for root in roots:
        try:
            children = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
        except OSError:
            continue
        candidates += [(p, 0.0) for p in children[:MAX_CHILDREN]]
    for folder, bonus in candidates:
        have = normalize(folder.name)
        if not have:
            continue
        alike = 1.0 if have == wanted else difflib.SequenceMatcher(None, wanted, have).ratio()
        if alike + bonus > score:
            best, score = folder, alike + bonus
    return best if best is not None and score >= MATCH else None


def act(codoh, arg: str, roots: list[Path] | None = None) -> Result:
    """Do what Claude's `ACTION codoh` line asks."""
    parts = [p.strip() for p in str(arg or "").split("|")]
    verb = parts[0].lower().replace(" ", "_") if parts else ""
    try:
        if verb in ("new", "create", "open"):
            return _folder_verb(codoh, verb, parts, roots)
        if verb == "send":
            return _send(codoh, "|".join(parts[1:]).strip())
        if verb == "set":
            return _set(codoh, " ".join(parts[1:]))
        if verb in ("allow", "always", "deny"):
            return _decide(codoh, verb)
        if verb == "answer":
            return _answer(codoh, "|".join(parts[1:]).strip())
        if verb == "stop":
            chat = current(codoh)
            if chat:
                codoh.stop(chat)
            return Result(chat=chat, show=bool(chat))
    except Exception:
        log.exception("Couldn't do %r in Codoh", arg)
        return Result("Something went wrong in Codoh.")
    return Result(UNKNOWN)


def current(codoh) -> str:
    """The chat the page shows, else the latest one ("" if there's none)."""
    if codoh.viewing and codoh.store.load(codoh.viewing) is not None:
        return codoh.viewing
    chats = codoh.store.chats()
    return chats[0]["id"] if chats else ""


def _folder_verb(codoh, verb: str, parts: list[str], roots) -> Result:
    name = parts[1] if len(parts) > 1 else ""
    message = "|".join(parts[2:]).strip()
    known = [Path(f["path"]) for f in codoh.store.folders()]
    if verb == "create":
        folder = Path(name).expanduser()
        if not folder.is_absolute() or not folder.parent.is_dir():
            return Result(f"I need the full path of the new folder, and {name} isn't one.")
        folder.mkdir(exist_ok=True)
        log.info("Codoh: made the folder %s", folder)
    else:
        folder = find_folder(name, known, places(known) if roots is None else roots)
        if folder is None:
            return Result(f"I couldn't find a folder called {name}. Say where it is.")
    opened = codoh.open_folder(str(folder))
    if not opened.get("ok"):
        return Result(opened.get("error") or "Codoh couldn't open that folder.")
    if verb == "open":
        log.info("Codoh: opened the folder %s by voice", folder)
        return Result(show=True)
    made = codoh.new_chat(str(folder))
    if not made.get("ok"):
        return Result(made.get("error") or "Codoh couldn't start a chat there.")
    chat = made["chat"]["id"]
    codoh.viewing = chat
    log.info("Codoh: a new chat in %s by voice", folder)
    if message:
        return _send(codoh, message, chat)
    return Result(chat=chat, show=True)


def _send(codoh, message: str, chat: str = "") -> Result:
    chat = chat or current(codoh)
    if not chat:
        return Result(NO_CHAT)
    if not message:
        return Result(chat=chat, show=True)
    sent = codoh.send(chat, message, by_voice=True)
    if not sent.get("ok"):
        return Result(sent.get("error") or "Codoh couldn't take that.", chat=chat, show=True)
    if sent.get("queued"):
        return Result(QUEUED, chat=chat, show=True)
    return Result(chat=chat, show=True)


def _set(codoh, words: str) -> Result:
    chat = current(codoh)
    if not chat:
        return Result(NO_CHAT)
    said = " ".join(words.lower().replace("-", " ").split())
    changes: dict = {}
    for mode, names in MODE_WORDS.items():
        if any(re.search(rf"\b{re.escape(n.replace('-', ' '))}\b", said) for n in names):
            changes["mode"] = mode
            break
    for effort in EFFORTS:
        if re.search(rf"\b{effort}\b( effort)?", said) and "mode" not in changes:
            changes["effort"] = effort
    model = _model(codoh, said)
    if model:
        changes["model"] = model
    if not changes:
        return Result(f"Codoh has no model, mode or effort called {words}.")
    done = codoh.configure(chat, changes)
    if not done.get("ok"):
        return Result(done.get("error") or "Codoh couldn't change that.", chat=chat, show=True)
    return Result(chat=chat, show=True)


def _model(codoh, said: str) -> str:
    """ "opus" -> "claude:opus"; "chatgpt" -> "chatgpt:" (its default); "" if none named."""
    from abdoh.codoh.claude import MODELS

    for m in codoh.claude_models or MODELS:
        names = {str(m.get("id", "")).lower(), str(m.get("name", "")).lower()}
        if any(n and n != "default" and re.search(rf"\b{re.escape(n)}\b", said) for n in names):
            return f"claude:{m['id']}"
    for m in getattr(codoh, "_chatgpt_list", []) or []:
        if str(m.get("id", "")).lower() in said:
            return f"chatgpt:{m['id']}"
    if re.search(r"\b(chat ?gpt|openai|codex)\b", said):
        return "chatgpt:"
    if re.search(r"\bclaude\b", said):
        return "claude:"
    return ""


def _waiting(codoh, chat: str) -> dict | None:
    """What the chat waits for the user to allow or answer. Read directly: codoh.chat() is the
    page asking, and would count as the user looking at the chat."""
    found = codoh._chat(chat)
    if found is None:
        return None
    with found.lock:
        waiting = [dict(i) for i in found.items if i.get("kind") == "approval"
                   and i.get("state") == "waiting"]  # fmt: skip
    return waiting[-1] if waiting else None


def _decide(codoh, decision: str) -> Result:
    chat = current(codoh)
    item = _waiting(codoh, chat) if chat else None
    if item is None:
        return Result(NOTHING_WAITING)
    if item.get("tool") == "AskUserQuestion":
        return Result("Codoh asked a question: say the answer.", chat=chat, show=True)
    done = codoh.answer(chat, item["id"], decision)
    return Result("" if done.get("ok") else done.get("error", ""), chat=chat, show=True)


def _answer(codoh, words: str) -> Result:
    chat = current(codoh)
    item = _waiting(codoh, chat) if chat else None
    if item is None:
        return Result(NOTHING_WAITING)
    if item.get("tool") != "AskUserQuestion":  # "yes" to an approval
        yes = re.match(r"^(yes|yeah|ok|okay|sure|allow|go ahead|do it)\b", words.lower())
        return _decide(codoh, "allow" if yes else "deny")
    questions = (item.get("input") or {}).get("questions") or []
    answers = {}
    for q in questions:
        labels = [str(o.get("label", "")) for o in q.get("options") or []]
        picked = [lab for lab in labels if lab and lab.lower() in words.lower()]
        answers[q.get("question", "")] = ", ".join(picked) if picked else words
    done = codoh.answer(chat, item["id"], "allow", answers)
    return Result("" if done.get("ok") else done.get("error", ""), chat=chat, show=True)


def notice(event: str, chat_title: str, item: dict | None = None, text: str = "") -> str:
    """What Abdoh says about a chat the voice started, when it needs the user or is done."""
    if event == "question":
        questions = (item or {}).get("input", {}).get("questions") or []
        if not questions:
            return "Codoh has a question for you."
        q = questions[0]
        labels = [str(o.get("label", "")) for o in q.get("options") or [] if o.get("label")]
        options = f" {', '.join(labels[:-1])} or {labels[-1]}?" if len(labels) > 1 else ""
        return f"Codoh asks: {q.get('question', '')}{options}"
    if event == "approval":
        item = item or {}
        kind = item.get("kind_of", "")
        what = (
            f"change {Path(item.get('title', '')).name}" if kind == "edit"
            else f"create {Path(item.get('title', '')).name}" if kind == "write"
            else "run a command: "
            + (item.get("description") or item.get("detail") or _short(item.get("title", "")))
            if kind == "command"
            else f"use {item.get('tool', 'a tool')}"
        )  # fmt: skip
        return f"Codoh wants to {what}. Allow it?"
    if event == "done":
        first = re.split(r"(?<=[.!?])\s", " ".join(str(text or "").split()), maxsplit=1)[0]
        first = re.sub(r"[*`_#]", "", first)[:220]
        return f"Codoh is done: {first}" if first else "Codoh is done."
    if event == "error":
        return f"Codoh stopped: {text}"
    return ""


# What a silent ACTION codoh reads as in the window ("Done: started a Codoh chat; told Codoh.").
DONE = {
    "new": "started a Codoh chat",
    "create": "made the folder and a Codoh chat",
    "open": "opened the folder in Codoh",
    "send": "told Codoh",
    "set": "changed Codoh's settings",
    "allow": "allowed it in Codoh",
    "always": "allowed it in Codoh for this chat",
    "deny": "said no to Codoh",
    "answer": "answered Codoh",
    "stop": "stopped Codoh",
}


def done_words(arg: str) -> str:
    verb = str(arg or "").split("|")[0].strip().lower()
    return DONE.get(verb, "Codoh")


def _short(command: str) -> str:
    words = str(command).split()
    return " ".join(words[:4]) + (" …" if len(words) > 4 else "")
