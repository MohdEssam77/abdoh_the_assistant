"""Abdoh's log, read back (abdoh/logs.py): the window's Log, and ACTION logs."""

from datetime import datetime

from abdoh import logs
from abdoh.claude.brain import system_prompt
from abdoh.commands.registry import CommandRegistry
from abdoh.config import Config
from abdoh.router import READING_LOG, Router

TODAY = """\
2026-11-26 09:00:01,100 INFO abdoh.daemon: You: what's the weather
2026-11-26 09:00:02,200 INFO abdoh.claude.code: Claude is using WebSearch
2026-11-26 09:00:05,300 WARNING abdoh.audio.stt: Slow transcription: 2.10s
2026-11-26 09:10:00,000 ERROR abdoh.daemon: Error handling 'play jazz'
Traceback (most recent call last):
  File "daemon.py", line 1, in handle
RuntimeError: boom
2026-11-26 09:20:00,000 INFO abdoh.claude.chatgpt: Signed in, token Bearer abcdefghijklmnop
2026-11-26 09:21:00,000 INFO abdoh.claude.api: key sk-ant-api03-ABCDEFGHIJKLMNOP saved
"""
YESTERDAY = """\
2026-11-25 20:27:03,112 INFO abdoh.daemon: You: Uh okay you can stop now
2026-11-25 20:27:04,000 WARNING abdoh.claude.code: Claude Code reported an error: usage limit
"""
NOW = datetime(2026, 11, 26, 9, 25)


def write_logs(tmp_path):
    path = tmp_path / "abdoh.log"
    path.write_text(TODAY, encoding="utf-8")
    (tmp_path / "abdoh.log.2026-11-25").write_text(YESTERDAY, encoding="utf-8")
    return path


def test_entries_of_both_days_in_order_with_tracebacks(tmp_path):
    entries = logs.read_entries(write_logs(tmp_path))
    assert [e.time.day for e in entries] == [25, 25, 26, 26, 26, 26, 26, 26]
    error = next(e for e in entries if e.level == "ERROR")
    assert error.text == "Error handling 'play jazz'"
    assert "RuntimeError: boom" in error.details
    assert error.part == "Abdoh" and error.problem
    assert entries[3].part == "Claude"
    assert next(e for e in entries if "Slow" in e.text).part == "Speech"


def test_keys_and_tokens_are_hidden(tmp_path):
    text = "\n".join(e.text for e in logs.read_entries(write_logs(tmp_path)))
    assert "abcdefghijklmnop" not in text and "ABCDEFGHIJKLMNOP" not in text
    assert text.count(logs.HIDDEN) == 2
    assert logs.hide_secrets("got code=abc123&state=x") == f"got code={logs.HIDDEN}&state=x"
    assert logs.hide_secrets("exit 1, nothing secret") == "exit 1, nothing secret"


def test_pick_by_time_problems_and_words(tmp_path):
    entries = logs.read_entries(write_logs(tmp_path))
    assert len(logs.pick(entries, problems=True)) == 3
    assert [e.text for e in logs.pick(entries, search="weather")] == ["You: what's the weather"]
    since = datetime(2026, 11, 26, 9, 5)
    assert len(logs.pick(entries, since=since)) == 3
    assert len(logs.pick(entries, limit=2)) == 2


def test_spans_from_words():
    assert logs.span("", NOW)[2] == "the last 30 minutes"
    start, end, words = logs.span("yesterday", NOW)
    assert (start.day, end.day, words) == (25, 26, "yesterday")
    assert logs.span("the last 10 minutes", NOW)[2] == "the last 10 minutes"
    assert logs.span("just now", NOW)[2] == "the last 5 minutes"
    start, _, words = logs.span("an hour ago", NOW)
    assert words == "the last 1 hour" and start < datetime(2026, 11, 26, 8, 25)
    assert logs.span("this morning", NOW)[2] == "this morning"
    assert logs.span("today", NOW)[0] == datetime(2026, 11, 26)


def test_for_claude_keeps_problems_and_words_first():
    entries = [
        logs.Entry(datetime(2026, 11, 26, 9, 0, i % 60), "INFO", "abdoh.daemon", f"line {i}")
        for i in range(400)
    ]
    entries[3].level = "ERROR"
    entries[5].text = "the microphone went quiet"
    chosen, left = logs.for_claude(entries, "why was the microphone quiet")
    assert len(chosen) == logs.FOR_CLAUDE_ENTRIES and left == 200
    assert entries[3] in chosen and entries[5] in chosen
    assert chosen[-1] is entries[-1]  # the latest of the rest


def test_claude_lines_are_short():
    e = logs.Entry(datetime(2026, 11, 26, 9, 10), "ERROR", "abdoh.daemon", "boom")
    e.details = "Traceback\n  File x\n  line 1\nRuntimeError: boom"
    assert (
        logs.claude_line(e) == "09:10:00 ERROR Abdoh: boom | File x / line 1 / RuntimeError: boom"
    )


def test_follow_up_has_the_log_and_how_it_works(tmp_path):
    cfg = Config(app_dir=tmp_path, log_file=str(write_logs(tmp_path)))
    text = logs.follow_up(cfg, "the error | the last hour", "did anything go wrong?", now=NOW)
    assert "Error handling 'play jazz'" in text and "RuntimeError: boom" in text
    assert "How Abdoh is meant to work" in text and '"did anything go wrong?"' in text
    empty = logs.follow_up(cfg, "x | yesterday", "why?", now=datetime(2026, 11, 28, 9))
    assert "has nothing for yesterday" in empty


def test_page_entries():
    e = logs.Entry(datetime(2026, 11, 25, 20, 27, 3), "WARNING", "abdoh.claude.code", "limit")
    shown = logs.for_page(e, today=NOW)
    assert shown == {
        "time": "20:27:03",
        "day": "yesterday",
        "level": "WARNING",
        "part": "Claude",
        "text": "limit",
        "details": "",
    }


# ----- ACTION logs -----


class Brain:
    remembers = True

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def stream(self, prompt, image_png=None):
        self.prompts.append(prompt)
        yield self.answers.pop(0)


def recent_log(tmp_path):
    """A log written a few minutes ago (the router reads it at the real time)."""
    from datetime import timedelta

    at = datetime.now() - timedelta(minutes=3)
    stamp = f"{at:%Y-%m-%d %H:%M:%S},000"
    path = tmp_path / "abdoh.log"
    path.write_text(
        f"{stamp} INFO abdoh.daemon: You: play jazz\n"
        f"{stamp} ERROR abdoh.daemon: Error handling 'play jazz'\n",
        encoding="utf-8",
    )
    return path


def test_claude_reads_the_log_and_answers(tmp_path):
    cfg = Config(app_dir=tmp_path, log_file=str(recent_log(tmp_path)))
    brain = Brain("ACTION logs: errors | today\n", "Playing jazz failed with an error.")
    router = Router(cfg, CommandRegistry(tmp_path / "commands.yaml"), brain=brain)
    seen = []
    router.on_activity = seen.append
    reply = " ".join(router.handle("check your logs, did anything go wrong today?"))
    assert reply == "Playing jazz failed with an error."
    assert seen == [READING_LOG]
    assert "Error handling 'play jazz'" in brain.prompts[1]


def test_the_permission_turns_it_off(tmp_path):
    cfg = Config(app_dir=tmp_path, log_file=str(write_logs(tmp_path)))
    assert "ACTION logs:" in system_prompt(cfg)
    cfg.claude.allow_logs = False
    assert "ACTION logs:" not in system_prompt(cfg)
    brain = Brain("ACTION logs: errors | today\nI can't check.")
    router = Router(cfg, CommandRegistry(tmp_path / "commands.yaml"), brain=brain)
    assert " ".join(router.handle("check your logs")) == "I can't check."
    assert len(brain.prompts) == 1


# ----- the window -----


def test_window_api_newest_first(tmp_path):
    from abdoh.events import Bus
    from abdoh.ui.api import AppApi, UiState

    cfg = Config(app_dir=tmp_path, log_file=str(write_logs(tmp_path)))
    opened = []
    api = AppApi(Bus(ui_attached=True), UiState(), cfg, open_path=opened.append)
    result = api.logs()
    assert result["ok"] and result["total"] == 8 and result["problems"] == 3
    assert result["entries"][0]["text"].startswith("key")
    assert [e["level"] for e in api.logs(problems=True)["entries"]] == [
        "ERROR",
        "WARNING",
        "WARNING",
    ]
    assert api.open_log() and opened == [tmp_path / "abdoh.log"]
