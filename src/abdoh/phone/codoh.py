"""Codoh from the phone (ABDOH_EPIC_11.md, 2.5): its chats, a chat's messages and cards live,
sending it instructions, stopping it, answering what it asks, a new chat in one of its folders.

It's the app's one Codoh (codoh.manager.shared), so the phone and the window show the same
chats. What the phone gets is trimmed: it needn't load a command's 20,000 characters of output
to show its last lines. Messages sent from here are the phone's (`by_phone`): what the chat
needs and when it's done is told to the phone, not said out loud on the computer.
"""

from pathlib import Path

OUTPUT = 4000  # the end of a command's output
DIFF = 12000  # the start of a change
TEXT = 30000  # an answer or a message
CHATS = 30
NO_CODOH = "Codoh isn't available on the computer right now."
NO_FOLDER = "That folder isn't one of Codoh's (or isn't there any more)."
KEEP = {
    "user": ("text",),
    "assistant": ("text", "engine", "model"),
    "tool": ("kind_of", "title", "detail", "diff", "output", "ok", "status"),
    "approval": ("tool", "kind_of", "title", "detail", "diff", "description", "state",
                 "answers", "suggestions"),
    "note": ("text",),
    "error": ("text",),
    "done": ("seconds",),
}  # fmt: skip


def _cut(text, size: int, end: bool = False) -> str:
    text = str(text or "")
    if len(text) <= size:
        return text
    return "…" + text[-size:] if end else text[:size] + "…"


def slim(item: dict) -> dict:
    """One of a chat's items as the phone shows it."""
    kind = item.get("kind", "")
    out = {"id": item.get("id"), "kind": kind, "rev": item.get("rev", 0)}
    for name in KEEP.get(kind, ("text",)):
        if name in item:
            out[name] = item[name]
    for name in ("text", "detail", "description", "title"):
        if name in out:
            out[name] = _cut(out[name], TEXT)
    if "output" in out:
        out["output"] = _cut(out["output"], OUTPUT, end=True)
    if "diff" in out:
        out["diff"] = _cut(out["diff"], DIFF)
    if "suggestions" in out:
        out["suggestions"] = bool(out["suggestions"])  # only whether "Always" can be offered
    if kind == "approval" and item.get("tool") == "AskUserQuestion":
        questions = (item.get("input") or {}).get("questions") or []
        out["questions"] = [
            {
                "question": str(q.get("question", "")),
                "header": str(q.get("header", "")),
                "multi": bool(q.get("multiSelect")),
                "options": [
                    {"label": str(o.get("label", "")), "about": str(o.get("description", ""))}
                    for o in q.get("options") or []
                    if isinstance(o, dict)
                ],
            }
            for q in questions
            if isinstance(q, dict) and q.get("question")
        ]
    return out


def chats(state: dict) -> dict:
    """Codoh's chats (running first, then the latest) and its folders."""
    found = sorted(
        state.get("chats") or [],
        key=lambda c: (not c.get("running"), -(c.get("updated") or 0)),
    )[:CHATS]
    return {
        "chats": [
            {
                "id": c.get("id"),
                "title": c.get("title") or "New chat",
                "folder": c.get("folder", ""),
                "where": Path(str(c.get("folder", ""))).name,
                "engine": c.get("engine", ""),
                "model": c.get("model", ""),
                "updated": c.get("updated") or 0,
                "running": bool(c.get("running")),
            }
            for c in found
        ],
        "folders": [
            {"path": f.get("path", ""), "name": Path(str(f.get("path", ""))).name}
            for f in state.get("folders") or []
            if f.get("exists", True)
        ],
        "limited": state.get("limited_text", ""),
    }


def chat(codoh, chat_id: str, since: int) -> dict:
    found = codoh.chat(chat_id, since, look=False)
    if not found.get("ok"):
        return found
    return {**found, "items": [slim(i) for i in found.get("items") or []]}


def new_chat(codoh, folder: str, text: str) -> dict:
    """A new chat, only in one of the folders Codoh already knows (the phone offers those)."""
    known = {str(Path(f.get("path", ""))) for f in codoh.state().get("folders") or []}
    if not Path(str(folder or "")).is_dir() or str(Path(str(folder))) not in known:
        return {"ok": False, "error": NO_FOLDER}
    made = codoh.new_chat(str(folder))
    if not made.get("ok"):
        return made
    chat_id = made["chat"]["id"]
    if text.strip():
        sent = codoh.send(chat_id, text, by_phone=True)
        if not sent.get("ok"):
            return {**sent, "chat": chat_id}
    return {"ok": True, "chat": chat_id}
