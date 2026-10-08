from abdoh.commands.matcher import normalize, strip_wake_words

WAKE = ["abdoh", "hey abdoh"]


def test_normalize():
    assert normalize("  Hey, Abdoh!  What's the TIME? ") == "hey abdoh whats the time"


def test_strip_wake_words_start_and_end():
    assert strip_wake_words("Hey Abdoh, what time is it?", WAKE) == "what time is it"
    assert strip_wake_words("Good morning Abdoh.", WAKE) == "good morning"
    assert strip_wake_words("Hey Abdoh.", WAKE) == ""


def test_strip_wake_words_whole_words_only():
    assert strip_wake_words("abdohs house", WAKE) == "abdohs house"
