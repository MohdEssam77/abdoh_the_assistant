"""Claude client and skills, with the Anthropic SDK mocked (no network, no API key)."""

from types import SimpleNamespace

import anthropic
import httpx2 as httpx
import pytest

from abdoh.claude.client import ClaudeClient, ClaudeError, clean_for_speech
from abdoh.config import ClaudeConfig, Config


class FakeMessages:
    def __init__(self, text="Tokyo.", stop_reason="end_turn", error=None):
        self.text = text
        self.stop_reason = stop_reason
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="text", text=self.text)],
        )


def make_client(**kwargs):
    messages = FakeMessages(**kwargs)
    cfg = Config(claude=ClaudeConfig(model="test-model", voice_reply_max_sentences=3))
    return ClaudeClient(cfg, client=SimpleNamespace(messages=messages)), messages


def status_error(cls, code):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("err", response=httpx.Response(code, request=request), body=None)


def test_ask_sends_system_prompt_and_text():
    client, messages = make_client()
    assert client.ask("What's the capital of Japan?") == "Tokyo."
    call = messages.calls[0]
    assert call["model"] == "test-model"
    assert "max 3 sentences" in call["system"]
    assert "no markdown" in call["system"]
    assert call["messages"][0]["content"] == [
        {"type": "text", "text": "What's the capital of Japan?"}
    ]


def test_ask_with_image():
    client, messages = make_client()
    client.ask("Describe", image_png=b"\x89PNG")
    content = messages.calls[0]["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/png"
    assert content[1]["text"] == "Describe"


def test_markdown_is_cleaned():
    client, _ = make_client(text="## Answer\n- **Tokyo** is the `capital`.")
    assert client.ask("q") == "Answer Tokyo is the capital."


def test_refusal():
    client, _ = make_client(stop_reason="refusal")
    assert "can't help" in client.ask("q")


@pytest.mark.parametrize(
    "error, spoken",
    [
        (status_error(anthropic.AuthenticationError, 401), "rejected your API key"),
        (status_error(anthropic.NotFoundError, 404), "wasn't found"),
        (status_error(anthropic.RateLimitError, 429), "busy"),
        (status_error(anthropic.InternalServerError, 500), "couldn't reach Claude"),
        (
            anthropic.APITimeoutError(httpx.Request("POST", "https://api.anthropic.com")),
            "couldn't reach Claude",
        ),
    ],
)
def test_errors_become_friendly_messages(error, spoken):
    client, _ = make_client(error=error)
    with pytest.raises(ClaudeError, match=spoken):
        client.ask("q")


def test_clean_for_speech():
    assert clean_for_speech("1. One\n2. Two") == "One Two"
    assert clean_for_speech("Use ```code``` here") == "Use here"
