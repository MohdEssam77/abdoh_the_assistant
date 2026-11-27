"""What Codoh is doing, for Abdoh's Claude when the user asks (ACTION codoh_state): every
recent chat, wherever it was started (by voice or on the page) and whatever Abdoh's window shows
(minimized, another page, the user in another app).

For each chat: where and with what, what it's doing now or waiting for (with the change it
asks to make, or its question), its own to-do list (what's done and what's left), the latest
of the conversation, its last steps and git's changed files. The latest chat gets the most room.
"""

import json
import time
from pathlib import Path

CHATS = 5  # the latest chats in the report (running or waiting ones always)
STEPS = 8
MESSAGES = (8, 3)  # the conversation's latest messages: the first chat, the others
TEXT = (1500, 500)  # letters of each of Codoh's answers: the first chat, the others
DIFF = 1000
FILES = 12

FOLLOW_UP = """Here is what Codoh, Abdoh's coding assistant, is doing: its recent chats, the \
latest first. Times are the user's local time; it's {now} now.

{chats}

The user's request was: "{request}". Answer it from this in a few spoken sentences: what Codoh is \
doing or did, what it waits for, what's left on its to-do list, or a summary, whatever they asked. \
Say it plainly, as you'd tell someone: no file paths unless they ask, no code read out. If they \
also want Codoh to do something, write the ACTION codoh lines for it. Don't ask for Codoh's state \
again."""
EMPTY = """Codoh has no chats yet. The user's request was: "{request}". Say so in one short \
sentence, and that they can start one by voice ("make a chat in my … folder and tell Codoh to …") \
or on the Codoh page. Don't ask for Codoh's state again."""

VERBS = {"read": "read", "search": "searched", "list": "listed", "edit": "edited",
         "write": "wrote", "command": "ran", "web": "looked up", "task": "delegated",
         "todo": "updated its to-do list"}  # fmt: skip
STEP_STATE = {
    "failed": " (failed)",
    "running": " (running now)",
    "waiting": " (not done yet: waiting for the user's OK)",
    "stopped": " (stopped)",
}
TODO_STATE = {"completed": "done", "in_progress": "doing now", "pending": "to do"}
MODE_NAMES = {"ask": "Ask first", "auto_edit": "Auto-edit", "plan": "Plan only",
              "full": "Full access"}  # fmt: skip


def ago(epoch: float, now: float) -> str:
    seconds = max(0, now - (now if epoch is None else epoch))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        minutes = int(seconds // 60)
        return "a minute ago" if minutes == 1 else f"{minutes} minutes ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return "an hour ago" if hours == 1 else f"{hours} hours ago"
    days = int(seconds // 86400)
    return "yesterday" if days == 1 else f"{days} days ago"


def todo_list(items: list[dict]) -> list[tuple[str, str]]:
    """Codoh's latest to-do list (Claude Code's TodoWrite): [(text, state)]."""
    for item in reversed(items):
        if item.get("kind") == "tool" and item.get("kind_of") == "todo":
            try:
                todos = json.loads(item.get("detail") or "[]")
            except ValueError:
                return []
            return [(str(t.get("text", "")), TODO_STATE.get(t.get("status"), "to do"))
                    for t in todos if isinstance(t, dict) and t.get("text")]  # fmt: skip
    return []


def _clip(text: str, chars: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= chars else text[:chars] + "…"


def chat_block(number: int, chat, codoh, now: float, first: bool) -> str:
    """One chat, for the report. `chat`: the manager's Chat (its lock is taken here)."""
    with chat.lock:
        data = chat.data
        items = list(chat.items)
        running, status, started = chat.running, chat.status, chat.started
    engine = {"claude": "Claude", "chatgpt": "ChatGPT"}.get(data.get("engine"), data.get("engine"))
    folder = Path(data.get("folder", ""))
    shown = " It's the chat open on Codoh's page." if codoh.viewing == data.get("id") else ""
    lines = [
        f'Chat {number}: "{data.get("title", "")}" in the folder {folder.name} ({folder}), with '
        f"{engine} ({data.get('model') or 'its default model'}), mode "
        f"{MODE_NAMES.get(data.get('mode'), data.get('mode'))}. Started "
        f"{ago(data.get('created', now), now)}, last active {ago(data.get('updated', now), now)}."
        + shown
    ]
    waiting = [i for i in items if i.get("kind") == "approval" and i.get("state") == "waiting"]
    if waiting:
        ask = waiting[-1]
        if ask.get("tool") == "AskUserQuestion":
            parts = []
            for q in (ask.get("input") or {}).get("questions") or []:
                labels = [str(o.get("label", "")) for o in q.get("options") or []]
                parts.append(f"{q.get('question', '')} (options: {', '.join(labels)})")
            lines.append("Now: waiting for the user to answer its question: " + "; ".join(parts))
        else:
            lines.append(
                "Now: waiting for the user to allow or deny this: "
                f"{ask.get('title') or ask.get('tool', '')}"
                + (f" ({why})" if (why := ask.get("description") or ask.get("detail")) else "")
            )
            if ask.get("diff"):
                lines.append(f"The change it asks to make:\n{ask['diff'][:DIFF]}")
    elif running:
        lines.append(f"Now: working, for {ago(started, now).replace(' ago', '')}: {status}.")
    else:
        last = next((i for i in reversed(items) if i.get("kind") in ("done", "error", "note")),
                    None)  # fmt: skip
        if last is None:
            lines.append("Now: nothing asked yet.")
        elif last["kind"] == "error":
            lines.append(f"Now: stopped with an error {ago(last.get('at', now), now)}: "
                         f"{_clip(last.get('text', ''), 300)}")  # fmt: skip
        elif last["kind"] == "note" and last.get("text") == "Stopped.":
            lines.append(f"Now: the user stopped it {ago(last.get('at', now), now)}.")
        else:
            lines.append(f"Now: finished {ago(last.get('at', now), now)}, waiting for the user's "
                         "next message.")  # fmt: skip
    todos = todo_list(items)
    if todos:
        left = sum(1 for _, state in todos if state != "done")
        lines.append(
            f"Its to-do list ({left} of {len(todos)} left): "
            + "; ".join(f"[{state}] {text}" for text, state in todos)
        )
    talk = [i for i in items if i.get("kind") in ("user", "assistant") and i.get("text")]
    talk = talk[-MESSAGES[0 if first else 1] :]
    if talk:
        said = []
        for item in talk:
            who = "User" if item["kind"] == "user" else "Codoh"
            limit = TEXT[0 if first else 1] if who == "Codoh" else 600
            said.append(f"{who}: {_clip(item['text'], limit)}")
        lines.append("The conversation, latest last:\n" + "\n".join(said))
    steps = [i for i in items if i.get("kind") == "tool"][-STEPS:]
    if steps:
        lines.append(
            "Its last steps, oldest first: "
            + "; ".join(
                f"{VERBS.get(s.get('kind_of', ''), 'used')} {_clip(s.get('title', ''), 120)}"
                f"{STEP_STATE.get(s.get('status', ''), '')}"
                for s in steps
            )
            + "."
        )
    try:
        changed = codoh._git.changes(folder) if folder.is_dir() else None
    except Exception:
        changed = None
    if changed is not None:
        files = ", ".join(
            f"{c['path']} (+{c.get('added', 0)} -{c.get('removed', 0)})" for c in changed[:FILES]
        )
        lines.append(f"Files changed in git in that folder: {files or 'none'}.")
    return "\n".join(lines)


def report(codoh, request: str, now: float | None = None) -> str:
    """Claude's follow-up: Codoh's recent chats, then what to answer."""
    from abdoh.claude.fallback import clock

    now = time.time() if now is None else now
    summaries = codoh.store.chats()
    ids = [c["id"] for c in summaries[:CHATS]]
    with codoh._lock:
        busy = [cid for cid, c in codoh._chats.items() if c.running and cid not in ids]
    chats = [c for c in (codoh._chat(cid) for cid in busy + ids) if c is not None]
    if not chats:
        return EMPTY.format(request=request)
    blocks = [chat_block(n, chat, codoh, now, n == 1) for n, chat in enumerate(chats, 1)]
    return FOLLOW_UP.format(now=clock(now), chats="\n\n".join(blocks), request=request)
