"""Other apps go quieter for the whole conversation: the browser, Spotify, a film.

From the moment Abdoh starts listening (or speaking) until the conversation is over, each other
app that plays sound drops to a share of its own volume in the Windows volume mixer. While they
are down, the mixer is checked about once a second, so an app that starts playing later (the
next song, a video you just started) goes down too. Abdoh's own voice and sounds (this process)
stay as they are. Afterwards each app gets its volume back, unless you changed it meanwhile.
"""

import logging
import os
import threading

from abdoh import winaudio

log = logging.getLogger(__name__)

FOLLOW_SECONDS = 1.0  # how often the mixer is checked while the others are down


class Ducker:
    """`sessions()` lists the mixer (winaudio.app_sessions), `set_volume(id, percent)` changes
    one app (winaudio.set_session_volume). Safe to call from any thread. With `follow`, a
    background thread lowers apps that start playing while the others are down."""

    def __init__(
        self,
        sessions=None,
        set_volume=None,
        own_pid: int | None = None,
        follow_seconds: float | None = FOLLOW_SECONDS,
    ):
        self._sessions = sessions or winaudio.app_sessions
        self._set = set_volume or (lambda sid, percent: winaudio.set_session_volume(sid, percent))
        self._own = os.getpid() if own_pid is None else own_pid
        self._follow_seconds = follow_seconds
        self._lock = threading.Lock()
        self._lowered: list[tuple[str, int, int]] | None = None  # (id, before, after)
        self._percent = 100.0
        self._released = threading.Event()

    @property
    def ducked(self) -> bool:
        return self._lowered is not None

    def duck(self, percent: float) -> int:
        """Lower every other app that is playing to `percent` of its volume, and keep doing so
        for apps that start later, until release(). Returns how many were lowered now; does
        nothing if they already are down."""
        with self._lock:
            if self._lowered is not None:
                return 0
            self._lowered, self._percent = [], percent
            sessions = self._sessions()
            lowered = self._lower(sessions)
            # Only the apps that make sound (a dozen silent, nameless ones were listed each time)
            playing = [s for s in sessions if s.pid != self._own and s.playing and s.program]
            log.info(
                "Lowered %d app(s) for the conversation%s",
                lowered,
                "".join(f"; {s.program}: {_state(s)}" for s in playing),
            )
            if self._follow_seconds:
                self._released = threading.Event()
                threading.Thread(
                    target=self._follow, args=(self._released,), name="abdoh-duck", daemon=True
                ).start()
            return lowered

    def refresh(self) -> int:
        """While the others are down: lower any app that started playing since. Returns how
        many were lowered."""
        with self._lock:
            if self._lowered is None:
                return 0
            lowered = self._lower(self._sessions())
            if lowered:
                log.info("Lowered %d more app(s) that started playing", lowered)
            return lowered

    def _lower(self, sessions) -> int:
        done = {session_id for session_id, _, _ in self._lowered}
        count = 0
        for session in sessions:
            if session.id in done or not session.playing or session.pid == self._own:
                continue
            if session.muted or session.volume <= 0:
                continue
            after = max(1, round(session.volume * self._percent / 100))
            if after >= session.volume:
                continue
            try:
                if self._set(session.id, after):
                    self._lowered.append((session.id, session.volume, after))
                    count += 1
            except Exception:
                log.debug("Couldn't lower %s", session.program, exc_info=True)
        return count

    def _follow(self, released: threading.Event) -> None:
        while not released.wait(self._follow_seconds):
            try:
                self.refresh()
            except Exception:
                log.debug("Couldn't check the volume mixer", exc_info=True)

    def release(self) -> None:
        """Give each lowered app its volume back, unless you changed it meanwhile."""
        with self._lock:
            self._released.set()
            lowered, self._lowered = self._lowered, None
            if not lowered:
                return
            now = {session.id: session.volume for session in self._sessions()}
            for session_id, before, after in lowered:
                if session_id in now and abs(now[session_id] - after) <= 1:
                    try:
                        self._set(session_id, before)
                    except Exception:
                        log.debug("Couldn't restore an app's volume", exc_info=True)
            log.info("Gave %d app(s) their volume back", len(lowered))


def _state(session) -> str:
    if session.muted:
        return "muted"
    return f"{session.volume}%" + ("" if session.playing else " (not playing)")
