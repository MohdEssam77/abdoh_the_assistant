"""Your ChatGPT plan answers while Claude's usage limit is used up (claude.fallback).

`FallbackBrain` wraps Claude Code. When Claude Code says the plan's limit was reached before it
said anything, the same request goes to ChatGPT, which starts with one sentence about it.
Until the limit resets (the time Claude Code gave, or RETRY_SECONDS when it gave none), every
request goes straight to ChatGPT; after that, Claude is tried again.
"""

import logging
import threading
import time
from collections.abc import Callable, Iterator
from datetime import datetime

from abdoh.claude.brain import Brain, BrainError
from abdoh.config import Config

log = logging.getLogger(__name__)

RETRY_SECONDS = 1800.0  # Claude didn't say when its limit resets: try it again after this
SWITCHED = "Claude's limit is used up until {clock}, so your ChatGPT plan answers for now."
SWITCHED_UNKNOWN = (
    "Claude's limit is used up for now, so your ChatGPT plan answers until it's back."
)


def clock(epoch: float) -> str:
    """'8:50 PM'."""
    t = datetime.fromtimestamp(epoch)
    minutes = f":{t.minute:02d}" if t.minute else ""
    return f"{t.hour % 12 or 12}{minutes} {'AM' if t.hour < 12 else 'PM'}"


class FallbackBrain(Brain):
    """Claude Code, with your ChatGPT plan behind it for when Claude's limit runs out."""

    def __init__(
        self,
        primary: Brain,
        make_backup: Callable[[], Brain | None],
        now: Callable[[], float] = time.time,
    ):
        self.primary = primary
        self._make_backup = make_backup
        self._backup: Brain | None = None
        self._now = now
        self._until = 0.0  # ChatGPT answers until then (epoch seconds); 0: Claude does
        self._known = False  # ... and Claude said when
        self._lock = threading.Lock()
        self._on_activity = None
        self._state = None
        self.on_switch: Callable[[bool], None] | None = None  # the window shows who answers

    # ----- what the daemon sets on a brain goes to both -----

    @property
    def on_activity(self):
        return self._on_activity

    @on_activity.setter
    def on_activity(self, value) -> None:
        self._on_activity = value
        for brain in (self.primary, self._backup):
            if brain is not None:
                brain.on_activity = value

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value) -> None:
        self._state = value
        for brain in (self.primary, self._backup):
            if brain is not None:
                brain.state = value

    # ----- which one answers -----

    def switched(self) -> bool:
        """True while ChatGPT answers for Claude. Once the limit has reset, it's Claude again."""
        with self._lock:
            if not self._until:
                return False
            if self._now() < self._until:
                return True
            self._until = 0.0
        log.info("Claude's limit should have reset: Claude answers again")
        self._told(False)
        return False

    @property
    def current(self) -> Brain:
        return self._backup if self.switched() and self._backup is not None else self.primary

    @property
    def name(self) -> str:
        return self.current.name

    @property
    def remembers(self) -> bool:
        return getattr(self.current, "remembers", False)

    def until(self) -> float:
        """When Claude's limit resets, while ChatGPT answers for it (0 otherwise)."""
        return self._until if self.switched() else 0.0

    def _backup_brain(self) -> Brain | None:
        if self._backup is None:
            try:
                self._backup = self._make_backup()
            except Exception:
                log.exception("Couldn't make the ChatGPT brain")
                self._backup = None
            if self._backup is not None:
                self._backup.on_activity = self._on_activity
                self._backup.state = self._state
        return self._backup

    def _switch(self, resets_at: float | None) -> str:
        """Claude's limit was reached: ChatGPT answers until it resets. Returns the sentence."""
        now = self._now()
        known = bool(resets_at and resets_at > now)
        with self._lock:
            self._until = resets_at if known else now + RETRY_SECONDS
            self._known = known
        when = clock(self._until) if known else "in a while"
        log.info("Claude's limit was reached: your ChatGPT plan answers until %s", when)
        self._told(True)
        return SWITCHED.format(clock=clock(self._until)) if known else SWITCHED_UNKNOWN

    def _told(self, on: bool) -> None:
        notify = self.on_switch
        if notify is not None:
            try:
                notify(on)
            except Exception:
                log.debug("Couldn't tell about the switch", exc_info=True)

    # ----- asking -----

    def stream(self, prompt: str, image_png: bytes | None = None) -> Iterator[str]:
        if self.switched() and self._backup_brain() is not None:
            yield from self._backup.stream(prompt, image_png)
            return
        said = False
        inner = self.primary.stream(prompt, image_png)
        try:
            for chunk in inner:
                said = True
                yield chunk
            return
        except BrainError as e:
            if said or not e.limit or self._backup_brain() is None:
                raise
            sentence = self._switch(e.resets_at)
        finally:
            inner.close()  # stops Claude if the reply was interrupted
        yield sentence + "\n"
        yield from self._backup.stream(prompt, image_png)

    def status(self) -> str:
        if self.switched() and self._backup is not None:
            until = f" until {clock(self._until)}" if self._known else ""
            return f"ChatGPT plan (Claude's limit is used up{until})"
        return self.primary.status()

    def same_setup(self, other) -> bool:
        return isinstance(other, FallbackBrain) and self.primary.same_setup(other.primary)

    def warm_up(self) -> None:
        warm = getattr(self.primary, "warm_up", None)
        if warm:
            warm()

    def close(self) -> None:
        for brain in (self.primary, self._backup):
            if brain is not None:
                brain.close()


def _chatgpt(cfg: Config) -> Brain | None:
    """Your ChatGPT plan's brain, if Abdoh may use the plan now."""
    from abdoh.claude.chatgpt import Account, ChatGPTBrain

    return ChatGPTBrain(cfg) if Account.of(cfg).plan_usage else None


def with_fallback(cfg: Config, brain: Brain, make_backup=None) -> Brain:
    """`brain` (Claude Code), with your ChatGPT plan behind it when claude.fallback is on and the
    plan may be used; otherwise `brain` as it is."""
    if not cfg.claude.fallback:
        return brain
    from abdoh.claude.chatgpt import Account

    if not Account.of(cfg).plan_usage:
        return brain
    return FallbackBrain(brain, make_backup or (lambda: _chatgpt(cfg)))
