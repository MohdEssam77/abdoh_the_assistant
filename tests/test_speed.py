"""Staying fast: no background throttling, and Claude kept ready between requests."""

import ctypes

from fakes import FakeMic, FakeTranscriber, FakeWakeWord

from abdoh.commands.registry import CommandRegistry
from abdoh.config import Config
from abdoh.daemon import Daemon
from abdoh.events import Bus
from abdoh.power import EXECUTION_SPEED, IGNORE_TIMER_RESOLUTION, keep_full_speed
from abdoh.router import Router
from abdoh.speech.tts import FakeSpeaker

# ----- Windows' background throttling -----


class FakeKernel32:
    def __init__(self, accept):
        self.accept = accept  # which control masks Windows says yes to
        self.asked = []

    def GetCurrentProcess(self):  # noqa: N802 - Windows' name
        return -1

    def SetProcessInformation(self, process, kind, state, size):  # noqa: N802
        control = ctypes.cast(state, ctypes.POINTER(ctypes.c_ulong * 3)).contents
        self.asked.append((kind, control[0], control[1], control[2]))
        return control[1] in self.accept


def test_throttling_is_turned_off():
    kernel = FakeKernel32(accept={EXECUTION_SPEED | IGNORE_TIMER_RESOLUTION})
    assert keep_full_speed(kernel) is True
    # ProcessPowerThrottling, version 1, "we control speed and timers", "and both are off"
    assert kernel.asked == [(4, 1, EXECUTION_SPEED | IGNORE_TIMER_RESOLUTION, 0)]


def test_windows_10_gets_the_request_it_understands():
    kernel = FakeKernel32(accept={EXECUTION_SPEED})
    assert keep_full_speed(kernel) is True
    assert [control for _, _, control, _ in kernel.asked] == [
        EXECUTION_SPEED | IGNORE_TIMER_RESOLUTION,
        EXECUTION_SPEED,
    ]


def test_a_refusal_is_not_an_error():
    assert keep_full_speed(FakeKernel32(accept=set())) is False


# ----- Claude stays ready -----


class Brain:
    name = "Claude Code"
    remembers = True

    def __init__(self, setup="a"):
        self.setup = setup
        self.warmed = self.closed = 0
        self.on_activity = None

    def same_setup(self, other):
        return self.setup == other.setup

    def warm_up(self):
        self.warmed += 1

    def close(self):
        self.closed += 1

    def status(self):
        return "Pro subscription (Claude Code)"

    def stream(self, prompt, image=None):
        yield "Okay."


def make_daemon(tmp_path, brain):
    path = tmp_path / "commands.yaml"
    path.write_text("[]\n")
    bus = Bus()
    router = Router(Config(app_dir=tmp_path), CommandRegistry(path), brain=brain)
    daemon = Daemon(
        router.cfg,
        router,
        FakeSpeaker(),
        lambda: FakeMic([]),
        FakeWakeWord(fire_on=10**9),
        FakeTranscriber([]),
        bus=bus,
    )
    return daemon, bus


def test_claude_is_warmed_up_and_reports_what_its_doing(tmp_path):
    brain = Brain()
    daemon, bus = make_daemon(tmp_path, brain)
    daemon._connect_brain()
    assert brain.warmed == 1
    brain.on_activity("Searching the web")
    assert ("activity", "Searching the web") in bus.pending_events()


def test_unrelated_settings_keep_the_open_conversation(tmp_path):
    old = Brain("a")
    daemon, _ = make_daemon(tmp_path, old)
    same = Brain("a")
    daemon._use_brain(same)
    assert daemon.router.brain is old and old.closed == 0
    assert same.closed == 1 and same.warmed == 0  # the spare one is let go


def test_changed_claude_settings_start_a_new_conversation(tmp_path):
    old = Brain("a")
    daemon, _ = make_daemon(tmp_path, old)
    new = Brain("b")
    daemon._use_brain(new)
    assert daemon.router.brain is new and old.closed == 1
    assert new.warmed == 1 and new.on_activity == daemon._activity
    daemon._use_brain(None)  # Claude turned off
    assert daemon.router.brain is None and new.closed == 1


def test_stopping_abdoh_closes_claude(tmp_path):
    brain = Brain()
    daemon, _ = make_daemon(tmp_path, brain)
    daemon.stop()
    assert brain.closed == 1


def test_a_brain_that_remembers_is_not_told_the_last_exchange_again(tmp_path):
    asked = []

    class Remembering(Brain):
        def stream(self, prompt, image=None):
            asked.append(prompt)
            yield "Fine."

    daemon, _ = make_daemon(tmp_path, Remembering())
    list(daemon.router.handle("how are you"))
    list(daemon.router.handle("and tomorrow"))
    assert asked == ["how are you", "and tomorrow"]  # no "previous exchange" pasted in
