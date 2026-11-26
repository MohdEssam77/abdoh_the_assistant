"""Codoh by voice (abdoh/codoh/voice.py): Abdoh starts chats in folders, sends them messages,
changes their model or mode, answers what they wait for, and says when they need the user."""

import time
from pathlib import Path

import pytest
from test_codoh_manager import World, items

from abdoh.codoh import manager as manager_module
from abdoh.codoh import voice
from abdoh.codoh.voice import NO_CHAT, NOTHING_WAITING, act, find_folder


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    w.code = tmp_path / "code"
    for name in ("myportfolio", "abdoh_the_assistant", "weather-app"):
        (w.code / name).mkdir(parents=True)
    w.said = []
    w.codoh.on_notice = w.said.append
    return w


def run(world, arg):
    return act(world.codoh, arg, roots=[world.code])


def wait_for(said, count=1):
    for _ in range(100):
        if len(said) >= count:
            return said
        time.sleep(0.01)
    return said


# ----- finding the folder the user means -----


@pytest.mark.parametrize(
    "said, name",
    [
        ("abdoh the assistant", "abdoh_the_assistant"),
        ("my portfolio", "myportfolio"),
        ("the weather app folder", "weather-app"),
        ("Weather App", "weather-app"),
    ],
)
def test_a_folder_by_its_spoken_name(tmp_path, said, name):
    code = tmp_path / "code"
    for n in ("myportfolio", "abdoh_the_assistant", "weather-app"):
        (code / n).mkdir(parents=True)
    assert find_folder(said, [], [code]) == code / name


def test_a_full_path_and_nothing_alike(tmp_path):
    assert find_folder(str(tmp_path), [], []) == tmp_path
    (tmp_path / "myportfolio").mkdir()
    assert find_folder("tax returns", [], [tmp_path]) is None
    assert find_folder("", [], [tmp_path]) is None


# ----- what Claude asks for -----


def test_a_new_chat_in_a_folder_with_a_message(world):
    result = run(world, "new | my portfolio | Add a dark mode toggle to the header.")
    assert result.said == "" and result.show and result.chat
    chat = world.codoh.chat(result.chat)["chat"]
    assert chat["folder"] == str(world.code / "myportfolio")
    assert world.engines[0].sent == ["Add a dark mode toggle to the header."]
    assert world.codoh.viewing == result.chat  # "send" goes on with it
    assert str(world.code / "myportfolio") in [f["path"] for f in world.codoh.state()["folders"]]


def test_a_folder_that_isnt_there(world):
    result = run(world, "new | tax returns | sort them")
    assert result.said.startswith("I couldn't find a folder called tax returns")
    assert world.engines == []


def test_opening_a_folder_without_a_chat(world):
    result = run(world, "open | weather app")
    assert result.said == "" and result.show and not result.chat
    assert world.codoh.state()["folders"][0]["name"] == "weather-app"


def test_a_new_folder_is_made_first(world, tmp_path):
    new = tmp_path / "code" / "space-game"
    result = run(world, f"create | {new} | Start a small canvas game.")
    assert new.is_dir() and result.chat and world.engines[0].sent == ["Start a small canvas game."]
    assert run(world, "create | space game | hi").said.startswith("I need the full path")


def test_sending_to_the_open_chat(world):
    assert run(world, "send | run the tests").said == NO_CHAT
    first = run(world, "new | weather app").chat
    result = run(world, "send | Also run the tests, please.")
    assert result.chat == first and world.engines[0].sent == ["Also run the tests, please."]


def test_changing_the_model_mode_and_effort(world):
    chat = run(world, "new | weather app").chat
    assert run(world, "set | full access").said == ""
    assert run(world, "set | opus").said == ""
    assert run(world, "set | high effort").said == ""
    summary = world.codoh.chat(chat)["chat"]
    assert (summary["mode"], summary["model"], summary["effort"]) == ("full", "opus", "high")
    assert run(world, "set | purple").said.startswith("Codoh has no model, mode or effort")


def ask(engine, tool="Bash", data=None):
    data = data if data is not None else {"command": "pnpm build", "description": "Build it"}
    engine.on_event({"type": "tool", "id": "t1", "name": tool, "input": data})
    engine.on_event(
        {"type": "approval", "id": "r1", "tool": tool, "input": data, "tool_use_id": "t1"}
    )


def test_allowing_what_codoh_waits_for(world):
    assert run(world, "allow").said == NOTHING_WAITING
    run(world, "new | weather app | build it")
    engine = world.engines[0]
    ask(engine)
    assert run(world, "allow").said == ""
    assert engine.answers[-1][:2] == ("r1", True)


def test_answering_codohs_question(world):
    run(world, "new | my portfolio | add the project")
    engine = world.engines[0]
    question = {"question": "Which project?", "options": [{"label": "Abdoh"}, {"label": "Quiz"}]}
    ask(engine, "AskUserQuestion", {"questions": [question]})
    assert run(world, "allow").said == "Codoh asked a question: say the answer."
    assert run(world, "answer | the Abdoh one").said == ""
    assert engine.answers[-1][2]["answers"] == {"Which project?": "Abdoh"}


def test_stopping_it(world):
    run(world, "new | weather app | build it")
    assert run(world, "stop").said == "" and world.engines[0].interrupted


def test_something_unknown(world):
    assert run(world, "dance").said == voice.UNKNOWN


# ----- Abdoh says what a voice chat needs, and when it's done -----


def test_a_voice_chat_says_what_it_needs_and_when_its_done(world):
    run(world, "new | weather app | build it")
    engine = world.engines[0]
    ask(engine)
    assert wait_for(world.said) == ["Codoh wants to run a command: Build it. Allow it?"]
    engine.on_event({"type": "text", "delta": "The build works now. I also fixed a warning."})
    engine.on_event({"type": "done", "ok": True, "seconds": 3})
    assert wait_for(world.said, 2)[1] == "Codoh is done: The build works now."


def test_a_chat_typed_on_the_page_stays_quiet(world):
    chat = world.chat()
    world.codoh.send(chat, "build it")
    engine = world.engines[0]
    ask(engine)
    engine.on_event({"type": "done", "ok": True, "seconds": 3})
    time.sleep(0.1)
    assert world.said == []
    assert items(world.codoh, chat, "approval")[0]["state"] == "expired"


def test_the_question_is_said_with_its_options():
    options = [{"label": "Abdoh"}, {"label": "Quiz"}]
    item = {"input": {"questions": [{"question": "Which project?", "options": options}]}}
    assert voice.notice("question", "", item) == "Codoh asks: Which project? Abdoh or Quiz?"
    edit = {"kind_of": "edit", "title": "src/calc.py"}
    assert voice.notice("approval", "", edit) == "Codoh wants to change calc.py. Allow it?"


# ----- Abdoh's Claude, the router, the one Codoh -----


def test_claude_gets_the_action_and_the_router_shows_the_chat(world):
    from test_router import FakeBrain

    from abdoh.commands.registry import CommandRegistry
    from abdoh.config import Config
    from abdoh.router import Router

    cfg = Config(app_dir=world.tmp_path / "abdoh")
    brain = FakeBrain(["ACTION codoh: new | weather app | Fix the forecast.\n", "Asked Codoh."])
    router = Router(cfg, CommandRegistry(world.tmp_path / "none.yaml"), brain=brain)
    " ".join(router.handle("make a chat in the weather app folder and fix the forecast"))
    assert world.engines == []  # without Codoh, Claude has no such action
    shown = []
    router.codoh = lambda: world.codoh
    router.on_codoh = shown.append
    monkey = voice.places
    voice.places = lambda known, **k: [world.code]
    try:
        brain.chunks = ["ACTION codoh: new | weather app | Fix the forecast.\n", "Asked Codoh."]
        reply = " ".join(router.handle("make a chat in the weather app folder and fix it"))
    finally:
        voice.places = monkey
    assert reply == "Asked Codoh." and world.engines[0].sent == ["Fix the forecast."]
    assert shown and shown[0] == world.codoh.viewing
    brain.chunks = ["ACTION codoh: new | tax returns | sort\n", "Asked Codoh."]
    voice.places = lambda known, **k: [world.code]
    try:
        reply = " ".join(router.handle("make a chat in tax returns"))
    finally:
        voice.places = monkey
    assert "I couldn't find a folder called tax returns" in reply


def test_the_prompt_has_codoh():
    from abdoh.claude.brain import system_prompt
    from abdoh.config import Config

    text = system_prompt(Config())
    assert "ACTION codoh: new | <folder> |" in text and "ACTION codoh: allow" in text


def test_the_window_and_the_voice_share_one_codoh(tmp_path):
    from abdoh.config import Config
    from abdoh.events import Bus
    from abdoh.ui.api import AppApi, UiState

    cfg = Config(app_dir=tmp_path / "a")
    first = manager_module.shared(cfg)
    assert manager_module.shared(cfg) is first
    assert AppApi(Bus(), UiState(), cfg)._codoh_manager() is first
    assert manager_module.shared(Config(app_dir=tmp_path / "b")) is not first


def test_the_daemon_shows_the_chat_and_says_the_notices(tmp_path, monkeypatch):
    from abdoh.config import Config
    from abdoh.daemon import Daemon
    from abdoh.events import Bus

    daemon = Daemon.__new__(Daemon)
    daemon.cfg = Config(app_dir=tmp_path)
    daemon.bus = Bus()
    daemon.bus.ui_attached = True
    codoh = daemon._codoh()
    assert codoh.on_notice == daemon._say_aside
    daemon._show_codoh("c1")
    assert daemon.bus.pending_events() == [("show", None), ("codoh_open", "c1")]


def test_a_folder_path_on_this_computer_is_used_as_it_is(world):
    result = run(world, f"new | {world.folder} | hello")
    assert Path(world.codoh.chat(result.chat)["chat"]["folder"]) == world.folder


def test_a_silent_action_reads_well_in_the_window():
    from abdoh.daemon import _what_was_done

    actions = [("codoh", "new | pocket calculator |"), ("codoh", "send | fix it")]
    assert _what_was_done(actions) == "Done: started a Codoh chat; told Codoh."
