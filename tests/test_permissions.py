"""Permissions and settings from the app are enforced, and applied while Abdoh runs."""

import threading
import time
from pathlib import Path

from fakes import FakeMic, FakeTranscriber, FakeWakeWord, silent_block

from abdoh.audio.mic import find_input_device, input_devices
from abdoh.claude.brain import NO_ACTIONS, system_prompt
from abdoh.claude.code import ClaudeCodeBrain
from abdoh.commands.registry import CommandRegistry
from abdoh.config import ClaudeConfig, Config
from abdoh.daemon import SAMPLE, Daemon
from abdoh.events import Bus
from abdoh.router import SCREEN_OFF, Router
from abdoh.settings import save_settings
from abdoh.speech.tts import FakeSpeaker


def cfg_with(**claude) -> Config:
    return Config(claude=ClaudeConfig(**claude))


# ----- choosing a microphone -----


class FakeSounddevice:
    class default:  # noqa: N801 - mirrors sounddevice.default
        device = (1, 4)

    def query_devices(self):
        return [
            {"name": "Microsoft Sound Mapper - Input", "max_input_channels": 2, "hostapi": 0},
            {"name": "Microphone (USB)", "max_input_channels": 1, "hostapi": 0},
            {"name": "Microphone Array", "max_input_channels": 2, "hostapi": 0},
            {"name": "Speakers", "max_input_channels": 0, "hostapi": 0},
            {"name": "Microphone (USB)", "max_input_channels": 1, "hostapi": 1},  # WASAPI
        ]


def test_microphones_are_listed_once_each():
    assert input_devices(FakeSounddevice()) == [
        {"name": "Microphone (USB)", "default": True},
        {"name": "Microphone Array", "default": False},
    ]


def test_a_microphone_is_found_by_name():
    sd = FakeSounddevice()
    assert find_input_device("Microphone Array", sd) == 2
    assert find_input_device("Microphone (USB)", sd) == 1  # not the WASAPI copy
    assert find_input_device("Unplugged Mic", sd) is None  # falls back to the default
    assert find_input_device("", sd) is None


# ----- the system prompt -----


def test_prompt_offers_only_the_allowed_actions():
    text = system_prompt(cfg_with(actions=["open_url", "timer"]))
    assert "ACTION open_url" in text and "ACTION timer" in text
    assert "ACTION open_app" not in text and "ACTION play_youtube" not in text


def test_prompt_without_any_actions():
    text = system_prompt(cfg_with(actions=[], allow_screen=False))
    assert "ACTION" not in text
    assert NO_ACTIONS.split(":")[0] in text


def test_claude_may_ask_to_look_only_when_the_screen_is_allowed():
    looking = system_prompt(cfg_with(actions=[]))
    assert "ACTION look:" in looking and "the screen they are using" in looking
    assert "ACTION open_url" not in looking  # looking isn't one of the switchable actions
    assert "ACTION look" not in system_prompt(cfg_with(allow_screen=False))


def test_prompt_has_your_instructions():
    text = system_prompt(cfg_with(instructions="Call me Mo. Use {Celsius}."))
    assert text.rstrip().endswith("Call me Mo. Use {Celsius}.")
    assert "own instructions" in text
    assert "own instructions" not in system_prompt(Config())


def test_prompt_with_only_some_folders(tmp_path):
    docs = tmp_path / "Documents"
    text = system_prompt(Config(), home=tmp_path, only=[docs])
    assert f"Only work with files in these folders, never anywhere else: {docs}." in text
    assert "home folder is" not in text


# ----- Claude Code: folders -----


def test_claude_code_only_gets_the_chosen_folders(tmp_path):
    docs, music = tmp_path / "Documents", tmp_path / "Music"
    cfg = cfg_with(folders=[str(docs), str(music), str(docs)])
    brain = ClaudeCodeBrain(cfg, Path("claude.exe"), home=tmp_path, folders={})
    assert brain.file_dirs() == [docs, music]
    command = brain.command(tmp_path / "prompt.txt")
    added = [command[i + 1] for i, arg in enumerate(command) if arg == "--add-dir"]
    assert added == [str(docs), str(music)]


def test_claude_code_without_chosen_folders_uses_home(tmp_path):
    brain = ClaudeCodeBrain(Config(), Path("claude.exe"), home=tmp_path, folders={})
    assert brain.file_dirs() == [tmp_path]


# ----- the router: screen and actions -----


class Brain:
    def __init__(self, text):
        self.text = text
        self.asked = []

    def stream(self, prompt, image=None):
        self.asked.append((prompt, image))
        yield self.text


def router_for(tmp_path, cfg, brain, acted, captured):
    path = tmp_path / "commands.yaml"
    path.write_text("[]\n")
    return Router(
        cfg,
        CommandRegistry(path),
        brain=brain,
        act=lambda kind, arg, computer=None: acted.append((kind, arg)),
        capture=lambda: captured.append(True) or b"PNG",
    )


def test_screen_is_not_captured_when_turned_off(tmp_path):
    acted, captured = [], []
    brain = Brain("It says hello.")
    router = router_for(tmp_path, cfg_with(allow_screen=False), brain, acted, captured)
    assert router.handle("translate my screen") == SCREEN_OFF
    assert router.handle("summarize my screen") == SCREEN_OFF
    assert captured == [] and brain.asked == []


def test_screen_is_captured_when_allowed(tmp_path):
    acted, captured = [], []
    router = router_for(tmp_path, Config(), Brain("It says hello."), acted, captured)
    assert list(router.handle("translate my screen")) == ["It says hello."]
    assert captured == [True]


def test_actions_claude_may_not_do_are_ignored(tmp_path):
    acted, captured = [], []
    brain = Brain("ACTION open_app: Spotify\nACTION open_url: https://x.com\nDone.")
    router = router_for(tmp_path, cfg_with(actions=["open_url"]), brain, acted, captured)
    assert list(router.handle("open spotify plus x")) == ["Done."]
    assert acted == [("open_url", "https://x.com")]


# ----- the daemon applies saved settings -----


class Engine(FakeWakeWord):
    threshold = 0.5


class TunableSpeaker(FakeSpeaker):
    def __init__(self):
        super().__init__()
        self.configured = []

    def configure(self, rate=None, voice=None):
        self.configured.append((rate, voice))


class SlowMic(FakeMic):
    """Like a real microphone, read() waits for the next block (and keeps none)."""

    level = 1234

    def read(self):
        time.sleep(0.005)
        return silent_block()


def offline_config(app_dir) -> Config:
    """Settings without Claude, so these tests never start the real Claude Code."""
    return save_settings(app_dir, {"claude": {"backend": "off"}})


def make_daemon(cfg, mics=None, speaker=None):
    path = cfg.app_dir / "commands.yaml"
    router = Router(cfg, CommandRegistry(path))
    mics = mics if mics is not None else []

    def mic_factory():
        mic = SlowMic([])
        mics.append(mic)
        return mic

    return Daemon(
        cfg,
        router,
        speaker or TunableSpeaker(),
        mic_factory,
        Engine(fire_on=10**9),
        FakeTranscriber([]),
        bus=Bus(),
        mic_retry_seconds=0.01,
    )


def test_saved_settings_are_used_right_away(app_dir):
    cfg = offline_config(app_dir)
    daemon = make_daemon(cfg)
    save_settings(
        app_dir,
        {
            "tts_rate": 220,
            "tts_voice": "Zira",
            "wake_word_threshold": 0.7,
            "allow_run": True,
            "claude": {"allow_web": False, "actions": ["timer"]},
        },
    )
    daemon.handle_request("settings_changed")
    assert daemon.speaker.configured == [(220, "Zira")]
    assert daemon.engine.threshold == 0.7
    assert cfg.allow_run is True and cfg.tts_rate == 220
    assert cfg.claude.allow_web is False and cfg.claude.actions == ["timer"]
    assert daemon.router.cfg is cfg  # the router sees the change too
    assert not daemon._reopen_mic.is_set()  # same microphone


def test_a_new_microphone_is_opened(app_dir):
    cfg = offline_config(app_dir)
    mics = []
    daemon = make_daemon(cfg, mics)
    thread = threading.Thread(target=daemon.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not mics and time.monotonic() < deadline:
        time.sleep(0.01)
    assert daemon.mic_level() == 1234
    new = save_settings(app_dir, {"mic_device": "USB Microphone"})
    daemon.apply_settings(new)
    while len(mics) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    daemon.stop()
    thread.join(timeout=5)
    assert len(mics) == 2 and cfg.mic_device == "USB Microphone"
    assert daemon.mic_level() is None  # closed when stopped


def test_voice_sample_plays_even_with_voice_replies_off(app_dir):
    daemon = make_daemon(offline_config(app_dir), speaker=TunableSpeaker())
    daemon.voice_enabled = False
    daemon.handle_request("say_sample")
    deadline = time.monotonic() + 2
    while not daemon.speaker.said and time.monotonic() < deadline:
        time.sleep(0.01)
    assert daemon.speaker.said == [SAMPLE]


def test_claude_is_told_your_modes_and_screens(tmp_path):
    import json

    from abdoh.config import ClaudeConfig, Config

    (tmp_path / "modes.yaml").write_text("- name: Movie\n  settings:\n    volume: 5\n")
    (tmp_path / "displays.json").write_text(json.dumps([
        {"id": "a", "number": 1, "name": "", "nickname": ""},
        {"id": "b", "number": 2, "name": "HP 32f", "nickname": "TV"},
    ]))  # fmt: skip
    text = system_prompt(Config(app_dir=tmp_path))
    assert "The user's modes: Movie." in text
    assert "Their screens: 1 Laptop screen, 2 HP 32f (TV)." in text
    assert "ACTION displays:" in text and "ACTION mode:" in text
    off = system_prompt(Config(app_dir=tmp_path, claude=ClaudeConfig(actions=["open_url"])))
    assert "Movie" not in off and "HP 32f" not in off


def test_claude_switches_modes_screens_speakers_and_the_theme():
    from abdoh.commands.actions import claude_action

    class Computer:
        def __init__(self):
            self.done = []
            self.modes = self

        def switch(self, name):
            self.done.append(("mode", name))

        def screens(self, layout):
            self.done.append(("screens", layout))

        def set_audio_output(self, name):
            self.done.append(("output", name))

        def set_dark_mode(self, on):
            self.done.append(("dark", on))

    computer = Computer()
    for kind, arg in [("mode", "Movie"), ("displays", "only 3"), ("audio_output", "headphones"),
                      ("dark_mode", "off")]:  # fmt: skip
        claude_action(kind, arg, computer)
    assert computer.done == [
        ("mode", "Movie"), ("screens", "only 3"), ("output", "headphones"), ("dark", False)
    ]  # fmt: skip


def test_claude_still_cant_type_press_keys_close_apps_or_shut_down():
    from abdoh.config import CLAUDE_ACTIONS

    for kind in ("type", "keys", "close_app", "power", "run", "wait", "focus_app"):
        assert kind not in CLAUDE_ACTIONS


def test_claude_moves_windows_but_never_closes_one():
    import pytest

    from abdoh.commands.actions import ActionError, claude_action

    class Computer:
        def __init__(self):
            self.calls = []

        def move_window(self, app, screen, how):
            self.calls.append(("move", app, screen, how))

        def window(self, action):
            self.calls.append(("window", action))

    computer = Computer()
    claude_action("window", "WhatsApp to 1 maximized", computer)
    claude_action("window", "minimize", computer)
    with pytest.raises(ActionError):
        claude_action("window", "close", computer)
    assert computer.calls == [("move", "whatsapp", "1", "maximized"), ("window", "minimize")]
