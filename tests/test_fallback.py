"""Your ChatGPT plan answers while Claude's usage limit is used up (claude/fallback.py)."""

import json

import pytest

from abdoh.claude.brain import Brain, BrainError, make_brain
from abdoh.claude.code import ClaudeCodeBrain, failure, limit_error, read_events
from abdoh.claude.fallback import (
    RETRY_SECONDS,
    SWITCHED_UNKNOWN,
    FallbackBrain,
    clock,
    with_fallback,
)
from abdoh.config import Config


class Scripted(Brain):
    """Answers from a list: text, or a BrainError to raise (after the text before it)."""

    def __init__(self, name, *answers):
        self.name = name
        self.answers = list(answers)
        self.asked = []
        self.closed = False

    def stream(self, prompt, image_png=None):
        self.asked.append(prompt)
        answer = self.answers.pop(0) if self.answers else "fine"
        for part in answer if isinstance(answer, list) else [answer]:
            if isinstance(part, BrainError):
                raise part
            yield part

    def close(self):
        self.closed = True


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def wrap(primary, backup, now):
    return FallbackBrain(primary, lambda: backup, now=now)


def test_a_limit_before_any_words_goes_to_chatgpt_with_one_sentence():
    now = Clock()
    claude = Scripted("Claude Code", limit_error(now.now + 3600))
    chatgpt = Scripted("ChatGPT", "It is sunny.")
    brain = wrap(claude, chatgpt, now)
    told = []
    brain.on_switch = told.append
    reply = "".join(brain.stream("weather?"))
    assert reply.startswith(f"Claude's limit is used up until {clock(now.now + 3600)}")
    assert reply.endswith("It is sunny.")
    assert chatgpt.asked == ["weather?"]
    assert told == [True]
    assert brain.name == "ChatGPT" and brain.until() == now.now + 3600


def test_chatgpt_answers_until_the_limit_resets_then_claude_again():
    now = Clock()
    claude = Scripted("Claude Code", limit_error(now.now + 600), "Claude here.")
    chatgpt = Scripted("ChatGPT", "first", "second")
    brain = wrap(claude, chatgpt, now)
    told = []
    brain.on_switch = told.append
    "".join(brain.stream("one"))
    assert "".join(brain.stream("two")) == "second"  # straight to ChatGPT, no sentence
    assert claude.asked == ["one"]
    now.now += 601
    assert "".join(brain.stream("three")) == "Claude here."
    assert told == [True, False]
    assert brain.name == "Claude Code"


def test_without_a_reset_time_claude_is_tried_again_later():
    now = Clock()
    claude = Scripted("Claude Code", limit_error(None), "back")
    brain = wrap(claude, Scripted("ChatGPT", "x", "y"), now)
    assert "".join(brain.stream("a")).startswith(SWITCHED_UNKNOWN)
    now.now += RETRY_SECONDS - 1
    assert "".join(brain.stream("b")) == "y"
    now.now += 2
    assert "".join(brain.stream("c")) == "back"


def test_no_switch_after_claude_said_something_or_for_other_errors():
    now = Clock()
    cut = Scripted("Claude Code", ["Half an answer", limit_error(now.now + 60)])
    with pytest.raises(BrainError):
        "".join(wrap(cut, Scripted("ChatGPT"), now).stream("q"))
    other = Scripted("Claude Code", BrainError("Claude took too long to answer."))
    chatgpt = Scripted("ChatGPT")
    with pytest.raises(BrainError, match="too long"):
        "".join(wrap(other, chatgpt, now).stream("q"))
    assert chatgpt.asked == []


def test_no_chatgpt_to_switch_to_keeps_the_limit_message():
    now = Clock()
    brain = FallbackBrain(Scripted("Claude Code", limit_error(now.now + 60)), lambda: None, now)
    with pytest.raises(BrainError) as e:
        "".join(brain.stream("q"))
    assert e.value.limit


def test_status_says_who_answers():
    now = Clock()
    claude = Scripted("Claude Code", limit_error(now.now + 60))
    claude.status = lambda: "Pro subscription (Claude Code)"
    brain = wrap(claude, Scripted("ChatGPT", "ok"), now)
    assert brain.status() == "Pro subscription (Claude Code)"
    "".join(brain.stream("q"))
    assert brain.status().startswith("your plan, while Claude's limit is used up until")
    assert brain.ai() == "ChatGPT"  # the window says who answers now


def test_activity_and_state_reach_both_brains():
    claude, chatgpt = Scripted("Claude Code", limit_error(None)), Scripted("ChatGPT", "ok")
    brain = FallbackBrain(claude, lambda: chatgpt, Clock())
    brain.on_activity = seen = object()
    brain.state = state = object()
    assert claude.on_activity is seen and claude.state is state
    "".join(brain.stream("q"))
    assert chatgpt.on_activity is seen and chatgpt.state is state


def test_interrupting_closes_claudes_reply():
    closed = []

    class Slow(Brain):
        name = "Claude Code"

        def stream(self, prompt, image_png=None):
            try:
                yield "one "
                yield "two"
            finally:
                closed.append(True)

    gen = FallbackBrain(Slow(), lambda: None, Clock()).stream("q")
    assert next(gen) == "one "
    gen.close()
    assert closed == [True]


def test_close_and_same_setup():
    claude, chatgpt = Scripted("Claude Code", limit_error(None)), Scripted("ChatGPT", "ok")
    brain = FallbackBrain(claude, lambda: chatgpt, Clock())
    "".join(brain.stream("q"))
    other = FallbackBrain(Scripted("Claude Code"), lambda: None)
    claude.same_setup = lambda o: o is other.primary
    assert brain.same_setup(other) and not brain.same_setup(claude)
    brain.close()
    assert claude.closed and chatgpt.closed


# ----- Claude Code marks its limits -----


def test_claude_code_limit_events_are_marked():
    info = {"status": "rejected", "resetsAt": 1795665000}
    line = json.dumps({"type": "rate_limit_event", "rate_limit_info": info})
    with pytest.raises(BrainError) as e:
        list(read_events([line]))
    assert e.value.limit and e.value.resets_at == 1795665000
    assert failure("You've hit your usage limit").limit
    assert not failure("something else").limit


# ----- make_brain -----


def _signed_in(tmp_path, plan_usage=True):
    folder = tmp_path / "chatgpt"
    folder.mkdir()
    (folder / "account.json").write_text(
        json.dumps({"connected": True, "plan_usage": plan_usage, "client_id": "c"}), "utf-8"
    )
    (folder / "tokens.bin").write_bytes(b"sealed")


def test_make_brain_puts_chatgpt_behind_claude_code(tmp_path):
    _signed_in(tmp_path)
    cfg = Config(app_dir=tmp_path)
    brain = make_brain(cfg, find_code=lambda _: tmp_path / "claude.exe")
    assert isinstance(brain, FallbackBrain) and isinstance(brain.primary, ClaudeCodeBrain)
    cfg.claude.fallback = False
    assert isinstance(make_brain(cfg, find_code=lambda _: tmp_path / "claude.exe"), ClaudeCodeBrain)


def test_no_fallback_without_the_plan(tmp_path):
    cfg = Config(app_dir=tmp_path)
    claude = Scripted("Claude Code")
    assert with_fallback(cfg, claude) is claude
    _signed_in(tmp_path, plan_usage=False)
    assert with_fallback(cfg, claude) is claude
