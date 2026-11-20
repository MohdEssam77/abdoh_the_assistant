"""Thread-safe message passing between the daemon threads and the UI.

daemon → UI events:   ("status", str), ("claude", str), ("wake", str), ("voice", bool),
                      ("history", str), ("activity", str), ("show", None), ("page", str),
                      ("hearing", str): why Xanthos can't hear you over itself ("" = it can),
                      ("clear", None): a new day: empty the conversation,
                      ("mode", str): the mode that is on ("" = none),
                      ("quit", None)
UI → daemon requests: ("text", str), ("listen", None), ("pause", None), ("resume", None),
                      ("reload", None), ("edit_commands", None), ("voice", bool),
                      ("set_key", str), ("stop_speaking", None), ("quit", None)
"""

import queue
from typing import Any

Message = tuple[str, Any]


class Bus:
    def __init__(self, ui_attached: bool = True):
        # Without a UI nobody drains to_ui, so events are dropped instead of piling up.
        self.ui_attached = ui_attached
        self.to_ui: queue.Queue[Message] = queue.Queue()
        self.to_daemon: queue.Queue[Message] = queue.Queue()

    def emit(self, kind: str, value: Any = None) -> None:
        """Daemon side: send an event to the UI."""
        if self.ui_attached:
            self.to_ui.put((kind, value))

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
