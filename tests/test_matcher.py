import pytest

from abdoh.commands.matcher import match, normalize, strip_wake_words
from abdoh.commands.registry import Command

WAKE = ["abdoh", "hey abdoh"]

COMMANDS = [
    Command("good_morning", ["good morning"], [("say", "hi")]),
    Command("open_mail", ["open my mail", "open email"], [("open_url", "https://mail")]),
    Command("open_vscode", ["open code", "open vs code"], [("open_app", "code")]),
    Command("what_time", ["what time is it", "time"], [("say", "{time}")]),
]


def matched(text):
    found = match(text, COMMANDS, 85, WAKE)
    return found[0].name if found else None


def test_normalize():
    assert normalize("  Hey, Abdoh!  What's the TIME? ") == "hey abdoh whats the time"


def test_strip_wake_words_start_and_end():
    assert strip_wake_words("Hey Abdoh, what time is it?", WAKE) == "what time is it"
    assert strip_wake_words("Good morning Abdoh.", WAKE) == "good morning"
    assert strip_wake_words("Hey Abdoh.", WAKE) == ""


def test_strip_wake_words_whole_words_only():
    assert strip_wake_words("abdohs house", WAKE) == "abdohs house"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("good morning", "good_morning"),
        ("Good morning, Abdoh!", "good_morning"),  # wake word at end
        ("Hey Abdoh, good morning.", "good_morning"),  # wake word at start
        ("good mornin", "good_morning"),  # typo
        ("goood morning abdoh", "good_morning"),  # typo + wake word
        ("open my email", "open_mail"),
        ("Hey Abdoh, open VS Code", "open_vscode"),
        ("what time is it", "what_time"),
        ("what time is it now", "what_time"),
        ("Time?", "what_time"),
    ],
)
def test_matches(text, expected):
    assert matched(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "what's the time difference between cairo and tokyo",
        "what's the capital of japan",
        "summarize my screen",
        "Hey Abdoh.",
        "",
    ],
)
def test_no_match(text):
    assert matched(text) is None
