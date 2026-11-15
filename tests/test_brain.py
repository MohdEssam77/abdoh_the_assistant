"""System prompt, choosing a Claude backend, and the API backend with a fake SDK."""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx2 as httpx
import pytest

from abdoh.claude.api import FALLBACK_BETA, ApiBrain
from abdoh.claude.brain import BrainError, make_brain, system_prompt
from abdoh.claude.code import ClaudeCodeBrain
from abdoh.config import ClaudeConfig, Config


def test_system_prompt():
    text = system_prompt(Config(), web=True, now=datetime(2026, 11, 14, 21, 5))
    assert "You are Abdoh" in text
    assert "at most 4 short spoken sentences" in text
    assert "ACTION open_url:" in text and "ACTION open_app:" in text
    assert "search the web" in text
    assert "Saturday, November 14, 2026" in text and "9:05 PM" in text
    assert "search the web" not in system_prompt(Config(), web=False)
    assert "You cannot run commands" in text  # no file access unless a home folder is given


def test_system_prompt_with_file_access():
    home = Path("C:/Users/me")
    text = system_prompt(Config(), home=home, folders={"Downloads": home / "Downloads"})
    assert f"Their home folder is {home} (Downloads: {home / 'Downloads'})." in text
    assert "ask whether to go ahead" in text and "never permanently" in text
    assert "use the action lines above, not commands" in text
    assert "You cannot run commands" not in text


def test_auto_prefers_claude_code():
    brain = make_brain(Config(), find_code=lambda path: Path("claude.exe"))
    assert isinstance(brain, ClaudeCodeBrain)


def test_auto_falls_back_to_the_api_key():
    c = Config(anthropic_api_key="sk-test")
    assert isinstance(make_brain(c, find_code=lambda path: None), ApiBrain)
    assert make_brain(Config(), find_code=lambda path: None) is None


def test_explicit_backends():
    with_key = Config(anthropic_api_key="sk", claude=ClaudeConfig(backend="api"))
    assert isinstance(make_brain(with_key, find_code=lambda p: Path("claude.exe")), ApiBrain)
    code_only = Config(anthropic_api_key="sk", claude=ClaudeConfig(backend="code"))
    assert make_brain(code_only, find_code=lambda p: None) is None
    off = Config(anthropic_api_key="sk", claude=ClaudeConfig(backend="off"))
    assert make_brain(off, find_code=lambda p: Path("claude.exe")) is None


def test_configured_code_path_is_passed_on():
    seen = []
    c = Config(claude=ClaudeConfig(code_path="D:/tools/claude.exe"))
    make_brain(c, find_code=lambda p: seen.append(p))
    assert seen == ["D:/tools/claude.exe"]


# ----- API backend -----


class FakeStream:
    def __init__(self, chunks, stop_reason):
        self.text_stream = iter(chunks)
        self.stop_reason = stop_reason

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return SimpleNamespace(stop_reason=self.stop_reason)


class FakeMessages:
    def __init__(self, chunks=("Tokyo.",), stop_reason="end_turn", error=None):
        self.chunks = chunks
        self.stop_reason = stop_reason
        self.error = error
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return FakeStream(self.chunks, self.stop_reason)


def api_brain(model="claude-opus-5-5", **kwargs):
    messages = FakeMessages(**kwargs)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    c = Config(anthropic_api_key="sk", claude=ClaudeConfig(model=model, effort="low"))
    return ApiBrain(c, client=client), messages


def test_api_streams_text_with_effort_and_fallbacks():
    brain, messages = api_brain(chunks=("Tokyo ", "is the capital."))
    assert "".join(brain.stream("Capital of Japan?")) == "Tokyo is the capital."
    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"] == {"effort": "low"}
    assert call["betas"] == [FALLBACK_BETA] and call["fallbacks"] == "default"
    assert "You are Abdoh" in call["system"]
    assert call["messages"][0]["content"] == [{"type": "text", "text": "Capital of Japan?"}]


def test_api_no_fallbacks_for_models_without_them():
    brain, messages = api_brain(model="claude-haiku-5-5")
    list(brain.stream("hi"))
    assert "fallbacks" not in messages.calls[0]


def test_api_image():
    brain, messages = api_brain()
    list(brain.stream("Describe", image_png=b"\x89PNG"))
    content = messages.calls[0]["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/png"
    assert content[1]["text"] == "Describe"


def test_api_refusal():
    brain, _ = api_brain(chunks=(), stop_reason="refusal")
    assert "can't help" in "".join(brain.stream("q"))


def status_error(cls, code):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("err", response=httpx.Response(code, request=request), body=None)


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
def test_api_errors_become_friendly_messages(error, spoken):
    brain, _ = api_brain(error=error)
    with pytest.raises(BrainError, match=spoken):
        list(brain.stream("q"))
