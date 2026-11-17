"""One app's volume in the Windows volume mixer: by voice, for Claude and in commands (fakes)."""

import os
from dataclasses import replace

import pytest
import yaml

from abdoh.commands.actions import ActionError, app_and_level, claude_action, run_action
from abdoh.commands.registry import CommandsFileError, parse_commands
from abdoh.computer import Computer, app_label, find_sessions
from abdoh.local_skills import LocalSkills
from abdoh.winaudio import AppSession


def session(sid, program, volume=100, pid=10, playing=True, name="", muted=False):
    return AppSession(sid, pid, program, name, volume, muted, playing)


class FakeMixer:
    """Stands in for abdoh.winaudio's volume mixer functions."""

    def __init__(self, *sessions):
        self.sessions = {s.id: s for s in sessions}

    def app_sessions(self):
        return list(self.sessions.values())

    def set_session_volume(self, session_id, percent=None, muted=None):
        s = self.sessions[session_id]
        if percent is not None:
            s = replace(s, volume=percent)
        if muted is not None:
            s = replace(s, muted=muted)
        self.sessions[session_id] = s
        return True


def mixer():
    return FakeMixer(
        session("b1", "brave", 80, pid=11),
        session("b2", "brave", 80, pid=11),
        session("c", "chrome", 60, pid=12, playing=False),
        session("s", "Spotify", 50, pid=13),
        session("w", "WhatsApp.Root", 100, pid=14, playing=False),
        session("me", "Abdoh", 100, pid=os.getpid()),  # Abdoh's own voice
        session("sys", "", 100, pid=0, name="@%SystemRoot%\\System32\\AudioSrv.Dll"),
    )


# ----- finding apps -----


def ids(found):
    return sorted(s.id for s in found)


def test_apps_are_found_by_name_alias_or_close_spelling():
    all_ = mixer().app_sessions()
    assert ids(find_sessions("the browser", all_)) == ["b1", "b2", "c"]  # every browser
    assert ids(find_sessions("YouTube", all_)) == ["b1", "b2", "c"]
    assert ids(find_sessions("brave", all_)) == ["b1", "b2"]
    assert ids(find_sessions("spotify app", all_)) == ["s"]
    assert ids(find_sessions("whatsapp", all_)) == ["w"]
    assert ids(find_sessions("spotfy", all_)) == ["s"]  # a speech recognition slip
    assert find_sessions("abdoh", all_) == []  # never Abdoh's own voice
    assert find_sessions("the lights", all_) == []
    assert find_sessions("it", all_) == []


def test_apps_have_names_you_can_say():
    assert app_label(session("x", "msedge")) == "Edge"
    assert app_label(session("x", "WhatsApp.Root")) == "WhatsApp"
    assert app_label(session("x", "brave")) == "Brave"
    assert app_label(session("x", "", name="@%SystemRoot%\\x.dll")) == "Windows sounds"


# ----- the computer -----


def test_setting_an_app_changes_all_its_sessions():
    fake = mixer()
    computer = Computer(audio=fake)
    assert computer.set_app_volume("browser", 30) == "Brave"
    assert [fake.sessions[i].volume for i in ("b1", "b2", "c")] == [30, 30, 30]
    assert fake.sessions["s"].volume == 50  # other apps untouched


def test_turning_an_app_down_and_up():
    computer = Computer(audio=mixer())
    assert computer.change_app_volume("spotify", -20) == ("Spotify", 30)
    assert computer.change_app_volume("spotify", 90) == ("Spotify", 100)


def test_muting_and_what_is_playing():
    fake = mixer()
    computer = Computer(audio=fake)
    computer.mute_app("spotify", True)
    assert fake.sessions["s"].muted
    assert computer.playing_apps() == ["Brave", "Spotify"]  # not Abdoh, not system sounds


def test_an_app_that_isnt_there_is_said():
    with pytest.raises(ActionError, match="can't find netflix"):
        Computer(audio=FakeMixer()).set_app_volume("netflix", 10)


# ----- by voice -----


@pytest.fixture
def say():
    fake = mixer()
    skills = LocalSkills(Computer(audio=fake))
    return lambda text: skills.handle(text, text), fake


def test_the_phrases(say):
    handle, fake = say
    assert handle("lower the browser") == "Brave at 60 percent."
    assert handle("turn the browser volume down") == "Brave at 40 percent."
    assert handle("turn up spotify") == "Spotify at 70 percent."
    assert handle("make spotify louder") == "Spotify at 90 percent."
    assert handle("set spotify to twenty percent") == "Spotify at 20 percent."
    assert handle("set the browser volume to 30") == "Brave at 30 percent."
    assert handle("mute spotify") == "Spotify muted." and fake.sessions["s"].muted
    assert handle("unmute spotify") == "Spotify unmuted."
    assert handle("whats playing") == "Playing now: Brave, Spotify."


def test_other_requests_are_left_alone(say):
    handle, fake = say
    assert handle("turn down the lights") is None  # your commands or Claude
    assert handle("set the alarm to 7") is None
    before = dict(fake.sessions)
    handle("turn the volume down")  # the speakers, as before
    assert fake.sessions == before


def test_the_speakers_volume_still_wins(say):
    handle, _ = say
    # The fake has no speakers: that the speakers' volume skill answered shows it came first.
    assert handle("set the volume to 30") == "I can't reach the volume control here."


def test_spoken_percentages_are_numbers():
    from abdoh.local_skills import spoken_number

    assert spoken_number("twenty percent") == 20
    assert spoken_number("75 percent") == 75
    assert spoken_number("percent") is None


# ----- in commands and for Claude -----


def test_an_app_and_a_level():
    assert app_and_level("browser | 30") == ("browser", 30)
    assert app_and_level("browser 30") == ("browser", 30)
    assert app_and_level("Spotify 20%") == ("Spotify", 20)
    assert app_and_level("google chrome 5") == ("google chrome", 5)
    with pytest.raises(ActionError):
        app_and_level("30")
    with pytest.raises(ActionError):
        app_and_level("browser loud")


def test_commands_and_claude_can_set_an_app():
    fake = mixer()
    computer = Computer(audio=fake)
    run_action("app_volume", "spotify 10", computer=computer)
    assert fake.sessions["s"].volume == 10
    claude_action("app_volume", "browser | 25", computer)
    assert fake.sessions["b1"].volume == 25


def test_the_commands_file_checks_app_volume():
    good = "- name: work\n  triggers: [work]\n  actions:\n    - app_volume: browser 30\n"
    assert parse_commands(yaml.safe_load(good))[0].actions == [("app_volume", "browser 30")]
    bad = "- name: work\n  triggers: [work]\n  actions:\n    - app_volume: browser\n"
    with pytest.raises(CommandsFileError, match="app_volume needs an app and a number"):
        parse_commands(yaml.safe_load(bad))
