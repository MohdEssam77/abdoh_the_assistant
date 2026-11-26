"""Watching the user's screen while they do something (ACTION watch).

Claude starts a watch ("tell me if I'm doing this right") with a goal. Every few seconds the
daemon asks `look()` for a picture of the screen in use; it gives one only when the screen
changed since the last picture it gave (a small grey thumbnail is compared), so a still screen
costs nothing. Claude sees each picture with the goal and what Abdoh said so far, and speaks up
only when something's wrong, or also with suggestions when the user wants them (`suggest`:
Claude picks it from the request, and the user changes it by talking). The watch ends when the
user says so, when Claude says the task is done, or after `minutes` without a word from the user.
"""

import logging
import threading
import time
from collections.abc import Callable

log = logging.getLogger(__name__)

THUMB = (64, 36)  # the size screens are compared at
CHANGE = 1.5  # the mean difference (0-255) between thumbnails that counts as a change
NOTES = 6  # what Abdoh said during the watch, kept for Claude (the latest)
# Nothing changed for this long: send a picture anyway (the user may be stuck).
STILL_SECONDS = 45.0


def parse(arg: str) -> tuple[str, bool | None]:
    """ACTION watch's argument: "<goal> | suggestions" is (goal, True), "<goal> | mistakes" is
    (goal, False), and a goal alone is (goal, None): the kind isn't said."""
    goal, _, kind = (arg or "").partition("|")
    kind = kind.strip().lower()
    if not kind:
        return goal.strip(), None
    return goal.strip(), "suggest" in kind and not kind.startswith(("no ", "mistake"))


class Watch:
    """One watch at a time: its goal, what Abdoh said, and the last picture sent."""

    def __init__(
        self,
        grab: Callable | None = None,
        window: Callable | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        from abdoh.claude.screen import front_window
        from abdoh.claude.screen import grab as grab_screen

        self._grab = grab or grab_screen
        self._window = window or front_window
        self._clock = clock
        self._lock = threading.Lock()
        self.goal = ""
        self.suggest = False  # also speak up with suggestions, not only about mistakes
        self.notes: list[str] = []
        self.started = 0.0
        self.last_word = 0.0  # when the user last said something (or the watch started)
        self._thumb = None  # the last picture sent, small and grey
        self._sent_at = 0.0
        self.generation = 0  # counts watches, so an old loop knows it's over

    @property
    def active(self) -> bool:
        return bool(self.goal)

    def start(self, goal: str, suggest: bool = False) -> None:
        with self._lock:
            self.goal = (goal or "").strip() or "what the user is doing"
            self.suggest = bool(suggest)
            self.notes = []
            self.started = self.last_word = self._clock()
            self._thumb = None
            self._sent_at = 0.0
            self.generation += 1
        log.info("Watching the screen%s: %s", " with suggestions" if suggest else "", self.goal)

    def change(self, goal: str = "", suggest: bool | None = None) -> None:
        """The same watch goes on, with a new goal or kind ("stop suggesting for now"): what was
        said and the time are kept."""
        with self._lock:
            if not self.goal:
                return
            self.goal = (goal or "").strip() or self.goal
            if suggest is not None:
                self.suggest = suggest
        log.info("Still watching%s: %s", " with suggestions" if self.suggest else "", self.goal)

    def stop(self) -> bool:
        """End the watch. False if none was on."""
        with self._lock:
            if not self.goal:
                return False
            self.goal = ""
            self.suggest = False
            self._thumb = None
            self.generation += 1
        log.info("Stopped watching the screen")
        return True

    def heard_user(self) -> None:
        self.last_word = self._clock()

    def note(self, said: str) -> None:
        """Something Abdoh said during the watch (Claude is reminded, so it doesn't repeat)."""
        if said:
            self.notes = [*self.notes, said][-NOTES:]

    def quiet_for(self) -> float:
        return self._clock() - self.last_word

    def minutes(self) -> str:
        """How long it's been on, in words: "a minute", "4 minutes"."""
        whole = int((self._clock() - self.started) // 60)
        if whole < 1:
            return "less than a minute"
        return "a minute" if whole == 1 else f"{whole} minutes"

    def look(self):
        """(png, window) when the screen changed since the last picture (or it's been still for
        a while), else None. Raises ScreenCaptureError if the screen can't be captured."""
        from abdoh.claude.screen import downscale, is_all_black, to_png

        window = self._window()
        image = self._grab("active", window)
        if is_all_black(image):
            return None  # locked, or a protected window
        thumb = _thumbnail(image)
        now = self._clock()
        with self._lock:
            if not self.goal:
                return None
            still = now - self._sent_at < STILL_SECONDS
            if self._thumb is not None and still and difference(self._thumb, thumb) < CHANGE:
                return None
            self._thumb, self._sent_at = thumb, now
        return to_png(downscale(image)), window


def _thumbnail(image):
    import numpy as np

    small = image.convert("L").resize(THUMB)
    return np.asarray(small, dtype=np.float32)


def difference(a, b) -> float:
    """The mean difference of two thumbnails, 0 (the same) to 255."""
    import numpy as np

    return float(np.abs(a - b).mean())
