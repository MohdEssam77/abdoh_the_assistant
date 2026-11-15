import pytest
import yaml

from abdoh.commands.registry import CommandsFileError, parse_commands
from abdoh.commands.store import HEADER, TEMPLATES, CommandsStore, dump


@pytest.fixture
def store(app_dir):
    path = app_dir / "commands.yaml"
    path.write_text((app_dir / "commands.example.yaml").read_text())
    return CommandsStore(path)


def form(name="Open news", triggers=("open the news",), actions=None):
    return {
        "name": name,
        "triggers": list(triggers),
        "actions": actions or [{"type": "open_url", "value": "https://news.google.com"}],
    }


def test_load_gives_form_data(store):
    commands = store.load()
    assert commands[0]["name"] == "good_morning"
    assert commands[0]["actions"][0] == {
        "type": "say",
        "value": "Good morning! Here's your playlist.",
    }


def test_add_a_command(store):
    saved = store.save(form())
    assert saved == form()
    assert store.load()[-1] == form()
    text = store.path.read_text(encoding="utf-8")
    assert text.startswith(HEADER)
    assert parse_commands(yaml.safe_load(text))[-1].name == "Open news"


def test_edit_and_rename_a_command(store):
    store.save(form())
    store.save(form(name="News", triggers=["news please"]), old_name="Open news")
    names = [c["name"] for c in store.load()]
    assert "News" in names and "Open news" not in names
    assert store.load()[-1]["triggers"] == ["news please"]


def test_names_must_be_unique(store):
    with pytest.raises(CommandsFileError, match="already have a command called 'Good_Morning'"):
        store.save(form(name="Good_Morning"))


def test_empty_rows_from_the_form_are_ignored(store):
    saved = store.save(
        form(
            triggers=["open the news", " ", "open the news"],
            actions=[
                {"type": "open_url", "value": "https://news.google.com"},
                {"type": "", "value": ""},
            ],
        )
    )
    assert saved["triggers"] == ["open the news"]
    assert len(saved["actions"]) == 1


@pytest.mark.parametrize(
    "command, message",
    [
        (form(name=" "), "Give the command a name"),
        (form(triggers=[]), "at least one phrase"),
        (form(actions=[{"type": "", "value": ""}]), "at least one action"),
        (form(actions=[{"type": "explode", "value": "x"}]), "unknown action 'explode'"),
        (form(actions=[{"type": "say", "value": " "}]), "needs a text value"),
        (form(actions=[{"type": "timer", "value": "soon"}]), "duration"),
        (
            form(triggers=["run {thing}"], actions=[{"type": "run", "value": "{thing}"}]),
            "unsafe",
        ),
    ],
)
def test_invalid_commands_never_reach_the_file(store, command, message):
    before = store.path.read_text()
    with pytest.raises(CommandsFileError, match=message):
        store.save(command)
    assert store.path.read_text() == before


def test_delete(store):
    store.delete("open_mail")
    assert "open_mail" not in [c["name"] for c in store.load()]
    with pytest.raises(CommandsFileError, match="no command called 'nope'"):
        store.delete("nope")


def test_a_broken_file_is_reported_and_left_alone(store):
    store.path.write_text("- name: [unclosed\n")
    with pytest.raises(CommandsFileError, match="isn't valid"):
        store.load()
    with pytest.raises(CommandsFileError):
        store.save(form())
    assert store.path.read_text() == "- name: [unclosed\n"


def test_missing_file_starts_empty(tmp_path):
    store = CommandsStore(tmp_path / "commands.yaml")
    assert store.load() == []
    store.save(form())
    assert [c["name"] for c in store.load()] == ["Open news"]


def test_arabic_and_quotes_round_trip(store):
    command = form(
        name="يوتيوب",
        triggers=["افتح يوتيوب"],
        actions=[{"type": "say", "value": 'He said "hi" #1'}],
    )
    assert store.save(command) == command
    assert store.load()[-1] == command


def test_every_template_is_a_valid_command():
    items = [
        {"name": t["name"], "triggers": t["triggers"],
         "actions": [{a["type"]: a["value"]} for a in t["actions"]]}
        for t in TEMPLATES
    ]  # fmt: skip
    assert len(parse_commands(yaml.safe_load(dump(items)))) == len(TEMPLATES)
    assert all(t["description"] for t in TEMPLATES)
