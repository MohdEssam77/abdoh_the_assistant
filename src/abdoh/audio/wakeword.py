"""Wake word detection behind a WakeWordEngine interface."""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable

log = logging.getLogger(__name__)


class WakeWordEngine(ABC):
    label = "wake word"  # shown in the window

    @abstractmethod
    def detect(self, block: bytes) -> bool:
        """Feed one audio block; True when the wake word was heard."""

    def reset(self) -> None:  # noqa: B027 - optional hook
        """Forget partial audio (call after handling a request)."""


class NoWakeWord(WakeWordEngine):
    """Used when the wake word model can't start: only the hotkey wakes Abdoh."""

    label = "No wake word (use the hotkey)"

    def detect(self, block: bytes) -> bool:
        return False


def load_wake_engine(cfg, oww=None) -> WakeWordEngine:
    """openWakeWord with your trained "Hey Abdoh" model."""
    model = cfg.resolve(cfg.wake_word_model)
    if not model.exists():
        raise FileNotFoundError(f"No wake word model at {model}")
    if oww is None:
        from abdoh.audio.oww import FEATURES_DIR, OpenWakeWord

        oww = lambda m, t: OpenWakeWord(m, cfg.resolve(FEATURES_DIR), t)  # noqa: E731
    engine = oww(model, cfg.wake_word_threshold)
    engine.label = f"openWakeWord ({model.stem})"
    return engine


def wait_for_trigger(
    read: Callable[[], bytes],
    engine: WakeWordEngine,
    should_stop: Callable[[], bool] = lambda: False,
    pressed: Callable[[], bool] = lambda: False,
    observe: Callable[[bytes], bool] | None = None,
) -> str | None:
    """Read blocks until the wake word is heard ("wake") or the hotkey was pressed ("hotkey").
    Every block also goes to `observe` (if given); "voice" when it returns True (you started
    talking over a reply). None if should_stop() turned true."""
    while not should_stop():
        if pressed():
            return "hotkey"
        block = read()
        if observe is not None and observe(block):
            return "voice"
        if engine.detect(block):
            return "wake"
    return None


def wait_for_wake_word(
    read: Callable[[], bytes],
    engine: WakeWordEngine,
    should_stop: Callable[[], bool] = lambda: False,
) -> bool:
    """Read blocks until the wake word is heard (True) or should_stop() is true (False)."""
    return wait_for_trigger(read, engine, should_stop) == "wake"
