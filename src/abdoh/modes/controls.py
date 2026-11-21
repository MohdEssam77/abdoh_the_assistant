"""The settings a mode can change, for real: read each one, set it, put it back.

Snapshots are plain JSON values (saved in mode_state.json), so a restart in the middle of a
mode can still undo it.
"""

import logging

from abdoh.commands.actions import ActionError

log = logging.getLogger(__name__)

FOLLOW_UP_ON = 6.0  # seconds, when a mode turns "keep listening" on


class ModeControls:
    """`computer`: abdoh.computer.Computer; `daemon`: the Daemon (Krekos's own switches)."""

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
