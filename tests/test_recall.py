"""Remembering earlier conversations: reading <when>, finding the exchanges, asking again."""

from datetime import date, datetime, timedelta

import pytest
from test_router import FakeAct, LookingBrain

from abdoh.claude.brain import system_prompt
from abdoh.commands.registry import CommandRegistry
from abdoh.config import Config
from abdoh.conversations import FOLDER, Conversations, Exchange
from abdoh.recall import MAX_CHARS, describe, find, follow_up, line, parse_when, split
from abdoh.router import Router

TODAY = date(2026, 11, 25)  # a Wednesday
NOW = datetime(2026, 11, 25, 18, 0)


def kept(folder, at=NOW):
    return Conversations(folder, now=lambda: at)


@pytest.mark.parametrize(
    "when, first, last",
    [
        ("2026-11-23", date(2026, 11, 23), date(2026, 11, 23)),
        ("2026-11-20 to 2026-11-23", date(2026, 11, 20), date(2026, 11, 23)),
        ("", date(2026, 11, 18), TODAY),
        ("today", TODAY, TODAY),
        ("yesterday", date(2026, 11, 24), date(2026, 11, 24)),
        ("gestern", date(2026, 11, 24), date(2026, 11, 24)),
        ("the day before yesterday", date(2026, 11, 23), date(2026, 11, 23)),
        ("monday", date(2026, 11, 23), date(2026, 11, 23)),
        ("on Wednesday", date(2026, 11, 18), date(2026, 11, 18)),  # last week's: today is one
        ("Thursday", date(2026, 11, 19), date(2026, 11, 19)),
        ("am Montag", date(2026, 11, 23), date(2026, 11, 23)),
        ("last night", date(2026, 11, 24), date(2026, 11, 24)),
        ("3 days ago", date(2026, 11, 22), date(2026, 11, 22)),
        ("vor 2 Tagen", date(2026, 11, 23), date(2026, 11, 23)),
        ("this week", date(2026, 11, 18), TODAY),
        ("last week", date(2026, 11, 18), date(2026, 11, 24)),
        ("2026-10-01", date(2026, 10, 1), date(2026, 10, 1)),  # older than kept: none found
        ("2026-13-45", date(2026, 11, 18), TODAY),  # not a date: the whole week
    ],
)
def test_when(when, first, last):
    assert parse_when(when, TODAY) == (first, last)


def test_saying_which_days():
    assert describe(date(2026, 11, 24), date(2026, 11, 24), TODAY) == "yesterday"
    assert describe(date(2026, 11, 21), date(2026, 11, 21), TODAY) == "Saturday 21 November"
    assert describe(date(2026, 11, 21), TODAY, TODAY) == "from Saturday 21 November to today"


def test_split():
    assert split("carbonara | 2026-11-24") == ("carbonara", "2026-11-24")
    assert split("the DFA") == ("the DFA", "")


def exchange(you, abdoh, minute=0, board=""):
    return Exchange(NOW.replace(minute=minute), you, abdoh, board=board)


DAY = [
    exchange("what's the weather", "Sunny, 12 degrees.", 1),
    exchange("show me a DFA for numbers divisible by 3", "Here's the automaton.", 2, "```dot```"),
    exchange("why three states?", "One per remainder: 0, 1 and 2.", 3),
    exchange("play some jazz", "Done.", 4),
    exchange("set a timer for pasta", "Ten minutes, starting now.", 5),
]


def test_the_best_matches_come_with_the_one_before_and_after():
    found = find(DAY, "the automata we did", TODAY)  # automaton ~ automata
    assert [e.you for e in found] == [
        "what's the weather",
        "show me a DFA for numbers divisible by 3",
        "why three states?",
    ]


def test_nothing_matches():
    assert find(DAY, "carbonara", TODAY) == []


def test_claude_is_asked_again_with_the_latest_when_no_words_match(tmp_path):
    talks = kept(tmp_path, NOW - timedelta(days=1))
    talks.add("show me a DFA for numbers divisible by 3", "The state is the remainder.")
    message = follow_up(kept(tmp_path), "automaton explanation", "yesterday", "how many states?")
    assert "User: show me a DFA" in message and "other words" in message


def test_everything_means_the_latest():
    assert [e.you for e in find(DAY, "everything", TODAY)] == [e.you for e in DAY]


def test_at_most_about_4000_characters():
    many = [exchange(f"question {i} about lamps", "word " * 200, i % 60) for i in range(60)]
    found = find(many, "lamps", TODAY)
    sent = "\n".join(line(e, TODAY) for e in found)  # what Claude gets
    assert 0 < len(found) < 60 and len(sent) <= MAX_CHARS
    assert found[-1].you == "question 59 about lamps"  # the latest of equal matches first


def test_the_message_for_claude(tmp_path):
    talks = kept(tmp_path, NOW - timedelta(days=1))
    talks.add("show me a DFA for numbers divisible by 3", "Here's the automaton.", role="Professor")
    message = follow_up(kept(tmp_path), "DFA", "2026-11-24", "what was yesterday's automaton?")
    assert "(yesterday)" in message and '"DFA"' in message
    assert "[Yesterday, 18:00, acting as Professor] User: show me a DFA" in message
    assert '"what was yesterday\'s automaton?"' in message and "recall again" in message


def test_the_message_when_nothing_is_found(tmp_path):
    kept(tmp_path).add("what's the weather", "Sunny.")
    nothing = follow_up(kept(tmp_path), "carbonara", "", "the recipe from last week?")
    # none in those words: the latest ones, and Claude judges (it said automaton, it was a DFA)
    assert 'none uses the words "carbonara"' in nothing and "User: what's the weather" in nothing
    assert "kept for 7 days" in nothing
    none_kept = follow_up(kept(tmp_path), "", "2026-11-22", "what did we talk about on Sunday?")
    assert none_kept.startswith("No conversations are kept from Sunday 22 November")
    too_old = follow_up(kept(tmp_path), "lamps", "2026-10-01", "what did I say on 1 October?")
    assert "from Thursday 1 October" in too_old and "kept for 7 days" in too_old


# ----- the router: Claude asks, Abdoh finds, Claude answers -----


def recall_router(tmp_path, brain, **cfg):
    path = tmp_path / "commands.yaml"
    path.write_text("[]", encoding="utf-8")
    router = Router(Config(app_dir=tmp_path, **cfg), CommandRegistry(path), brain=brain,
                    act=FakeAct())  # fmt: skip
    seen = []
    router.on_activity = seen.append
    return router, seen


def test_claude_recalls_and_then_answers(tmp_path):
    talks = Conversations(tmp_path / FOLDER)
    talks.add("how do I make carbonara", "Eggs, pecorino, guanciale, no cream.")
    brain = LookingBrain(
        first=("ACTION recall: carbonara | \n",), second=("You said eggs ", "and pecorino.")
    )
    router, seen = recall_router(tmp_path, brain)
    said = list(router.handle("what was in the carbonara you told me about"))
    assert said == ["You said eggs and pecorino."] and seen == ["Remembering"]
    (_, _), (message, image) = brain.asked
    assert image is None and "Eggs, pecorino, guanciale" in message
    assert '"what was in the carbonara you told me about"' in message


def test_only_one_recall_per_request(tmp_path):
    brain = LookingBrain(
        first=("ACTION recall: lamps | \n",),
        second=("ACTION recall: again |\n", "I don't remember."),
    )
    router, seen = recall_router(tmp_path, brain)
    assert list(router.handle("what did I say about the lamps")) == ["I don't remember."]
    assert len(brain.asked) == 2


@pytest.mark.parametrize("cfg", [{"memory": False}, {"keep_conversations": False}])
def test_no_recall_when_conversations_are_not_kept(tmp_path, cfg):
    brain = LookingBrain(first=("ACTION recall: lamps | \n", "I can't remember that."))
    router, seen = recall_router(tmp_path, brain, **cfg)
    assert list(router.handle("what did I say about the lamps")) == ["I can't remember that."]
    assert len(brain.asked) == 1 and seen == []


def test_claude_is_told_only_while_they_are_kept(tmp_path):
    def prompt(**cfg):
        return system_prompt(Config(app_dir=tmp_path, **cfg))

    assert "ACTION recall:" in prompt() and "last 7 days" in prompt()
    assert "ACTION recall:" not in prompt(keep_conversations=False)
    assert "ACTION recall:" not in prompt(memory=False)
    assert "last 14 days" in prompt(conversation_days=14)
