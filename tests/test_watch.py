"""Watching the screen while the user does something (abdoh/watch.py, ACTION watch)."""

import time

import pytest
from fakes import FakeTranscriber, FakeWakeWord
from PIL import Image
from test_keep_listening import FakeVad
from test_router import FakeBrain

from abdoh.claude.brain import system_prompt
from abdoh.claude.screen import FrontWindow
from abdoh.commands.registry import CommandRegistry
from abdoh.config import Config
from abdoh.daemon import Daemon
from abdoh.events import Bus
from abdoh.local_skills import stop_watching
from abdoh.router import STOPPED_WATCHING, WATCH_FRAME, WATCH_WHEN, Router
from abdoh.speech.tts import FakeSpeaker
from abdoh.ui.api import AppApi, UiState
from abdoh.watch import STILL_SECONDS, Watch, parse

WINDOW = FrontWindow(title="Tax form - Chrome", program="chrome.exe", rect=(0, 0, 800, 600))


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Screen:
    """The screen, as a picture: a grey level, changed by the test."""

    def __init__(self):
        self.level = 120
        self.grabs = 0

    def __call__(self, which="active", window=None):
        self.grabs += 1
        image = Image.new("RGB", (320, 180), (self.level,) * 3)
        image.paste((255, 255, 255), (0, 0, 40, 20))  # never all black
        return image


def make_watch():
    clock, screen = Clock(), Screen()
    return Watch(grab=screen, window=lambda: WINDOW, clock=clock), clock, screen


# ----- the watch -----


def test_a_picture_only_when_the_screen_changed():
    watch, clock, screen = make_watch()
    assert watch.look() is None  # no watch on
    watch.start("filling in the form")
    png, window = watch.look()
    assert png.startswith(b"\x89PNG") and window is WINDOW
    assert watch.look() is None  # the same screen
    screen.level = 30  # something changed
    assert watch.look() is not None
    clock.now += STILL_SECONDS + 1  # still for a while: one anyway (they may be stuck)
    assert watch.look() is not None


def test_a_black_screen_is_skipped():
    watch, _, screen = make_watch()
    watch.start("x")
    screen.__call__ = None
    watch._grab = lambda which, window: Image.new("RGB", (64, 36))
    assert watch.look() is None


def test_notes_and_time():
    watch, clock, _ = make_watch()
    watch.start("")
    assert watch.goal == "what the user is doing"
    for i in range(8):
        watch.note(f"said {i}")
    assert watch.notes == [f"said {i}" for i in range(2, 8)]
    assert watch.minutes() == "less than a minute"
    clock.now += 61
    assert watch.minutes() == "a minute" and watch.quiet_for() == 61
    watch.heard_user()
    assert watch.quiet_for() == 0
    assert watch.stop() and not watch.stop() and not watch.active


# ----- "stop looking at the screen", in any words -----


@pytest.mark.parametrize(
    "said",
    [
        "Okay, you can stop looking at the screen.",
        "stop watching",
        "You can stop watching me now, thanks.",
        "End the session.",
        "I'm done, no need to keep checking.",
        "That's enough watching.",
        "Okay stop looking at my screen please",
        "quit monitoring",
    ],
)
def test_stop_watching_phrases(said):
    assert stop_watching(said)


@pytest.mark.parametrize(
    "said",
    [
        "How do I stop the screen from dimming?",
        "Is this field right?",
        "stop",
        "what should I click next",
        "I stopped at the second page, look at this, what does the error mean and why",
    ],
)
def test_not_stop_watching(said):
    assert not stop_watching(said)


# ----- the router -----


def make_router(tmp_path, *answers, allow_screen=True):
    cfg = Config(app_dir=tmp_path)
    cfg.claude.allow_screen = allow_screen
    shots = []

    def capture():
        shots.append(True)
        return b"PNG"

    brain = FakeBrain()
    replies = list(answers)

    def stream(prompt, image_png=None):
        brain.asked.append((prompt, image_png))
        yield replies.pop(0) if replies else "fine"

    brain.stream = stream
    screen = Screen()
    router = Router(
        cfg,
        CommandRegistry(tmp_path / "none.yaml"),
        brain=brain,
        capture=capture,
        window=lambda: WINDOW,
        grab=screen,
    )
    changes = []
    router.on_watch = changes.append
    return router, brain, shots, changes


def test_claude_starts_a_watch(tmp_path):
    router, brain, _, changes = make_router(
        tmp_path,
        "ACTION watch: filling in the tax form; check each field\n"
        "Okay, I'm watching your screen. Go ahead.",
    )
    reply = " ".join(router.handle("watch me fill this in and tell me if I get it wrong"))
    assert reply == "Okay, I'm watching your screen. Go ahead."
    assert router.watching and router.watch.goal.startswith("filling in the tax form")
    assert changes == [True]
    assert "ACTION watch:" in system_prompt(router.cfg)


def test_no_watch_without_the_screen_permission(tmp_path):
    router, _, _, changes = make_router(
        tmp_path, "ACTION watch: the form\nOkay.", allow_screen=False
    )
    " ".join(router.handle("watch me do this"))
    assert not router.watching and changes == []


def test_while_watching_what_you_say_comes_with_the_screen(tmp_path):
    router, brain, shots, _ = make_router(
        tmp_path, "ACTION watch: the form\nOk.", "Yes, that's right."
    )
    " ".join(router.handle("watch me do this"))
    reply = " ".join(router.handle("is this field right?", aside=True))
    assert reply == "Yes, that's right."
    prompt, image = brain.asked[-1]
    assert image == b"PNG" and shots == [True]
    assert "You're watching the user's screen: the form" in prompt


def test_stop_looking_ends_the_watch(tmp_path):
    router, brain, _, changes = make_router(tmp_path, "ACTION watch: the form\nOk.")
    " ".join(router.handle("watch me do this"))
    assert router.handle("okay you can stop looking at the screen", aside=True) == STOPPED_WATCHING
    assert not router.watching and changes == [True, False]
    assert len(brain.asked) == 1  # without Claude


def test_claude_ends_the_watch(tmp_path):
    router, _, _, changes = make_router(
        tmp_path, "ACTION watch: the form\nOk.", "ACTION watch: off\nGlad I could help."
    )
    " ".join(router.handle("watch me do this"))
    assert " ".join(router.handle("thanks, that's all")) == "Glad I could help."
    assert not router.watching and changes == [True, False]


def test_a_frame_is_quiet_when_all_is_well(tmp_path):
    router, brain, _, _ = make_router(
        tmp_path, "ACTION watch: the form\nOk.", "ACTION ignore: fine\nThey're doing fine."
    )
    " ".join(router.handle("watch me do this"))
    assert list(router.watch_frame(b"PNG", WINDOW.title, WINDOW.program)) == []
    prompt, image = brain.asked[-1]
    assert image == b"PNG" and prompt.startswith("(Watching the user's screen: the form")
    assert '"Tax form - Chrome", chrome.exe' in prompt


def test_a_frame_speaks_up_and_remembers_what_it_said(tmp_path):
    router, brain, _, _ = make_router(
        tmp_path,
        "ACTION watch: the form\nOk.",
        "The date goes day first.",
        "ACTION ignore: fine",
    )
    " ".join(router.handle("watch me do this"))
    assert list(router.watch_frame(b"PNG")) == ["The date goes day first."]
    router.watch.note("The date goes day first.")
    list(router.watch_frame(b"PNG"))
    assert 'What you said during the watch so far: "The date goes day first."' in brain.asked[-1][0]


def test_a_frame_can_end_the_watch(tmp_path):
    router, _, _, changes = make_router(
        tmp_path, "ACTION watch: the form\nOk.", "ACTION watch: off\nAll done, well done!"
    )
    " ".join(router.handle("watch me do this"))
    assert list(router.watch_frame(b"PNG")) == ["All done, well done!"]
    assert not router.watching and changes == [True, False]


def test_frame_prompt_mentions_the_quiet_line():
    assert "ACTION watch: off" in WATCH_FRAME
    assert all("ACTION ignore: fine" in when for when in WATCH_WHEN.values())


# ----- mistakes only, or suggestions too -----


@pytest.mark.parametrize(
    ("arg", "goal", "suggest"),
    [
        ("shopping for headphones | suggestions", "shopping for headphones", True),
        ("the tax form; check each field | mistakes", "the tax form; check each field", False),
        ("the form | mistakes only", "the form", False),
        ("the form | no suggestions", "the form", False),
        ("the form", "the form", None),
        ("| suggestions", "", True),
    ],
)
def test_the_kind_of_watch(arg, goal, suggest):
    assert parse(arg) == (goal, suggest)


def test_a_watch_with_suggestions(tmp_path):
    router, brain, _, changes = make_router(
        tmp_path,
        "ACTION watch: shopping for headphones on Amazon | suggestions\nOkay, I'm watching.",
        "This one has the same sound for half the price, two results down.",
    )
    " ".join(router.handle("watch the screen while I shop and give me suggestions"))
    assert router.watch.goal == "shopping for headphones on Amazon" and router.watch.suggest
    assert list(router.watch_frame(b"PNG")) == [
        "This one has the same sound for half the price, two results down."
    ]
    prompt = brain.asked[-1][0]
    assert "They want suggestions too" in prompt and "a better or cheaper choice" in prompt
    assert "suggestions" in system_prompt(router.cfg)


def test_mistakes_only_has_no_suggestions(tmp_path):
    router, brain, _, _ = make_router(tmp_path, "ACTION watch: the form | mistakes\nOk.", "fine")
    " ".join(router.handle("watch me fill this in"))
    assert not router.watch.suggest
    list(router.watch_frame(b"PNG"))
    assert "suggestions" not in brain.asked[-1][0].split("Nobody asked anything")[1]


def test_a_goal_alone_is_mistakes_only(tmp_path):
    router, _, _, _ = make_router(tmp_path, "ACTION watch: the form\nOk.")
    " ".join(router.handle("watch me fill this in"))
    assert router.watching and not router.watch.suggest


def test_stop_suggesting_keeps_the_watch_going(tmp_path):
    router, brain, _, changes = make_router(
        tmp_path,
        "ACTION watch: shopping on Amazon | suggestions\nOkay, I'm watching.",
        "ACTION watch: shopping on Amazon | mistakes\nOkay, no more suggestions.",
        "ACTION watch: shopping on Amazon | suggestions\nSure, I'll suggest things again.",
    )
    " ".join(router.handle("watch me shop and give me tips"))
    watch = router.watch
    generation, started = watch.generation, watch.started
    watch.note("This one is cheaper.")
    reply = " ".join(router.handle("stop suggesting for now", aside=True))
    assert reply == "Okay, no more suggestions."
    prompt = brain.asked[-1][0]
    assert "You speak up about mistakes and with suggestions" in prompt
    assert "ACTION watch: shopping on Amazon | mistakes" in prompt
    assert router.watching and not watch.suggest
    assert (watch.generation, watch.started, watch.notes) == (
        generation,
        started,
        ["This one is cheaper."],
    )
    " ".join(router.handle("okay you can suggest things again", aside=True))
    assert watch.suggest and "ACTION watch: shopping on Amazon | suggestions" in brain.asked[-1][0]
    assert changes == [True, True, True]


@pytest.mark.parametrize(
    "said", ["stop suggesting for now", "no more suggestions please", "stop the suggestions"]
)
def test_stop_suggesting_is_not_stop_watching(said):
    assert not stop_watching(said)


def test_the_watch_ends_without_its_suggestions(tmp_path):
    router, _, _, _ = make_router(tmp_path, "ACTION watch: shopping | suggestions\nOk.")
    " ".join(router.handle("watch me shop"))
    router.end_watch()
    assert not router.watching and not router.watch.suggest


# ----- the daemon -----


DAEMONS = []


@pytest.fixture(autouse=True)
def stop_daemons():
    """The watch loops of a test's daemons end with it."""
    yield
    while DAEMONS:
        daemon = DAEMONS.pop()
        daemon.stop_event.set()
        daemon.router.end_watch()


def make_daemon(tmp_path, *answers):
    router, brain, _, _ = make_router(tmp_path, *answers)
    bus = Bus()
    speaker = FakeSpeaker()
    daemon = Daemon(
        router.cfg, router, speaker, None, FakeWakeWord(10_000), FakeTranscriber([]),
        bus=bus, vad=FakeVad(),
    )  # fmt: skip
    DAEMONS.append(daemon)
    return daemon, router, speaker, bus


def events(bus, kind):
    return [value for k, value in bus.pending_events() if k == kind]


def test_watching_listens_without_the_wake_word(tmp_path):
    daemon, router, _, bus = make_daemon(tmp_path, "ACTION watch: the form\nOk.")
    assert not daemon.keeps_listening()
    daemon.handle_text("watch me do this")
    assert daemon.keeps_listening()
    assert {"goal": "the form", "suggest": False} in events(bus, "watch")
    daemon.set_paused(True)
    assert not daemon.keeps_listening()


def test_a_frame_is_spoken_and_noted(tmp_path):
    daemon, router, speaker, _ = make_daemon(
        tmp_path, "ACTION watch: the form\nOk.", "That field wants your tax number."
    )
    daemon.handle_text("watch me do this")
    daemon._watch_frame(b"PNG", WINDOW)
    assert speaker.said[-1] == "That field wants your tax number."
    assert router.watch.notes == ["That field wants your tax number."]


def test_no_frame_while_someone_talks(tmp_path):
    daemon, router, speaker, _ = make_daemon(tmp_path, "ACTION watch: the form\nOk.", "Hey!")
    daemon.handle_text("watch me do this")
    with daemon._handle_lock:  # a request is being answered
        assert daemon._watch_busy()
        daemon._watch_frame(b"PNG", WINDOW)
    assert speaker.said == ["Ok."]
    daemon._recording = True
    assert daemon._watch_busy()


def test_stop_listening_ends_the_watch(tmp_path):
    daemon, router, _, _ = make_daemon(tmp_path, "ACTION watch: the form\nOk.")
    daemon.handle_text("watch me do this")
    daemon.handle_text("stop listening")
    assert daemon.paused and not router.watching


def test_the_window_button_ends_it(tmp_path):
    daemon, router, _, bus = make_daemon(tmp_path, "ACTION watch: the form\nOk.")
    daemon.handle_text("watch me do this")
    AppApi(bus, UiState(), router.cfg).stop_watching()
    kind, value = bus.next_request(1)
    daemon.handle_request(kind, value)
    assert not router.watching


def test_the_loop_looks_and_ends_after_quiet_minutes(tmp_path, monkeypatch):
    daemon, router, speaker, _ = make_daemon(
        tmp_path, "ACTION watch: the form\nOk.", "Careful, that's the wrong year."
    )
    daemon.WATCH_MIN_SECONDS = 0.01
    daemon.cfg.watch_seconds = 0.01
    daemon.handle_text("watch me do this")  # starts the loop
    deadline = time.monotonic() + 5
    while "Careful, that's the wrong year." not in speaker.said and time.monotonic() < deadline:
        time.sleep(0.02)
    assert "Careful, that's the wrong year." in speaker.said
    router.watch.last_word -= 25 * 60  # 25 quiet minutes
    while router.watching and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not router.watching
    while not speaker.said[-1].startswith("I stopped watching") and time.monotonic() < deadline:
        time.sleep(0.02)
    assert "20 minutes" in speaker.said[-1]
    daemon.stop_event.set()


def test_the_window_remembers_the_watch():
    state = UiState()
    state.feed("watch", {"goal": "the form", "suggest": True})
    assert state.snapshot()["watch"] == {"goal": "the form", "suggest": True}
    state.feed("watch", None)
    assert state.snapshot()["watch"] is None


def counted_loops(daemon):
    """The generations of the look loops running now (a list that follows them). The loops
    don't look: a picture would take the fake Claude's next answer."""
    daemon.WATCH_MIN_SECONDS = 0.01
    daemon.cfg.watch_seconds = 0.01
    daemon._watch_busy = lambda: True
    running = []
    loop = daemon._watch_loop

    def counted(generation):
        running.append(generation)
        try:
            loop(generation)
        finally:
            running.remove(generation)

    daemon._watch_loop = counted
    return running


def test_one_loop_while_the_watch_changes(tmp_path):
    daemon, router, _, bus = make_daemon(
        tmp_path, "ACTION watch: a | suggestions\nOk.", "ACTION watch: a | mistakes\nOkay."
    )
    running = counted_loops(daemon)
    daemon.handle_text("watch me do a and give me tips")
    daemon.handle_text("stop suggesting for now")
    time.sleep(0.3)
    assert running == [router.watch.generation] and router.watching
    assert events(bus, "watch")[-2:] == [
        {"goal": "a", "suggest": True},
        {"goal": "a", "suggest": False},
    ]
    router.end_watch()
    time.sleep(0.1)
    assert running == []


def test_a_new_watch_after_the_last_one_ended(tmp_path):
    daemon, router, _, _ = make_daemon(tmp_path, "ACTION watch: a\nOk.", "ACTION watch: b\nOk.")
    running = counted_loops(daemon)
    daemon.handle_text("watch me do a")
    time.sleep(0.1)
    first = router.watch.generation
    router.end_watch()
    daemon.handle_text("now watch me do b")
    time.sleep(0.3)
    assert running == [router.watch.generation] and router.watch.generation != first
    assert router.watch.goal == "b"
    router.end_watch()
    time.sleep(0.1)
    assert running == []
