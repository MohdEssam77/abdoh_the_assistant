"""Memory: what Abdoh remembers about you (facts) and what works on this computer (lessons),
across conversations. Claude adds and forgets; nothing is kept or sent with memory off."""

from datetime import date

import pytest
from test_router import FakeAct, FakeBrain

from abdoh.claude.brain import system_prompt
from abdoh.commands.registry import CommandRegistry
from abdoh.config import Config
from abdoh.memory import (
    FULL,
    MAX_CHARS,
    MAX_ENTRIES,
    NOT_THERE,
    Entry,
    Memory,
    MemoryChangeError,
    MemoryFileError,
    for_claude,
)
from abdoh.router import Router


def memory(tmp_path) -> Memory:
    return Memory(tmp_path / "memory.yaml", today=lambda: date(2026, 11, 23))


# ----- the file -----


def test_add_and_forget(tmp_path):
    mem = memory(tmp_path)
    assert mem.load() == []
    mem.add("Their sister is called  Lina.")
    mem.add("WhatsApp: maximize its main window.", "lesson")
    assert mem.load() == [
        Entry("Their sister is called Lina.", "fact", "2026-11-23"),
        Entry("WhatsApp: maximize its main window.", "lesson", "2026-11-23"),
    ]
    assert memory(tmp_path).load() == mem.load()  # it's in the file
    assert mem.forget("their sister is called lina").text == "Their sister is called Lina."
    assert [e.kind for e in mem.load()] == ["lesson"]


def test_the_same_thing_is_kept_once(tmp_path):
    mem = memory(tmp_path)
    mem.add("They like jazz.")
    mem.add("they like jazz")
    assert len(mem.load()) == 1


def test_forget_finds_nearly_the_same_words(tmp_path):
    mem = memory(tmp_path)
    mem.add("Their sister is called Lina.")
    mem.add("They work at the university.")
    assert mem.forget("Their sister's called Lina").text == "Their sister is called Lina."
    with pytest.raises(MemoryChangeError, match=NOT_THERE):
        mem.forget("They have a dog.")
    assert len(mem.load()) == 1


def test_the_limits(tmp_path):
    mem = memory(tmp_path)
    for i in range(MAX_ENTRIES):
        mem.add(f"Fact number {i}.")
    with pytest.raises(MemoryChangeError, match="full"):
        mem.add("One more.")
    assert len(mem.load()) == MAX_ENTRIES
    long = memory(tmp_path / "long")
    for i in range(MAX_CHARS // 290):
        long.add(f"{i} " + "x" * 285)
    with pytest.raises(MemoryChangeError) as e:
        long.add("y" * 290)
    assert str(e.value) == FULL
    with pytest.raises(MemoryChangeError, match="too long"):
        long.add("z" * 400)


def test_a_broken_file_is_never_overwritten(tmp_path):
    path = tmp_path / "memory.yaml"
    path.write_text("- text: [broken", encoding="utf-8")
    mem = memory(tmp_path)
    with pytest.raises(MemoryFileError):
        mem.add("They like jazz.")
    assert path.read_text(encoding="utf-8") == "- text: [broken"
    assert mem.entries() == []  # Claude just gets nothing meanwhile


def test_the_page_changes_an_entry_in_place(tmp_path):
    mem = memory(tmp_path)
    mem.add("They like jazz.")
    mem.add("Their sister is called Lina.")
    mem.change("They like jazz.", "They like jazz and soul.", "fact")
    assert [e.text for e in mem.load()] == [
        "They like jazz and soul.",
        "Their sister is called Lina.",
    ]
    with pytest.raises(MemoryChangeError, match="already"):
        mem.change("They like jazz and soul.", "Their sister is called Lina.", "fact")


# ----- what Claude gets -----


def test_claude_knows_what_you_told_it(tmp_path):
    mem = memory(tmp_path)
    mem.add("Their sister is called Lina.")
    mem.add("WhatsApp: maximize its main window.", "lesson")
    text = system_prompt(Config(app_dir=tmp_path))
    assert "What you know about the user:\n- Their sister is called Lina." in text
    assert "Lessons (what works on this computer):\n- WhatsApp: maximize its main window." in text
    assert "ACTION remember:" in text and "ACTION lesson:" in text and "ACTION forget:" in text


def test_the_prompt_carries_the_never_store_rule(tmp_path):
    text = system_prompt(Config(app_dir=tmp_path))
    assert "never passwords, keys, card numbers or health details" in text
    assert "You don't know anything about the user yet." in text


def test_off_sends_nothing(tmp_path):
    memory(tmp_path).add("Their sister is called Lina.")
    text = system_prompt(Config(app_dir=tmp_path, memory=False))
    assert "Lina" not in text and "ACTION remember" not in text


def test_nearly_full_says_to_merge_first(tmp_path):
    mem = memory(tmp_path)
    for i in range(MAX_ENTRIES):
        mem.add(f"Fact number {i}.")
    assert "nearly full" in system_prompt(Config(app_dir=tmp_path))
    assert "nearly full" not in system_prompt(Config(app_dir=tmp_path / "empty"))


def test_facts_and_lessons_apart():
    text = for_claude([Entry("A.", "fact"), Entry("B.", "lesson"), Entry("C.", "fact")])
    assert (
        text
        == "What you know about the user:\n- A.\n- C.\nLessons (what works on this computer):\n- B."
    )


# ----- Claude remembers and forgets -----


def make_router(tmp_path, reply: str, memory_on: bool = True) -> Router:
    path = tmp_path / "commands.yaml"
    path.write_text("[]", encoding="utf-8")
    router = Router(
        Config(app_dir=tmp_path, memory=memory_on), CommandRegistry(path), act=FakeAct()
    )
    router.brain = FakeBrain((reply,))
    return router


def test_claude_remembers(tmp_path):
    router = make_router(
        tmp_path, "ACTION remember: Their sister is called Lina.\nNice, I'll remember."
    )
    told = []
    router.on_memory = lambda: told.append(True)
    assert " ".join(router.handle("my sister is called Lina")) == "Nice, I'll remember."
    assert [e.text for e in memory(tmp_path).load()] == ["Their sister is called Lina."]
    assert told == [True]  # the Memory page refreshes


def test_claude_learns_a_lesson_and_forgets(tmp_path):
    router = make_router(tmp_path, "ACTION lesson: Spotify: open it before pressing play.")
    list(router.handle("play some jazz"))
    assert memory(tmp_path).load()[0].kind == "lesson"
    router.brain = FakeBrain(("ACTION forget: Spotify: open it before pressing play.\nForgotten.",))
    assert " ".join(router.handle("forget that")) == "Forgotten."
    assert memory(tmp_path).load() == []


def test_claude_is_told_when_it_cant(tmp_path):
    router = make_router(tmp_path, "ACTION forget: They have a dog.\nDone.")
    assert " ".join(router.handle("forget my dog")) == f"{NOT_THERE} Done."


def test_off_offers_no_memory_actions(tmp_path):
    router = make_router(tmp_path, "ACTION remember: Their sister is called Lina.\nOkay.", False)
    assert " ".join(router.handle("my sister is called Lina")) == "Okay."
    assert not (tmp_path / "memory.yaml").exists()  # nothing kept


def test_remember_that_after_telling_it_something_goes_to_claude(tmp_path):
    router = make_router(tmp_path, "My sister is Lina? Nice.")
    list(router.handle("my sister is called Lina"))
    router.brain = FakeBrain(("ACTION remember: Their sister is called Lina.\nGot it.",))
    assert " ".join(router.handle("remember that")) == "Got it."  # not "nothing to remember"
    assert memory(tmp_path).load()[0].text == "Their sister is called Lina."


# ----- the Memory page -----


def make_api(tmp_path):
    from abdoh.events import Bus
    from abdoh.ui.api import AppApi, UiState

    return AppApi(Bus(), UiState(), Config(app_dir=tmp_path))


def test_the_memory_page(tmp_path):
    api = make_api(tmp_path)
    assert api.add_memory("My sister is called Lina.", "fact")["ok"]
    assert api.add_memory("  ", "fact") == {"ok": False, "error": "There's nothing to remember."}
    page = api.memory()
    assert [e["text"] for e in page["entries"]] == ["My sister is called Lina."]
    assert page["max_entries"] == MAX_ENTRIES and page["chars"] == len("My sister is called Lina.")
    assert api.change_memory(
        "My sister is called Lina.", "My sister Lina lives in Berlin.", "fact"
    )["ok"]
    assert api.forget_memory("My sister Lina lives in Berlin.")["ok"]
    assert api.memory()["entries"] == []


def test_the_page_says_when_the_file_is_broken(tmp_path):
    (tmp_path / "memory.yaml").write_text("- text: [broken", encoding="utf-8")
    result = make_api(tmp_path).memory()
    assert not result["ok"] and "can't be read" in result["error"]


def test_the_page_refreshes_when_claude_changes_the_memory(tmp_path):
    from fakes import FakeTranscriber, FakeWakeWord

    from abdoh.daemon import Daemon
    from abdoh.events import Bus
    from abdoh.speech.tts import FakeSpeaker

    router = Router(Config(app_dir=tmp_path), CommandRegistry(tmp_path / "none.yaml"))
    bus = Bus()
    Daemon(Config(app_dir=tmp_path), router, FakeSpeaker(), None, FakeWakeWord(99),
           FakeTranscriber([]), bus=bus)  # fmt: skip
    router.on_memory()
    assert ("memory", None) in bus.pending_events()
