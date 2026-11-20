"""Start Menu shortcut, icon, and running as the built Xanthos.exe (no PowerShell or real paths)."""

import sys
from pathlib import Path

import pytest
from PIL import Image

from abdoh import autostart, config, shortcut
from abdoh.cli import build_parser, main


def test_icon_has_several_sizes(tmp_path):
    path = shortcut.make_icon(tmp_path / "xanthos.ico")
    with Image.open(path) as ico:
        assert ico.format == "ICO"
        assert (16, 16) in ico.info["sizes"] and (256, 256) in ico.info["sizes"]


def test_shortcut_values_go_through_the_environment(tmp_path):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))

    lnk = tmp_path / "Start Menu" / "Xanthos.lnk"
    command = [r"C:\Program Files\Py thon\pythonw.exe", "-m", "abdoh", "run", "--show"]
    shortcut.create_shortcut(lnk, command, Path(r"C:\it's\here"), tmp_path / "a.ico", run=run)
    ((args, kwargs),) = calls
    assert args[0] == "powershell.exe" and "CreateShortcut($env:ABDOH_LNK)" in args[-1]
    env = kwargs["env"]
    assert env["ABDOH_TARGET"] == command[0]
    assert env["ABDOH_ARGS"] == "-m abdoh run --show"
    assert env["ABDOH_DIR"] == r"C:\it's\here"  # never pasted into the script itself
    assert lnk.parent.is_dir()


class FakeAutostart:
    def __init__(self):
        self.calls = []

    def install(self):
        self.calls.append("install")
        return "Starts at login."

    def uninstall(self):
        self.calls.append("uninstall")
        return "Removed start at login."


@pytest.mark.skipif(sys.platform != "win32", reason="the Start Menu is Windows-only")
def test_install_and_uninstall(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(shortcut, "ICON", tmp_path / "xanthos.ico")
    made = []

    def run(args, env, **kwargs):
        Path(env["ABDOH_LNK"]).write_text("lnk")
        made.append(env)

    fake = FakeAutostart()
    done = shortcut.install(login=True, autostart=fake, run=run)
    assert "Added Xanthos to the Start Menu" in done[0] and done[1] == "Starts at login."
    assert made[0]["ABDOH_ARGS"].endswith("run --show")
    assert shortcut.start_menu_shortcut().exists()
    done = shortcut.uninstall(autostart=fake)
    assert done == ["Removed the Start Menu shortcut.", "Removed start at login."]
    assert not shortcut.start_menu_shortcut().exists()


def test_launch_command_for_the_built_app(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\Xanthos\Xanthos.exe")
    assert autostart.launch_command() == [r"C:\Apps\Xanthos\Xanthos.exe", "run", "--minimized"]
    assert autostart.launch_command(show=True)[-1] == "--show"


def test_launch_command_from_python():
    command = autostart.launch_command()
    assert command[1:] == ["-m", "abdoh", "run", "--minimized"]


def test_built_app_keeps_your_files_in_appdata(monkeypatch, tmp_path):
    monkeypatch.delenv("ABDOH_HOME", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert config._default_app_dir() == tmp_path / "Xanthos"
    monkeypatch.setenv("ABDOH_HOME", str(tmp_path / "custom"))
    assert config._default_app_dir() == tmp_path / "custom"


def test_files_fall_back_to_the_bundled_copy(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    (bundle / "models").mkdir(parents=True)
    (bundle / "models" / "hey_xanthos.onnx").write_bytes(b"x")
    (bundle / "config.example.yaml").write_text("match_threshold: 70\n")
    (bundle / "commands.example.yaml").write_text("[]\n")
    monkeypatch.setattr(config, "BUNDLE_DIR", bundle)
    app = tmp_path / "AppData" / "Xanthos"  # doesn't exist yet
    cfg = config.load_config(app)
    assert (app / "config.yaml").exists() and cfg.match_threshold == 70
    assert cfg.resolve("models/hey_xanthos.onnx") == bundle / "models" / "hey_xanthos.onnx"
    (app / "models").mkdir()
    (app / "models" / "hey_xanthos.onnx").write_bytes(b"mine")
    assert cfg.resolve("models/hey_xanthos.onnx") == app / "models" / "hey_xanthos.onnx"


def test_double_clicking_the_built_app_runs_it(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    seen = []
    parser = build_parser()
    monkeypatch.setattr("abdoh.cli.build_parser", lambda: parser)
    parser._subparsers._group_actions[0].choices["run"].set_defaults(
        func=lambda cfg, args: seen.append((args.command, args.show)) or 0
    )
    monkeypatch.setattr("abdoh.cli.load_config", lambda: config.Config())
    monkeypatch.setattr("abdoh.cli.setup_logging", lambda *a, **k: None)
    assert main([]) == 0
    assert seen == [("run", True)]
