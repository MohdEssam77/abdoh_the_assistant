import os
import shutil

import pytest
from conftest import REPO

from abdoh.commands.registry import CommandRegistry, CommandsFileError, parse_commands


def write(path, text, bump=0):
    path.write_text(text, encoding="utf-8")
    if bump:  # make sure the mtime changes even on coarse filesystems
        st = path.stat()
        os.utime(path, (st.st_atime, st.st_mtime + bump))


def test_example_file_is_valid(tmp_path):
    shutil.copyfile(REPO / "commands.example.yaml", tmp_path / "commands.yaml")
    reg = CommandRegistry(tmp_path / "commands.yaml")
    assert reg.error is None
    names = [c.name for c in reg.commands]
    assert names == ["good_morning", "open_mail", "open_vscode", "what_time"]
    assert reg.commands[0].actions[1][0] == "open_url"


@pytest.mark.parametrize(
    "data",
    [
        {"name": "x"},
        [{"triggers": ["a"], "actions": [{"say": "hi"}]}],
        [{"name": "x", "triggers": [], "actions": [{"say": "hi"}]}],
        [{"name": "x", "triggers": "a", "actions": [{"say": "hi"}]}],
        [{"name": "x", "triggers": ["a"], "actions": []}],
        [{"name": "x", "triggers": ["a"], "actions": [{"dance": "now"}]}],
        [{"name": "x", "triggers": ["a"], "actions": [{"say": "hi", "open_url": "u"}]}],
        [{"name": "x", "triggers": ["a"], "actions": [{"say": None}]}],
    ],
)
def test_schema_errors(data):
    with pytest.raises(CommandsFileError):
        parse_commands(data)


def test_empty_file_means_no_commands(tmp_path):
    write(tmp_path / "commands.yaml", "")
    reg = CommandRegistry(tmp_path / "commands.yaml")
    assert reg.commands == [] and reg.error is None


def test_invalid_yaml_keeps_last_valid_version(tmp_path):
    path = tmp_path / "commands.yaml"
    write(path, '- name: a\n  triggers: ["hi"]\n  actions:\n    - say: "hello"\n')
    reg = CommandRegistry(path)
    assert [c.name for c in reg.commands] == ["a"]

    write(path, "- name: a\n  triggers: [unclosed\n", bump=5)
    error = reg.refresh()
    assert error
    assert reg.error == error
    assert [c.name for c in reg.commands] == ["a"]
    assert reg.refresh() is None  # unchanged file: not reported again


def test_hot_reload_on_change(tmp_path):
    path = tmp_path / "commands.yaml"
    write(path, '- name: a\n  triggers: ["hi"]\n  actions:\n    - say: "hello"\n')
    reg = CommandRegistry(path)
    write(path, '- name: b\n  triggers: ["yo"]\n  actions:\n    - say: "hey"\n', bump=5)
    assert reg.refresh() is None
    assert [c.name for c in reg.commands] == ["b"]


def test_missing_file(tmp_path):
    reg = CommandRegistry(tmp_path / "nope.yaml")
    assert reg.commands == []
