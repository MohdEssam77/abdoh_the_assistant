import pytest
import yaml

from abdoh.commands.learn import append_command, command_name
from abdoh.commands.registry import parse_commands

EXISTING = """# My commands. Keep this comment!
- name: good_morning
  triggers: ["good morning"]   # inline comment
  actions:
    - say: "Morning!"
"""


def test_command_names_are_unique():
    assert command_name("open the Python website!", set()) == "learned_open_the_python_website"
    taken = {"learned_lofi", "learned_lofi_2"}
    assert command_name("lofi", taken) == "learned_lofi_3"
    assert command_name("???", set()) == "learned_command"


def test_append_keeps_the_rest_of_the_file(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text(EXISTING, encoding="utf-8")
    actions = [("open_url", "https://www.python.org"), ("open_app", "Spotify")]
    name = append_command(path, "python site", actions, 'open "the" Python website', set())
    text = path.read_text(encoding="utf-8")
    assert text.startswith(EXISTING)  # untouched, comments included
    assert "# Learned on " in text and 'from: open "the" Python website' in text
    commands = parse_commands(yaml.safe_load(text))
    learned = commands[-1]
    assert learned.name == name == "learned_python_site"
    assert learned.triggers == ["python site"]
    assert learned.actions == actions


def test_append_to_a_file_without_a_final_newline(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text(EXISTING.rstrip("\n"), encoding="utf-8")
    append_command(path, "focus", [("media", "play_pause")], "focus", set())
    assert len(parse_commands(yaml.safe_load(path.read_text(encoding="utf-8")))) == 2


def test_append_to_a_missing_file(tmp_path):
    path = tmp_path / "commands.yaml"
    append_command(path, "focus", [("timer", "25 minutes")], "focus", set())
    assert parse_commands(yaml.safe_load(path.read_text(encoding="utf-8")))[0].name == (
        "learned_focus"
    )


def test_append_to_an_empty_list(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text("# None yet.\n[]\n", encoding="utf-8")
    append_command(path, "focus", [("timer", "25 minutes")], "focus", set())
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# None yet.")
    assert [c.name for c in parse_commands(yaml.safe_load(text))] == ["learned_focus"]


def test_nothing_is_written_if_the_result_would_be_invalid(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text(EXISTING, encoding="utf-8")
    with pytest.raises(ValueError):
        append_command(path, "x", [("media", "louder")], "x", set())
    assert path.read_text(encoding="utf-8") == EXISTING
