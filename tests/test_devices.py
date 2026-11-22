"""Audio devices follow Windows: new microphones and defaults are noticed, PortAudio reads its
list again only while no stream is open, and the daemon reopens the microphone."""

import threading

import pytest
from fakes import FakeMic, FakeTranscriber, FakeWakeWord, silent_block

from abdoh.audio import devices
from abdoh.audio.devices import DeviceWatch, Snapshot, describe, reload_portaudio
from abdoh.audio.mic import MicrophoneError, find_input_device, same_name
from abdoh.config import Config
from abdoh.daemon import Daemon
from abdoh.events import Bus
from abdoh.speech.tts import FakeSpeaker

LAPTOP = ("{mic-1}", "Microphone Array (Realtek(R) Audio)")
CAMERA = ("{mic-2}", "Microphone (Lenovo FHD Webcam Audio)")
HEADSET = ("{mic-3}", "Headset (WH-1000XM4)")


def snap(default, *mics, speakers="{spk-1}") -> Snapshot:
    return Snapshot(default[0], speakers, tuple(sorted(mics)))


@pytest.fixture(autouse=True)
def no_open_streams():
    devices._open_streams = 0
    yield
    devices._open_streams = 0


# ----- noticing changes -----


def test_the_first_look_only_remembers_and_a_change_is_reported():
    seen = [snap(CAMERA, LAPTOP, CAMERA)]
    changes = []
    watch = DeviceWatch(lambda old, new: changes.append((old, new)), lambda: seen[-1])
    watch.check()
    watch.check()
    assert changes == []
    seen.append(snap(HEADSET, LAPTOP, HEADSET))  # undocked, headset on
    watch.check()
    assert changes == [(seen[0], seen[1])]
    watch.check()
    assert len(changes) == 1  # nothing new


def test_a_new_default_speaker_is_a_change():
    seen = [snap(LAPTOP, LAPTOP)]
    changes = []
    watch = DeviceWatch(lambda old, new: changes.append(new), lambda: seen[-1])
    watch.check()
    seen.append(snap(LAPTOP, LAPTOP, speakers="{spk-2}"))
    watch.check()
    assert len(changes) == 1


def test_reading_windows_can_fail_quietly():
    calls = []

    def broken():
        calls.append(1)
        raise OSError("COM is busy")

    watch = DeviceWatch(lambda old, new: calls.append("changed"), broken)
    watch.check()
    watch = DeviceWatch(lambda old, new: calls.append("changed"), lambda: None)  # not Windows
    watch.check()
    assert "changed" not in calls


def test_the_watch_runs_until_stopped():
    stop = threading.Event()
    looks = []
    watch = DeviceWatch(lambda old, new: None, lambda: looks.append(1), every=0.01)
    thread = watch.start(stop)
    for _ in range(200):
        if len(looks) >= 3:
            break
        threading.Event().wait(0.01)
    stop.set()
    thread.join(2)
    assert len(looks) >= 3 and not thread.is_alive()


def test_the_log_says_what_changed():
    old = snap(CAMERA, LAPTOP, CAMERA)
    new = snap(HEADSET, LAPTOP, HEADSET, speakers="{spk-2}")
    text = describe(old, new)
    assert "default microphone: Headset (WH-1000XM4)" in text
    assert "default speakers changed" in text
    assert "plugged in: Headset (WH-1000XM4)" in text
    assert "unplugged: Microphone (Lenovo FHD Webcam Audio)" in text


# ----- reading the devices again -----


class FakePortAudio:
    def __init__(self):
        self.calls = []

    def _terminate(self):
        self.calls.append("terminate")

    def _initialize(self):
        self.calls.append("initialize")


def test_portaudio_reads_the_devices_again_only_with_no_stream_open():
    sd = FakePortAudio()
    devices.stream_opened()
    assert reload_portaudio(sd) is False
    assert sd.calls == []
    devices.stream_closed()
    assert reload_portaudio(sd) is True
    assert sd.calls == ["terminate", "initialize"]


def test_closing_more_streams_than_were_opened_doesnt_go_negative():
    devices.stream_closed()
    devices.stream_opened()
    assert reload_portaudio(FakePortAudio()) is False


class FakeSounddevice:
    class default:  # noqa: N801 - mirrors sounddevice.default
        device = (1, 3)

    def query_devices(self):
        return [
            {"name": "Microsoft Sound Mapper - Input", "max_input_channels": 2, "hostapi": 0},
            {"name": "Microphone Array (Realtek(R) Au", "max_input_channels": 2, "hostapi": 0},
            {"name": "Headset (WH-1000XM4)", "max_input_channels": 1, "hostapi": 0},
            {"name": "Speakers", "max_input_channels": 0, "hostapi": 0},
        ]


def test_a_microphone_is_found_by_its_full_or_cut_name():
    sd = FakeSounddevice()
    assert find_input_device("Microphone Array (Realtek(R) Audio)", sd) == 1  # Windows' name
    assert find_input_device("Microphone Array (Realtek(R) Au", sd) == 1  # saved by 0.8
    assert find_input_device("Headset (WH-1000XM4)", sd) == 2
    assert find_input_device("Microphone (Lenovo FHD Webcam Audio)", sd) is None  # undocked
    assert same_name("Headset", "Headset ") and not same_name("Headset", "")


# ----- the daemon follows them -----


class CountingMic(FakeMic):
    opened = 0

    def start(self):
        CountingMic.opened += 1


def make_daemon(mic_factory, bus=None):
    return Daemon(
        Config(),
        StubRouter(),
        FakeSpeaker(),
        mic_factory,
        FakeWakeWord(fire_on=10_000),
        FakeTranscriber([]),
        bus=bus,
        mic_retry_seconds=0.01,
    )


class StubRouter:
    brain = None
    computer = None
    modes = None

    def __init__(self):
        self.on_thinking = self.on_activity = None

    def add_builtin(self, *args):
        pass


def run_until(daemon, condition, timeout=5.0):
    thread = threading.Thread(target=daemon.run, daemon=True)
    thread.start()
    for _ in range(int(timeout / 0.01)):
        if condition():
            break
        threading.Event().wait(0.01)
    daemon.stop()
    thread.join(timeout)
    assert not thread.is_alive()


def test_a_device_change_reads_the_devices_again_and_reopens_the_mic():
    CountingMic.opened = 0
    bus = Bus()
    reloads = []
    daemon = make_daemon(lambda: CountingMic([silent_block()] * 5), bus)
    daemon.reload_devices = lambda: reloads.append(1) or True
    events = []
    daemon.bus.emit = lambda kind, value=None: events.append(kind)

    def change_once():
        if CountingMic.opened == 1 and not reloads and "devices" not in events:
            daemon.devices_changed(snap(CAMERA, CAMERA), snap(HEADSET, HEADSET))
        return CountingMic.opened >= 2

    run_until(daemon, change_once)
    assert reloads == [1]
    assert "devices" in events  # Settings lists the microphones again
    assert CountingMic.opened >= 2


def test_the_reload_waits_while_something_plays():
    answers = [False, False, True]
    daemon = make_daemon(lambda: CountingMic([]))
    daemon.reload_devices = lambda: answers.pop(0)
    daemon._devices_stale = True
    daemon._read_devices_again()
    assert answers == [] and daemon._devices_stale is False


def test_a_lost_microphone_reads_the_devices_again_before_retrying():
    attempts, reloads = [], []

    def flaky():
        attempts.append(1)
        if len(attempts) < 2:
            raise MicrophoneError("unplugged")
        return CountingMic([])

    daemon = make_daemon(flaky)
    daemon.reload_devices = lambda: reloads.append(1) or True
    run_until(daemon, lambda: len(attempts) >= 2)
    assert reloads  # read again before the second try
