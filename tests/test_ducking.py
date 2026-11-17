"""Other apps go quieter while Abdoh listens (a fake volume mixer)."""

from dataclasses import replace

from abdoh.audio.ducking import Ducker
from abdoh.winaudio import AppSession

OWN = 100


class Mixer:
    def __init__(self, *sessions):
        self.sessions = {s.id: s for s in sessions}
        self.changes = []

    def list(self):
        return list(self.sessions.values())

    def set(self, session_id, percent):
        self.changes.append((session_id, percent))
        if session_id not in self.sessions:
            return False
        self.sessions[session_id] = replace(self.sessions[session_id], volume=percent)
        return True

    def volume(self, session_id):
        return self.sessions[session_id].volume


def app(sid, program, volume=100, playing=True, pid=1, muted=False):
    return AppSession(sid, pid, program, "", volume, muted, playing)


def make(*sessions):
    mixer = Mixer(*sessions)
    return Ducker(mixer.list, mixer.set, own_pid=OWN), mixer


def test_playing_apps_go_down_and_come_back():
    ducker, mixer = make(app("b", "brave", 100), app("s", "spotify", 60, pid=2))
    assert ducker.duck(30) == 2
    assert (mixer.volume("b"), mixer.volume("s")) == (30, 18)
    ducker.release()
    assert (mixer.volume("b"), mixer.volume("s")) == (100, 60)


def test_abdoh_itself_and_quiet_apps_are_left_alone():
    ducker, mixer = make(
        app("me", "Abdoh", pid=OWN),  # Abdoh's own voice
        app("idle", "discord", playing=False),
        app("muted", "spotify", muted=True),
        app("zero", "chrome", volume=0),
    )
    assert ducker.duck(30) == 0
    assert mixer.changes == []


def test_ducking_twice_does_nothing_more():
    ducker, mixer = make(app("b", "brave", 100))
    ducker.duck(30)
    ducker.duck(30)
    assert mixer.volume("b") == 30
    ducker.release()
    ducker.release()
    assert mixer.volume("b") == 100 and len(mixer.changes) == 2


def test_an_app_you_changed_meanwhile_keeps_your_volume():
    ducker, mixer = make(app("b", "brave", 100), app("s", "spotify", 80, pid=2))
    ducker.duck(30)
    mixer.set("s", 50)  # you turned Spotify up yourself
    ducker.release()
    assert (mixer.volume("b"), mixer.volume("s")) == (100, 50)


def test_an_app_that_closed_meanwhile_is_skipped():
    ducker, mixer = make(app("b", "brave", 100))
    ducker.duck(30)
    del mixer.sessions["b"]
    ducker.release()  # no error
    assert not ducker.ducked


def test_a_quiet_app_never_goes_to_zero():
    ducker, mixer = make(app("b", "brave", 2))
    ducker.duck(30)
    assert mixer.volume("b") == 1


# ----- when Abdoh does it -----


class FakeDucker:
    """Writes what happened into `order`, next to what was said."""

    def __init__(self, order):
        self.order = order

    def duck(self, percent):
        self.order.append(("duck", percent))

    def release(self):
        self.order.append(("release",))


class Router:
    brain = None
    registry = None

    def __init__(self, *replies):
        self.replies = list(replies)

    def add_builtin(self, name, triggers, handler):
        pass

    def builtin_name(self, text):
        return None

    def handle(self, text):
        return self.replies.pop(0) if self.replies else "Okay."


def daemon_with(router, texts, cfg=None):
    from fakes import FakeMic, FakeTranscriber, FakeWakeWord, silent_block, tone_block

    from abdoh.config import Config
    from abdoh.daemon import Daemon
    from abdoh.speech.tts import FakeSpeaker

    mic = FakeMic([tone_block()] * 2 + [silent_block()] * 12)
    order = []
    daemon = Daemon(
        cfg or Config(follow_up_seconds=0),
        router,
        FakeSpeaker(),
        lambda: mic,
        FakeWakeWord(fire_on=2),
        FakeTranscriber(texts),
        ducker=FakeDucker(order),
    )
    original = daemon.speaker.say
    daemon.speaker.say = lambda text: (order.append(("say", text)), original(text))
    return daemon, mic, order


def test_other_apps_are_quiet_from_the_wake_word_until_the_answer_is_said():
    daemon, mic, order = daemon_with(Router("It's noon."), ["Abdoh what time is it"])
    daemon._listen_once(mic)
    assert order == [("duck", 30), ("say", "It's noon."), ("release",)]


def test_they_stay_quiet_while_abdoh_listens_for_more():
    from abdoh.config import Config

    daemon, mic, order = daemon_with(Router(["Which city?"]), ["Abdoh weather"], Config())
    daemon._listen_once(mic)  # Claude asked a question: Abdoh listens for the answer next
    assert daemon._awaiting_answer and ("release",) not in order
    daemon._listen_once(mic)  # nothing was said: done
    assert order[-1] == ("release",)


def test_turned_off_nothing_changes():
    from abdoh.config import Config

    daemon, mic, order = daemon_with(
        Router("It's noon."), ["Abdoh time"], Config(follow_up_seconds=0, duck_others=False)
    )
    daemon._listen_once(mic)
    assert ("duck", 30) not in order


def test_the_share_comes_from_the_settings():
    from abdoh.config import Config

    daemon, mic, order = daemon_with(
        Router("Okay."), ["Abdoh hi"], Config(follow_up_seconds=0, duck_percent=10)
    )
    daemon._listen_once(mic)
    assert order[0] == ("duck", 10)


def test_quitting_gives_the_volume_back():
    daemon, _, order = daemon_with(Router(), [])
    daemon.stop()
    assert order == [("release",)]
