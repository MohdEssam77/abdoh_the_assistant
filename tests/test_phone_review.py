"""What a review of the whole phone feature found (ABDOH_EPIC_11.md, story 152), so it stays
fixed."""

import base64

from test_codoh_manager import World
from test_phone import Clock, make_hub
from test_router import FakeAct, FakeBrain, text_of

from abdoh.commands.registry import CommandRegistry
from abdoh.config import Config
from abdoh.phone.media import MediaStore
from abdoh.router import FROM_PHONE, Router


def router_for(tmp_path, brain):
    path = tmp_path / "commands.yaml"
    path.write_text("[]", encoding="utf-8")
    router = Router(Config(app_dir=tmp_path), CommandRegistry(path), act=FakeAct())
    router.brain = brain
    return router


def test_translate_this_with_a_photo_is_about_the_photo(tmp_path):
    """Not the shortcut that translates the screen."""
    photo = tmp_path / "menu.jpg"
    photo.write_bytes(b"x" * 2048)
    router = router_for(tmp_path, FakeBrain(["It says: soup of the day."]))
    router.phone, router.phone_files = True, [str(photo)]
    text_of(router.handle("translate this [sent menu.jpg]"))
    prompt, image = router.brain.asked[0]
    assert image is None  # no picture of the laptop's screen
    assert prompt.startswith(FROM_PHONE) and str(photo) in prompt


def test_each_part_of_a_request_from_the_phone_says_so(tmp_path):
    router = router_for(tmp_path, FakeBrain(["Done."]))
    router.phone = True
    text_of(router.handle("what's the time and what's the weather"))
    assert router.brain.asked and all(p.startswith(FROM_PHONE) for p, _ in router.brain.asked)


def test_after_looking_at_the_screen_claude_can_still_send_a_file(tmp_path):
    class LookThenSend:
        def __init__(self):
            self.asked = []

        def stream(self, prompt, image_png=None):
            self.asked.append(prompt)
            if image_png is None:
                yield "ACTION look: the open PDF\n"
            else:
                yield "ACTION send_file: C:/Users/me/report.pdf\n"
                yield "Sent it."

    router = router_for(tmp_path, LookThenSend())
    router._capture = lambda: b"PNG"
    router._window = lambda: type("W", (), {"title": "report.pdf", "program": "msedge"})()
    sent = []
    router.on_send_file = lambda path: sent.append(path) or ""
    router.phone = True
    assert "Sent it." in text_of(router.handle("send me the pdf I have open"))
    assert sent == ["C:/Users/me/report.pdf"]


def test_a_queued_message_decides_its_own_notices(tmp_path):
    world = World(tmp_path)
    codoh = world.codoh
    said, phoned = [], []
    codoh.on_notice = lambda text, still=None: said.append(text)
    codoh.on_phone_notice = lambda chat, text: phoned.append(text)
    chat_id = world.chat()
    codoh.send(chat_id, "Fix the form")  # from the page
    engine = world.engines[0]
    codoh.send(chat_id, "then run the tests", by_phone=True)  # queued from the phone
    engine.on_event({"type": "approval", "id": "r1", "tool": "Bash", "input": {"command": "ls"}})
    assert phoned == []  # the page's reply: not the phone's business yet
    engine.on_event({"type": "done", "seconds": 5})  # the phone's message goes now
    engine.on_event({"type": "done", "seconds": 7})
    assert len(phoned) == 1  # its "done" went to the phone...
    assert len(said) == 1  # ... while the page's reply asked out loud, as before


def test_each_phone_gets_the_events_of_its_own_request():
    bus, hub = make_hub()
    hub.ask("something slow", phone="A")
    hub.take("history", "You (phone): something slow")
    hub.ask("what time is it", phone="B")  # B asks while A's answer is still coming
    hub.take("phone_step", "Reading notes.txt")
    hub.take("phone_say", "Here's what I found.")
    hub.take("phone_done", None)
    hub.take("history", "You (phone): what time is it")
    hub.take("phone_say", "It's nine.")
    events = [e for e in hub.events(0, wait=0)["events"] if e["type"] in ("step", "say", "done")]
    assert [(e["type"], e["for"]) for e in events] == [
        ("step", "A"), ("say", "A"), ("done", "A"), ("say", "B")]  # fmt: skip


def test_board_pictures_last_as_long_as_the_board():
    clock = Clock()
    bus, hub = make_hub(clock=clock)
    src = "data:image/png;base64," + base64.b64encode(b"PNG").decode()
    hub.take("board", {"id": 1, "text": "[picture: pizza]"})
    hub.take("board_picture", {"what": "pizza", "ok": True, "src": src})
    key = hub.state()["pictures"]["pizza"]["src"].removeprefix("/media/")
    for _ in range(60):
        hub.media.add_picture(b"JPEG")  # many screenshots
    clock.now += 7200
    assert hub.media.get(key) is not None  # two hours on, still there
    hub.take("board", None)
    assert hub.media.get(key) is None  # the board was cleared: gone with it


def test_screenshots_still_expire():
    clock = Clock()
    store = MediaStore(clock)
    key = store.add_picture(b"JPEG")
    clock.now += 3601
    assert store.get(key) is None
