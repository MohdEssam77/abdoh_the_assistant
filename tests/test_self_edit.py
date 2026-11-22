"""Abdoh edits itself: Claude makes, changes and deletes your commands, modes and roles with
ACTION save_item / delete_item / undo_change, through the same checks as the app's pages."""

import json

import pytest
from test_router import FakeAct, FakeBrain

from abdoh.claude.brain import system_prompt
from abdoh.commands.registry import CommandRegistry
from abdoh.config import ClaudeConfig, Config
from abdoh.router import Router
from abdoh.self_edit import UNDO_STEPS, SelfEditError, SelfEditor, current_items

# Shaped like real files: the app's header, flow-style lists, quoted URLs.
COMMANDS = """\
# Your commands: edit them in the Abdoh app (Commands), or here by hand.
- name: "Good morning"
  triggers: ["good morning"]
  actions:
    - say: "Good morning! It's {time}."
    - open_url: "https://news.google.com"
"""
MODES = """\
# Your modes: make them in the Abdoh app (Modes), or here by hand.
- name: Work
  icon: briefcase
  phrases: [work mode, time to work]
  settings: {displays: all, volume: 75, power_mode: best_performance}
  actions:
  - {open_app: Visual Studio Code}
  - {window: Visual Studio Code to 3 maximized}
  exit_actions:
  - {close_app: Visual Studio Code}
- name: Movie
  icon: film
  settings:
    displays: ['2']
    volume: 100
  actions:
  - {open_url: 'https://www.netflix.com/'}
"""
ROLES = """\
- name: German teacher
  phrases: [german lesson]
  instructions: You are my German teacher, and I'm a beginner. Speak German slowly and simply,
    explain new words in English, correct my mistakes kindly, and ask me to repeat new phrases.
  speed: slow
  answers: long
  board: true
"""
INSTALLED = {"spotify", "visual studio code", "notion", "discord"}


def find_app(name):
    return name if name.lower() in INSTALLED else None


@pytest.fixture
def files(tmp_path):
    (tmp_path / "commands.yaml").write_text(COMMANDS, encoding="utf-8")
    (tmp_path / "modes.yaml").write_text(MODES, encoding="utf-8")
    (tmp_path / "roles.yaml").write_text(ROLES, encoding="utf-8")
    return tmp_path


def editor(app_dir, allow_run=False, changed=None):
    cfg = Config(app_dir=app_dir, allow_run=allow_run)
    told = changed if changed is not None else []
    return SelfEditor(cfg, find_app=find_app, on_change=told.append)


def save(ed, kind, item) -> str:
    return ed.save(f"{kind} | {json.dumps(item)}")


def text(app_dir, name):
    return (app_dir / name).read_text(encoding="utf-8")


# ----- save, change, delete, undo -----


def test_a_new_command(files):
    changed = []
    ed = editor(files, changed=changed)
    said = save(ed, "command", {"name": "Good evening", "triggers": ["good evening"],
                                "actions": [{"power": "lock"}]})  # fmt: skip
    assert said == "Saved the command Good evening."
    commands = CommandRegistry(files / "commands.yaml").commands
    assert [c.name for c in commands] == ["Good morning", "Good evening"]
    assert commands[1].actions == [("power", "lock")]
    assert changed == ["command"]  # reloaded, and the page refreshes
    assert text(files, "commands.yaml").startswith("# Your commands")  # the help stays on top


def test_add_spotify_to_work_mode_keeps_the_rest(files):
    from abdoh.modes.store import ModesStore

    ed = editor(files)
    work = ModesStore(files / "modes.yaml").items()[0]
    actions = [*work["actions"], {"open_app": "Spotify"}]
    assert save(ed, "mode", {"name": "work", "actions": actions}) == "Changed Work mode."
    mode = ModesStore(files / "modes.yaml").load()[0]
    assert mode.name == "Work" and mode.actions[-1] == ("open_app", "Spotify")
    assert mode.settings["volume"] == 75 and mode.exit_actions == (
        ("close_app", "Visual Studio Code"),
    )
    assert mode.phrases == ("work mode", "time to work")


def test_a_mode_for_three_screens_made_while_undocked(files):
    from abdoh.modes.store import ModesStore

    ed = editor(files)
    save(ed, "mode", {"name": "Study", "icon": "book", "settings": {"displays": [2, 3]},
                      "actions": [{"open_app": "Notion"}]})  # fmt: skip
    assert ModesStore(files / "modes.yaml").load()[-1].settings["displays"] == ["2", "3"]


def test_delete_and_undo_put_the_file_back_exactly(files):
    ed = editor(files)
    before = text(files, "modes.yaml")
    assert ed.delete("mode | movie") == "Deleted Movie mode."
    from abdoh.modes.store import ModesStore

    assert [m.name for m in ModesStore(files / "modes.yaml").load()] == ["Work"]
    assert ed.undo() == "Undone: Movie mode is back as it was."
    assert text(files, "modes.yaml") == before  # every byte, comments too


def test_undo_a_new_file(tmp_path):
    ed = editor(tmp_path)
    save(ed, "role", {"name": "Chef", "instructions": "You are my friendly chef."})
    assert (tmp_path / "roles.yaml").exists()
    ed.undo()
    assert not (tmp_path / "roles.yaml").exists()  # there was none before


def test_undo_goes_back_the_last_ten_changes(files):
    ed = editor(files)
    for i in range(UNDO_STEPS + 2):
        save(ed, "command", {"name": f"Test {i}", "triggers": [f"test {i}"],
                             "actions": [{"say": "hi"}]})  # fmt: skip
    for _ in range(UNDO_STEPS):
        ed.undo()
    names = [c.name for c in CommandRegistry(files / "commands.yaml").commands]
    assert names == ["Good morning", "Test 0", "Test 1"]
    with pytest.raises(SelfEditError, match="no change"):
        ed.undo()


def test_a_role_sent_back_as_claude_saw_it_keeps_its_instructions(files):
    from abdoh.roles.store import RoleStore

    ed = editor(files)
    shown = next(line for line in current_items(ed.cfg).splitlines() if line.startswith("role:"))
    item = json.loads(shown.removeprefix("role: "))
    assert item["instructions"].endswith("…")  # cut short in Claude's list
    save(ed, "role", {**item, "speed": "normal"})  # "make the German teacher speak normally"
    role = RoleStore(files / "roles.yaml").load()[0]
    assert role.speed == "normal" and role.instructions.endswith("repeat new phrases.")


# ----- what isn't saved -----


@pytest.mark.parametrize(
    ("arg", "said"),
    [
        ('command | {"name": "x", "triggers": ["x"], "actions": [{"fly": "away"}]}', "fly"),
        ('mode | {"name": "Empty"}', "at least one setting or action"),
        ('command | {"name": "x"', "couldn't read"),
        ('command | {"triggers": ["x"]}', "needs a name"),
        ('lamp | {"name": "x"}', "only change commands, modes and roles"),
        ('role | {"name": "Off", "instructions": "x"}', "can't be called"),
    ],
)
def test_an_invalid_item_changes_nothing(files, arg, said):
    before = {name: text(files, name) for name in ("commands.yaml", "modes.yaml", "roles.yaml")}
    changed = []
    with pytest.raises(SelfEditError) as e:
        editor(files, changed=changed).save(arg)
    assert said.lower() in str(e.value).lower() and str(e.value).endswith(".")
    assert {name: text(files, name) for name in before} == before and changed == []


def test_an_unknown_app_is_named_back(files):
    with pytest.raises(SelfEditError, match="I can't find an app called Spotfy"):
        save(editor(files), "command", {"name": "Music", "triggers": ["music"],
                                        "actions": [{"open_app": "Spotfy"}]})  # fmt: skip
    save(editor(files), "command", {"name": "Notes", "triggers": ["notes"],
                                    "actions": [{"open_app": "C:\\Tools\\notes.exe"}]})  # fmt: skip


def test_run_steps_need_allow_run(files):
    item = {"name": "Backup", "triggers": ["backup"], "actions": [{"run": "robocopy a b"}]}
    with pytest.raises(SelfEditError, match="Running programs is off"):
        save(editor(files), "command", item)
    assert save(editor(files, allow_run=True), "command", item) == "Saved the command Backup."


def test_a_broken_file_is_left_alone(files):
    (files / "modes.yaml").write_text("- name: [broken", encoding="utf-8")
    with pytest.raises(SelfEditError, match="has an error"):
        save(editor(files), "mode", {"name": "Night", "settings": {"volume": 20}})
    assert text(files, "modes.yaml") == "- name: [broken"


def test_delete_something_that_isnt_there(files):
    with pytest.raises(SelfEditError, match="There's no command called Dance"):
        editor(files).delete("command | Dance")


# ----- what Claude is told -----


def test_claude_gets_the_reference_and_your_items(files):
    prompt = system_prompt(Config(app_dir=files))
    assert "ACTION save_item: command |" in prompt and "ACTION undo_change: last" in prompt
    assert 'mode: {"name": "Work", "icon": "briefcase"' in prompt  # to change it
    assert 'command: {"name": "Good morning"' in prompt
    assert "Mode icons: sparkles, film" in prompt
    assert ", run" not in prompt  # allow_run is off
    assert ", run" in system_prompt(Config(app_dir=files, allow_run=True))


def test_not_allowed_means_not_told(files):
    prompt = system_prompt(Config(app_dir=files, claude=ClaudeConfig(allow_self_edit=False)))
    assert "save_item" not in prompt


# ----- through Claude -----


def make_router(app_dir, reply, allow=True):
    cfg = Config(app_dir=app_dir, claude=ClaudeConfig(allow_self_edit=allow))
    router = Router(cfg, CommandRegistry(app_dir / "commands.yaml"), act=FakeAct())
    router.brain = FakeBrain((reply,))
    return router


def test_claude_makes_a_command_and_it_works_right_away(files):
    item = {"name": "Good evening", "triggers": ["good evening"], "actions": [{"power": "lock"}]}
    router = make_router(files, f"ACTION save_item: command | {json.dumps(item)}")
    edited = []
    router.on_self_edit = edited.append
    said = " ".join(router.handle("make a command called good evening that locks the screen"))
    assert said == "Saved the command Good evening." and edited == ["command"]
    assert "good evening" in [t for c in router.registry.commands for t in c.triggers]


def test_claude_hears_why_not(files):
    item = {"name": "Music", "triggers": ["music"], "actions": [{"open_app": "Spotfy"}]}
    router = make_router(files, f"ACTION save_item: command | {json.dumps(item)}")
    router.computer = type(
        "Computer", (), {"apps": type("Apps", (), {"find": staticmethod(find_app)})()}
    )()
    assert " ".join(router.handle("make a music command")) == (
        "I can't find an app called Spotfy, so nothing was saved."
    )


def test_not_allowed_changes_nothing(files):
    item = {"name": "Good evening", "triggers": ["good evening"], "actions": [{"power": "lock"}]}
    router = make_router(files, f"ACTION save_item: command | {json.dumps(item)}", allow=False)
    list(router.handle("make a command called good evening"))
    assert text(files, "commands.yaml") == COMMANDS


def test_the_role_thats_on_follows_its_change(files):
    from fakes import FakeTranscriber, FakeWakeWord

    from abdoh.daemon import Daemon
    from abdoh.events import Bus
    from abdoh.roles.acting import Acting
    from abdoh.roles.store import RoleStore
    from abdoh.speech.tts import FakeSpeaker

    router = Router(Config(app_dir=files), CommandRegistry(files / "commands.yaml"))
    bus = Bus()
    daemon = Daemon(Config(app_dir=files), router, FakeSpeaker(), None, FakeWakeWord(99),
                    FakeTranscriber([]), bus=bus)  # fmt: skip
    store = RoleStore(files / "roles.yaml")
    daemon.use_roles(Acting(store.load, on_change=daemon._role_changed))
    daemon.acting.start("German teacher")
    save(editor(files), "role", {"name": "German teacher", "speed": "fast"})
    router.on_self_edit("role")
    assert daemon.acting.current.speed == "fast"
    assert ("roles", None) in bus.pending_events()  # the Act as page refreshes
