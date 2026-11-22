"""The settings a mode can change, for real: read each one, set it, put it back.

Snapshots are plain JSON values (saved in mode_state.json), so a restart in the middle of a
mode can still undo it.
"""

import logging
from dataclasses import replace

from abdoh.commands.actions import ActionError, parse_window

log = logging.getLogger(__name__)

FOLLOW_UP_ON = 6.0  # seconds, when a mode turns "keep listening" on


class ModeControls:
    """`computer`: abdoh.computer.Computer; `daemon`: the Daemon (Abdoh's own switches)."""

    def __init__(self, computer, daemon):
        self.computer = computer
        self.daemon = daemon

    def capture(self, key: str):
        c, d = self.computer, self.daemon
        if key == "displays":
            if c.displays is None:
                raise ActionError("I can't control the screens here.")
            return sorted(x.id for x in c.displays.all() if x.active)
        if key == "audio_output":
            return next((o.id for o in c.audio_outputs() if o.default), None)
        if key == "volume":
            return [c.volume(), c.muted()]
        if key == "brightness":
            return c.screen_brightness()
        if key == "dark_mode":
            return c.dark_mode()
        if key == "power_mode":
            return c.power_mode()
        if key == "night_light":
            return c.night_light()
        if key == "wake_word":
            return not d.paused
        if key == "voice_replies":
            return d.voice_enabled
        if key == "follow_up":
            return d.cfg.follow_up_seconds
        raise ValueError(key)

    def apply(self, key: str, value) -> None:
        c, d = self.computer, self.daemon
        if key == "displays":
            c.screens("all" if value == "all" else f"only {', '.join(value)}")
        elif key == "audio_output":
            c.set_audio_output(value)
        elif key == "volume":
            c.set_volume(value)
        elif key == "brightness":
            c.set_brightness(value)
        elif key == "dark_mode":
            c.set_dark_mode(bool(value))
        elif key == "power_mode":
            c.set_power_mode(value)
        elif key == "night_light":
            c.set_night_light(bool(value))
        elif key == "wake_word":
            d.set_paused(not value)
        elif key == "voice_replies":
            d.set_voice(bool(value))
        elif key == "follow_up":
            # In memory only: config.yaml keeps your own choice.
            d.cfg.follow_up_seconds = FOLLOW_UP_ON if value is True else (value or 0)
        else:
            raise ValueError(key)

    # ----- what a mode needs that isn't connected -----

    def fit(self, mode) -> tuple[object, list[str], str]:
        """The mode as it can run with what's connected now, what it needs that isn't there
        (["screens 2 and 3", "the C34H89x speakers"]), and which screens are there ("only
        screen 1, laptop, is connected"). Nothing missing: the mode as it is."""
        c = self.computer
        displays = getattr(c, "displays", None)
        settings, actions = dict(mode.settings), list(mode.actions)
        missing_screens: list[str] = []
        connected = []
        if displays is not None:
            try:
                connected = displays.all()
            except Exception:
                log.debug("Couldn't read the screens", exc_info=True)
                displays = None
        if displays is not None and connected:
            wanted = settings.get("displays")
            if isinstance(wanted, list | tuple):
                there = [part for part in wanted if displays.find(str(part))]
                missing_screens += [str(part) for part in wanted if str(part) not in there]
                if there:
                    settings["displays"] = there
                else:
                    settings.pop("displays")  # none of them: the screens stay as they are
            main = next((d for d in connected if d.primary), None) or next(
                (d for d in connected if d.internal), connected[0]
            )
            for i, (kind, arg) in enumerate(actions):
                if kind != "window":
                    continue
                try:
                    place = parse_window(arg)
                except ActionError:
                    continue
                if isinstance(place, tuple) and not displays.find(place[1]):
                    if place[1] not in missing_screens:
                        missing_screens.append(place[1])
                    app, _, how = place
                    actions[i] = (kind, f"{app or 'this'} to {main.number} {how}")
        missing = [_screens_text(missing_screens)] if missing_screens else []
        speakers = settings.get("audio_output")
        if speakers and not self._speakers_there(str(speakers)):
            missing.append(f"the {speakers} speakers")
            settings.pop("audio_output")
        if not missing:
            return mode, [], ""
        have = ""
        if missing_screens and connected:
            numbers = displays.numbers(connected)
            have = (
                f"only {numbers}, {connected[0].label}, is connected"
                if len(connected) == 1
                else f"only {numbers} are connected"
            )
        return replace(mode, settings=settings, actions=tuple(actions)), missing, have

    def _speakers_there(self, name: str) -> bool:
        from abdoh.computer import find_output

        try:
            return find_output(name, self.computer.audio_outputs()) is not None
        except Exception:
            return True  # can't tell: let the mode try as before

    def restore(self, key: str, snapshot) -> None:
        c, d = self.computer, self.daemon
        if snapshot is None:
            return
        if key == "displays":
            c.displays.set_active(set(snapshot))
        elif key == "audio_output":
            c.restore_audio_output(snapshot)
        elif key == "volume":
            level, muted = snapshot
            c.set_volume(level)
            c.set_muted(bool(muted))
        elif key == "brightness":
            c.restore_brightness(snapshot)
        elif key == "follow_up":
            d.cfg.follow_up_seconds = float(snapshot)
        else:
            self.apply(key, snapshot)


def _screens_text(parts: list[str]) -> str:
    """["2", "3"] -> "screens 2 and 3"; ["2"] -> "screen 2"; ["the TV"] -> "the TV"."""
    numbers = sorted((p for p in parts if p.isdigit()), key=int)
    names = [p for p in parts if not p.isdigit()]
    said = []
    if numbers:
        listed = numbers[0] if len(numbers) == 1 else f"{', '.join(numbers[:-1])} and {numbers[-1]}"
        said.append(f"screen{'s' if len(numbers) > 1 else ''} {listed}")
    said += [n if n.startswith("the ") else f"the {n}" for n in names]
    return " and ".join(said)
