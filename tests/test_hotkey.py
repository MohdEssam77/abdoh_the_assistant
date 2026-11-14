import pytest

from abdoh.hotkey import MODIFIERS, Hotkey, parse_hotkey


def test_default_hotkey():
    flags, key = parse_hotkey("ctrl+alt+space")
    assert flags == MODIFIERS["ctrl"] | MODIFIERS["alt"]
    assert key == 0x20


@pytest.mark.parametrize(
    "text, key",
    [("Ctrl + Shift + A", ord("A")), ("win+1", ord("1")), ("alt+f9", 0x78), ("ctrl+f12", 0x7B)],
)
def test_other_hotkeys(text, key):
    assert parse_hotkey(text)[1] == key


@pytest.mark.parametrize("text", ["", "space", "a", "ctrl+", "hyper+a", "ctrl+banana", "ctrl+f25"])
def test_bad_hotkeys(text):
    with pytest.raises(ValueError):
        parse_hotkey(text)


def test_hotkey_object_parses_on_creation():
    with pytest.raises(ValueError):
        Hotkey("nonsense", lambda: None)
    hk = Hotkey("ctrl+alt+space", lambda: None)
    assert hk.key == 0x20
