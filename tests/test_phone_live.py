"""The computer's screens on the phone, live, and pictures of the right one (story 155)."""

import threading
import time

import pytest
from PIL import Image
from test_daemon import StubRouter, make_daemon
from test_phone import Recorder, call, make_app, make_hub, paired

from abdoh.claude.screen import ScreenCaptureError
from abdoh.commands.registry import CommandRegistry
from abdoh.config import Config
from abdoh.daemon import _app_of
from abdoh.events import Bus
from abdoh.phone import live as live_module
from abdoh.phone.live import LiveScreen
from abdoh.router import Router

LAPTOP = {"left": -3840, "top": 0, "width": 1920, "height": 1080}
MID = {"left": -1920, "top": 0, "width": 1920, "height": 1080}
RIGHT = {"left": 0, "top": 0, "width": 3440, "height": 1440}
NAMES = [(1, "laptop", (-3840, 0, 1920, 1080)), (2, "mid screen", (-1920, 0, 1920, 1080)),
         (3, "right screen", (0, 0, 3440, 1440))]  # fmt: skip


class FakeGrabber:
    """Three screens; each shows one colour, which a test can change."""

    def __init__(self):
        self.colours = {str(m): (40, 90, 160) for m in (LAPTOP, MID, RIGHT)}
        self.front = (100, 100)  # on the right screen
        self.apps = {"WhatsApp": (-1000, 500)}  # on the mid screen
        self.grabs = 0

    def monitors(self):
        return [dict(LAPTOP), dict(MID), dict(RIGHT)]

    def grab(self, monitor):
        self.grabs += 1
        return Image.new("RGB", (monitor["width"] // 10, monitor["height"] // 10),
                         self.colours[str(monitor)])  # fmt: skip

    def front_point(self):
        return self.front

    def app_point(self, name):
        return self.apps.get(name)


def make_live(**kw):
    grabber = FakeGrabber()
    return grabber, LiveScreen(grabber, names=lambda: NAMES, **kw)


def test_the_screens_by_abdohs_numbers_and_names():
    grabber, live = make_live()
    screens = live.screens()
    assert [(s.id, s.label, s.primary) for s in screens] == [
        ("1", "Screen 1 · laptop", False), ("2", "Screen 2 · mid screen", False),
        ("3", "Screen 3 · right screen", True)]  # fmt: skip
    _, unnamed = (None, LiveScreen(grabber))  # Abdoh doesn't know them: Windows' order
    assert [s.id for s in unnamed.screens()] == ["m1", "m2", "m3"]


def test_a_frame_only_when_the_screen_changed():
    grabber, live = make_live()
    assert live.shoot("2") is True  # the first look: a frame
    assert live.shoot("2") is False  # nothing moved: nothing sent
    grabber.colours[str(MID)] = (200, 30, 30)
    assert live.shoot("2") is True
    number, jpeg, label = live.frame("2", after=0, wait=0)
    assert number == 2 and jpeg[:2] == b"\xff\xd8" and label == "Screen 2 · mid screen"
    assert live.frame("2", after=number, wait=0) is None  # nothing newer


def test_follow_shows_the_screen_youre_working_on():
    grabber, live = make_live()
    live.shoot("follow")
    assert live._frames["follow"][2] == "Screen 3 · right screen"
    grabber.front = (-3000, 300)  # you went to the laptop's screen
    assert live.shoot("follow") is True  # another screen: a new frame even if it looks alike
    assert live._frames["follow"][2] == "Screen 1 · laptop"


def test_a_picture_of_the_screen_where_the_app_is():
    grabber, live = make_live()
    data, screen = live.picture("WhatsApp")
    assert screen.id == "2" and data[:2] == b"\xff\xd8"
    assert live.picture("Teams")[1].id == "3"  # not open: the screen you're working on
    assert live.picture(which="1")[1].id == "1"
    grabber.colours[str(RIGHT)] = (0, 0, 0)
    with pytest.raises(ScreenCaptureError, match="locked"):
        live.picture()


def test_watching_starts_a_look_and_stops_when_nobody_watches(monkeypatch):
    monkeypatch.setattr(live_module, "IDLE", 0.2)
    monkeypatch.setattr(live_module, "STILL_EVERY", 0.02)
    grabber, live = make_live(fps=50)
    found = live.frame("3", after=0, wait=2)
    assert found is not None and found[2] == "Screen 3 · right screen"
    time.sleep(0.6)
    assert live._thread is None  # nobody asked for a while: it stopped looking
    looks = grabber.grabs
    time.sleep(0.2)
    assert grabber.grabs == looks


# ----- the page's API -----


def test_live_frames_through_the_page(tmp_path):
    grabber, live = make_live()
    bus, hub, phones, app = make_app(tmp_path, live=live)
    key = paired(app, phones)
    _, data = call(app, "GET", "/api/live/screens", key=key)
    assert [s["id"] for s in data["screens"]] == ["1", "2", "3"]
    response, _ = call(app, "GET", "/api/live?screen=2&after=0", key=key)
    assert response.status == 200 and response.type == "image/jpeg"
    assert response.headers["X-Screen"] == "Screen%202%20%C2%B7%20mid%20screen"
    number = int(response.headers["X-Frame"])
    live.frame = lambda which, after, wait=2.0: None  # nothing new within the wait
    assert call(app, "GET", f"/api/live?screen=2&after={number}", key=key)[0].status == 204
    assert call(app, "GET", "/api/live?screen=2")[0].status == 401


def test_a_picture_from_the_live_view_goes_into_the_conversation(tmp_path):
    grabber, live = make_live()
    bus, hub, phones, app = make_app(tmp_path, live=live)
    key = paired(app, phones)
    _, data = call(app, "POST", "/api/screen", key=key, body={"screen": "1"})
    event = hub.events(0, wait=0)["events"][-1]
    assert event["type"] == "image" and event["id"] == data["id"]
    assert event["caption"] == "Screen 1 · laptop" and event["for"] == phones.list()[0]["id"]


def test_the_phone_is_told_to_show_a_screen_live():
    bus, hub = make_hub()
    hub.ask("open whatsapp", phone="p1")
    hub.take("phone_live", {"screen": "2"})
    event = hub.events(0, wait=0)["events"][-1]
    assert event == {"seq": 1, "type": "live", "screen": "2", "for": "p1"}


# ----- the daemon -----


def test_which_app_a_request_opened_or_moved():
    assert _app_of("open_app", "WhatsApp") == "WhatsApp"
    assert _app_of("window", "WhatsApp to 2 maximized") == "WhatsApp"
    assert _app_of("window", "this to 3") == ""
    assert _app_of("window", "minimize") == ""
    assert _app_of("open_url", "https://example.com") == ""  # the browser: the window in front


def test_after_moving_an_app_its_screen_goes_to_the_phone(monkeypatch):
    import abdoh.daemon as daemon_module

    monkeypatch.setitem(daemon_module.PHONE_SETTLE, "window", 0.01)
    bus = Bus(ui_attached=False)
    seen = Recorder(bus)
    daemon = make_daemon(StubRouter([]), bus=bus)
    asked = []
    sent = threading.Event()

    def grab(app=""):
        asked.append(app)
        sent.set()
        return b"JPEG", "Screen 2 · mid screen", "2"

    daemon._grab_screen = grab
    daemon._phone_turn = True
    daemon._did("window", "WhatsApp to 2 maximized")
    daemon._show_screen("WhatsApp on the second screen")  # covered by the picture after the move
    assert sent.wait(2)
    deadline = time.monotonic() + 2
    while not seen.of("phone_live") and time.monotonic() < deadline:
        time.sleep(0.01)
    assert asked == ["WhatsApp"]  # where WhatsApp is, not the screen in front
    caption = "Window: WhatsApp to 2 maximized · Screen 2 · mid screen"
    assert seen.of("phone_image") == [{"data": b"JPEG", "caption": caption}]
    assert seen.of("phone_live") == [{"screen": "2"}]  # and that screen, live


def test_show_screen_live_shows_it_live():
    bus = Bus(ui_attached=False)
    seen = Recorder(bus)
    daemon = make_daemon(StubRouter([]), bus=bus)
    daemon._phone_turn = True
    daemon._show_screen("live")
    assert seen.of("phone_live") == [{"screen": "follow"}] and seen.of("phone_image") == []


def test_abdohs_own_skills_are_reported_like_claudes_actions(tmp_path):
    """ "Open WhatsApp" is done without Claude: the phone still gets the step and the screen."""
    path = tmp_path / "commands.yaml"
    path.write_text("[]", encoding="utf-8")
    router = Router(Config(app_dir=tmp_path), CommandRegistry(path))

    class Computer:
        def open_app(self, name):
            return "WhatsApp"

    did = []
    router.on_action = lambda kind, arg: did.append((kind, arg))
    router.computer = Computer()
    router.local.computer.open_app("whatsapp")  # what the built-in "open ..." skill calls
    assert did == [("open_app", "WhatsApp")] and router._done == [("open_app", "WhatsApp")]
