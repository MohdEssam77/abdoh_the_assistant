"""OpenRouter: any model with one key. A fake network (httpx.MockTransport): no key, no internet."""

import json

import httpx
import pytest

from abdoh.claude.brain import BrainError, make_brain
from abdoh.claude.openrouter import DEFAULT_MODEL, OpenRouterBrain, _price, models
from abdoh.config import ClaudeConfig, Config, load_config


def sse(*events):
    """A streamed answer as OpenRouter sends it."""
    lines = [": OPENROUTER PROCESSING", ""]
    for event in events:
        lines += [f"data: {json.dumps(event) if not isinstance(event, str) else event}", ""]
    return "\n".join(lines).encode()


def delta(text):
    return {"choices": [{"delta": {"content": text}}]}


def brain_with(handler, **claude):
    seen = []

    def record(request):
        seen.append(request)
        return handler(request)

    cfg = Config(openrouter_api_key="sk-or-test", claude=ClaudeConfig(**claude))
    brain = OpenRouterBrain(cfg, client=httpx.Client(transport=httpx.MockTransport(record)))
    brain.state = lambda: "no mode on; lamps: Main Lamp (colours and whites)"
    return brain, seen


def test_it_streams_the_answer_and_sends_what_abdoh_needs():
    answer = sse(delta("Turning the "), delta("lamp blue."), {"choices": [{"delta": {}}]}, "[DONE]")
    brain, seen = brain_with(
        lambda r: httpx.Response(200, content=answer), openrouter_model="openai/gpt-5"
    )
    assert "".join(brain.stream("make the lamp blue", image_png=b"png")) == "Turning the lamp blue."
    (request,) = seen
    assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer sk-or-test"
    assert request.headers["X-Title"] == "Abdoh"  # the app's name, never the user's
    body = json.loads(request.content)
    assert body["model"] == "openai/gpt-5" and body["stream"] is True
    system, user = body["messages"]
    assert system["role"] == "system" and "You are Abdoh" in system["content"]
    assert "ACTION lamp" in system["content"]  # Abdoh's actions work with any model
    assert "openai/gpt-5 through OpenRouter" in system["content"]
    text, image = user["content"]
    assert text["text"].startswith("[Abdoh now: no mode on; lamps: Main Lamp")
    assert image["image_url"]["url"] == "data:image/png;base64,cG5n"


def test_the_automatic_model_by_default():
    brain, _ = brain_with(lambda r: httpx.Response(200, content=sse("[DONE]")))
    assert brain.model == DEFAULT_MODEL == "openrouter/auto"
    assert brain.status() == "OpenRouter (openrouter/auto)"


@pytest.mark.parametrize(
    "status, error, said",
    [
        (401, "No auth credentials found", "OpenRouter rejected your key"),
        (402, "Insufficient credits", "credits have run out"),
        (429, "Rate limited", "busy right now"),
        (404, "No endpoints found that support image input", "can't look at pictures"),
        (400, "x-ai/nope is not a valid model ID", "couldn't use the model"),
        (502, "Bad gateway", "couldn't answer right now"),
    ],
)
def test_problems_are_said_plainly(status, error, said):
    brain, _ = brain_with(
        lambda r: httpx.Response(status, json={"error": {"message": error, "code": status}})
    )
    with pytest.raises(BrainError, match=said):
        list(brain.stream("hi"))


def test_a_failure_after_it_started():
    failed = sse(delta("Sure"), {"error": {"message": "Provider returned error", "code": 502}})
    brain, _ = brain_with(lambda r: httpx.Response(200, content=failed))
    with pytest.raises(BrainError, match="couldn't answer"):
        list(brain.stream("hi"))


def test_no_internet():
    def offline(request):
        raise httpx.ConnectError("no route", request=request)

    brain, _ = brain_with(offline)
    with pytest.raises(BrainError, match="couldn't reach OpenRouter"):
        list(brain.stream("hi"))


def test_which_connection_abdoh_uses():
    only_openrouter = Config(openrouter_api_key="sk-or-x")
    assert isinstance(make_brain(only_openrouter, find_code=lambda p: None), OpenRouterBrain)
    both = Config(anthropic_api_key="sk-ant-x", openrouter_api_key="sk-or-x")
    assert make_brain(both, find_code=lambda p: None).name == "API key"  # Anthropic's first
    chosen = Config(anthropic_api_key="sk-ant-x", openrouter_api_key="sk-or-x",
                    claude=ClaudeConfig(backend="openrouter"))  # fmt: skip
    assert isinstance(make_brain(chosen, find_code=lambda p: "claude.exe"), OpenRouterBrain)


def test_the_key_lives_in_env_never_in_the_settings_file(app_dir):
    from abdoh.claude import setup
    from abdoh.settings import save_settings

    cfg = load_config(app_dir)
    with pytest.raises(setup.SetupError, match="sk-or-"):
        setup.set_openrouter_key(cfg, "sk-ant-wrong-kind")
    setup.set_openrouter_key(cfg, "sk-or-v1-abc")
    again = load_config(app_dir)
    assert again.openrouter_api_key == "sk-or-v1-abc" and again.has_openrouter_key
    save_settings(app_dir, {"claude": {"openrouter_model": "google/gemini-3-pro"}})
    assert "sk-or-" not in (app_dir / "config.yaml").read_text(encoding="utf-8")
    assert load_config(app_dir).claude.openrouter_model == "google/gemini-3-pro"
    state = setup.claude_state(load_config(app_dir), find=lambda p: None, status=lambda e: None)
    assert state["using"] == "openrouter" and state["connected"]
    assert state["summary"] == "Connected through OpenRouter (google/gemini-3-pro)."
    setup.set_openrouter_key(cfg, "")
    assert load_config(app_dir).openrouter_api_key is None


LIST = {
    "data": [
        {"id": "openai/gpt-5", "name": "OpenAI: GPT-5",
         "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
         "pricing": {"prompt": "0.00000125", "completion": "0.00001"}},
        {"id": "meta-llama/llama-4:free", "name": "Meta: Llama 4 (free)",
         "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
         "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "black-forest/flux", "name": "FLUX",
         "architecture": {"input_modalities": ["text"], "output_modalities": ["image"]}},
    ]
}  # fmt: skip


def test_the_models_to_pick_from():
    from abdoh.claude import openrouter

    openrouter._models.update(at=0.0, list=[])
    found = models(fetch=lambda: LIST)
    assert [m["id"] for m in found] == [
        "openrouter/auto",
        "meta-llama/llama-4:free",
        "openai/gpt-5",
    ]
    gpt = found[2]
    assert gpt["images"] is True and gpt["price"] == "$1.25 / $10 per million tokens"
    assert (
        found[1]["price"] == "free" and found[1]["images"] is False
    )  # no image models: FLUX left out
    assert models(fetch=lambda: {"data": []}) == found  # kept for an hour
    assert _price({"prompt": "-1", "completion": "-1"}) == ""


def test_the_app_saves_the_key_and_lists_models(app_dir):
    from abdoh.claude import openrouter
    from abdoh.events import Bus
    from abdoh.ui.api import AppApi, UiState

    bus = Bus()
    api = AppApi(bus, UiState(), load_config(app_dir))
    assert api.set_openrouter_key("nope")["ok"] is False
    assert api.set_openrouter_key("sk-or-v1-abc") == {"ok": True}
    assert bus.next_request(timeout=0) == ("settings_changed", None)  # Abdoh reconnects
    openrouter._models.update(at=0.0, list=[])
    openrouter._fetch_models, real = (lambda: LIST), openrouter._fetch_models
    try:
        assert api.openrouter_models()["models"][0]["id"] == "openrouter/auto"
    finally:
        openrouter._fetch_models = real
        openrouter._models.update(at=0.0, list=[])
