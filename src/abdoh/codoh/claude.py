"""A Codoh chat run by Claude Code, paid by the user's Claude plan.

One `claude -p` process per chat, started in the project folder as plain Claude Code: its own
coding prompt and tools, the user's settings and CLAUDE.md, nothing of Abdoh's. Requests go in on
stdin as stream-json lines; what Claude Code does comes out as events. Before a tool that needs
permission runs, Claude Code asks Codoh (`--permission-prompts host --permission-prompt-tool
stdio`, after an `initialize` request), and Codoh shows an approval card. The model and the
permission mode change mid-chat (`set_model`, `set_permission_mode`); a chat comes back after a
restart with `--resume`. Checked with Claude Code 2.1.332 (ABDOH_EPIC_9.md, section 2).

Events for the manager (`on_event(dict)`):
  ready {models, account}; session {id}; status {text}; text {delta}; tool {id, name, input};
  tool_result {id, ok, output, result}; approval {id, tool, input, description, suggestions};
  done {ok, error, limit, resets_at, stopped, cost, seconds}
"""

import json
import logging
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from abdoh.claude.code import NO_WINDOW, child_env, error_message, limit_message
from abdoh.codoh.cards import text_of

log = logging.getLogger(__name__)

# Codoh's modes as Claude Code's permission modes.
PERMISSION_MODES = {
    "ask": "default",
    "auto_edit": "acceptEdits",
    "plan": "plan",
    "full": "bypassPermissions",
}
# Claude's models when Claude Code hasn't said yet (its initialize answer replaces them).
MODELS = [
    {"id": "default", "name": "Default", "line": "Your Claude Code default model"},
    {"id": "opus", "name": "Opus", "line": "For complex work and everyday tasks"},
    {"id": "sonnet", "name": "Sonnet", "line": "Most efficient for simpler tasks"},
    {"id": "haiku", "name": "Haiku", "line": "Fastest for quick answers"},
]
START_FAILED = "Codoh couldn't start Claude Code."
DIED = "Claude Code stopped unexpectedly."


def models_from(init: dict) -> list[dict]:
    """The plan's models from Claude Code's initialize answer."""
    found = []
    for m in init.get("models") or []:
        if not isinstance(m, dict) or not m.get("value"):
            continue
        found.append(
            {
                "id": str(m["value"]),
                "name": str(m.get("displayName") or m["value"]),
                "line": str(m.get("description") or ""),
                "efforts": [str(e) for e in m.get("supportedEffortLevels") or []],
            }
        )
    return found


def plan_name(init: dict) -> str:
    account = init.get("account") or {}
    return str(account.get("subscriptionType") or "")


class ClaudeChat:
    """One chat's Claude Code process (started when the first message is sent)."""

    engine = "claude"

    def __init__(
        self,
        exe: Path,
        folder: Path,
        on_event: Callable[[dict], None],
        model: str = "",
        mode: str = "ask",
        effort: str = "",
        session_id: str = "",
        popen=subprocess.Popen,
    ):
        self.exe = Path(exe)
        self.folder = Path(folder)
        self.on_event = on_event
        self.model = model
        self.mode = mode
        self.effort = effort
        self.session_id = session_id
        self._popen = popen
        self._proc = None
        self._stderr = None
        self._lock = threading.Lock()
        self._numbers = 0
        self.busy = False  # a reply is running
        self._stopping = False  # Stop was pressed during this reply
        self._streamed: set[str] = set()  # messages whose text came as deltas
        self._started_at = 0.0
        self.last_used = time.monotonic()

    # ----- the process -----

    def command(self) -> list[str]:
        args = [
            str(self.exe),
            "-p",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--permission-prompts",
            "host",
            "--permission-prompt-tool",
            "stdio",
            "--permission-mode",
            PERMISSION_MODES.get(self.mode, "default"),
        ]
        if self.model and self.model != "default":
            args += ["--model", self.model]
        if self.effort:
            args += ["--effort", self.effort]
        if self.session_id:
            args += ["--resume", self.session_id]
        return args

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _start(self) -> None:
        self._stderr = tempfile.TemporaryFile()
        try:
            self._proc = self._popen(
                self.command(),
                cwd=self.folder,
                env=child_env(),  # no API key: the plan pays
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=NO_WINDOW,
            )
        except OSError as e:
            log.error("Codoh couldn't start Claude Code (%s): %s", self.exe, e)
            self._proc = None
            raise RuntimeError(START_FAILED) from e
        log.info("Codoh: Claude Code started in %s", self.folder)
        proc = self._proc
        threading.Thread(
            target=self._read, args=(proc,), name="abdoh-codoh-claude", daemon=True
        ).start()
        self._control({"subtype": "initialize", "hooks": None})

    def _write(self, message: dict) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise OSError("Claude Code isn't running")
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()

    def _control(self, request: dict) -> str:
        self._numbers += 1
        request_id = f"codoh-{self._numbers}"
        self._write({"type": "control_request", "request_id": request_id, "request": request})
        return request_id

    # ----- what the user does -----

    def send(self, text: str) -> None:
        """A message from the user: starts the process if needed. Raises RuntimeError."""
        with self._lock:
            if not self.alive():
                self._start()
            self.busy = True
            self._stopping = False
            self._started_at = time.monotonic()
            self.last_used = time.monotonic()
            message = {"type": "user", "message": {"role": "user", "content": text}}
            try:
                self._write(message)
            except (OSError, ValueError) as e:
                self.busy = False
                raise RuntimeError(DIED) from e

    def interrupt(self) -> None:
        """Stop the reply that's running (the chat goes on)."""
        with self._lock:
            if not self.busy or not self.alive():
                return
            self._stopping = True
            try:
                self._control({"subtype": "interrupt"})
            except (OSError, ValueError):
                pass

    def answer(self, request_id: str, allow: bool, data=None, rules=None, note: str = ""):
        """The user's answer to an approval card. `rules`: Claude Code's own suggestions to
        allow it for the rest of the chat (kept for this session only, never saved)."""
        if allow:
            response = {"behavior": "allow", "updatedInput": data or {}}
            if rules:
                response["updatedPermissions"] = [
                    {**s, "destination": "session"} for s in rules if isinstance(s, dict)
                ]
        else:
            response = {"behavior": "deny", "message": note or "The user said no."}
        message = {
            "type": "control_response",
            "response": {"subtype": "success", "request_id": request_id, "response": response},
        }
        with self._lock:
            try:
                self._write(message)
            except (OSError, ValueError):
                log.info("Codoh: Claude Code was gone before the answer")

    def set_model(self, model: str) -> None:
        self.model = model
        self._change({"subtype": "set_model", "model": model or "default"})

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._change({"subtype": "set_permission_mode", "mode": PERMISSION_MODES.get(mode)})

    def set_effort(self, effort: str) -> None:
        """Claude Code takes the effort when it starts: the next message starts it afresh
        (the chat goes on with --resume)."""
        self.effort = effort
        if not self.busy:
            self.close()

    def _change(self, request: dict) -> None:
        with self._lock:
            if self.alive():
                try:
                    self._control(request)
                except (OSError, ValueError):
                    pass

    def close(self) -> None:
        with self._lock:
            proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
        except Exception:
            log.debug("Codoh: couldn't stop Claude Code cleanly", exc_info=True)
        for stream in (proc.stdin, proc.stdout, self._stderr):
            try:
                if stream is not None:
                    stream.close()
            except Exception:  # noqa: S110 - already gone
                pass

    # ----- what Claude Code says -----

    def _emit(self, event: dict) -> None:
        try:
            self.on_event(event)
        except Exception:
            log.exception("Codoh: couldn't handle %s", event.get("type"))

    def _read(self, proc) -> None:
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._handle(event)
        except (OSError, ValueError):
            pass
        if self.busy:  # it ended in the middle of a reply
            self.busy = False
            detail = self._error_text(proc)
            stopped = self._stopping
            if detail:
                log.warning("Codoh: Claude Code ended: %s", detail[-300:])
            message = error_message(detail) if detail else DIED
            limit = "limit" in detail.lower()
            self._emit(
                {
                    "type": "done",
                    "ok": False,
                    "error": None if stopped else message,
                    "limit": limit,
                    "resets_at": None,
                    "stopped": stopped,
                }
            )

    def _error_text(self, proc) -> str:
        try:
            proc.wait(timeout=5)
            self._stderr.seek(0)
            return self._stderr.read().decode("utf-8", "replace").strip()[-800:]
        except Exception:
            return ""

    def _handle(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "control_response":
            response = event.get("response") or {}
            data = response.get("response") or {}
            if "models" in data or "account" in data:
                self._emit({"type": "ready", "models": models_from(data), "plan": plan_name(data)})
            elif response.get("subtype") == "error":
                log.info("Codoh: Claude Code refused %s", str(response)[:200])
        elif kind == "control_request":
            request = event.get("request") or {}
            if request.get("subtype") == "can_use_tool":
                self._emit(
                    {
                        "type": "approval",
                        "id": event.get("request_id"),
                        "tool": request.get("tool_name") or "",
                        "input": request.get("input") or {},
                        "description": request.get("description") or "",
                        "suggestions": request.get("permission_suggestions") or [],
                        "tool_use_id": request.get("tool_use_id") or "",
                    }
                )
        elif kind == "system" and event.get("subtype") == "init":
            sid = event.get("session_id")
            if sid and sid != self.session_id:
                self.session_id = sid
                self._emit({"type": "session", "id": sid})
        elif kind == "stream_event":
            self._stream_event(event.get("event") or {})
        elif kind == "assistant":
            self._assistant(event.get("message") or {})
        elif kind == "user":
            self._tool_results(event)
        elif kind == "rate_limit_event":
            info = event.get("rate_limit_info") or {}
            if info.get("status") == "rejected":
                self._limit = info.get("resetsAt")
        elif kind == "result":
            self._result(event)

    _limit = None  # Claude's limit was reached during this reply (when it resets)

    def _stream_event(self, inner: dict) -> None:
        what = inner.get("type")
        if what == "message_start":
            message = inner.get("message") or {}
            self._current = message.get("id") or ""
        elif what == "content_block_start":
            block = inner.get("content_block") or {}
            if block.get("type") == "thinking":
                self._emit({"type": "status", "text": "Thinking"})
        elif what == "content_block_delta":
            delta = inner.get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                self._streamed.add(getattr(self, "_current", ""))
                self._emit({"type": "text", "delta": delta["text"]})

    def _assistant(self, message: dict) -> None:
        streamed = message.get("id") in self._streamed
        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                self._emit(
                    {
                        "type": "tool",
                        "id": block.get("id") or "",
                        "name": block.get("name") or "",
                        "input": block.get("input") or {},
                    }
                )
            elif block.get("type") == "text" and block.get("text") and not streamed:
                self._emit({"type": "text", "delta": block["text"]})  # no deltas came

    def _tool_results(self, event: dict) -> None:
        message = event.get("message") or {}
        content = message.get("content")
        if not isinstance(content, list):
            return
        result = event.get("tool_use_result")
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                self._emit(
                    {
                        "type": "tool_result",
                        "id": block.get("tool_use_id") or "",
                        "ok": not block.get("is_error"),
                        "output": text_of(block.get("content")),
                        "result": result if isinstance(result, dict) else None,
                    }
                )

    def _result(self, event: dict) -> None:
        self.busy = False
        self.last_used = time.monotonic()
        stopped, self._stopping = self._stopping, False
        limit, self._limit = self._limit, None
        seconds = time.monotonic() - self._started_at if self._started_at else 0.0
        failed = event.get("is_error") or event.get("subtype", "success") != "success"
        error = None
        text = str(event.get("result") or "")
        reached = limit is not None or (failed and "limit" in text.lower())
        if failed and not stopped:
            error = limit_message(limit) if reached else error_message(text)
            log.warning("Codoh: Claude Code reported an error: %s", text[:300])
        self._emit(
            {
                "type": "done",
                "ok": not failed or stopped,
                "error": error,
                "limit": bool(reached) and not stopped,
                "resets_at": float(limit) if limit else None,
                "stopped": stopped,
                "cost": event.get("total_cost_usd"),
                "seconds": round(seconds, 1),
            }
        )
