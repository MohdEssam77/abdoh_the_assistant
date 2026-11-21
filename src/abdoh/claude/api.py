"""Claude through an Anthropic API key (optional; the default is Claude Code)."""

import base64
import logging
from collections.abc import Iterator

from abdoh.about import about
from abdoh.claude.brain import Brain, BrainError, system_prompt
from abdoh.config import Config

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30.0
# Server-side refusal fallback: if the model declines, the API retries on a suitable model.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {
    "claude-fable-5-2",
    "claude-fable-5-1",
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-sonnet-5-5",
}


class ApiBrain(Brain):
    name = "API key"

    def __init__(self, cfg: Config, client=None):
        self.cfg = cfg
        self._client = client  # created on first use: importing the SDK takes ~2 s

    def _sdk(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(
                api_key=self.cfg.anthropic_api_key, timeout=TIMEOUT_SECONDS, max_retries=1
            )
        return self._client

    def request(self, prompt: str, image_png: bytes | None = None) -> dict:
        content: list[dict] = []
        if image_png:
            data = base64.standard_b64encode(image_png).decode("ascii")
            source = {"type": "base64", "media_type": "image/png", "data": data}
            content.append({"type": "image", "source": source})
        state = self.state_now()  # the mode that's on, ... (abdoh.about.state_line)
        text = f"[Abdoh now: {state}]\n{prompt}" if state else prompt
        content.append({"type": "text", "text": text})
        model = self.cfg.claude.model
        params: dict = {
            "model": model,
            "max_tokens": self.cfg.claude.max_tokens,
            "system": system_prompt(self.cfg, about=about(self.cfg, "api")),
            "messages": [{"role": "user", "content": content}],
        }
        if self.cfg.claude.effort:
            params["output_config"] = {"effort": self.cfg.claude.effort}
        if model in FALLBACK_MODELS:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        return params

    def stream(self, prompt: str, image_png: bytes | None = None) -> Iterator[str]:
        import anthropic

        try:
            with self._sdk().beta.messages.stream(**self.request(prompt, image_png)) as stream:
                yield from stream.text_stream
                message = stream.get_final_message()
            if message.stop_reason == "refusal":
                yield "\nSorry, I can't help with that one."
        except anthropic.AuthenticationError as e:
            log.error("Claude rejected the API key: %s", e)
            raise BrainError("Claude rejected your API key. Please set a new key.") from e
        except anthropic.NotFoundError as e:
            log.error("Claude model not found: %s", e)
            model = self.cfg.claude.model
            raise BrainError(f"The Claude model {model} wasn't found. Check config.") from e
        except anthropic.RateLimitError as e:
            log.warning("Claude rate limited: %s", e)
            raise BrainError("Claude is busy right now. Try again in a moment.") from e
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as e:
            log.error("Claude request failed: %s", e)
            raise BrainError("I couldn't reach Claude right now.") from e
