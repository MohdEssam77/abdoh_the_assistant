"""Codoh's chats while the app runs: what the page shows, the engines, approvals.

Each chat is a list of items the page draws: the user's messages, the model's answers, tool
cards, approval cards, notes and errors. Every change bumps the chat's revision, and the page
asks for the items changed since the revision it has (`chat(id, since)`), several times a
second while a reply runs.

A chat moves to the other plan when the user picks a model of it, or by itself when Claude's
usage limit runs out and the ChatGPT plan is connected (claude.fallback): the new engine gets
a summary of the chat so far, made from the items (ABDOH_EPIC_9.md, 3.1.3).
"""

import logging
import threading
import time
from pathlib import Path

from abdoh.codoh import DEFAULT_MODE, EFFORTS, ENGINES, MODES, cards, git
from abdoh.codoh.store import FOLDER, CodohStore, new_id
from abdoh.config import Config

log = logging.getLogger(__name__)

IDLE_SECONDS = 900.0  # a chat's Claude Code process is closed after this long unused
RETRY_SECONDS = 1800.0  # Claude's limit without a reset time: try Claude again after this
MODELS_SECONDS = 600.0  # the ChatGPT plan's models are asked again after this
SUMMARY_CHARS = 12_000
TITLE_CHARS = 60
NEW_CHAT = "New chat"
ENGINE_NAMES = {"claude": "Claude", "chatgpt": "ChatGPT"}
SWITCHED = "Claude's limit is used up{until}, so your ChatGPT plan continues this chat."
HANDOFF = """(This chat started with another coding assistant, {before}. It's yours now: here is \
what happened so far, oldest first. The files on disk are as it left them.)
{lines}
(End of the summary.)

"""
NO_CLAUDE = (
    "Claude Code isn't installed. Install it in Settings → Claude, or use your ChatGPT plan."
)
NO_CHATGPT = "Your ChatGPT plan isn't connected. Connect it in Settings → Claude."
BUSY = "Codoh is still answering. Stop it first, or wait."
# Tools that ask the user something rather than for permission: never answered by the mode.
QUESTION = "AskUserQuestion"
DECISIONS = (QUESTION, "ExitPlanMode")
MODE_NAMES = {"ask": "Ask first", "auto_edit": "Auto-edit", "plan": "Plan only",
              "full": "Full access"}  # fmt: skip
# What Abdoh's Claude is told about Codoh while its page is open (ABDOH_EPIC_9.md, story 122).
BRIEF = """(Codoh, Abdoh's coding page, is open in Abdoh's window. Here is what it's doing, so \
answer questions about Codoh from this and don't ask to look at the screen for it: Abdoh's \
pictures of the screen never show Abdoh's own window. Codoh is a separate coding assistant: you \
can't control it, but you can tell the user what it's doing and what it changed.
{lines}
)
"""
BRIEF_STEPS = 8
BRIEF_TEXT = 600
BRIEF_DIFF = 1200
# What the header says while a tool runs.
DOING = {
    "read": "Reading",
    "search": "Searching",
    "list": "Looking around",
    "edit": "Editing",
    "write": "Writing",
    "command": "Running",
    "web": "Searching the web",
    "task": "Working on a part",
    "todo": "Planning",
}


# How a tool card reads in the summary for the other plan.
VERBS = {"read": "read", "search": "searched", "list": "listed", "edit": "edited",
         "write": "wrote", "command": "ran", "web": "looked up"}  # fmt: skip


def clock(epoch: float) -> str:
    from abdoh.claude.fallback import clock as fmt

    return fmt(epoch)


def summary(items: list[dict], engine: str, chars: int = SUMMARY_CHARS) -> str:
    """The chat so far in lines, for the engine that takes it over (the latest kept)."""
    lines = []
    for item in items:
        kind = item.get("kind")
        if kind == "user":
            lines.append(f"User: {item.get('text', '')}")
        elif kind == "assistant" and item.get("text"):
            text = item["text"].strip()
            lines.append(f"Assistant: {text[:1500]}{'…' if len(text) > 1500 else ''}")
        elif kind == "tool":
            verb = VERBS.get(item.get("kind_of", ""), "used")
            state = "" if item.get("ok", True) else " (it failed)"
            lines.append(f"[{verb} {item.get('title', '')}{state}]")
    text, total = [], 0
    for line in reversed(lines):
        total += len(line) + 1
        if total > chars:
            break
        text.append(line)
    return HANDOFF.format(before=ENGINE_NAMES.get(engine, engine), lines="\n".join(reversed(text)))


class Chat:
    """One chat while the app runs: its saved data, its engine, and what the page has."""

    def __init__(self, data: dict):
        self.data = data
        self.items: list[dict] = data.setdefault("items", [])
        self.by_id = {item["id"]: item for item in self.items}
        self.rev = max((item.get("rev", 0) for item in self.items), default=0)
        self.engine = None
        self.running = False
        self.status = ""
        self.started = 0.0
        self.writing: str | None = None  # the answer being written (its item's id)
        self.tools: dict[str, str] = {}  # the engine's tool id -> the card's item id
        self.lock = threading.RLock()

    def bump(self, item: dict | None = None) -> None:
        self.rev += 1
        if item is not None:
            item["rev"] = self.rev

    def add(self, kind: str, **fields) -> dict:
        item = {"id": new_id(), "kind": kind, "at": time.time(), **fields}
        self.items.append(item)
        self.by_id[item["id"]] = item
        self.bump(item)
        return item

    def summary(self) -> dict:
        return {k: self.data.get(k) for k in ("id", "title", "folder", "engine", "model", "mode",
                                               "effort", "created", "updated")}  # fmt: skip


_ACTIVE = None  # the app's Codoh (the latest made)


def brief_for_abdoh() -> str:
    """What Codoh is doing, while its page is the one Abdoh's window shows ("" otherwise)."""
    codoh = _ACTIVE
    if codoh is None or not codoh.page_open or not codoh.viewing:
        return ""
    try:
        return codoh.brief()
    except Exception:  # never in the way of an answer
        log.debug("Couldn't tell Abdoh about Codoh", exc_info=True)
        return ""


class Codoh:
    def __init__(
        self,
        cfg: Config,
        find_code=None,
        make_claude=None,
        make_chatgpt=None,
        chatgpt_ready=None,
        chatgpt_models=None,
        probe=None,
        git_module=git,
        clock_fn=time.time,
    ):
        from abdoh.claude.code import find_claude_code
        from abdoh.codoh.chatgpt import ChatGPTChat
        from abdoh.codoh.claude import ClaudeChat
        from abdoh.codoh.claude import probe as probe_claude

        self.cfg = cfg
        self.store = CodohStore(cfg.app_dir / FOLDER, clock=clock_fn)
        self._find_code = find_code or find_claude_code
        self._make_claude = make_claude or ClaudeChat
        self._make_chatgpt = make_chatgpt or ChatGPTChat
        self._chatgpt_ready = chatgpt_ready or self._plan_allowed
        self._chatgpt_models = chatgpt_models or self._ask_chatgpt_models
        self._probe = probe or probe_claude
        self._git = git_module
        self._now = clock_fn
        self._lock = threading.RLock()
        self._chats: dict[str, Chat] = {}
        self.claude_models: list[dict] = []
        self.claude_plan = ""
        self._probing = False
        self._chatgpt_list: list[dict] = []
        self._chatgpt_at = 0.0
        self._chatgpt_error = ""
        self.limited_until = 0.0  # Claude's limit is used up until then (0: it isn't)
        self.page_open = False  # the Codoh page is the one showing in Abdoh's window
        self.viewing = ""  # the chat the page shows
        global _ACTIVE
        _ACTIVE = self

    # ----- what's there -----

    def _plan_allowed(self) -> bool:
        from abdoh.claude.chatgpt import Account

        return Account.of(self.cfg).plan_usage

    def _ask_chatgpt_models(self) -> dict:
        from abdoh.claude import chatgpt

        return chatgpt.models(self.cfg)

    def claude_exe(self):
        return self._find_code(self.cfg.claude.code_path)

    def engines(self) -> dict:
        exe = self.claude_exe()
        chatgpt = self._chatgpt_ready()
        return {
            "claude": {
                "ready": bool(exe),
                "plan": self.claude_plan,
                "why": "" if exe else NO_CLAUDE,
            },
            "chatgpt": {"ready": chatgpt, "why": "" if chatgpt else NO_CHATGPT},
        }

    def default_engine(self) -> str:
        ready = self.engines()
        if ready["claude"]["ready"] and not (self.claude_limited() and ready["chatgpt"]["ready"]):
            return "claude"
        return "chatgpt" if ready["chatgpt"]["ready"] else "claude"

    def claude_limited(self) -> bool:
        if self.limited_until and self._now() >= self.limited_until:
            self.limited_until = 0.0
        return bool(self.limited_until)

    def models(self, refresh: bool = False) -> dict:
        """Both plans' models: Claude's from Claude Code (asked once in the background), the
        ChatGPT plan's from OpenAI (kept for a while)."""
        from abdoh.codoh.claude import MODELS

        self._probe_claude()
        chatgpt: list[dict] = []
        error = ""
        if self._chatgpt_ready():
            if refresh or self._now() - self._chatgpt_at > MODELS_SECONDS or not self._chatgpt_list:
                found = self._chatgpt_models()
                if found.get("ok"):
                    self._chatgpt_list = [
                        {"id": m["id"], "name": m.get("name") or m["id"], "line": ""}
                        for m in found.get("models") or []
                    ]
                    self._chatgpt_error = ""
                else:
                    self._chatgpt_error = found.get("error") or "Couldn't get the models."
                self._chatgpt_at = self._now()
            chatgpt, error = self._chatgpt_list, self._chatgpt_error
        return {
            "claude": self.claude_models or MODELS,
            "claude_plan": self.claude_plan,
            "chatgpt": chatgpt,
            "chatgpt_error": error,
        }

    def _probe_claude(self) -> None:
        if self.claude_models or self._probing:
            return
        exe = self.claude_exe()
        if not exe:
            return
        self._probing = True
        folder = self.store.root
        folder.mkdir(parents=True, exist_ok=True)

        def run() -> None:
            try:
                found = self._probe(exe, folder)
                if found and found.get("models"):
                    self.claude_models = found["models"]
                    self.claude_plan = found.get("plan") or self.claude_plan
            except Exception:
                log.debug("Codoh: couldn't ask Claude Code for its models", exc_info=True)
            finally:
                self._probing = False

        threading.Thread(target=run, name="abdoh-codoh-models", daemon=True).start()

    def state(self) -> dict:
        """Everything the page needs to draw its side: folders, chats, plans."""
        self._close_idle()
        folders = []
        for f in self.store.folders():
            path = Path(f["path"])
            folders.append({**f, "exists": path.is_dir()})
        chats = self.store.chats()
        with self._lock:
            for chat in self._chats.values():
                if chat.running:
                    for c in chats:
                        if c["id"] == chat.data["id"]:
                            c["running"] = True
        limited = self.claude_limited()
        return {
            "folders": folders,
            "chats": chats,
            "engines": self.engines(),
            "default_engine": self.default_engine(),
            "limited_until": self.limited_until if limited else 0,
            "limited_text": f"until {clock(self.limited_until)}" if limited else "",
        }

    # ----- folders -----

    def open_folder(self, path: str) -> dict:
        folder = Path(str(path or "")).expanduser()
        if not str(path or "").strip() or not folder.is_dir():
            return {"ok": False, "error": "That folder doesn't exist."}
        entry = self.store.add_folder(folder.resolve())
        return {"ok": True, "folder": entry, "git": self._git.info(folder)}

    def folder_info(self, path: str) -> dict:
        folder = Path(path)
        return {"ok": folder.is_dir(), "git": self._git.info(folder) if folder.is_dir() else None}

    def forget_folder(self, path: str) -> dict:
        self.store.forget_folder(path)
        return {"ok": True}

    def changes(self, path: str) -> dict:
        found = self._git.changes(Path(path))
        if found is None:
            return {
                "ok": False,
                "error": "This folder isn't a git repository (or git isn't installed).",
            }
        return {"ok": True, "files": found, "git": self._git.info(Path(path))}

    def diff(self, path: str, file: str) -> dict:
        return {"ok": True, "diff": self._git.diff(Path(path), file)}

    # ----- chats -----

    def new_chat(self, folder: str, engine: str = "", model: str = "", mode: str = "") -> dict:
        if not Path(folder).is_dir():
            return {"ok": False, "error": "That folder doesn't exist anymore."}
        engine = engine if engine in ENGINES else self.default_engine()
        now = self._now()
        data = {
            "id": new_id(),
            "title": NEW_CHAT,
            "folder": str(folder),
            "engine": engine,
            "model": model,
            "mode": mode if mode in MODES else DEFAULT_MODE,
            "effort": "",
            "created": now,
            "updated": now,
            "claude_session": "",
            "openai_items": [],
            "items": [],
        }
        self.store.save(data)
        self.store.add_folder(Path(folder))
        with self._lock:
            self._chats[data["id"]] = Chat(data)
        return {"ok": True, "chat": self._chats[data["id"]].summary()}

    def _chat(self, chat_id: str) -> Chat | None:
        with self._lock:
            chat = self._chats.get(chat_id)
            if chat is None:
                data = self.store.load(chat_id)
                if data is None:
                    return None
                chat = self._chats[chat_id] = Chat(data)
            return chat

    def chat(self, chat_id: str, since: int = 0) -> dict:
        """The chat's items changed since revision `since` (all of them for 0)."""
        chat = self._chat(chat_id)
        if chat is None:
            return {"ok": False, "error": "That chat is gone."}
        self.viewing = chat_id  # the page asks for the chat it shows
        with chat.lock:
            items = [i for i in chat.items if since <= 0 or i.get("rev", 0) > since]
            return {
                "ok": True,
                "chat": chat.summary(),
                "rev": chat.rev,
                "items": [dict(i) for i in items],
                "running": chat.running,
                "status": chat.status,
                "seconds": round(self._now() - chat.started, 1) if chat.running else 0,
            }

    def rename(self, chat_id: str, title: str) -> dict:
        chat = self._chat(chat_id)
        title = " ".join(str(title or "").split())[:TITLE_CHARS]
        if chat is None or not title:
            return {"ok": False}
        with chat.lock:
            chat.data["title"] = title
            self._save(chat)
        return {"ok": True}

    def delete(self, chat_id: str) -> dict:
        with self._lock:
            chat = self._chats.pop(chat_id, None)
        if chat is not None and chat.engine is not None:
            chat.engine.close()
        self.store.delete(chat_id)
        return {"ok": True}

    def _save(self, chat: Chat) -> None:
        chat.data["updated"] = self._now()
        try:
            self.store.save(chat.data)
        except OSError:
            log.exception("Codoh: couldn't save the chat")

    # ----- sending -----

    def _engine(self, chat: Chat):
        """The chat's engine, started for its plan (RuntimeError when that plan isn't
        there)."""
        data = chat.data
        kind = data["engine"]
        if chat.engine is not None and chat.engine.engine == kind:
            return chat.engine
        if chat.engine is not None:
            chat.engine.close()
        on_event = lambda event: self._on_event(chat, event)  # noqa: E731
        folder = Path(data["folder"])
        if kind == "claude":
            exe = self.claude_exe()
            if not exe:
                raise RuntimeError(NO_CLAUDE)
            chat.engine = self._make_claude(
                exe,
                folder,
                on_event,
                model=data.get("model", ""),
                mode=data.get("mode", DEFAULT_MODE),
                effort=data.get("effort", ""),
                session_id=data.get("claude_session", ""),
            )
        else:
            if not self._chatgpt_ready():
                raise RuntimeError(NO_CHATGPT)
            chat.engine = self._make_chatgpt(
                self.cfg,
                folder,
                on_event,
                model=data.get("model", ""),
                mode=data.get("mode", DEFAULT_MODE),
                effort=data.get("effort", ""),
                items=data.get("openai_items") or [],
            )
        return chat.engine

    def send(self, chat_id: str, text: str) -> dict:
        text = str(text or "").strip()
        chat = self._chat(chat_id)
        if chat is None or not text:
            return {"ok": False, "error": "Nothing to send."}
        with chat.lock:
            if chat.running:
                return {"ok": False, "error": BUSY}
            if not Path(chat.data["folder"]).is_dir():
                return {"ok": False, "error": "The chat's folder doesn't exist anymore."}
            if chat.data["engine"] == "claude" and self.claude_limited() and self._fallback():
                self._move(chat, "chatgpt", "", note=self._switched_text())
            chat.add("user", text=text)
            if chat.data.get("title") in (None, "", NEW_CHAT):
                chat.data["title"] = " ".join(text.split())[:TITLE_CHARS]
            self._save(chat)
            log.info(
                "Codoh: a request in %s with %s",
                Path(chat.data["folder"]).name,
                chat.data.get("model") or chat.data["engine"],
            )
            return self._run(chat, text)

    def _run(self, chat: Chat, text: str) -> dict:
        """Hand the message to the engine (with the summary first after a move)."""
        handoff = chat.data.pop("handoff", "")
        try:
            engine = self._engine(chat)
            chat.running, chat.status, chat.started = True, "Thinking", self._now()
            chat.writing = None
            chat.bump()
            engine.send(handoff + text if handoff else text)
        except RuntimeError as e:
            chat.running = False
            chat.status = ""
            if handoff:
                chat.data["handoff"] = handoff
            chat.add("error", text=str(e))
            self._save(chat)
            return {"ok": False, "error": str(e)}
        return {"ok": True, "rev": chat.rev}

    def stop(self, chat_id: str) -> dict:
        chat = self._chat(chat_id)
        if chat is not None and chat.running and chat.engine is not None:
            chat.status = "Stopping"
            chat.bump()
            chat.engine.interrupt()
        return {"ok": True}

    def answer(self, chat_id: str, item_id: str, decision: str, answers=None) -> dict:
        """An approval card answered: "allow", "always" (for this chat) or "deny". A question
        card: "allow" with `answers` ({question: the option picked, or the user's words}), or
        "deny" to skip it."""
        chat = self._chat(chat_id)
        if chat is None:
            return {"ok": False}
        with chat.lock:
            item = chat.by_id.get(item_id)
            if item is None or item.get("kind") != "approval" or item.get("state") != "waiting":
                return {"ok": False, "error": "That was already answered."}
            allow = decision in ("allow", "always")
            data = dict(item.get("input") or {})
            if item.get("tool") == QUESTION and allow:
                answers = {str(k): str(v) for k, v in dict(answers or {}).items() if str(v)}
                if not answers:
                    return {"ok": False, "error": "Pick an answer first."}
                data["answers"] = item["answers"] = answers
            item["state"] = "allowed" if allow else "denied"
            if decision == "always":
                item["state"] = "always"
            chat.status = "Working" if allow else "Thinking"
            chat.bump(item)
            engine = chat.engine
        if engine is not None:
            engine.answer(
                item["request_id"],
                allow,
                data=data,
                rules=item.get("suggestions") if decision == "always" else None,
                note="The user skipped the question." if item.get("tool") == QUESTION else "",
            )
        return {"ok": True}

    @staticmethod
    def _mode_allows(mode: str, tool: str) -> bool:
        """The chat's mode answers this approval by itself (Claude Code asked anyway: it
        couldn't switch to the mode, or it asks for what the mode allows)."""
        if tool in DECISIONS:
            return False
        if mode == "full":
            return True
        return mode == "auto_edit" and cards.kind_of(tool) in ("edit", "write")

    # ----- what Abdoh is told about Codoh -----

    def brief(self, chat_id: str = "") -> str:
        """What Codoh's chat (the one the page shows) is doing, for Abdoh's Claude."""
        chat = self._chat(chat_id or self.viewing)
        if chat is None:
            return ""
        with chat.lock:
            data = chat.data
            model = data.get("model") or "its default model"
            lines = [
                f'Chat: "{data.get("title", "")}" in the folder {data.get("folder", "")}, with '
                f"{ENGINE_NAMES.get(data.get('engine'), data.get('engine'))} ({model}), "
                f"mode {MODE_NAMES.get(data.get('mode'), data.get('mode'))}."
            ]
            waiting = [i for i in chat.items if i.get("kind") == "approval"
                       and i.get("state") == "waiting"]  # fmt: skip
            if waiting:
                ask = waiting[-1]
                if ask.get("tool") == QUESTION:
                    questions = (ask.get("input") or {}).get("questions") or []
                    asked = "; ".join(str(q.get("question", "")) for q in questions)
                    lines.append(f"Now: waiting for the user to answer its question: {asked}")
                else:
                    lines.append(
                        "Now: waiting for the user to allow or deny this in Codoh: "
                        f"{ask.get('title') or ask.get('tool', '')}."
                    )
                    if ask.get("diff"):
                        lines.append(f"The change it asks to make:\n{ask['diff'][:BRIEF_DIFF]}")
            elif chat.running:
                seconds = round(self._now() - chat.started)
                lines.append(f"Now: working for {seconds} s: {chat.status or 'thinking'}.")
            else:
                lines.append("Now: done, waiting for the user's next message.")
            users = [i for i in chat.items if i.get("kind") == "user"]
            if users:
                lines.append(f'The user\'s latest message to it: "{users[-1].get("text", "")}"')
            answers = [i for i in chat.items if i.get("kind") == "assistant" and i.get("text")]
            if answers:
                text = " ".join(answers[-1]["text"].split())
                cut = "…" if len(text) > BRIEF_TEXT else ""
                lines.append(f'Its latest words: "{text[:BRIEF_TEXT]}{cut}"')
            steps = [i for i in chat.items if i.get("kind") == "tool"][-BRIEF_STEPS:]
            if steps:
                done = []
                for step in steps:
                    verb = VERBS.get(step.get("kind_of", ""), "used")
                    status = step.get("status")
                    state = {
                        "failed": " (failed)",
                        "running": " (running)",
                        "waiting": " (not done yet: waiting for the user's OK)",
                        "stopped": " (stopped)",
                    }.get(status, "")
                    done.append(f"{verb} {str(step.get('title', ''))[:120]}{state}")
                lines.append("Its last steps, oldest first: " + "; ".join(done) + ".")
            folder = Path(data.get("folder", ""))
        try:
            changed = self._git.changes(folder)
        except Exception:
            changed = None
        if changed is not None:
            files = ", ".join(
                f"{c['path']} (+{c.get('added', 0)} -{c.get('removed', 0)})" for c in changed[:12]
            )
            lines.append(f"Files changed in git now: {files or 'none'}.")
        return BRIEF.format(lines="\n".join(lines))

    # ----- settings of a chat -----

    def configure(self, chat_id: str, changes: dict) -> dict:
        """Change a chat's model ("claude:opus", "chatgpt:gpt-6.2"), mode or effort."""
        chat = self._chat(chat_id)
        if chat is None:
            return {"ok": False, "error": "That chat is gone."}
        changes = changes or {}
        with chat.lock:
            data = chat.data
            if "model" in changes:
                engine, _, model = str(changes["model"] or "").partition(":")
                if engine not in ENGINES:
                    engine, model = data["engine"], str(changes["model"] or "")
                if engine != data["engine"]:
                    if chat.running:
                        return {"ok": False, "error": BUSY}
                    ready = self.engines()[engine]
                    if not ready["ready"]:
                        return {"ok": False, "error": ready["why"]}
                    self._move(chat, engine, model)
                elif model != data.get("model", ""):
                    data["model"] = model
                    if chat.engine is not None:
                        chat.engine.set_model(model)
            if changes.get("mode") in MODES:
                data["mode"] = changes["mode"]
                if chat.engine is not None:
                    chat.engine.set_mode(data["mode"])
            if "effort" in changes and (changes["effort"] in EFFORTS or changes["effort"] == ""):
                data["effort"] = changes["effort"]
                if chat.engine is not None:
                    chat.engine.set_effort(data["effort"])
            chat.bump()
            self._save(chat)
            return {"ok": True, "chat": chat.summary()}

    def _move(self, chat: Chat, engine: str, model: str, note: str = "") -> None:
        """The chat goes on with the other plan, which gets a summary of it first."""
        data = chat.data
        before = data["engine"]
        if chat.engine is not None:
            chat.engine.close()
            chat.engine = None
        if any(i.get("kind") == "user" for i in chat.items):
            data["handoff"] = summary(chat.items, before)
        data["engine"], data["model"] = engine, model
        if engine == "claude":
            data["claude_session"] = ""  # a new Claude Code session, told what happened
        else:
            data["openai_items"] = []
        chat.add(
            "note", text=note or f"Now with {ENGINE_NAMES[engine]}. It got a summary of this chat."
        )
        log.info("Codoh: a chat moved from %s to %s", before, engine)

    # ----- what the engines say -----

    def _fallback(self) -> bool:
        return bool(self.cfg.claude.fallback and self._chatgpt_ready())

    def _switched_text(self) -> str:
        until = f" until {clock(self.limited_until)}" if self.limited_until else ""
        return SWITCHED.format(until=until)

    def _on_event(self, chat: Chat, event: dict) -> None:
        kind = event.get("type")
        resend = None
        allowed = None  # an approval the chat's mode answers: (request id, input)
        with chat.lock:
            if kind == "ready":
                if event.get("models"):
                    self.claude_models = event["models"]
                self.claude_plan = event.get("plan") or self.claude_plan
                return
            if kind == "session":
                chat.data["claude_session"] = event.get("id", "")
                self._save(chat)
                return
            if kind == "items":
                chat.data["openai_items"] = event.get("items") or []
                return
            if kind == "status":
                chat.status = event.get("text") or chat.status
                chat.bump()
                return
            if kind == "text":
                item = chat.by_id.get(chat.writing or "")
                if item is None:
                    item = chat.add(
                        "assistant",
                        text="",
                        engine=chat.data["engine"],
                        model=chat.data.get("model", ""),
                    )
                    chat.writing = item["id"]
                item["text"] += event.get("delta", "")
                chat.status = "Writing"
                chat.bump(item)
                return
            if kind == "tool":
                chat.writing = None  # what's said after the tool is a new part
                found = cards.card(
                    event.get("name", ""), event.get("input") or {}, Path(chat.data["folder"])
                )
                found["kind_of"] = found.pop("kind")
                item = chat.add("tool", **found)
                chat.tools[event.get("id", "")] = item["id"]
                doing = DOING.get(item["kind_of"], "Working")
                chat.status = f"{doing} {item['title']}".strip()[:80]
                chat.bump()
                return
            if kind == "tool_result":
                item = chat.by_id.get(chat.tools.get(event.get("id", ""), ""))
                if item is not None:
                    kind_of = item.pop("kind_of", "")
                    item["kind"] = kind_of  # finish() reads the tool's kind
                    cards.finish(
                        item, event.get("ok", True), event.get("output", ""), event.get("result"),
                        Path(chat.data["folder"]),
                    )  # fmt: skip
                    item["kind_of"], item["kind"] = item["kind"], "tool"
                    chat.bump(item)
                chat.status = "Thinking"
                return
            if kind == "approval" and self._mode_allows(
                chat.data.get("mode", ""), event.get("tool", "")
            ):
                allowed = (event.get("id", ""), event.get("input") or {})
            elif kind == "approval":
                chat.writing = None
                if event.get("tool") == QUESTION:
                    found = {"kind": "question", "title": "", "detail": "", "diff": ""}
                else:
                    found = cards.card(
                        event.get("tool", ""), event.get("input") or {}, Path(chat.data["folder"])
                    )
                item = chat.add(
                    "approval",
                    request_id=event.get("id", ""),
                    tool=event.get("tool", ""),
                    kind_of=found["kind"],
                    title=found["title"],
                    detail=found["detail"],
                    diff=found["diff"],
                    description=event.get("description", ""),
                    input=event.get("input") or {},
                    suggestions=event.get("suggestions") or [],
                    state="waiting",
                )
                tool = chat.by_id.get(chat.tools.get(event.get("tool_use_id", ""), ""))
                if tool is not None:
                    tool["status"] = "waiting"
                    chat.bump(tool)
                chat.status = "Waiting for you"
                chat.bump(item)
                return
            if kind == "done":
                resend = self._done(chat, event)
        if allowed is not None and chat.engine is not None:
            chat.engine.answer(allowed[0], True, data=allowed[1])
        if resend is not None:
            with chat.lock:
                self._run(chat, resend)

    def _done(self, chat: Chat, event: dict) -> str | None:
        """The reply ended. Returns the message to send again when the chat moved to ChatGPT
        because Claude's limit ran out."""
        chat.running = False
        chat.status = ""
        chat.writing = None
        for item in chat.items:  # nothing waits anymore
            if item.get("kind") == "approval" and item.get("state") == "waiting":
                item["state"] = "expired"
                chat.bump(item)
            if item.get("kind") == "tool" and item.get("status") in ("running", "waiting"):
                item["status"] = "stopped" if event.get("stopped") else "done"
                chat.bump(item)
        if event.get("stopped"):
            chat.add("note", text="Stopped.")
        elif event.get("limit") and chat.data["engine"] == "claude" and self._fallback():
            resets = event.get("resets_at")
            self.limited_until = (
                float(resets) if resets and resets > self._now() else (self._now() + RETRY_SECONDS)
            )
            last = next((i for i in reversed(chat.items) if i.get("kind") == "user"), None)
            self._move(chat, "chatgpt", "", note=self._switched_text())
            self._save(chat)
            return last.get("text") if last else None
        elif event.get("error"):
            chat.add("error", text=event["error"])
        else:
            chat.add("done", seconds=event.get("seconds") or round(self._now() - chat.started, 1))
        chat.bump()
        self._save(chat)
        return None

    # ----- housekeeping -----

    def _close_idle(self) -> None:
        now = time.monotonic()
        with self._lock:
            chats = list(self._chats.values())
        for chat in chats:
            engine = chat.engine
            if engine is None or chat.running:
                continue
            if now - getattr(engine, "last_used", now) > IDLE_SECONDS and engine.alive():
                log.info("Codoh: closing a chat's Claude Code after a quiet while")
                engine.close()

    def close_all(self) -> None:
        with self._lock:
            chats = list(self._chats.values())
        for chat in chats:
            if chat.engine is not None:
                chat.engine.close()
