"""Is there a graphics card that can run the speech model? (Windows, through DXGI.)

Only a card with plenty of memory of its own counts: built-in graphics (Intel UHD and the like)
share the computer's RAM, so running the model there would save nothing. Speech recognition
then uses DirectML (abdoh/audio/stt.py), which works with NVIDIA, AMD and Intel cards."""

import ctypes
import logging
import sys
from dataclasses import dataclass

log = logging.getLogger(__name__)

# The full speech model takes about 2.6 GB of the card's memory; the rest stays free for games
# and the screen. Cards sold as "4 GB" report a little less.
MIN_MEMORY = int(3.5 * 2**30)
_MICROSOFT = 0x1414  # the "Microsoft Basic Render Driver": not a real card
_SOFTWARE = 2  # DXGI_ADAPTER_FLAG_SOFTWARE
_VENDORS = {0x10DE: "NVIDIA", 0x1002: "AMD", 0x8086: "Intel"}
DIRECTML = "DmlExecutionProvider"


@dataclass(frozen=True)
class Gpu:
    name: str  # "NVIDIA GeForce RTX 3050 6GB Laptop GPU"
    memory: int  # bytes of its own memory
    vendor: str = ""

    def describe(self) -> str:
        return f"{self.name} ({self.memory / 2**30:.0f} GB)"


class _Luid(ctypes.Structure):
    _fields_ = [("LowPart", ctypes.c_uint32), ("HighPart", ctypes.c_int32)]


class _AdapterDesc1(ctypes.Structure):
    _fields_ = [
        ("Description", ctypes.c_wchar * 128),
        ("VendorId", ctypes.c_uint),
        ("DeviceId", ctypes.c_uint),
        ("SubSysId", ctypes.c_uint),
        ("Revision", ctypes.c_uint),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("AdapterLuid", _Luid),
        ("Flags", ctypes.c_uint),
    ]


class _Guid(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


# IID_IDXGIFactory1 {770aae78-f26f-4dba-a829-253c83d1b387}
_IID_FACTORY1 = _Guid(
    0x770AAE78, 0xF26F, 0x4DBA, (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87)
)
# Places in the COM interfaces' tables of functions.
_RELEASE, _ENUM_ADAPTERS1, _GET_DESC1 = 2, 12, 10
_NOT_FOUND = 0x887A0002  # DXGI_ERROR_NOT_FOUND: no more adapters


def _call(obj: ctypes.c_void_p, index: int, restype, argtypes: tuple, *args):
    """Call the COM method at `index` of the object's table of functions."""
    table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    method = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(table[index])
    return method(obj, *args)


def adapters() -> list[Gpu]:
    """The real graphics cards Windows knows (empty elsewhere, or if DXGI fails)."""
    if sys.platform != "win32":
        return []
    found = []
    factory = ctypes.c_void_p()
    try:
        dxgi = ctypes.WinDLL("dxgi")
        result = dxgi.CreateDXGIFactory1(ctypes.byref(_IID_FACTORY1), ctypes.byref(factory))
        if result != 0 or not factory:
            return []
        index = 0
        while True:
            adapter = ctypes.c_void_p()
            result = _call(
                factory,
                _ENUM_ADAPTERS1,
                ctypes.c_long,
                (ctypes.c_uint, ctypes.c_void_p),
                index,
                ctypes.addressof(adapter),
            )
            if (result & 0xFFFFFFFF) == _NOT_FOUND or result != 0:
                break
            try:
                desc = _AdapterDesc1()
                got = _call(
                    adapter, _GET_DESC1, ctypes.c_long, (ctypes.c_void_p,), ctypes.addressof(desc)
                )
                if got == 0:
                    if desc.VendorId != _MICROSOFT and not desc.Flags & _SOFTWARE:
                        found.append(
                            Gpu(
                                desc.Description.strip(),
                                int(desc.DedicatedVideoMemory),
                                _VENDORS.get(desc.VendorId, ""),
                            )
                        )
            finally:
                _call(adapter, _RELEASE, ctypes.c_ulong, ())
            index += 1
    except Exception:
        log.debug("Couldn't list the graphics cards", exc_info=True)
    finally:
        if factory:
            _call(factory, _RELEASE, ctypes.c_ulong, ())
    return found


def suitable(cards: list[Gpu]) -> Gpu | None:
    """The card with the most memory of its own, if it has enough for the speech model."""
    best = max(cards, key=lambda g: g.memory, default=None)
    return best if best is not None and best.memory >= MIN_MEMORY else None


def directml_ready() -> bool:
    """Can onnxruntime run models on the graphics card here (the DirectML build)?"""
    try:
        import onnxruntime as ort

        return DIRECTML in ort.get_available_providers()
    except Exception:
        return False


def find_gpu(list_cards=adapters, ready=directml_ready) -> Gpu | None:
    """A graphics card the speech model can run on, or None."""
    if not ready():
        return None
    return suitable(list_cards())
