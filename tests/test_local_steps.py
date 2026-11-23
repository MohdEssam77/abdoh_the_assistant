"""What Abdoh does by itself counts too: "remember that" keeps it, Claude is told about it, and
asking for the same steps a second time (in any words or order) makes Abdoh offer to save them
as a command. Claude understands the answer."""

import os

import pytest
from test_router import Answers, FakeAct, FakeBrain, FakeRun, text_of

from abdoh.commands.registry import CommandRegistry
from abdoh.commands.steps import StepRecorder
from abdoh.config import Config
from abdoh.router import ABDOH_DID, NOTHING_TO_SAVE, OFFER, OFFER_SECONDS, Router
from abdoh.system_skills import Question

WHATSAPP = [("open_app", "WhatsApp"), ("volume", "75")]


class Computer:
    """Enough of a computer for "open WhatsApp" and "set the volume to 75"."""

    class Apps:
        @staticmethod
        def find(name):
            return name if name in ("whatsapp", "notepad") else None

    def __init__(self):
        self.apps = self.Apps()
        self.did = []

    def open_app(self, name):
        self.did.append(("open", name))
        return {"whatsapp": "WhatsApp", "notepad": "Notepad"}[name]

    def set_volume(self, level):
        self.did.append(("volume", level))
        return level

    def media(self, key):
        self.did.append(("media", key))


@pytest.fixture
def router(tmp_path):
    path = tmp_path / "commands.yaml"
    path.write_text("[]", encoding="utf-8")
    made = Router(Config(app_dir=tmp_path), CommandRegistry(path), run=FakeRun(), act=FakeAct())
    made.computer = Computer()
    made.brain = FakeBrain(["Sure."])
    return made


def said(router, text, *replies):
    """What Abdoh says to `text`; with `replies`, Claude answers each request in turn."""
    if replies:
        router.brain = Answers(*replies)
    return text_of(router.handle(text))


# ----- the steps it does by itself -----


def test_what_abdoh_did_itself_is_the_last_turn(router):
    assert said(router, "open WhatsApp and set the volume to 75") == (
        "Opening WhatsApp. Volume at 75 percent."
    )
    turn = router.last_turn
    assert turn.by_abdoh and turn.actions == WHATSAPP
    assert router.brain.asked == []  # no Claude


def test_keep_that_after_abdohs_own_steps(router, tmp_path):
    said(router, "open WhatsApp and set the volume to 75")
    reply = said(router, "keep that as chat time", "ACTION save_steps: chat time\n")
    assert reply == "Saved. Next time just say: chat time."
    assert (
        ABDOH_DID.format(
            request="open WhatsApp and set the volume to 75", steps="open_app: WhatsApp; volume: 75"
        )
        in router.brain.asked[0]
    )
    text = (tmp_path / "commands.yaml").read_text(encoding="utf-8")
    assert 'open_app: "WhatsApp"' in text and 'volume: "75"' in text


def test_claude_is_told_once(router):
    said(router, "open WhatsApp and set the volume to 75")
    said(router, "what's the weather", "Sunny.", "Still sunny.")
    said(router, "and tomorrow")
    first, second = router.brain.asked
    assert "Abdoh did this itself" in first and "Abdoh did this itself" not in second


def test_nothing_done_keeps_the_last_turn(router):
    said(router, "what's the weather", "ACTION open_url: https://weather.com\nSunny.\n")
    claude = router.last_turn
    said(router, "what time is it")  # answered, but nothing done
    assert router.last_turn is claude


# ----- asking for the same again -----


def test_the_second_time_abdoh_offers(router, tmp_path):
    first = router.handle("open WhatsApp and set the volume to 75")
    assert not isinstance(first, Question)
    second = router.handle("set the volume to 75 and open WhatsApp")  # other order, same thing
    assert isinstance(second, Question) and second.endswith(OFFER)
    reply = said(router, "yes, call it chat time", "ACTION save_steps: chat time\n")
    assert reply == "Saved. Next time just say: chat time."
    assert "Abdoh asked them" in router.brain.asked[0]
    assert "chat time" in (tmp_path / "commands.yaml").read_text(encoding="utf-8")


def test_no_means_never_again(router, tmp_path):
    router.handle("open WhatsApp and set the volume to 75")
    assert isinstance(router.handle("open WhatsApp and set the volume to 75"), Question)
    assert said(router, "no thanks", "Okay.") == "Okay."
    third = router.handle("open WhatsApp and set the volume to 75")
    assert not isinstance(third, Question)
    assert "WhatsApp" not in (tmp_path / "commands.yaml").read_text(encoding="utf-8")


ASKS_NAME = "What should I call it, maybe chat time?"


def test_yes_without_a_name_and_claude_asks_for_one(router, tmp_path):
    router.handle("open WhatsApp and set the volume to 75")
    router.handle("open WhatsApp and set the volume to 75")
    assert said(router, "yes please", ASKS_NAME, "ACTION save_steps: chat time\n") == ASKS_NAME
    assert "WhatsApp" not in (tmp_path / "commands.yaml").read_text(encoding="utf-8")
    reply = said(router, "chat time")  # straight to Claude, like the yes
    assert reply == "Saved. Next time just say: chat time."
    assert "Abdoh asked them" in router.brain.asked[1]
    text = (tmp_path / "commands.yaml").read_text(encoding="utf-8")
    assert '- name: "chat time"' in text and 'open_app: "WhatsApp"' in text


def test_remember_that_without_a_name(router, tmp_path):
    said(router, "open WhatsApp and set the volume to 75")
    said(router, "remember that", ASKS_NAME, "ACTION save_steps: chat time\n")
    assert said(router, "chat time") == "Saved. Next time just say: chat time."
    assert 'open_app: "WhatsApp"' in (tmp_path / "commands.yaml").read_text(encoding="utf-8")


def test_only_a_question_keeps_the_steps_waiting(router):
    said(router, "open WhatsApp and set the volume to 75")
    said(router, "what's the weather", "Sunny.", "ACTION save_steps: chat time\n")
    assert said(router, "chat time") == NOTHING_TO_SAVE


def test_the_answer_goes_to_claude_even_if_it_sounds_like_a_skill(router):
    router.handle("open WhatsApp and set the volume to 75")
    router.handle("open WhatsApp and set the volume to 75")
    said(router, "next", "Okay.")  # "next" is a media key on its own
    assert len(router.brain.asked) == 1 and router.computer.did[-1] != ("media", "next")


def test_an_old_offer_is_forgotten(router):
    router.handle("open WhatsApp and set the volume to 75")
    router.handle("open WhatsApp and set the volume to 75")
    router._offer_at -= OFFER_SECONDS + 1
    router.handle("next")  # a media key, as usual
    assert router.computer.did[-1] == ("media", "next")


def test_not_for_one_of_your_commands(router, tmp_path):
    (tmp_path / "commands.yaml").write_text(
        '- name: chat\n  triggers: ["chat time"]\n  actions:\n'
        '    - volume: 75\n    - open_app: "WhatsApp"\n',
        encoding="utf-8",
    )
    st = (tmp_path / "commands.yaml").stat()
    os.utime(tmp_path / "commands.yaml", (st.st_atime, st.st_mtime + 5))  # seen as changed
    router.handle("open WhatsApp and set the volume to 75")
    assert not isinstance(router.handle("open WhatsApp and set the volume to 75"), Question)


def test_not_for_a_single_action(router):
    router.handle("open WhatsApp")
    assert not isinstance(router.handle("open WhatsApp"), Question)


def test_nothing_is_kept_with_memory_off(router, tmp_path):
    router.cfg.memory = False
    router.handle("open WhatsApp and set the volume to 75")
    assert not isinstance(router.handle("open WhatsApp and set the volume to 75"), Question)
    assert not (tmp_path / "repeats.json").exists()


def test_part_abdoh_part_claude(router):
    """ "Open WhatsApp and play some jazz": Abdoh opens it, Claude plays the jazz."""
    jazz = "ACTION play_youtube: jazz\n"
    said(router, "open WhatsApp and play some jazz", jazz)
    assert router.last_turn.actions == [("open_app", "WhatsApp"), ("play_youtube", "jazz")]
    reply = said(router, "open WhatsApp and play some jazz", jazz)
    assert reply.endswith(OFFER)


def test_claude_doing_it_again_gets_the_offer_too(router):
    both = "ACTION open_url: https://python.org\nACTION volume: 30\n"
    said(router, "python and volume 30", both)
    assert said(router, "python site with volume 30", both) == OFFER


def test_no_second_question_when_claude_already_offered(router):
    both = "ACTION open_url: https://python.org\nACTION volume: 30\n"
    said(router, "python and volume 30", both)
    asks = both + "Want me to save that as a command, say python time?"
    assert said(router, "python site with volume 30", asks).endswith("say python time?")
    assert router._offer is None


# ----- the recorder -----


def test_the_recorder_notes_what_a_command_step_would_be():
    noted = []

    class Real:
        lamps = type("Lamps", (), {"set": lambda self, which, how: [which]})()

        def set_app_volume(self, app, level):
            return app

        def set_dark_mode(self, on):
            pass

        def lock(self):
            pass

        def move_window(self, app, screen, how=None):
            return screen

        def volume(self):
            return 40

    rec = StepRecorder(Real(), noted.append)
    rec.set_app_volume("Spotify", 20)
    rec.set_dark_mode(True)
    rec.lock()
    rec.move_window("Chrome", "2", "maximized")
    rec.move_window(None, "current", "left")
    rec.lamps.set("desk lamp", "blue")
    assert rec.volume() == 40  # asking isn't doing
    assert noted == [
        ("app_volume", "Spotify | 20"),
        ("dark_mode", "on"),
        ("power", "lock"),
        ("window", "Chrome to 2 maximized"),
        ("window", "left"),
        ("lamp", "desk lamp | blue"),
    ]


def test_what_failed_is_not_noted():
    noted = []

    class Broken:
        def set_volume(self, level):
            raise RuntimeError("no speakers")

    with pytest.raises(RuntimeError):
        StepRecorder(Broken(), noted.append).set_volume(50)
    assert noted == []
    assert not hasattr(StepRecorder(Broken(), noted.append), "find_app_audio")
