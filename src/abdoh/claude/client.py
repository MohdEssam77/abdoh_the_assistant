"""Thin wrapper over the Anthropic SDK that returns short, speakable answers."""

import base64
import logging
import re

import anthropic

from abdoh.config import Config

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 20.0
NOT_CONNECTED = (
    "Claude isn't connected. To connect it, add your Anthropic API key to the .env file, "
    "or use Set Claude key in Abdoh's window."
)
SYSTEM_PROMPT = (
    "You are Abdoh, a voice assistant. Answers are spoken aloud: be brief "
    "(max {n} sentences), no markdown, no lists, no emojis."
)


class ClaudeError(RuntimeError):
    """A Claude request failed; the message is safe to speak."""


def clean_for_speech(text: str) -> str:
    """Remove markdown that would sound odd when read aloud."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"^\s*(#+|[-*•]|\d+\.)\s+", "", text, flags=re.M)
    text = re.sub(r"[*_`#]", "", text)
    return re.sub(r"\s+", " ", text).strip()


class ClaudeClient:
    def __init__(self, cfg: Config, client: anthropic.Anthropic | None = None):
        self.model = cfg.claude.model
        self.max_tokens = cfg.claude.max_tokens
        self.system = SYSTEM_PROMPT.format(n=cfg.claude.voice_reply_max_sentences)
        self._client = client or anthropic.Anthropic(
            api_key=cfg.anthropic_api_key, timeout=TIMEOUT_SECONDS, max_retries=1
        )

    def ask(self, text: str, image_png: bytes | None = None, max_tokens: int | None = None) -> str:
        """Ask Claude (optionally about an image). Raises ClaudeError with a speakable message."""
        content: list[dict] = []
        if image_png:
            data = base64.standard_b64encode(image_png).decode("ascii")
            source = {"type": "base64", "media_type": "image/png", "data": data}
            content.append({"type": "image", "source": source})
        content.append({"type": "text", "text": text})
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens or self.max_tokens,
                system=self.system,
                messages=[{"role": "user", "content": content}],
            )
        except anthropic.AuthenticationError as e:
            log.error("Claude rejected the API key: %s", e)
            raise ClaudeError("Claude rejected your API key. Please set a new key.") from e
        except anthropic.NotFoundError as e:
            log.error("Claude model not found: %s", e)
            raise ClaudeError(f"The Claude model {self.model} wasn't found. Check config.") from e
        except anthropic.RateLimitError as e:
            log.warning("Claude rate limited: %s", e)
            raise ClaudeError("Claude is busy right now. Try again in a moment.") from e
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as e:
            log.error("Claude request failed: %s", e)
            raise ClaudeError("I couldn't reach Claude right now.") from e

        if response.stop_reason == "refusal":
            return "Sorry, I can't help with that one."
        answer = " ".join(b.text for b in response.content if b.type == "text")
        return clean_for_speech(answer) or "Claude didn't have an answer."


def make_claude(cfg: Config) -> ClaudeClient | None:
    """A Claude client if an API key is configured, else None."""
    return ClaudeClient(cfg) if cfg.claude_enabled else None
