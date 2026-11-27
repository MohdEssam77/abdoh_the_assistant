"""Thread-safe message passing between the daemon threads and the UI.

daemon → UI events:   ("status", str), ("claude", str), ("wake", str), ("voice", bool),
                      ("history", str), ("activity", str), ("show", None), ("page", str),
                      ("hearing", str): why Abdoh can't hear you over itself ("" = it can),
                      ("clear", None): a new day: empty the conversation,
                      ("mode", str): the mode that is on ("" = none),
                      ("phone_say", str): a sentence of a reply to the phone (not spoken here),
                      ("phone_aside", str), ("phone_question", str): see abdoh/phone/hub.py,
                      ("quit", None)
Listeners (Bus.listen) get every event too, also without a window: the phone's hub.
UI → daemon requests: ("text", str), ("listen", None), ("pause", None), ("resume", None),
                      ("reload", None), ("edit_commands", None), ("voice", bool),
                      ("set_key", str), ("stop_speaking", None), ("quit", None)
"""

import logging
import queue
import threading
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

Message = tuple[str, Any]


class Bus:
    def __init__(self, ui_attached: bool = True):
        # Without a UI nobody drains to_ui, so events are dropped instead of piling up.
        self.ui_attached = ui_attached
        self.to_ui: queue.Queue[Message] = queue.Queue()
        self.to_daemon: queue.Queue[Message] = queue.Queue()
        self._listeners: list[Callable[[str, Any], None]] = []
        self._lock = threading.Lock()

    def emit(self, kind: str, value: Any = None) -> None:
        """Daemon side: send an event to the UI (and to the listeners)."""
        if self.ui_attached:
            self.to_ui.put((kind, value))
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(kind, value)
            except Exception:
                log.exception("A listener couldn't take the event %r", kind)

    def listen(self, listener: Callable[[str, Any], None]) -> None:
        """Get every event from now on (called on the emitting thread: be quick)."""
        with self._lock:
            self._listeners.append(listener)

    def unlisten(self, listener: Callable[[str, Any], None]) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def request(self, kind: str, value: Any = None) -> None:
        """UI side: ask the daemon to do something."""
        self.to_daemon.put((kind, value))

    def next_request(self, timeout: float) -> Message | None:
        try:
            return self.to_daemon.get(timeout=timeout)
        except queue.Empty:
            return None

    def pending_events(self) -> list[Message]:
        events = []
        while True:
            try:
                events.append(self.to_ui.get_nowait())
            except queue.Empty:
                return events
