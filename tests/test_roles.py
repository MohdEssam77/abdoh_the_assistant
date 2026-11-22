"""Act as: roles in roles.yaml, starting and stopping them (by name, by Claude, from a mode or a
command), what Claude hears while one is on, the voice's speed, and the app's page."""

import pytest
import yaml
from fakes import FakeTranscriber, FakeWakeWord
from test_router import FakeAct, FakeBrain

from abdoh.about import state_line
from abdoh.claude.brain import system_prompt
from abdoh.commands.actions import run_action
from abdoh.commands.registry import CommandRegistry, parse_commands
from abdoh.config import Config
from abdoh.daemon import Daemon
from abdoh.events import Bus
from abdoh.roles.acting import Acting
from abdoh.roles.model import Role, RolesFileError, parse_role, parse_roles
from abdoh.roles.store import SUGGESTIONS, RoleStore
from abdoh.router import Router
from abdoh.system_skills import Done
from abdoh.ui.api import AppApi, UiState

TEACHER = {
    "name": "German teacher",
    "phrases": ["german lesson"],
    "instructions": "You are my German teacher. Speak German slowly.",
    "speed": "slow",
    "answers": "long",
    "board": True,
}

# ----- the file -----


def test_a_role_reads():
    role = parse_role(TEACHER)
    assert role == Role(
        "German teacher", "You are my German teacher. Speak German slowly.", ("german lesson",),
        "slow", "long", True,
    )  # fmt: skip
    assert role.sentences(4) == 10
    assert parse_role({"name": "Chef", "instructions": "Cook."}).sentences(4) == 5  # normal
    assert (
        parse_role({"name": "Chef", "instructions": "Cook.", "answers": "short"}).sentences(4) == 4
    )


@pytest.mark.parametrize(
    "item, problem",
    [
        ({"instructions": "x"}, "needs a name"),
        ({"name": "Chef"}, "instructions"),
        ({"name": "off", "instructions": "x"}, "can't be called"),
        ({"name": "Chef", "instructions": "x", "speed": "very"}, "speed"),
        ({"name": "Chef", "instructions": "x", "answers": "huge"}, "answers"),
        ({"name": "Chef", "instructions": "x", "board": "yes"}, "board"),
        ({"name": "Chef", "instructions": "x", "voice": "deep"}, "unknown field"),
        ({"name": "Chef", "instructions": "x" * 1501}, "at most"),
    ],
)
def test_mistakes_are_explained(item, problem):
    with pytest.raises(RolesFileError, match=problem):
        parse_role(item)


def test_two_roles_with_one_name_are_refused():
    with pytest.raises(RolesFileError, match="two roles"):
        parse_roles([TEACHER, {**TEACHER, "name": "german TEACHER"}])


def test_the_store_saves_replaces_and_deletes(tmp_path):
    store = RoleStore(tmp_path / "roles.yaml")
    assert store.load() == []
    store.save(TEACHER)
    store.save({"name": "Chef", "instructions": "Talk like a chef."})
    with pytest.raises(RolesFileError, match="already have"):  # renaming onto another role
        store.save({"name": "chef", "instructions": "Another chef."}, old_name="German teacher")
    store.save({**TEACHER, "name": "German tutor"}, old_name="German teacher")
    assert [r.name for r in store.load()] == ["German tutor", "Chef"]
    store.delete("chef")
    assert [r.name for r in store.load()] == ["German tutor"]
    text = (tmp_path / "roles.yaml").read_text(encoding="utf-8")
    assert text.startswith("# Your roles") and yaml.safe_load(text)[0]["speed"] == "slow"


def test_the_suggestions_are_valid_roles():
    for suggestion in SUGGESTIONS:
        item = {k: v for k, v in suggestion.items() if k != "description"}
        assert parse_role(item).board is True


# ----- acting -----


def make_acting(roles=(TEACHER,)):
    changes = []
    acting = Acting(lambda: parse_roles(list(roles)), on_change=changes.append)
    return acting, changes


def test_starting_and_stopping_a_saved_role():
    acting, changes = make_acting()
    role = acting.start("my German teacher")
    assert role.name == "German teacher" and role.saved
    assert changes == [role]
    assert acting.stop() is True and acting.current is None
    assert changes[-1] is None
    assert acting.stop() is False  # nothing was on


def test_a_role_made_up_on_the_spot():
    acting, _ = make_acting()
    role = acting.start("a friendly chef who loves pasta")
    assert role.name == "Friendly chef who loves pasta" and role.saved is False
    assert role.instructions == "Act as a friendly chef who loves pasta."
    assert acting.switch("off") == "Stopped acting." and acting.current is None


def test_claude_hears_the_role_with_every_message():
    acting, _ = make_acting()
    assert acting.state_text(4) == ""
    acting.start("German teacher")
    text = acting.state_text(4)
    assert text.startswith("acting as German teacher: You are my German teacher.")
    assert "(answers may be up to 10 sentences)" in text
    line = state_line("Study", True, False, "1 laptop (on)", text)
    assert line.endswith("screens: 1 laptop (on); " + text)


def test_a_broken_roles_file_means_no_roles():
    def broken():
        raise RolesFileError("bad")

    acting = Acting(broken)
    assert acting.roles() == [] and acting.find("anything") is None


# ----- by voice and by Claude -----


@pytest.fixture
def router(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text("[]", encoding="utf-8")
    router = Router(Config(app_dir=tmp_path), CommandRegistry(path), act=FakeAct())
    router.acting, _ = make_acting()
    return router


@pytest.mark.parametrize("said", ["act as my german teacher", "Abdoh, act as german teacher",
                                  "german lesson", "be my german teacher"])  # fmt: skip
def test_a_saved_role_starts_by_voice_without_claude(router, said):
    reply = router.handle(said)
    assert isinstance(reply, Done) and reply == "Acting as German teacher."
    assert router.acting.current.name == "German teacher"


def test_claude_starts_a_made_up_role(router):
    router.brain = FakeBrain(("ACTION role: a friendly chef\n", "Bonjour! What shall we cook?"))
    assert (
        " ".join(router.handle("pretend you're a friendly chef")) == "Bonjour! What shall we cook?"
    )
    assert router.acting.current.name == "Friendly chef"
    assert router.last_turn.actions == [("role", "a friendly chef")]


def test_stopping_in_any_words_is_claudes_to_understand(router):
    router.acting.start("German teacher")
    router.brain = FakeBrain(("ACTION role: off\n", "Okay, back to normal."))
    reply = router.handle("I'm good, you can stop being my teacher")
    assert " ".join(reply) == "Okay, back to normal."
    assert router.acting.current is None
    assert router.brain.asked  # it went to Claude, not to a phrase list


def test_claude_is_told_how_roles_work(tmp_path):
    RoleStore(tmp_path / "roles.yaml").save(TEACHER)
    text = system_prompt(Config(app_dir=tmp_path))
    assert "ACTION role: off" in text and "The user's roles: German teacher." in text


# ----- modes and commands -----


def test_a_command_can_start_a_role(tmp_path):
    [command] = parse_commands(
        [{"name": "lesson", "triggers": ["lesson time"], "actions": [{"role": "German teacher"}]}]
    )
    acting, _ = make_acting()
    computer = type("Computer", (), {"acting": acting})()
    for kind, arg in command.actions:
        run_action(kind, arg, computer=computer)
    assert acting.current.name == "German teacher"


def test_a_mode_starts_a_role_and_ending_the_mode_ends_it(tmp_path):
    from abdoh.modes.controls import ModeControls
    from abdoh.modes.engine import ModeEngine
    from abdoh.modes.model import parse_modes

    acting, _ = make_acting()
    daemon = type("D", (), {"acting": acting})()
    modes = [{"name": "Study", "settings": {"role": "German teacher"}}]
    engine = ModeEngine(
        lambda: parse_modes(modes), ModeControls(computer=None, daemon=daemon),
        lambda actions: [], tmp_path / "state.json",
    )  # fmt: skip
    engine.activate("Study")
    assert acting.current.name == "German teacher"
    engine.deactivate()
    assert acting.current is None


# ----- the daemon -----


class Speaker:
    def __init__(self):
        self.rates = []
        self.said = []

    def say(self, text):
        self.said.append(text)

    def configure(self, rate=None, voice=None, voices=None):
        self.rates.append(rate)


def make_daemon(tmp_path):
    router = Router(Config(app_dir=tmp_path), CommandRegistry(tmp_path / "none.yaml"))
    bus = Bus()
    daemon = Daemon(
        Config(app_dir=tmp_path, tts_rate=200), router, Speaker(), None, FakeWakeWord(10_000),
        FakeTranscriber([]), bus=bus,
    )  # fmt: skip
    acting = Acting(lambda: parse_roles([TEACHER]), on_change=daemon._role_changed)
    daemon.use_roles(acting)
    return daemon, bus


def test_a_role_slows_the_voice_and_the_window_shows_it(tmp_path):
    daemon, bus = make_daemon(tmp_path)
    daemon.handle_request("role", "German teacher")
    assert daemon.speaker.rates == [160]  # slow: 0.8 times your 200
    assert ("role", "German teacher") in bus.pending_events()
    assert "acting as German teacher" in daemon._state_line()
    daemon.handle_request("role", "")
    assert daemon.speaker.rates[-1] == 200
    assert ("role", "") in bus.pending_events()
    assert "acting as" not in daemon._state_line()


def test_the_router_hears_roles_through_the_daemon(tmp_path):
    daemon, _ = make_daemon(tmp_path)
    assert daemon.router.acting is daemon.acting


# ----- the app -----


def test_the_page_lists_saves_and_deletes_roles(tmp_path):
    bus = Bus()
    api = AppApi(bus, UiState(), Config(app_dir=tmp_path))
    shown = api.roles()
    assert shown["ok"] and shown["roles"] == [] and shown["current"] is None
    assert [s["name"] for s in shown["suggestions"]] == [
        "German teacher", "Math teacher", "Programming teacher"
    ]  # fmt: skip
    assert api.save_role(TEACHER)["ok"]
    assert api.save_role({"name": "", "instructions": "x"})["error"].endswith("needs a name.")
    assert [r["name"] for r in api.roles()["roles"]] == ["German teacher"]
    api.start_role("German teacher")
    api.stop_role()
    requests = iter(lambda: bus.next_request(0), None)
    assert [r for r in requests if r[0] == "role"] == [("role", "German teacher"), ("role", "")]
    assert api.delete_role("German teacher")["ok"] and api.roles()["roles"] == []


def test_the_window_knows_the_role_that_is_on():
    state = UiState()
    state.feed("role", "German teacher")
    assert state.snapshot()["role"] == "German teacher"
