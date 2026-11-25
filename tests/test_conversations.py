"""A week of conversations: what's kept, what isn't, and when it goes."""

from datetime import date, datetime, timedelta

import pytest
from test_daemon import StubRouter, make_daemon

from abdoh.config import Config
from abdoh.conversations import FOLDER, MAX_ABDOH, Conversations, Exchange, day_label
from abdoh.events import Bus
from abdoh.system_skills import Done

NOW = datetime(2026, 11, 25, 14, 3, 7)


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


def kept(folder, now=NOW, days=7):
    return Conversations(folder, days, now=Clock(now))


def test_an_exchange_is_kept_with_its_time_mode_role_and_board(tmp_path):
    talks = kept(tmp_path)
    talks.add("what does carbonara look like?", "Here it is.", role="Chef", board="## Carbonara")
    talks.add("movie mode", "Done.", typed=True, mode="Movie")
    first, second = talks.day(NOW.date())
    assert first.as_item() == {
        "at": "14:03", "you": "what does carbonara look like?", "abdoh": "Here it is.",
        "typed": False, "mode": "", "role": "Chef", "board": "## Carbonara",
    }  # fmt: skip
    assert second.typed and second.mode == "Movie"
    assert (tmp_path / "2026-11-25.jsonl").read_text(encoding="utf-8").count("\n") == 2


@pytest.mark.parametrize("you, abdoh", [("", "Hi."), ("hello", ""), ("  ", "  ")])
def test_nothing_is_kept_without_both_sides(tmp_path, you, abdoh):
    assert kept(tmp_path).add(you, abdoh) is None
    assert not list(tmp_path.iterdir())


def test_a_very_long_answer_is_cut(tmp_path):
    talks = kept(tmp_path)
    talks.add("tell me everything", "word " * 5000)
    (exchange,) = talks.day(NOW.date())
    assert len(exchange.abdoh) == MAX_ABDOH and exchange.abdoh.endswith("…")


def test_a_week_is_kept_and_older_days_are_deleted(tmp_path):
    for back in range(10):
        kept(tmp_path, NOW - timedelta(days=back)).add(f"day {back}", "ok")
    talks = kept(tmp_path)
    assert talks.clean() == 2  # 8 and 9 days ago
    assert [d for d, _ in talks.days_kept()] == [NOW.date() - timedelta(days=b) for b in range(8)]
    assert talks.oldest_kept() == date(2026, 11, 18)


def test_the_first_exchange_of_a_day_cleans_up(tmp_path):
    kept(tmp_path, NOW - timedelta(days=9)).add("old", "ok")
    kept(tmp_path).add("new", "ok")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["2026-11-25.jsonl"]


def test_days_newest_first_with_how_many(tmp_path):
    kept(tmp_path, NOW - timedelta(days=1)).add("a", "b")
    for _ in range(3):
        kept(tmp_path).add("c", "d")
    assert kept(tmp_path).days_kept() == [(date(2026, 11, 25), 3), (date(2026, 11, 24), 1)]


def test_exchanges_between_two_days(tmp_path):
    for back in range(4):
        kept(tmp_path, NOW - timedelta(days=back)).add(f"day {back}", "ok")
    talks = kept(tmp_path)
    found = talks.exchanges(date(2026, 11, 23), date(2026, 11, 24))
    assert [e.you for e in found] == ["day 2", "day 1"]
    assert [e.you for e in talks.exchanges()] == ["day 3", "day 2", "day 1", "day 0"]


def test_delete_a_day_and_forget_all(tmp_path):
    kept(tmp_path, NOW - timedelta(days=1)).add("a", "b")
    talks = kept(tmp_path)
    talks.add("c", "d")
    assert talks.delete_day(date(2026, 11, 24)) and not talks.delete_day(date(2026, 11, 24))
    assert talks.forget_all() == 1 and talks.days_kept() == []


def test_a_broken_line_is_skipped(tmp_path):
    talks = kept(tmp_path)
    talks.add("first", "one")
    with (tmp_path / "2026-11-25.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"at": "2026-11-25T14:04:00", "you": "cut of\n')  # the computer went off
    talks.add("second", "two")
    assert [e.you for e in talks.day(NOW.date())] == ["first", "second"]
    assert Exchange.read("not json") is None


def test_other_files_in_the_folder_are_left_alone(tmp_path):
    (tmp_path / "notes.txt").write_text("mine")
    (tmp_path / "2020-01-01.jsonl.bak").write_text("mine")
    kept(tmp_path).clean()
    kept(tmp_path).forget_all()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["2020-01-01.jsonl.bak", "notes.txt"]


@pytest.mark.parametrize(
    "day, label",
    [
        (date(2026, 11, 25), "Today"),
        (date(2026, 11, 24), "Yesterday"),
        (date(2026, 11, 21), "Saturday 21 November"),
        (date(2025, 12, 31), "Wednesday 31 December 2025"),
    ],
)
def test_day_labels(day, label):
    assert day_label(day, date(2026, 11, 25)) == label


def test_a_week_of_a_busy_owner_is_small(tmp_path):
    """The owner's heaviest day so far was about 52 KB of log: a week stays well under 1 MB."""
    talks = kept(tmp_path)
    for _ in range(150):
        talks.add("explain the pumping lemma once more " * 3, "Sure. " * 60, role="Professor")
    assert (tmp_path / "2026-11-25.jsonl").stat().st_size < 100_000


# ----- the daemon keeps what you said and what it answered -----


def daemon_with(tmp_path, replies, **cfg):
    bus = Bus()
    daemon = make_daemon(StubRouter(replies), cfg=Config(app_dir=tmp_path, **cfg), bus=bus)
    return daemon, Conversations(tmp_path / FOLDER)


def test_spoken_and_typed_requests_are_kept(tmp_path):
    daemon, talks = daemon_with(tmp_path, ["It's sunny.", Done(""), iter(["Sure.", "Here."])])
    daemon.handle_text("what's the weather", voice=True)
    daemon.handle_text("open spotify")
    daemon.handle_text("tell me more")
    found = talks.exchanges()
    assert [(e.you, e.abdoh, e.typed) for e in found] == [
        ("what's the weather", "It's sunny.", False),
        ("open spotify", "Done.", True),
        ("tell me more", "Sure. Here.", True),
    ]
    assert ("conversations", None) in daemon.bus.pending_events()


@pytest.mark.parametrize("cfg", [{"memory": False}, {"keep_conversations": False}])
def test_nothing_is_kept_with_memory_or_the_switch_off(tmp_path, cfg):
    daemon, talks = daemon_with(tmp_path, ["It's sunny."], **cfg)
    daemon.handle_text("what's the weather")
    assert talks.exchanges() == [] and not (tmp_path / FOLDER).exists()


def test_what_abdoh_says_by_itself_is_not_kept(tmp_path):
    daemon, talks = daemon_with(tmp_path, [])
    daemon.announce("Your 10 minute timer is done.")
    assert talks.exchanges() == []


def test_what_was_not_meant_for_abdoh_is_not_kept(tmp_path):
    class Turn:
        ignored, actions = True, []

    daemon, talks = daemon_with(tmp_path, [iter([])])
    daemon.router.last_turn = Turn()
    daemon.handle_text("no, I was talking to my sister", voice=True, woken=True)
    assert talks.exchanges() == []


def test_the_board_and_the_role_are_kept_with_the_answer(tmp_path):
    class Role:
        name = "Chef"

    class Acting:
        current = Role()

    daemon, talks = daemon_with(tmp_path, [])

    def answer():
        daemon._on_board(7, "## Carbonara")
        yield "Here it is."

    daemon.router.replies = [answer()]
    daemon.router.acting = Acting()
    daemon.handle_text("show me carbonara")
    (exchange,) = talks.exchanges()
    assert (exchange.role, exchange.board, exchange.abdoh) == (
        "Chef",
        "## Carbonara",
        "Here it is.",
    )


def test_housekeeping_deletes_old_conversations(tmp_path):
    old = datetime.now() - timedelta(days=9)
    kept(tmp_path / FOLDER, now=old).add("old", "ok")  # 9 days ago
    daemon, talks = daemon_with(tmp_path, [])
    daemon._housekeeping_tick()
    assert not list((tmp_path / FOLDER).iterdir())


# ----- the Memory page -----


def test_the_memory_page_lists_opens_and_deletes_days(tmp_path, monkeypatch):
    from abdoh.ui.api import AppApi, UiState

    monkeypatch.setattr("abdoh.conversations.datetime", FrozenDatetime)
    api = AppApi(Bus(), UiState(), Config(app_dir=tmp_path))
    kept(tmp_path / FOLDER, NOW - timedelta(days=4)).add("a", "b")
    kept(tmp_path / FOLDER).add("what's the weather", "It's sunny.")
    listed = api.conversations()
    assert listed["since"] == "Saturday 21 November" and listed["keep_days"] == 7
    assert [(d["label"], d["count"]) for d in listed["days"]] == [
        ("Today", 1),
        ("Saturday 21 November", 1),
    ]
    day = api.conversation_day("2026-11-25")
    assert (
        day["ok"] and day["label"] == "Today" and day["exchanges"][0]["you"] == "what's the weather"
    )
    assert api.conversation_day("2026-11-20")["ok"] is False
    assert api.conversation_day("../../etc")["ok"] is False
    assert api.delete_conversation_day("2026-11-21") == {"ok": True}
    assert api.forget_conversations() == {"ok": True, "days": 1}
    assert api.conversations()["days"] == []


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


def test_how_long_they_are_kept_is_a_setting(app_dir):
    from abdoh.settings import SettingsError, save_settings

    assert save_settings(app_dir, {"conversation_days": 14}).conversation_days == 14
    with pytest.raises(SettingsError):
        save_settings(app_dir, {"conversation_days": 0})
    assert save_settings(app_dir, {"keep_conversations": False}).keep_conversations is False
