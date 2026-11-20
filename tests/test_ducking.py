"""Other apps go quieter while Xanthos listens (a fake volume mixer)."""

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
        app("me", "Xanthos", pid=OWN),  # Xanthos's own voice
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


# ----- when Xanthos does it -----


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

    def handle(self, text, aside=False):
        return self.replies.pop(0) if self.replies else "Okay."


def daemon_with(router, texts, cfg=None):
    from fakes import FakeMic, FakeTranscriber, FakeWakeWord, silent_block, tone_block

    from abdoh.config import Config
    from abdoh.daemon import Daemon
    from abdoh.speech.tts import FakeSpeaker

    mic = FakeMic([tone_block()] * 2 + [tone_block()] * 3 + [silent_block()] * 12)  # wake, request
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
    daemon, mic, order = daemon_with(Router("It's noon."), ["Xanthos what time is it"])
    daemon._listen_once(mic)
    # Ducked on the wake word, when recording starts and when speaking (the real Ducker ignores
    # the repeats).
    assert order == [("duck", 30)] * 3 + [("say", "It's noon."), ("release",)]


def test_they_stay_quiet_while_abdoh_listens_for_more():
    from abdoh.config import Config

    daemon, mic, order = daemon_with(Router(["Which city?"]), ["Xanthos weather"], Config())
    daemon._listen_once(mic)  # Claude asked a question: Xanthos listens for the answer next
    assert daemon._awaiting_answer and ("release",) not in order
    daemon._listen_once(mic)  # nothing was said: done
    assert order[-1] == ("release",)


def test_turned_off_nothing_changes():
    from abdoh.config import Config

    daemon, mic, order = daemon_with(
        Router("It's noon."), ["Xanthos time"], Config(follow_up_seconds=0, duck_others=False)
    )
    daemon._listen_once(mic)
    assert ("duck", 30) not in order


def test_the_share_comes_from_the_settings():
    from abdoh.config import Config

    daemon, mic, order = daemon_with(
        Router("Okay."), ["Xanthos hi"], Config(follow_up_seconds=0, duck_percent=10)
    )
    daemon._listen_once(mic)
    assert order[0] == ("duck", 10)


def test_quitting_gives_the_volume_back():
    daemon, _, order = daemon_with(Router(), [])
    daemon.stop()
    assert order == [("release",)]


# ----- for the whole conversation -----


def test_an_app_that_starts_playing_later_goes_down_too():
    later = app("b", "spotify.exe", 80, playing=False, pid=2)
    mixer = Mixer(app("a", "chrome.exe", 100), later)
    ducker = Ducker(mixer.list, mixer.set, own_pid=OWN, follow_seconds=None)
    assert ducker.duck(30) == 1
    assert ducker.refresh() == 0  # nothing new yet
    mixer.sessions["b"] = replace(later, playing=True)  # the next song starts
    assert ducker.refresh() == 1
    assert (mixer.volume("a"), mixer.volume("b")) == (30, 24)
    assert ducker.refresh() == 0  # once is enough
    ducker.release()
    assert (mixer.volume("a"), mixer.volume("b")) == (100, 80)


def test_nothing_is_lowered_after_the_conversation():
    mixer = Mixer(app("a", "chrome.exe", 100, playing=False))
    ducker = Ducker(mixer.list, mixer.set, own_pid=OWN, follow_seconds=None)
    ducker.duck(30)
    ducker.release()
    mixer.sessions["a"] = replace(mixer.sessions["a"], playing=True)
    assert ducker.refresh() == 0 and mixer.volume("a") == 100


def test_the_mixer_is_followed_in_the_background():
    import time

    later = app("b", "spotify.exe", 80, playing=False, pid=2)
    mixer = Mixer(later)
    ducker = Ducker(mixer.list, mixer.set, own_pid=OWN, follow_seconds=0.01)
    ducker.duck(50)
    mixer.sessions["b"] = replace(later, playing=True)
    for _ in range(200):
        if mixer.volume("b") == 40:
            break
        time.sleep(0.01)
    ducker.release()
    assert mixer.volume("b") == 80 and ("b", 40) in mixer.changes


def test_a_typed_requests_spoken_reply_lowers_the_others_and_gives_them_back():
    daemon, _, order = daemon_with(Router("It's noon."), [])
    daemon.handle_text("what time is it")
    assert order == [("duck", 30), ("say", "It's noon."), ("release",)]


def test_a_quiet_action_doesnt_touch_the_others():
    from abdoh.system_skills import Done

    daemon, _, order = daemon_with(Router(Done("Opening Spotify.")), [])
    daemon.handle_text("open spotify")
    assert ("duck", 30) not in order
