"""Keep Abdoh at full speed in the background.

Windows 11 slows down apps that have no visible window ("efficiency mode"). Abdoh lives in the
tray and does its heavy work (speech recognition) exactly then, so it asks Windows not to.
"""

import logging
import sys

log = logging.getLogger(__name__)

PROCESS_POWER_THROTTLING = 4  # PROCESS_INFORMATION_CLASS.ProcessPowerThrottling
EXECUTION_SPEED = 0x1
IGNORE_TIMER_RESOLUTION = 0x4  # Windows 11 only


def keep_full_speed(kernel32=None) -> bool:
    """Opt this process out of Windows' power throttling. True if Windows accepted it."""
    if sys.platform != "win32" and kernel32 is None:
        return False
    import ctypes

    class State(ctypes.Structure):  # PROCESS_POWER_THROTTLING_STATE
        _fields_ = [
            ("Version", ctypes.c_ulong),
            ("ControlMask", ctypes.c_ulong),
            ("StateMask", ctypes.c_ulong),
        ]

    try:
        if kernel32 is None:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            kernel32.SetProcessInformation.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_void_p,
                ctypes.c_ulong,
            ]
        process = kernel32.GetCurrentProcess()
        # "We control these settings" (ControlMask) and "they're off" (StateMask = 0). Windows
        # 10 doesn't know the timer flag, so try again without it.
        for control in (EXECUTION_SPEED | IGNORE_TIMER_RESOLUTION, EXECUTION_SPEED):
            state = State(1, control, 0)
            if kernel32.SetProcessInformation(
                process, PROCESS_POWER_THROTTLING, ctypes.byref(state), ctypes.sizeof(state)
            ):
                log.info("Background throttling is off for Abdoh")
                return True
    except Exception:
        log.debug("Couldn't turn off background throttling", exc_info=True)
        return False
    log.debug("Windows didn't accept the request to turn off background throttling")
    return False
