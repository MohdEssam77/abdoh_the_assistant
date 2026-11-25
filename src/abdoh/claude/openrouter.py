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


# ----- pictures made by AI (the board's [picture: draw: ...]) -----

DEFAULT_IMAGE_MODEL = "black-forest-labs/flux-3-image-klein"  # about $0.01 a picture
TOKENS_PER_PICTURE = 1290  # models priced per token (Gemini): about this many for a 1K picture
IMAGE_TIMEOUT_SECONDS = 120.0
CREDIT_CACHE_SECONDS = 300.0


class PictureRefused(RuntimeError):
    """No AI picture: the message says why (credit, key, model) and is safe to say."""


def _get(http, path: str, key: str | None = None) -> dict:
    headers = dict(APP_HEADERS)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    r = http.get(f"{API}{path}", headers=headers, timeout=20.0)
    if r.status_code != 200:
        raise PictureRefused(f"OpenRouter said {r.status_code}")
    return r.json()


def image_models(http=None) -> list[dict]:
    """The models that make pictures: [{"id", "name", "free"}], by name (public list)."""
    http = http or _client()
    data = _get(http, "/images/models").get("data") or []
    found = [{"id": m["id"], "name": m.get("name") or m["id"], "free": m["id"].endswith(":free")}
             for m in data if m.get("id")]  # fmt: skip
    return sorted(found, key=lambda m: m["name"].lower())


_prices: dict[str, float | None] = {}
_one_k: set[str] = set()  # models that take resolution "1K" (Abdoh asks for that size)


def picture_price(model: str, http=None) -> float | None:
    """About what one picture costs in USD (the 1K size where there are sizes: FLUX 3 Klein
    lists 768 at $0.008 and 1k at $0.009), from the model's pricing; None if OpenRouter
    doesn't say. Kept once asked."""
    if model in _prices:
        return _prices[model]
    http = http or _client()
    price = None
    try:
        endpoints = _get(http, f"/images/models/{model}/endpoints").get("endpoints") or []
        first = endpoints[0] if endpoints else {}
        sizes = ((first.get("supported_parameters") or {}).get("resolution") or {}).get("values")
        if any(str(v).lower() == "1k" for v in sizes or []):
            _one_k.add(model)
        for row in first.get("pricing") or []:
            if row.get("billable") != "output_image":
                continue
            cost = float(row.get("cost_usd") or 0)
            if row.get("unit") == "token":
                cost *= TOKENS_PER_PICTURE
            if price is None or str(row.get("variant", "")).lower() == "1k":
                price = cost
        if endpoints and not first.get("pricing"):
            price = 0.0  # a free model
    except (PictureRefused, ValueError, KeyError, IndexError) as e:
        log.info("No price for %s: %s", model, e)
    _prices[model] = price
    return price


_credit: dict = {"at": -1e9, "left": None, "key": None}


def credit_left(key: str, http=None, fresh: bool = False) -> float | None:
    """What the key can still spend, in USD, as far as OpenRouter tells a normal key: the
    account's balance (a management key only) and the key's own spending limit. None if
    neither is known (no limit set): then only trying tells. Kept for a few minutes."""
    fresh = fresh or _credit["key"] != key
    if not fresh and time.monotonic() - _credit["at"] < CREDIT_CACHE_SECONDS:
        return _credit["left"]
    http = http or _client()
    known = []
    try:
        limit = (_get(http, "/key", key).get("data") or {}).get("limit_remaining")
        if limit is not None:
            known.append(float(limit))
    except (PictureRefused, ValueError) as e:
        log.info("Couldn't read the key's limit: %s", e)
    try:  # needs a management key; a normal key gets 403
        data = _get(http, "/credits", key).get("data") or {}
        known.append(float(data["total_credits"]) - float(data["total_usage"]))
    except (PictureRefused, ValueError, KeyError):
        pass
    left = min(known) if known else None
    _credit.update(at=time.monotonic(), left=left, key=key)
    return left


def known_credit(key: str | None) -> float | None:
    """The credit last read for this key (no network): for Claude's status line."""
    if key and _credit["key"] == key and time.monotonic() - _credit["at"] < CREDIT_CACHE_SECONDS:
        return _credit["left"]
    return None


def make_picture(key: str | None, model: str, prompt: str, http=None) -> tuple[bytes, str, float]:
    """A picture made by `model` from `prompt`: (bytes, mime type, cost in USD). Checks the
    credit first. Raises PictureRefused with what to tell the user."""
    import base64

    if not key:
        raise PictureRefused(
            "I can't make pictures with AI: that needs an OpenRouter key (Settings, Claude card)."
        )
    model = model or DEFAULT_IMAGE_MODEL
    http = http or _client()
    price = picture_price(model, http)
    left = credit_left(key, http)
    if price and left is not None and left < price:
        raise PictureRefused(
            f"Your OpenRouter credit is too low for a picture: about ${price:.2f} is needed and "
            f"${max(left, 0):.2f} is left. Add credit at openrouter.ai."
        )
    body = {"model": model, "prompt": prompt, "n": 1, "response_format": "b64_json"}
    if model in _one_k:
        body["resolution"] = "1K"  # the size the price shown is for
    headers = {"Authorization": f"Bearer {key}", **APP_HEADERS}
    try:
        r = http.post(f"{API}/images", json=body, headers=headers, timeout=IMAGE_TIMEOUT_SECONDS)
    except Exception as e:
        log.info("The picture request failed: %s", e)
        raise PictureRefused("I couldn't reach OpenRouter to make the picture.") from e
    if r.status_code == 402:
        _credit.update(at=time.monotonic(), left=0.0)
        raise PictureRefused(
            "Your OpenRouter credit has run out, so I can't make the picture. Add credit at "
            "openrouter.ai."
        )
    if r.status_code == 403:
        raise PictureRefused("Your OpenRouter key's spending limit is used up.")
    if r.status_code == 401:
        raise PictureRefused("OpenRouter rejected your key. Please set a new one in Settings.")
    if r.status_code != 200:
        log.info("OpenRouter said %s to a picture: %s", r.status_code, r.text[:300])
        raise PictureRefused("The picture couldn't be made this time. Nothing was charged.")
    answer = r.json()
    item = (answer.get("data") or [{}])[0]
    if not item.get("b64_json"):
        raise PictureRefused("The picture couldn't be made this time.")
    cost = float((answer.get("usage") or {}).get("cost") or price or 0)
    _credit["at"] = -1e9  # spent: read it again next time
    return base64.b64decode(item["b64_json"]), item.get("media_type") or "image/png", cost


def _client():
    import httpx

    return httpx.Client(timeout=20.0)
