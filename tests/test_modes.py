"""Modes: the file, the store, switching and putting things back, and the phrases (fakes)."""

import json

import pytest
import yaml

from abdoh.commands.actions import ActionError
from abdoh.modes.engine import BACK_TO_NORMAL, NO_MODE, ModeEngine
from abdoh.modes.model import ModesFileError, parse_modes
from abdoh.modes.store import TEMPLATES, ModesStore

# The owner's own two examples.
OWNER = """
- name: Movie
  icon: film
  phrases: ["movie night"]
  settings:
    displays: [2]
    volume: 60
  actions:
    - say: "Enjoy the movie."
  exit_actions:
    - media: play_pause
- name: Work
  icon: briefcase
  settings:
    displays: all
    brightness: 100
  actions:
    - play_youtube: "jazz music"
    - open_app: "Visual Studio Code"
"""


class Controls:
    """The computer's settings as plain values."""

    def __init__(self):
        self.values = {
            "displays": ["laptop", "hp", "wide"],
            "volume": [40, False],
            "brightness": {"laptop": 80},
            "dark_mode": False,
            "power_mode": "balanced",
            "audio_output": "spk",
            "wake_word": True,
            "voice_replies": True,
            "follow_up": 6.0,
        }
        self.applied = []
        self.fail = set()

    def capture(self, key):
        return self.values[key]

    def apply(self, key, value):
        if key in self.fail:
            raise ActionError(f"The {key} didn't change.")
        self.applied.append((key, value))
        self.values[key] = {
            "displays": ["laptop", "hp", "wide"] if value == "all" else value,
            "volume": [value, False],
            "brightness": {"laptop": value},
        }.get(key, value)

    def restore(self, key, snapshot):
        self.applied.append(("restore " + key, snapshot))
        self.values[key] = snapshot


def make(tmp_path, text=OWNER, controls=None):
    controls = controls or Controls()
    ran, shown = [], []

    def run(actions):
        ran.extend(actions)
        return [value for kind, value in actions if kind == "say"]

    engine = ModeEngine(
        lambda: parse_modes(yaml.safe_load(text)),
        controls,
        run,
        tmp_path / "mode_state.json",
        emit=shown.append,
    )
    return engine, controls, ran, shown


# ----- the file -----


def test_the_owners_modes_read():
    movie, work = parse_modes(yaml.safe_load(OWNER))
    assert movie.settings == {"displays": ["2"], "volume": 60}
    assert work.settings == {"displays": "all", "brightness": 100}
    assert work.actions == (("play_youtube", "jazz music"), ("open_app", "Visual Studio Code"))
    assert movie.exit_actions == (("media", "play_pause"),)


@pytest.mark.parametrize(
    "item, problem",
    [
        ({"name": "X", "settings": {"volume": 120}}, "volume must be a number from 0 to 100"),
        ({"name": "X", "settings": {"dark_mode": "yes"}}, "dark_mode must be true or false"),
        ({"name": "X", "settings": {"power_mode": "turbo"}}, "power_mode must be one of"),
        ({"name": "X", "settings": {"warp": 9}}, "unknown setting 'warp'"),
        ({"name": "X", "settings": {"displays": []}}, "displays is 'all' or a list"),
        ({"name": "X", "actions": [{"fly": "now"}]}, "unknown action 'fly'"),
        ({"name": "X", "actions": [{"say": "hi {name}"}]}, "can't use {slots} here"),
        ({"name": "X"}, "at least one setting or action"),
        ({"name": "Normal", "settings": {"volume": 5}}, "can't be called Normal"),
        ({"name": "X", "icon": "unicorn", "settings": {"volume": 5}}, "icon must be one of"),
    ],
)
def test_mistakes_are_explained(item, problem):
    with pytest.raises(ModesFileError, match=problem):
        parse_modes([item])


def test_two_modes_with_one_name():
    with pytest.raises(ModesFileError, match="two modes called work"):
        parse_modes([{"name": "Work", "settings": {"volume": 1}},
                     {"name": "work", "settings": {"volume": 2}}])  # fmt: skip


def test_screens_can_be_written_many_ways():
    (mode,) = parse_modes([{"name": "X", "settings": {"displays": "1, 3"}}])
    assert mode.settings["displays"] == ["1", "3"]
    (mode,) = parse_modes([{"name": "X", "settings": {"displays": 2}}])
    assert mode.settings["displays"] == ["2"]


# ----- the store -----


def test_the_store_saves_renames_and_deletes(tmp_path):
    store = ModesStore(tmp_path / "modes.yaml")
    empty_row = {"type": "", "value": ""}  # rows left empty in the form are skipped
    store.save(
        {
            "name": "Movie",
            "icon": "film",
            "settings": {"displays": ["2"], "volume": 60},
            "actions": [{"type": "say", "value": "Enjoy."}, empty_row],
        }
    )
    store.save({"name": "Cinema", "settings": {"volume": 50}}, old_name="Movie")
    assert [m.name for m in store.load()] == ["Cinema"]
    assert store.load()[0].settings == {"volume": 50}
    store.save({"name": "Work", "settings": {"displays": "all"}})
    with pytest.raises(ModesFileError, match="already have a mode called Work"):
        store.save({"name": "work", "settings": {"volume": 1}}, old_name="Cinema")
    store.delete("cinema")
    assert [m.name for m in store.load()] == ["Work"]
    assert store.path.read_text(encoding="utf-8").startswith("# Your modes")


def test_the_store_never_writes_a_broken_file(tmp_path):
    store = ModesStore(tmp_path / "modes.yaml")
    store.save({"name": "Work", "settings": {"volume": 10}})
    before = store.path.read_text(encoding="utf-8")
    with pytest.raises(ModesFileError):
        store.save({"name": "Bad", "settings": {"volume": 500}})
    assert store.path.read_text(encoding="utf-8") == before


def test_the_templates_are_valid(tmp_path):
    store = ModesStore(tmp_path / "modes.yaml")
    for template in TEMPLATES:
        store.save(template)
    assert len(store.load()) == len(TEMPLATES)
    assert not any("displays" in t["settings"] and t["settings"]["displays"] != "all"
                   for t in TEMPLATES)  # fmt: skip


# ----- switching -----


def test_movie_mode_keeps_only_screen_2(tmp_path):
    engine, controls, ran, shown = make(tmp_path)
    assert engine.activate("movie") == "Movie mode. Enjoy the movie."
    assert controls.applied == [("displays", ["2"]), ("volume", 60)]
    assert ran == [("say", "Enjoy the movie.")]
    assert shown == ["Movie"] and engine.current == "Movie"


def test_work_mode_turns_everything_on_and_runs_both_actions(tmp_path):
    engine, controls, ran, _ = make(tmp_path)
    engine.activate("Work")
    assert ("displays", "all") in controls.applied and ("brightness", 100) in controls.applied
    assert ran == [("play_youtube", "jazz music"), ("open_app", "Visual Studio Code")]


def test_back_to_normal_puts_everything_back(tmp_path):
    engine, controls, ran, shown = make(tmp_path)
    engine.activate("Movie")
    assert engine.deactivate() == BACK_TO_NORMAL
    assert controls.values["displays"] == ["laptop", "hp", "wide"]
    assert controls.values["volume"] == [40, False]
    assert ran[-1] == ("media", "play_pause")  # the mode's exit action
    assert shown == ["Movie", ""] and engine.current is None
    assert engine.deactivate() == NO_MODE


def test_switching_modes_restores_what_the_new_one_leaves_alone(tmp_path):
    engine, controls, ran, _ = make(tmp_path)
    engine.activate("Movie")  # screens: only 2, volume 60
    engine.activate("Work")  # screens: all, brightness 100 (volume not set)
    assert controls.values["volume"] == [40, False]  # Movie's volume went back
    assert ("media", "play_pause") in ran  # Movie's exit action ran
    engine.deactivate()
    # Back to how it was before Movie, not before Work.
    assert controls.values["displays"] == ["laptop", "hp", "wide"]
    assert controls.values["brightness"] == {"laptop": 80}


def test_a_setting_that_fails_doesnt_stop_the_rest(tmp_path):
    controls = Controls()
    controls.fail = {"displays"}
    engine, controls, ran, _ = make(tmp_path, controls=controls)
    reply = engine.activate("Movie")
    assert reply.startswith("Movie mode. But the displays didn't change.")
    assert ("volume", 60) in controls.applied and ran


def test_unknown_modes(tmp_path):
    engine, *_ = make(tmp_path)
    with pytest.raises(ActionError, match="don't have a mode called Party"):
        engine.activate("Party")
    assert engine.switch("normal") == NO_MODE


def test_a_mode_survives_a_restart(tmp_path):
    engine, controls, *_ = make(tmp_path)
    engine.activate("Movie")
    state = json.loads((tmp_path / "mode_state.json").read_text())
    assert state["current"] == "Movie" and "displays" in state["remembered"]
    again, controls2, *_ = make(tmp_path)
    assert again.current == "Movie"
    again.deactivate()
    assert controls2.applied[0] == ("restore displays", ["laptop", "hp", "wide"])


def test_abdohs_own_switches_come_back_after_a_restart(tmp_path):
    quiet = OWNER + "- name: Quiet\n  settings:\n    wake_word: false\n    volume: 10\n"
    engine, *_ = make(tmp_path, quiet)
    engine.activate("Quiet")
    again, controls, _, shown = make(tmp_path, quiet)
    again.start()
    assert controls.applied == [("wake_word", False)]  # not the volume: Windows kept it
    assert shown == ["Quiet"]


def test_a_deleted_mode_is_forgotten_at_start(tmp_path):
    engine, *_ = make(tmp_path)
    engine.activate("Movie")
    again, *_ = make(tmp_path, "[]")
    again.start()
    assert again.current is None


def test_a_mode_can_hand_over_only_once(tmp_path):
    loop = """
- name: A
  actions: [{mode: B}]
- name: B
  actions: [{mode: A}]
"""
    controls = Controls()
    holder = {}

    def run(actions):
        out = []
        for kind, value in actions:
            if kind == "mode":
                out.append(holder["engine"].switch(value))
        return out

    engine = ModeEngine(lambda: parse_modes(yaml.safe_load(loop)), controls, run,
                        tmp_path / "s.json")  # fmt: skip
    holder["engine"] = engine
    reply = engine.activate("A")
    assert "only hand over to one other mode" in reply


# ----- the phrases -----


@pytest.fixture
def router(tmp_path):
    from test_router import FakeAct

    from abdoh.commands.registry import CommandRegistry
    from abdoh.config import Config
    from abdoh.router import Router

    path = tmp_path / "commands.yaml"
    path.write_text("[]", encoding="utf-8")
    router = Router(Config(app_dir=tmp_path), CommandRegistry(path), act=FakeAct())
    engine, controls, ran, _ = make(tmp_path, OWNER + "- name: Dark\n  settings:\n    volume: 5\n")
    router.modes = engine
    return router


@pytest.mark.parametrize(
    "said, reply",
    [
        ("Xanthos, movie mode", "Movie mode. Enjoy the movie."),
        ("switch to work mode", "Work mode."),
        ("turn on movie mode", "Movie mode. Enjoy the movie."),
        ("movie night", "Movie mode. Enjoy the movie."),  # the mode's own phrase
        ("dark mode", "Dark mode."),  # your mode wins over the dark theme
    ],
)
def test_switching_on_by_voice(router, said, reply):
    assert router.handle(said) == reply


def test_ending_and_asking(router):
    assert router.handle("which mode am i in") == "No mode is on."
    router.handle("movie mode")
    assert router.handle("what mode is on") == "Movie mode is on."
    assert router.handle("exit work mode") == "Work mode isn't on."
    assert router.handle("back to normal") == BACK_TO_NORMAL
    router.handle("movie mode")
    assert router.handle("exit movie mode") == BACK_TO_NORMAL
    router.handle("movie mode")
    assert router.handle("turn off this mode") == BACK_TO_NORMAL
    assert router.handle("what modes do i have") == "Your modes: Movie, Work, Dark."


def test_other_mode_words_are_left_alone(router):
    router.modes = make(router.cfg.app_dir, OWNER)[0]  # no mode called Dark here
    assert router.handle("turn off dark mode") != BACK_TO_NORMAL
    assert router.handle("party mode") != "Party mode."  # not yours: Claude or a skill


# ----- the real controls, with a fake computer -----


def test_the_controls_reach_the_computer_and_abdoh(tmp_path):
    from test_displays import FakeBackend

    from abdoh.config import Config
    from abdoh.displays import Displays
    from abdoh.modes.controls import ModeControls

    class Computer:
        def __init__(self):
            self.displays = Displays(tmp_path / "d.json", FakeBackend())
            self.calls = []
            self.level, self.is_muted = 40, True

        def screens(self, layout):
            self.calls.append(("screens", layout))
            return self.displays.apply(layout)

        def volume(self):
            return self.level

        def muted(self):
            return self.is_muted

        def set_volume(self, level):
            self.level = level

        def set_muted(self, muted):
            self.is_muted = muted

    class Daemon:
        def __init__(self):
            self.cfg = Config(app_dir=tmp_path)
            self.paused, self.voice_enabled = False, True

        def set_paused(self, paused):
            self.paused = paused

        def set_voice(self, on):
            self.voice_enabled = on

    computer, daemon = Computer(), Daemon()
    controls = ModeControls(computer, daemon)
    screens = controls.capture("displays")
    controls.apply("displays", ["2"])
    assert computer.calls == [("screens", "only 2")]
    controls.restore("displays", screens)
    assert all(d.active for d in computer.displays.all())

    volume = controls.capture("volume")
    controls.apply("volume", 60)
    controls.restore("volume", volume)
    assert (computer.level, computer.is_muted) == (40, True)  # muted again, as it was

    controls.apply("wake_word", False)
    assert daemon.paused
    before = controls.capture("follow_up")
    controls.apply("follow_up", False)
    assert daemon.cfg.follow_up_seconds == 0
    controls.restore("follow_up", before)
    assert daemon.cfg.follow_up_seconds == before
    assert not (tmp_path / "config.yaml").exists()  # in memory only


def test_the_window_switches_modes_through_abdoh(tmp_path):
    from abdoh.config import Config
    from abdoh.daemon import Daemon
    from abdoh.events import Bus
    from abdoh.speech.tts import FakeSpeaker

    class Router:
        brain = registry = computer = None
        modes = None

        def add_builtin(self, *args):
            pass

    bus = Bus()
    daemon = Daemon(Config(app_dir=tmp_path), Router(), FakeSpeaker(), None, None, None, bus=bus)
    engine, *_ = make(tmp_path)
    daemon.use_modes(engine)
    daemon.handle_request("mode", "Movie")
    daemon.handle_request("mode", "")
    daemon.handle_request("mode", "Party")
    history = [v for k, v in bus.pending_events() if k == "history"]
    assert history == [
        "Xanthos: Movie mode. Enjoy the movie.",
        "Xanthos: Back to normal.",
        "Xanthos: You don't have a mode called Party.",
    ]


# ----- modes at a time of day -----


def test_schedules_are_read():
    from abdoh.modes.model import parse_schedule

    assert parse_schedule("weekdays 09:00") == (frozenset({0, 1, 2, 3, 4}), 9, 0)
    assert parse_schedule("daily 23:30")[0] == frozenset(range(7))
    assert parse_schedule("sat, sun 10:05") == (frozenset({5, 6}), 10, 5)
    for bad in ("weekdays", "daily 25:00", "someday 09:00", "9am"):
        with pytest.raises(ValueError):
            parse_schedule(bad)
    with pytest.raises(ModesFileError, match="schedule"):
        parse_modes([{"name": "X", "settings": {"volume": 5}, "schedule": ["soon"]}])


def test_a_mode_switches_on_at_its_time_once(tmp_path):
    from datetime import datetime

    timed = OWNER + '- name: Night\n  settings:\n    volume: 20\n  schedule: ["daily 23:00"]\n'
    engine, controls, _, shown = make(tmp_path, timed)
    assert engine.tick(datetime(2026, 11, 17, 22, 59)) is None
    assert engine.tick(datetime(2026, 11, 17, 23, 0, 5)) == "Night mode."
    assert engine.tick(datetime(2026, 11, 17, 23, 0, 40)) is None  # the same minute: once
    engine.deactivate()
    assert engine.tick(datetime(2026, 11, 17, 23, 1)) is None  # no catching up
    assert engine.tick(datetime(2026, 11, 18, 23, 0)) == "Night mode."  # the next day


def test_weekday_schedules_skip_the_weekend(tmp_path):
    from datetime import datetime

    timed = OWNER + '- name: Desk\n  settings:\n    volume: 20\n  schedule: ["weekdays 09:00"]\n'
    engine, *_ = make(tmp_path, timed)
    assert engine.tick(datetime(2026, 11, 21, 9, 0)) is None  # a Saturday
    assert engine.tick(datetime(2026, 11, 23, 9, 0)) == "Desk mode."  # Monday


def test_the_schedule_runs_until_abdoh_stops(tmp_path):
    import threading
    from datetime import datetime

    timed = OWNER + '- name: Night\n  settings:\n    volume: 20\n  schedule: ["daily 23:00"]\n'
    engine, *_ = make(tmp_path, timed)
    stop, said = threading.Event(), []

    def announce(text):
        said.append(text)
        stop.set()

    at_eleven = lambda: datetime(2026, 11, 17, 23, 0)  # noqa: E731
    thread = threading.Thread(target=engine.run_schedule, args=(stop, announce, at_eleven, 0.01))
    thread.start()
    thread.join(2)
    assert said == ["Night mode."] and not thread.is_alive()
