import pytest

from abdoh.commands.matcher import match, normalize, strip_wake_words
from abdoh.commands.registry import Command

WAKE = ["krekos", "hey krekos"]

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
    assert normalize("  Hey, Krekos!  What's the TIME? ") == "hey krekos whats the time"


def test_strip_wake_words_start_and_end():
    assert strip_wake_words("Hey Krekos, what time is it?", WAKE) == "what time is it"
    assert strip_wake_words("Good morning Krekos.", WAKE) == "good morning"
    assert strip_wake_words("Hey Krekos.", WAKE) == ""


def test_strip_wake_words_whole_words_only():
    assert strip_wake_words("krekoss house", WAKE) == "krekoss house"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("good morning", "good_morning"),
        ("Good morning, Krekos!", "good_morning"),  # wake word at end
        ("Hey Krekos, good morning.", "good_morning"),  # wake word at start
        ("good mornin", "good_morning"),  # typo
        ("goood morning krekos", "good_morning"),  # typo + wake word
        ("open my email", "open_mail"),
        ("Hey Krekos, open VS Code", "open_vscode"),
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
        "Hey Krekos.",
        "",
    ],
)
def test_no_match(text):
    assert matched(text) is None


def test_remove_wake_words_keeps_your_wording():
    from abdoh.commands.matcher import remove_wake_words

    w = ["krekos", "hey krekos", "santos"]
    assert remove_wake_words("Hey Krekos, what's 15% of 80?", w) == "what's 15% of 80?"
    assert remove_wake_words("Good morning Krekos.", w) == "Good morning."
    assert remove_wake_words("Who is Santoshi, Krekos?", w) == "Who is Santoshi?"
    assert remove_wake_words("Krekos. Open Spotify.", w) == "Open Spotify."
    assert remove_wake_words("Krekos", w) == ""


def test_slot_triggers_capture_words():
    from abdoh.commands.matcher import match_command
    from abdoh.commands.registry import Command

    yt = Command("yt", ["search youtube for {query}", "play {query} on youtube"], [])
    exact = Command("cats", ["search youtube for cats"], [])
    commands = [yt, exact]
    found = match_command("search youtube for lofi music", commands, 85)
    assert found.command is yt and found.slots == {"query": "lofi music"}
    found = match_command("please play daft punk on youtube", commands, 85)
    assert found.command is yt and found.slots == {"query": "daft punk"}
    found = match_command("search youtube for cats", commands, 85)  # exact trigger wins
    assert found.command is exact and found.slots == {}
    assert match_command("search youtube", [yt], 85) is None  # the slot needs words


def test_slot_triggers_are_not_fuzzy_matched():
    from abdoh.commands.matcher import match
    from abdoh.commands.registry import Command

    yt = Command("yt", ["search youtube for {query}"], [])
    assert match("search youtube for", [yt], 50) is None
