"""Single-instance lock, plus a tiny localhost socket so a second launch can show the window."""

import logging
import os
import socket
import sys
import threading
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

STATE_DIR = Path.home() / ".krekos"


class InstanceLock:
    """Holds an OS file lock on ~/.krekos/krekos.lock while Krekos runs."""

    def __init__(self, state_dir: Path = STATE_DIR):
        self.state_dir = Path(state_dir)
        self.lock_path = self.state_dir / "krekos.lock"
        self.port_path = self.state_dir / "krekos.port"
        self._file = None
        self._server: socket.socket | None = None

    def acquire(self) -> bool:
        """True if this is the only running instance."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        f = open(self.lock_path, "a+")  # noqa: SIM115 - kept open while running
        try:
            if sys.platform == "win32":
                import msvcrt

                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self._file = f
        return True

    def serve(self, on_show: Callable[[], None]) -> None:
        """Listen on localhost; a "show" message from a second launch calls on_show."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen()
        self._server = server
        self.port_path.write_text(str(server.getsockname()[1]))

        def loop():
            while True:
                try:
                    conn, _ = server.accept()
                except OSError:
                    return  # closed
                with conn:
                    conn.settimeout(2)
                    try:
                        if conn.recv(16).strip() == b"show":
                            on_show()
                    except OSError:
                        pass

        threading.Thread(target=loop, name="abdoh-instance", daemon=True).start()

    def release(self) -> None:
        if self._server:
            self._server.close()
            self._server = None
        if self._file:
            self._file.close()
            self._file = None
            try:
                os.remove(self.port_path)
            except OSError:
                pass


def ask_running_instance_to_show(state_dir: Path = STATE_DIR) -> bool:
    """Tell the running Krekos to show its window. True if it answered."""
    try:
        port = int((Path(state_dir) / "krekos.port").read_text().strip())
        with socket.create_connection(("127.0.0.1", port), timeout=2) as s:
            s.sendall(b"show")
        return True
    except (OSError, ValueError):
        return False
