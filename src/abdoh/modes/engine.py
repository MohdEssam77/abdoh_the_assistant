"""Switching modes on and off.

Before a mode changes a setting for the first time, the engine remembers what it was. Switching
from one mode to another first puts back what the old mode changed and the new one doesn't
set; "back to normal" puts everything back. What's remembered is saved (mode_state.json), so
a restart in the middle of a movie still knows how to undo it.
"""

import json
import logging
import threading
from collections.abc import Callable
from pathlib import Path

from abdoh.commands.actions import ActionError
from abdoh.modes.model import SETTINGS, Mode, ModesFileError, parse_schedule
from abdoh.system_skills import Done

log = logging.getLogger(__name__)

NO_MODE = "No mode is on."
BACK_TO_NORMAL = "Back to normal."
# Abdoh's own switches: Windows keeps the rest by itself across a restart.
ABDOH_SWITCHES = ("wake_word", "voice_replies", "follow_up")


class ModeEngine:
    """`modes()` lists the modes (the store's load), `controls` reads, sets and puts back each
    setting (ModeControls), `run(actions)` runs a list of actions and returns what to say,
    `emit(name)` tells the window and the tray which mode is on ("" for none)."""

    def __init__(
        self,
        modes: Callable[[], list[Mode]],
        controls,
        run: Callable[[list[tuple[str, str]]], list[str]],
        state_path: Path,
        emit: Callable[[str], None] = lambda name: None,
    ):
        self._modes = modes
        self.controls = controls
        self._run = run
        self.path = Path(state_path)
        self._emit = emit
        self._lock = threading.RLock()
        self._depth = 0  # a mode's actions switching to another mode: once only
        self._last_tick = ""  # the minute the schedules were last checked
        state = self._load()
        self.current: str | None = state.get("current")
        self.remembered: dict = state.get("remembered", {})

    # ----- the modes -----

    def modes(self) -> list[Mode]:
        try:
            return self._modes()
        except ModesFileError as e:
            log.warning("Modes file error: %s", e)
            return []

    def find(self, name: str) -> Mode | None:
        wanted = name.strip().lower().removesuffix(" mode").strip()
        return next((m for m in self.modes() if m.name.lower() == wanted), None)

    # ----- switching -----

    def switch(self, name: str) -> str:
        """For the `mode:` action: a mode's name, or "normal"."""
        if name.strip().lower() in ("normal", "off", "none"):
            return self.deactivate()
        return self.activate(name)

    def activate(self, name: str) -> str:
        with self._lock:
            mode = self.find(name)
            if mode is None:
                raise ActionError(f"You don't have a mode called {name.strip()}.")
            if self._depth > 1:
                raise ActionError("A mode can only hand over to one other mode.")
            self._depth += 1
            try:
                return self._activate(mode)
            finally:
                self._depth -= 1

    def _activate(self, mode: Mode) -> str:
        problems: list[str] = []
        old = self.find(self.current) if self.current else None
        if old is not None and old.name != mode.name:
            self._run_quietly(old.exit_actions, problems)
        # What the old mode changed and this one leaves alone goes back first.
        for key in [k for k in SETTINGS if k in self.remembered and k not in mode.settings]:
            problems += self._restore(key)
        for key, value in mode.settings.items():
            if key not in self.remembered:
                try:
                    self.remembered[key] = self.controls.capture(key)
                except Exception as e:
                    log.warning("Couldn't read %s before changing it: %s", key, e)
            try:
                self.controls.apply(key, value)
            except ActionError as e:
                problems.append(str(e))
            except Exception:
                log.exception("Couldn't apply %s", key)
                problems.append(f"I couldn't change the {key.replace('_', ' ')}.")
        self.current = mode.name
        self._save()
        self._emit(mode.name)
        log.info("Mode on: %s", mode.name)
        spoken = self._run_quietly(mode.actions, problems)
        reply = f"{mode.name} mode."
        if not problems:
            return " ".join(spoken) if spoken else Done(reply)  # your mode's own words, if any
        reply += f" But {problems[0][:1].lower()}{problems[0][1:]}"
        return " ".join([reply, *spoken]).strip()

    def deactivate(self) -> str:
        with self._lock:
            if self.current is None and not self.remembered:
                return NO_MODE
            mode = self.find(self.current) if self.current else None
            problems: list[str] = []
            if mode:
                self._run_quietly(mode.exit_actions, problems)
            for key in [k for k in SETTINGS if k in self.remembered]:
                problems += self._restore(key)
            self.current = None
            self._save()
            self._emit("")
            log.info("Back to normal")
            if problems:
                return f"{BACK_TO_NORMAL} But {problems[0][:1].lower()}{problems[0][1:]}"
            return Done(BACK_TO_NORMAL)

    def start(self) -> None:
        """When Abdoh starts: if a mode is on, its own switches again (they live in memory)."""
        with self._lock:
            if self.current is None:
                return
            mode = self.find(self.current)
            if mode is None:  # deleted meanwhile: nothing to keep up
                log.info("Mode %s no longer exists", self.current)
                self.current, self.remembered = None, {}
                self._save()
                return
            for key in ABDOH_SWITCHES:
                if key in mode.settings:
                    try:
                        self.controls.apply(key, mode.settings[key])
                    except Exception:
                        log.exception("Couldn't apply %s", key)
            self._emit(mode.name)

    # ----- modes at a time of day -----

    def tick(self, now) -> str | None:
        """Switch on a mode whose time it is (call at least once a minute). Each time fires
        once; times that passed while Abdoh was off don't catch up. Returns what was said."""
        minute = now.strftime("%Y-%m-%d %H:%M")
        if minute == self._last_tick:
            return None
        self._last_tick = minute
        for mode in self.modes():
            for entry in mode.schedule:
                days, hour, mins = parse_schedule(entry)
                if now.weekday() in days and (now.hour, now.minute) == (hour, mins):
                    if self.current == mode.name:
                        return None
                    log.info("It's %s: %s mode", entry, mode.name)
                    try:
                        return self.activate(mode.name)
                    except ActionError as e:
                        return str(e)
        return None

    def run_schedule(self, stop, announce, clock=None, every: float = 20.0) -> None:
        """Check the schedules until `stop` is set; `announce(text)` says what happened."""
        from datetime import datetime

        clock = clock or datetime.now
        while not stop.wait(every):
            try:
                said = self.tick(clock())
            except Exception:
                log.exception("Mode schedule failed")
                continue
            if said:
                announce(said)

    def describe(self) -> str:
        if self.current:
            return f"{self.current} mode is on."
        return "No mode is on."

    def names(self) -> list[str]:
        return [m.name for m in self.modes()]

    # ----- helpers -----

    def _restore(self, key: str) -> list[str]:
        snapshot = self.remembered.pop(key)
        try:
            self.controls.restore(key, snapshot)
        except ActionError as e:
            return [str(e)]
        except Exception:
            log.exception("Couldn't put %s back", key)
            return [f"I couldn't put the {key.replace('_', ' ')} back."]
        return []

    def _run_quietly(self, actions, problems: list[str]) -> list[str]:
        """Run actions; what they say comes back, a failure goes into `problems`."""
        spoken: list[str] = []
        for action in actions:
            try:
                spoken += self._run([action])
            except ActionError as e:
                problems.append(str(e))
            except Exception:
                log.exception("A mode's action failed: %s", action)
                problems.append("One of the mode's actions failed.")
        return spoken

    def _load(self) -> dict:
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
            return state if isinstance(state, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        state = {"current": self.current, "remembered": self.remembered}
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self.path)
