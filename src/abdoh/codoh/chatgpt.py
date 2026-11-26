"""A Codoh chat run by the user's ChatGPT plan, with Codoh's own tools.

Each request goes to the plan's Responses API (story 109's sign-in and tokens) with Codoh's
tools as functions. When the answer calls tools, Codoh runs them in the project folder (asking
first when the mode says so), sends their output back, and asks again, until an answer calls
none (at most MAX_ROUNDS times a request). `store: false`: OpenAI keeps nothing, so the chat's
items (messages, calls, their output, and the model's encrypted reasoning) are kept here and
sent each time; the manager saves them with the chat. Not tried with a real ChatGPT account.

Events for the manager: the same as codoh/claude.py, plus items {items} after each round.
"""

import json
import logging
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from abdoh.claude.brain import BrainError
from abdoh.codoh import cards
from abdoh.codoh.tools import (
    KIND,
    READ_ONLY_TOOLS,
    TOOLS,
    ToolError,
    Workspace,
    command_prefix,
)

log = logging.getLogger(__name__)

_EXIT = re.compile(r"\(exit code (-?\d+)\)\s*$")
MAX_ROUNDS = 40
KEEP_ITEMS = 160  # of the chat, sent and saved (cut at one of the user's messages)
INSTRUCTIONS = """You are Codoh, a coding assistant working in the folder {folder} on the user's \
{platform} computer. Today is {date}. Use the tools to read, search and change files and to run \
{shell} commands there; never work outside it. Read before you change; keep changes small and \
in the project's style; run the project's tests when there are any. When you're done, say \
briefly what you did. Answer in the user's language, in Markdown.{plan}"""
PLAN_ONLY = """

You are in plan mode: don't change anything and don't run commands. Read what you need, then \
propose a plan as a short numbered list."""
OFF = "Your ChatGPT plan isn't connected. Connect it in Settings → Claude → Continue with ChatGPT."
TOO_MANY = "I stopped after {n} steps. Say “go on” to continue."
EFFORTS = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}


def instructions(folder: Path, mode: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    windows = sys.platform == "win32"
    return INSTRUCTIONS.format(
        folder=folder,
        platform="Windows" if windows else "Mac" if sys.platform == "darwin" else "Linux",
        date=f"{now:%A}, {now:%B} {now.day}, {now.year}",
        shell="PowerShell" if windows else "bash",
        plan=PLAN_ONLY if mode == "plan" else "",
    )


def clean(item: dict) -> dict | None:
    """An output item as it can go back in: only what the API takes as input."""
    kind = item.get("type")
    if kind == "message":
        texts = [
            {"type": "output_text", "text": c.get("text", "")}
            for c in item.get("content") or []
            if isinstance(c, dict) and c.get("type") == "output_text"
        ]
        return {"type": "message", "role": "assistant", "content": texts} if texts else None
    if kind == "function_call":
        return {
            "type": "function_call",
            "call_id": item.get("call_id", ""),
            "name": item.get("name", ""),
            "arguments": item.get("arguments", "") or "{}",
        }
    if kind == "reasoning" and item.get("encrypted_content"):
        kept = {"type": "reasoning", "summary": item.get("summary") or []}
        kept["encrypted_content"] = item["encrypted_content"]
        if item.get("id"):
            kept["id"] = item["id"]
        return kept
    return None


def trimmed(items: list[dict], keep: int = KEEP_ITEMS) -> list[dict]:
    """The latest `keep` items or so, starting at one of the user's messages (so no call is
    left without its output)."""
    if len(items) <= keep:
        return items
    for i in range(len(items) - keep, len(items)):
        if items[i].get("type") == "message" and items[i].get("role") == "user":
            return items[i:]
    return items[-keep:]


class ChatGPTChat:
    """One chat on the ChatGPT plan. Each message runs on a thread of its own."""

    engine = "chatgpt"

    def __init__(
        self,
        cfg,
        folder: Path,
        on_event: Callable[[dict], None],
        model: str = "",
        mode: str = "ask",
        effort: str = "",
        items: list[dict] | None = None,
        session=None,
        http=None,
        run=subprocess.run,
    ):
        from abdoh.claude.chatgpt import Account, Session

        self.cfg = cfg
        self.folder = Path(folder)
        self.on_event = on_event
        self.model = model
        self.mode = mode
        self.effort = effort
        self.items: list[dict] = list(items or [])
        self.account = session.account if session is not None else Account.of(cfg)
        self.session = session or Session(self.account, http)
        self._http = http
        self.workspace = Workspace(folder, run=run)
        self.busy = False
        self._stop = threading.Event()
        self._pending: dict[str, dict] = {}  # approvals waiting: id -> {event, allow, ...}
        self._numbers = 0
        self._response = None  # the HTTP response being read (closed by Stop)
        self.auto_edits = False  # "allow for this chat" on a change
        self.allowed_commands: set[str] = set()  # ... on a command (its first words)
        self.session_id = ""  # not used: the items are the chat
        self.last_used = time.monotonic()

    def alive(self) -> bool:
        return self.busy

    # ----- what the user does -----

    def send(self, text: str) -> None:
        if self.busy:
            raise RuntimeError("Codoh is still answering.")
        self.busy = True
        self._stop.clear()
        self.last_used = time.monotonic()
        self.items.append(
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}
        )
        threading.Thread(target=self._run, name="abdoh-codoh-chatgpt", daemon=True).start()

    def interrupt(self) -> None:
        if not self.busy:
            return
        self._stop.set()
        for waiting in list(self._pending.values()):
            waiting["allow"] = False
            waiting["event"].set()
        response = self._response
        if response is not None:
            try:
                response.close()
            except Exception:  # noqa: S110 - it's being stopped anyway
                pass

    def answer(self, request_id: str, allow: bool, data=None, rules=None, note: str = ""):
        waiting = self._pending.get(request_id)
        if waiting is None:
            return
        if allow and rules:
            for rule in rules:
                if rule.get("kind") == "edits":
                    self.auto_edits = True
                elif rule.get("kind") == "command" and rule.get("prefix"):
                    self.allowed_commands.add(rule["prefix"])
        waiting["allow"] = bool(allow)
        waiting["event"].set()

    def set_model(self, model: str) -> None:
        self.model = model

    def set_mode(self, mode: str) -> None:
        self.mode = mode

    def set_effort(self, effort: str) -> None:
        self.effort = effort

    def close(self) -> None:
        self.interrupt()

    # ----- the loop -----

    def _emit(self, event: dict) -> None:
        try:
            self.on_event(event)
        except Exception:
            log.exception("Codoh: couldn't handle %s", event.get("type"))

    def _run(self) -> None:
        started = time.monotonic()
        error = None
        try:
            if not self.account.plan_usage:
                raise BrainError(OFF)
            for _ in range(MAX_ROUNDS):
                if self._stop.is_set():
                    break
                output = self._respond()
                self.items.extend(i for i in (clean(o) for o in output) if i is not None)
                self._emit({"type": "items", "items": trimmed(self.items)})
                calls = [o for o in output if o.get("type") == "function_call"]
                if not calls or self._stop.is_set():
                    break
                for call in calls:
                    result = self._call(call)
                    self.items.append(
                        {
                            "type": "function_call_output",
                            "call_id": call.get("call_id", ""),
                            "output": result,
                        }
                    )
                self._emit({"type": "items", "items": trimmed(self.items)})
            else:
                self._emit({"type": "text", "delta": "\n\n" + TOO_MANY.format(n=MAX_ROUNDS)})
        except BrainError as e:
            if not self._stop.is_set():
                error = str(e)
        except Exception as e:
            if not self._stop.is_set():
                log.exception("Codoh: the ChatGPT chat failed")
                error = f"ChatGPT couldn't answer: {e}"
        finally:
            self._response = None
            self.busy = False
            self.last_used = time.monotonic()
        stopped = self._stop.is_set()
        self._emit(
            {
                "type": "done",
                "ok": error is None,
                "error": error,
                "limit": False,
                "resets_at": None,
                "stopped": stopped,
                "seconds": round(time.monotonic() - started, 1),
            }
        )

    def _model(self) -> str:
        if self.model:
            return self.model
        chosen = self.cfg.claude.chatgpt_model.strip()
        if chosen:
            return chosen
        models = self.session.models()
        if not models:
            raise BrainError("Your ChatGPT plan has no models Codoh can use.")
        self.model = models[0]["id"]
        return self.model

    def body(self, reasoning: bool = True) -> dict:
        body = {
            "model": self._model(),
            "instructions": instructions(self.folder, self.mode),
            "input": list(trimmed(self.items)),  # as it is now (the chat goes on)
            "tools": READ_ONLY_TOOLS if self.mode == "plan" else TOOLS,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "stream": True,
            "store": False,
        }
        if reasoning:
            body["include"] = ["reasoning.encrypted_content"]
            if self.effort in EFFORTS:
                body["reasoning"] = {"effort": EFFORTS[self.effort]}
        return body

    def _client(self):
        if self._http is None:
            from abdoh.claude.chatgpt import _http

            self._http = _http()
        return self._http

    def _respond(self) -> list[dict]:
        """One request to the Responses API: its text is streamed out; returns the output
        items. Raises BrainError."""
        import httpx

        from abdoh.claude.chatgpt import API, UNREACHABLE, _body, problem

        body = self.body()
        for attempt in (1, 2, 3):
            token = self.session.access_token(force=attempt == 2)
            headers = {"Authorization": f"Bearer {token}"}
            try:
                with self._client().stream(
                    "POST", f"{API}/responses", json=body, headers=headers
                ) as r:
                    if r.status_code == 401 and attempt == 1:
                        r.read()
                        continue
                    if r.status_code == 400 and "include" in body:
                        r.read()
                        if "reasoning" in str(_body(r)).lower():  # a model without it
                            body = self.body(reasoning=False)
                            continue
                        raise BrainError(problem(r.status_code, _body(r), body["model"]))
                    if r.status_code != 200:
                        r.read()
                        raise BrainError(problem(r.status_code, _body(r), body["model"]))
                    self._response = r
                    return self._events(r.iter_lines(), body["model"])
            except httpx.HTTPError as e:
                if self._stop.is_set():
                    return []
                log.error("Codoh: the ChatGPT request failed: %s", e)
                raise BrainError(UNREACHABLE) from e
            finally:
                self._response = None
        raise BrainError(UNREACHABLE)

    def _events(self, lines, model: str) -> list[dict]:
        from abdoh.claude.chatgpt import CUT_OFF, INCOMPLETE, problem

        done: list[dict] = []
        for line in lines:
            if self._stop.is_set():
                return done
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[5:].strip())
            except ValueError:
                continue
            kind = event.get("type", "")
            if kind == "response.output_text.delta" and event.get("delta"):
                self._emit({"type": "text", "delta": event["delta"]})
            elif kind == "response.reasoning_summary_text.delta":
                self._emit({"type": "status", "text": "Thinking"})
            elif kind == "response.output_item.done":
                item = event.get("item") or {}
                done.append(item)
            elif kind == "response.completed":
                output = (event.get("response") or {}).get("output")
                return output if isinstance(output, list) and output else done
            elif kind == "response.failed":
                error = (event.get("response") or {}).get("error") or {}
                raise BrainError(problem(0, {"error": error}, model))
            elif kind == "response.incomplete":
                raise BrainError(INCOMPLETE)
            elif kind == "error":
                raise BrainError(problem(0, {"error": event.get("error") or event}, model))
        if self._stop.is_set():
            return done
        raise BrainError(CUT_OFF)

    # ----- tools -----

    def _needs_asking(self, name: str, args: dict) -> bool:
        kind = KIND.get(name, "command")
        if self.mode == "full" or kind == "read":
            return False
        if kind == "edit":
            return self.mode == "ask" and not self.auto_edits
        return command_prefix(args.get("command", "")) not in self.allowed_commands

    def _call(self, call: dict) -> str:
        """Run one function call (asking first when the mode says so). Returns its output."""
        name = call.get("name", "")
        call_id = call.get("call_id", "") or f"call-{self._numbers}"
        try:
            args = json.loads(call.get("arguments") or "{}")
            if not isinstance(args, dict):
                raise ValueError("not an object")
        except ValueError:
            return "The arguments weren't valid JSON."
        self._emit({"type": "tool", "id": call_id, "name": name, "input": args})
        if self.mode == "plan" and KIND.get(name) != "read":
            self._emit({"type": "tool_result", "id": call_id, "ok": False, "output": "Plan mode"})
            return "Plan mode: nothing may be changed or run. Propose it in your plan instead."
        if self._needs_asking(name, args) and not self._ask(name, args, call_id):
            self._emit({"type": "tool_result", "id": call_id, "ok": False, "output": "Denied"})
            return "The user said no. Don't try it another way; ask them what they'd like."
        before = None
        if name in ("write_file", "edit_file"):
            try:
                before = self.workspace.current(args.get("path", ""))
            except ToolError:
                before = None
        try:
            output = self.workspace.call(name, args)
            ok = True
        except ToolError as e:
            output, ok = str(e), False
        result = None
        if ok and before is not None:
            path = str(args.get("path", ""))
            try:
                after = self.workspace.current(path)
                result = {"diff": cards.unified(before, after, path.replace("\\", "/"))}
            except ToolError:
                result = None
        if ok and name == "run_command":
            code = _EXIT.search(output)
            ok = code is None or code.group(1) == "0"
        self._emit(
            {"type": "tool_result", "id": call_id, "ok": ok, "output": output, "result": result}
        )
        return output

    def _ask(self, name: str, args: dict, call_id: str) -> bool:
        """An approval card: wait for the user (or Stop). True if allowed."""
        self._numbers += 1
        request_id = f"ask-{self._numbers}"
        kind = KIND.get(name, "command")
        if kind == "edit":
            rules = [{"type": "codoh", "kind": "edits", "label": "Allow changes in this chat"}]
            description = f"Change {args.get('path', '')}"
        else:
            prefix = command_prefix(args.get("command", ""))
            rules = [{"type": "codoh", "kind": "command", "prefix": prefix,
                      "label": f"Allow “{prefix}” in this chat"}]  # fmt: skip
            description = "Run a command"
        waiting = {"event": threading.Event(), "allow": False}
        self._pending[request_id] = waiting
        self._emit(
            {
                "type": "approval",
                "id": request_id,
                "tool": name,
                "input": args,
                "description": description,
                "suggestions": rules,
                "tool_use_id": call_id,
            }
        )
        while not waiting["event"].wait(0.2):
            if self._stop.is_set():
                break
        self._pending.pop(request_id, None)
        return bool(waiting["allow"]) and not self._stop.is_set()
