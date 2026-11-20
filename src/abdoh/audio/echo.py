"""Takes Xanthos's own voice (and whatever else the speakers play) back out of the microphone.

WebRTC's echo canceller (AEC3), through the `livekit` package. It works on 10 ms frames: for
every frame, first what the speakers played, then what the microphone heard. Measured in a
simulation: about 40 dB less of Xanthos's voice from the first second on, at under 1% of one CPU.
"""

import logging

log = logging.getLogger(__name__)

RATE = 16000
FRAME = RATE // 100  # 10 ms
FRAME_BYTES = FRAME * 2


def echo_available() -> bool:
    try:
        from livekit import rtc  # noqa: F401
    except Exception:
        return False
    return True


def _webrtc_module():
    from livekit import rtc

    return rtc.AudioProcessingModule(
        echo_cancellation=True,
        noise_suppression=False,  # the recognizer copes better with the natural sound
        high_pass_filter=True,
        auto_gain_control=False,  # the transcriber normalizes the level itself
    )


def _frame(data: bytes):
    from livekit import rtc

    return rtc.AudioFrame(data, RATE, 1, FRAME)


class EchoCanceller:
    """Cleans microphone audio with what the speakers played at the same time."""

    def __init__(self, module_factory=_webrtc_module, frame=_frame, delay_ms: int | None = None):
        self._factory = module_factory
        self._frame = frame
        self._delay_ms = delay_ms
        self._module = None
        self.reset()

    def reset(self) -> None:
        """Start learning the room again (after the speakers changed)."""
        self._module = self._factory()
        if self._delay_ms is not None:
            self._module.set_stream_delay_ms(self._delay_ms)

    def clean(self, mic: bytes, speakers: bytes) -> bytes:
        """`mic` with the echo of `speakers` taken out. Both: the same length, 16 kHz mono int16,
        a whole number of 10 ms frames. Frames go in strictly alternating (speakers, then mic):
        feeding a whole block of either at once shifts the echo inside the block and spoils it."""
        if len(mic) != len(speakers) or len(mic) % FRAME_BYTES:
            raise ValueError("mic and speakers must be the same whole number of 10 ms frames")
        out = bytearray()
        for at in range(0, len(mic), FRAME_BYTES):
            self._module.process_reverse_stream(self._frame(speakers[at : at + FRAME_BYTES]))
            frame = self._frame(mic[at : at + FRAME_BYTES])
            self._module.process_stream(frame)  # changes the frame in place
            out += bytes(frame.data)
        return bytes(out)
