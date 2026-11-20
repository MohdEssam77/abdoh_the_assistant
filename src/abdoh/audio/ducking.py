"""Other apps go quieter while Xanthos listens and answers: the browser, Spotify, a film.

Each app that is playing sound drops to a share of its own volume in the Windows volume mixer;
Xanthos's own voice and sounds (this process) stay as they are. Afterwards each app gets its
volume back, unless you changed it in the meantime.
"""

import logging
import os
import threading

from abdoh import winaudio

log = logging.getLogger(__name__)


class Ducker:
    """`sessions()` lists the mixer (winaudio.app_sessions), `set_volume(id, percent)` changes
    one app (winaudio.set_session_volume). Safe to call from any thread."""

    def __init__(self, sessions=None, set_volume=None, own_pid: int | None = None):
        self._sessions = sessions or winaudio.app_sessions
        self._set = set_volume or (lambda sid, percent: winaudio.set_session_volume(sid, percent))
        self._own = os.getpid() if own_pid is None else own_pid
        self._lock = threading.Lock()
        self._lowered: list[tuple[str, int, int]] | None = None  # (id, before, after)

    @property
    def ducked(self) -> bool:
        return self._lowered is not None

    def duck(self, percent: float) -> int:
        """Lower every other app that is playing to `percent` of its volume. Returns how many
        were lowered; does nothing if they already are."""
        with self._lock:
            if self._lowered is not None:
                return 0
            self._lowered = []
            for session in self._sessions():
                if not session.playing or session.pid == self._own:
                    continue
                if session.muted or session.volume <= 0:
                    continue
                after = max(1, round(session.volume * percent / 100))
                if after >= session.volume:
                    continue
                try:
                    if self._set(session.id, after):
                        self._lowered.append((session.id, session.volume, after))
                except Exception:
                    log.debug("Couldn't lower %s", session.program, exc_info=True)
            if self._lowered:
                log.info("Lowered %d app(s) while listening", len(self._lowered))
            return len(self._lowered)

    def release(self) -> None:
        """Give each lowered app its volume back, unless you changed it meanwhile."""
        with self._lock:
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
