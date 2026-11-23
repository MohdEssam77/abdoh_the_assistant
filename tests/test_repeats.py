"""Asked for the same several-step thing again: Claude offers once to make it a command
(abdoh/commands/repeats.py, the router noting it, the prompt telling Claude)."""

import json
from datetime import date

from test_router import FakeAct, FakeBrain, text_of

from abdoh.claude.brain import ASKED_ONCE, BEFORE, system_prompt
from abdoh.commands import repeats
from abdoh.commands.registry import CommandRegistry
from abdoh.config import Config
from abdoh.router import Router

SPOTIFY = [("open_app", "Spotify"), ("volume", "30")]
TWO_STEPS = "ACTION open_app: Spotify\nACTION volume: 30\n"


def path_in(tmp_path):
    return tmp_path / repeats.FILE


def saved(tmp_path):
    return json.loads(path_in(tmp_path).read_text(encoding="utf-8"))


# ----- the record -----


def test_several_steps_are_noted_and_counted(tmp_path):
    path = path_in(tmp_path)
    repeats.record(path, "open spotify at 30", SPOTIFY, date(2026, 11, 23))
    assert saved(tmp_path) == [
        {
            "request": "open spotify at 30",
            "steps": [["open_app", "Spotify"], ["volume", "30"]],
            "times": 1,
            "last": "2026-11-23",
        }
    ]
    repeats.record(path, "spotify please, volume 30", SPOTIFY)
    [entry] = saved(tmp_path)
    assert entry["times"] == 2 and entry["request"] == "spotify please, volume 30"


def test_a_single_action_is_never_noted(tmp_path):
    repeats.record(path_in(tmp_path), "open spotify", [("open_app", "Spotify")])
    assert not path_in(tmp_path).exists()


def test_only_the_most_recent_are_kept(tmp_path):
    path = path_in(tmp_path)
    for i in range(repeats.KEEP + 5):
        repeats.record(path, f"thing {i}", [("open_app", "Notion"), ("volume", str(i))])
    entries = saved(tmp_path)
    assert len(entries) == repeats.KEEP and entries[-1]["request"] == f"thing {repeats.KEEP + 4}"


def test_a_broken_file_starts_again(tmp_path):
    path_in(tmp_path).write_text("{not json", encoding="utf-8")
    assert repeats.for_claude(path_in(tmp_path), []) == ""
    repeats.record(path_in(tmp_path), "open spotify at 30", SPOTIFY)
    assert len(saved(tmp_path)) == 1


def test_claude_hears_of_what_was_asked_once_and_isnt_a_command(tmp_path):
    path = path_in(tmp_path)
    repeats.record(path, "open spotify at 30", SPOTIFY)
    repeats.record(path, "work setup", [("open_app", "Notion"), ("open_app", "Slack")])
    repeats.record(path, "movie night", [("lamp", "all | off"), ("volume", "60")])
    repeats.record(path, "movie night", [("lamp", "all | off"), ("volume", "60")])  # twice: done
    text = repeats.for_claude(path, saved=[[("open_app", "Notion"), ("open_app", "Slack")]])
    assert text == '- "open spotify at 30" (open_app: Spotify; volume: 30)'


def test_newest_first_and_only_a_few(tmp_path):
    path = path_in(tmp_path)
    for i in range(repeats.SHOWN + 3):
        repeats.record(path, f"thing {i}", [("open_app", "Notion"), ("volume", str(i))])
    lines = repeats.for_claude(path, []).splitlines()
    assert len(lines) == repeats.SHOWN and lines[0].startswith(f'- "thing {repeats.SHOWN + 2}"')


# ----- the router notes it -----


def router_for(tmp_path, reply=TWO_STEPS, memory=True):
    commands = tmp_path / "commands.yaml"
    commands.write_text("[]", encoding="utf-8")
    router = Router(
        Config(app_dir=tmp_path, memory=memory), CommandRegistry(commands), act=FakeAct()
    )
    router.brain = FakeBrain((reply,))
    return router


def test_claude_doing_several_things_is_noted(tmp_path):
    router = router_for(tmp_path)
    text_of(router.handle("open spotify at 30"))
    assert saved(tmp_path)[0]["request"] == "open spotify at 30"
    text_of(router.handle("spotify at 30 please"))
    assert saved(tmp_path)[0]["times"] == 2


def test_nothing_is_noted_with_memory_off(tmp_path):
    text_of(router_for(tmp_path, memory=False).handle("open spotify at 30"))
    assert not path_in(tmp_path).exists()


def test_what_was_saved_right_away_isnt_noted(tmp_path):
    router = router_for(tmp_path, TWO_STEPS + "ACTION save_steps: music time\n")
    assert text_of(router.handle("spotify at 30, save it as music time")) == (
        "Saved. Next time just say: music time."
    )
    assert not path_in(tmp_path).exists()


def test_failed_steps_arent_noted(tmp_path):
    router = router_for(tmp_path)
    router._act = FakeAct(fail="I couldn't find Spotify.")
    text_of(router.handle("open spotify at 30"))
    assert not path_in(tmp_path).exists()


# ----- the prompt -----


def test_claude_is_told_to_offer_and_what_was_asked_once(tmp_path):
    cfg = Config(app_dir=tmp_path)
    plain = system_prompt(cfg)
    assert "ask once in one short sentence whether to save it as a command" in plain
    assert f"({BEFORE})" in plain and "Asked for once before" not in plain
    repeats.record(path_in(tmp_path), "open spotify at 30", SPOTIFY)
    told = system_prompt(cfg)
    assert (
        ASKED_ONCE.format(things='- "open spotify at 30" (open_app: Spotify; volume: 30)') in told
    )


def test_a_command_with_those_steps_isnt_offered(tmp_path):
    repeats.record(path_in(tmp_path), "open spotify at 30", SPOTIFY)
    (tmp_path / "commands.yaml").write_text(
        '- name: music\n  triggers: ["music time"]\n  actions:\n'
        '    - open_app: "Spotify"\n    - volume: 30\n',
        encoding="utf-8",
    )
    assert "Asked for once before" not in system_prompt(Config(app_dir=tmp_path))


def test_with_memory_off_claude_only_goes_by_this_conversation(tmp_path):
    repeats.record(path_in(tmp_path), "open spotify at 30", SPOTIFY)
    text = system_prompt(Config(app_dir=tmp_path, memory=False))
    assert "Asked for once before" not in text and f"({BEFORE})" in text
