"""Monitors: numbers, names, turning them on and off (a fake backend; no screens touched)."""

from dataclasses import replace

import pytest

from abdoh.commands.actions import ActionError
from abdoh.displays import NO_SCREEN_LEFT, NOT_ACCEPTED, Displays, Monitor

LAPTOP = Monitor("path-laptop", "", True, True, False, (-3840, 0, 1920, 1080), r"\\.\DISPLAY1")
HP = Monitor("path-hp", "HP 32f", False, True, False, (-1920, 0, 1920, 1080), r"\\.\DISPLAY5")
WIDE = Monitor("path-wide", "C34H89x", False, True, True, (0, 0, 3440, 1440), r"\\.\DISPLAY6")


class FakeBackend:
    """The owner's three monitors. set_active turns them on and off (or refuses)."""

    def __init__(self, *monitors, refuse=False):
        self.monitors_ = {m.id: m for m in (monitors or (WIDE, LAPTOP, HP))}
        self.refuse = refuse
        self.applied = []
        self.brightness_ = {"path-wide": 80}

    def monitors(self):
        return list(self.monitors_.values())

    def set_active(self, wanted_ids):
        self.applied.append(set(wanted_ids))
        if self.refuse:
            raise OSError("SetDisplayConfig failed (87)")
        for mid, m in self.monitors_.items():
            on = mid in wanted_ids
            self.monitors_[mid] = replace(m, active=on, gdi=m.gdi if on else "")

    def brightness(self, display):
        return self.brightness_.get(display.id)

    def set_brightness(self, display, percent):
        if display.id not in self.brightness_:
            return False
        self.brightness_[display.id] = percent
        return True


@pytest.fixture
def displays(tmp_path):
    return Displays(tmp_path / "displays.json", FakeBackend())


def numbers(found):
    return [d.number for d in found]


def test_new_monitors_are_numbered_the_way_windows_lists_them(displays):
    found = displays.all()
    assert [(d.number, d.label) for d in found] == [
        (1, "Laptop screen"), (2, "HP 32f"), (3, "C34H89x")
    ]  # fmt: skip


def test_numbers_stay_when_a_monitor_is_off_or_unplugged(displays):
    displays.all()
    backend = displays.backend
    backend.monitors_["path-hp"] = replace(HP, active=False, gdi="")  # off: listed, no GDI name
    assert numbers(displays.all()) == [1, 2, 3]
    del backend.monitors_["path-laptop"]  # unplugged
    assert numbers(displays.all()) == [2, 3]
    backend.monitors_["path-tv"] = Monitor("path-tv", "LG TV", False, True, gdi=r"\\.\DISPLAY7")
    assert [(d.number, d.name) for d in displays.all()][-1] == (4, "LG TV")  # the next free one


def test_you_can_rename_and_renumber(displays):
    displays.rename("path-wide", "TV")
    assert displays.find("the tv")[0].id == "path-wide"
    displays.renumber(["path-hp", "path-wide", "path-laptop"])
    assert [d.id for d in displays.all()] == ["path-hp", "path-wide", "path-laptop"]


@pytest.mark.parametrize(
    "spoken, expected",
    [
        ("2", [2]), ("two", [2]), ("the second screen", [2]), ("monitor 3", [3]),
        ("laptop", [1]), ("the built in screen", [1]), ("hp", [2]), ("c34", [3]),
        ("1 and 3", [1, 3]), ("one, two", [1, 2]), ("all", [1, 2, 3]),
        ("tv", []), ("2 and the moon", []), ("7", []),
    ],
)  # fmt: skip
def test_finding_monitors_by_what_you_say(displays, spoken, expected):
    assert numbers(displays.find(spoken)) == expected


def test_layouts_in_words(displays):
    backend = displays.backend
    assert displays.apply("only 2") == "Only screen 2, HP 32f, is on."
    assert backend.applied[-1] == {"path-hp"}
    assert displays.apply("3 on") == "Screens 2 and 3 are on."
    assert displays.apply("2 off") == "Only screen 3, C34H89x, is on."
    assert displays.apply("all") == "All screens are on."


def test_nothing_happens_when_it_is_already_so(displays):
    displays.apply("all")
    assert displays.backend.applied == []


def test_never_every_screen_off(displays):
    with pytest.raises(ActionError, match=NO_SCREEN_LEFT):
        displays.apply("1 and 2 and 3 off")
    assert displays.backend.applied == []


def test_a_refused_layout_is_said(tmp_path):
    displays = Displays(tmp_path / "displays.json", FakeBackend(refuse=True))
    with pytest.raises(ActionError, match=NOT_ACCEPTED):
        displays.apply("only 1")


def test_unknown_screens_and_words(displays):
    with pytest.raises(ActionError, match="which screen"):
        displays.apply("only the moon")
    with pytest.raises(ActionError, match="don't understand"):
        displays.apply("sideways")


def test_brightness_only_where_the_monitor_supports_it(displays):
    laptop, hp, wide = displays.all()
    assert displays.brightness(wide) == 80 and displays.brightness(hp) is None
    assert displays.brightness(laptop) is None  # the laptop panel uses WMI instead
    assert displays.set_brightness(wide, 40) and not displays.set_brightness(hp, 40)


def test_the_registry_survives_a_broken_file(tmp_path):
    path = tmp_path / "displays.json"
    path.write_text("{not json")
    assert numbers(Displays(path, FakeBackend()).all()) == [1, 2, 3]
