"""What Abdoh does by itself, written down as the steps of a command.

The built-in skills ("open WhatsApp", "set the volume to 75") call the computer directly. The
router hands them a StepRecorder instead: it does the same, and notes each thing done the way a
command's step is written, ("open_app", "WhatsApp"), ("volume", "75"). So "remember that" can
keep it, and asking for it a second time can be noticed (abdoh/commands/repeats.py)."""

from collections.abc import Callable

Step = tuple[str, str]


def _on_off(on) -> str:
    return "on" if on else "off"


def _move(app, screen, how=None) -> Step | None:
    if app is None and screen == "current":
        return ("window", how) if how else None  # "snap this left": the window in front
    where = f"{'this' if app is None else app} to {screen}"
    return ("window", f"{where} {how}" if how else where)


# The computer's methods that do something a command can do, and the step each one is.
STEPS: dict[str, Callable[..., Step | None]] = {
    "open_app": lambda name: ("open_app", str(name)),
    "launch": lambda name: ("open_app", str(name)),
    "open_url": lambda url: ("open_url", str(url)),
    "play_youtube": lambda what: ("play_youtube", str(what)),
    "media": lambda key: ("media", str(key)),
    "timer": lambda text: ("timer", str(text)),
    "set_volume": lambda level: ("volume", str(level)),
    "set_brightness": lambda level: ("brightness", str(level)),
    "set_app_volume": lambda app, level: ("app_volume", f"{app} | {level}"),
    "screens": lambda layout: ("displays", str(layout)),
    "set_audio_output": lambda name: ("audio_output", str(name)),
    "set_dark_mode": lambda on: ("dark_mode", _on_off(on)),
    "set_night_light": lambda on: ("night_light", _on_off(on)),
    "set_power_mode": lambda mode: ("power_mode", str(mode)),
    "power": lambda what: ("power", str(what)),
    "lock": lambda: ("power", "lock"),
    "press_keys": lambda keys: ("keys", str(keys)),
    "close_app": lambda app: ("close_app", str(app)),
    "focus_app": lambda app: ("focus_app", str(app)),
    "window": lambda action: ("window", str(action)),
    "move_window": _move,
    "type_text": lambda text: ("type", str(text)),
}


# Methods that return the app's proper name ("whatsapp" -> "WhatsApp"): that's the step's value.
NAMED = ("open_app",)


def _noting(method, make: Callable[..., Step | None], note: Callable[[Step], None], name=""):
    def call(*args, **kwargs):
        result = method(*args, **kwargs)  # only what worked is noted
        try:
            step = make(*args, **kwargs)
        except TypeError:
            step = None
        if step is not None and name in NAMED and isinstance(result, str) and result.strip():
            step = (step[0], result.strip())
        if step is not None:
            note(step)
        return result

    return call


class StepRecorder:
    """Stands in for the computer: does what it's asked, and notes each step done."""

    def __init__(self, computer, note: Callable[[Step], None]):
        self._computer = computer
        self._note = note

    def __getattr__(self, name: str):
        found = getattr(self._computer, name)
        if name == "lamps" and found is not None:
            return _Lamps(found, self._note)
        make = STEPS.get(name)
        if make is None or not callable(found):
            return found
        return _noting(found, make, self._note, name)


class _Lamps:
    """The smart lamps, noting what was set ("desk lamp | blue")."""

    def __init__(self, lamps, note: Callable[[Step], None]):
        self._lamps = lamps
        self._note = note

    def __getattr__(self, name: str):
        found = getattr(self._lamps, name)
        if name != "set":
            return found
        return _noting(found, lambda which, how: ("lamp", f"{which} | {how}"), self._note)
