"""Any model on OpenRouter (Claude, GPT, Gemini, Llama, ...) through your own OpenRouter key:
one key, many models, paid from your OpenRouter credits (openrouter.ai).

It works like an Anthropic API key: Abdoh's actions (lamps, apps, modes, ...) and looking at the
screen (with a model that sees images) work; Claude Code's own tools (your files, web search,
Gmail and Calendar) don't, and only the last exchange is remembered. OpenRouter speaks the
OpenAI chat format: https://openrouter.ai/api/v1/chat/completions, streamed as server-sent events.
"""

import base64
import json
import logging
import threading
import time
from collections.abc import Callable, Iterator

from abdoh.about import about
from abdoh.claude.brain import Brain, BrainError, system_prompt
from abdoh.config import Config

log = logging.getLogger(__name__)

API = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openrouter/auto"  # OpenRouter picks a model for each request
KEY_PREFIX = "sk-or-"
TIMEOUT_SECONDS = 60.0
# OpenRouter shows which app made a request (its public rankings): Abdoh, never who you are.
APP_HEADERS = {
    "HTTP-Referer": "https://mohdessam77.github.io/abdoh_the_assistant/",
    "X-Title": "Abdoh",
}
MODELS_CACHE_SECONDS = 3600.0


class OpenRouterBrain(Brain):
    name = "OpenRouter"

    def __init__(self, cfg: Config, client=None):
        self.cfg = cfg
        self._client = client  # an httpx.Client (a fake one in tests)

    @property
    def model(self) -> str:
        return self.cfg.claude.openrouter_model.strip() or DEFAULT_MODEL

    def _http(self):
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=TIMEOUT_SECONDS)
        return self._client

    def request(self, prompt: str, image_png: bytes | None = None) -> dict:
        state = self.state_now()  # the mode that's on, the lamps, ... (abdoh.about.state_line)
        text = f"[Abdoh now: {state}]\n{prompt}" if state else prompt
        content: list[dict] = [{"type": "text", "text": text}]
        if image_png:
            data = base64.standard_b64encode(image_png).decode("ascii")
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}}
            )
        return {
            "model": self.model,
            "max_tokens": self.cfg.claude.max_tokens,
            "stream": True,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt(self.cfg, about=about(self.cfg, "openrouter")),
                },
                {"role": "user", "content": content},
            ],
        }

    def stream(self, prompt: str, image_png: bytes | None = None) -> Iterator[str]:
        import httpx

        headers = {"Authorization": f"Bearer {self.cfg.openrouter_api_key}", **APP_HEADERS}
        body = self.request(prompt, image_png)
        try:
            with self._http().stream(
                "POST", f"{API}/chat/completions", json=body, headers=headers
            ) as r:
                if r.status_code != 200:
                    r.read()
                    raise BrainError(self._problem(r.status_code, _message(r.text)))
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue  # ": OPENROUTER PROCESSING" keeps the connection alive
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        continue
                    if chunk.get("error"):  # failed after it started (the model's provider)
                        raise BrainError(self._problem(0, _message(json.dumps(chunk))))
                    for choice in chunk.get("choices") or []:
                        piece = (choice.get("delta") or {}).get("content")
                        if piece:
                            yield piece
        except httpx.HTTPError as e:
            log.error("OpenRouter request failed: %s", e)
            raise BrainError("I couldn't reach OpenRouter right now.") from e

    def _problem(self, status: int, message: str) -> str:
        """What to say when OpenRouter says no (its own message goes to the log)."""
        log.error("OpenRouter said %s: %s", status or "error", message)
        if status == 401:
            return "OpenRouter rejected your key. Please set a new one in Settings."
        if status == 402:
            return "Your OpenRouter credits have run out. Add some at openrouter.ai."
        if status == 429:
            return "OpenRouter is busy right now. Try again in a moment."
        if "image" in message.lower():
            return f"The model {self.model} can't look at pictures. Pick another in Settings."
        if status in (400, 404):
            return f"OpenRouter couldn't use the model {self.model}. Pick another in Settings."
        return "OpenRouter couldn't answer right now."

    def status(self) -> str:
        return f"OpenRouter ({self.model})"

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


def _message(text: str) -> str:
    try:
        error = json.loads(text).get("error") or {}
    except (ValueError, AttributeError):
        return text[:300]
    return str(error.get("message") or error)[:300] if isinstance(error, dict) else str(error)


# ----- the models there are (for the Settings card) -----

_models: dict = {"at": 0.0, "list": []}
_models_lock = threading.Lock()


def models(fetch: Callable[[], dict] | None = None) -> list[dict]:
    """The models on OpenRouter that write text: [{"id", "name", "images", "price"}], the
    automatic choice first. OpenRouter's list is public (no key needed); kept for an hour."""
    with _models_lock:
        if _models["list"] and time.monotonic() - _models["at"] < MODELS_CACHE_SECONDS:
            return _models["list"]
        data = (fetch or _fetch_models)()
        found = []
        for m in data.get("data") or []:
            arch = m.get("architecture") or {}
            if "text" not in (arch.get("output_modalities") or ["text"]):
                continue
            found.append({
                "id": m.get("id", ""),
                "name": m.get("name") or m.get("id", ""),
                "images": "image" in (arch.get("input_modalities") or []),
                "price": _price(m.get("pricing") or {}),
            })  # fmt: skip
        found = [m for m in found if m["id"] and ":batch" not in m["id"]]  # batch: answers late
        found.sort(key=lambda m: m["name"].lower())
        if not any(m["id"] == DEFAULT_MODEL for m in found):
            found.insert(
                0,
                {
                    "id": DEFAULT_MODEL,
                    "name": "Auto (OpenRouter picks)",
                    "images": True,
                    "price": "",
                },
            )
        else:
            found.sort(key=lambda m: m["id"] != DEFAULT_MODEL)
        _models.update(at=time.monotonic(), list=found)
        return found


def _price(pricing: dict) -> str:
    """ "$3 / $15 per million tokens" (in / out), or "free"."""
    try:
        prompt, completion = float(pricing.get("prompt", 0)), float(pricing.get("completion", 0))
    except (TypeError, ValueError):
        return ""
    if prompt == 0 and completion == 0:
        return "free"
    if prompt < 0 or completion < 0:
        return ""  # the automatic router: depends on the model it picks

    def per_million(per_token: float) -> str:
        value = per_token * 1_000_000
        return f"${value:.2f}".rstrip("0").rstrip(".") if value < 10 else f"${value:.0f}"

    return f"{per_million(prompt)} / {per_million(completion)} per million tokens"


def _fetch_models() -> dict:
    import httpx

    try:
        r = httpx.get(f"{API}/models", headers=APP_HEADERS, timeout=15.0)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise BrainError("Couldn't get OpenRouter's list of models.") from e
