"""Windows' own volume controls (Core Audio): the speakers' and a microphone's volume and mute.

Thin wrappers over COM through comtypes; everything else uses the small `Endpoint` class, which
tests replace with a fake.
"""

import logging
import sys

log = logging.getLogger(__name__)

RENDER, CAPTURE = 0, 1  # EDataFlow: speakers, microphones
ACTIVE = 1  # DEVICE_STATE_ACTIVE
NAME_LIMIT = 31  # the classic audio API (what sounddevice lists) cuts device names here


class AudioError(RuntimeError):
    """The volume couldn't be read or changed."""


def _com():
    """The COM interface definitions, created on first use (comtypes is Windows-only)."""
    if hasattr(_com, "cache"):
        return _com.cache
    from ctypes import HRESULT, POINTER, Structure, c_float, c_int, c_uint, c_void_p, c_wchar_p

    from comtypes import COMMETHOD, GUID, IUnknown

    class PROPERTYKEY(Structure):
        _fields_ = [("fmtid", GUID), ("pid", c_uint)]

    class PROPVARIANT(Structure):  # only text values are read here
        _fields_ = [("vt", c_uint), ("reserved", c_uint), ("text", c_wchar_p), ("pad", c_void_p)]

    def unused(name):  # keeps the method order right for calls we never make
        return COMMETHOD([], HRESULT, name)

    class IPropertyStore(IUnknown):
        _iid_ = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
        _methods_ = (
            unused("GetCount"),
            unused("GetAt"),
            COMMETHOD([], HRESULT, "GetValue",
                      (["in"], POINTER(PROPERTYKEY), "key"),
                      (["out"], POINTER(PROPVARIANT), "value")),
        )  # fmt: skip

    class IAudioEndpointVolume(IUnknown):
        _iid_ = GUID("{5CDF2C82-841E-4546-9722-0CF74078229A}")
        _methods_ = (
            unused("RegisterControlChangeNotify"),
            unused("UnregisterControlChangeNotify"),
            unused("GetChannelCount"),
            unused("SetMasterVolumeLevel"),
            COMMETHOD([], HRESULT, "SetMasterVolumeLevelScalar",
                      (["in"], c_float, "level"), (["in"], c_void_p, "context")),
            unused("GetMasterVolumeLevel"),
            COMMETHOD([], HRESULT, "GetMasterVolumeLevelScalar",
                      (["out"], POINTER(c_float), "level")),
            unused("SetChannelVolumeLevel"),
            unused("SetChannelVolumeLevelScalar"),
            unused("GetChannelVolumeLevel"),
            unused("GetChannelVolumeLevelScalar"),
            COMMETHOD([], HRESULT, "SetMute",
                      (["in"], c_int, "mute"), (["in"], c_void_p, "context")),
            COMMETHOD([], HRESULT, "GetMute", (["out"], POINTER(c_int), "mute")),
        )  # fmt: skip

    class IMMDevice(IUnknown):
        _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
        _methods_ = (
            COMMETHOD([], HRESULT, "Activate",
                      (["in"], POINTER(GUID), "iid"), (["in"], c_uint, "context"),
                      (["in"], c_void_p, "params"),
                      (["out"], POINTER(POINTER(IUnknown)), "interface")),
            COMMETHOD([], HRESULT, "OpenPropertyStore",
                      (["in"], c_uint, "access"),
                      (["out"], POINTER(POINTER(IPropertyStore)), "store")),
            COMMETHOD([], HRESULT, "GetId", (["out"], POINTER(c_void_p), "id")),
            COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(c_uint), "state")),
        )  # fmt: skip

    class IMMDeviceCollection(IUnknown):
        _iid_ = GUID("{0BD7A1BE-7A1A-44DB-8397-CC5392387B5E}")
        _methods_ = (
            COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(c_uint), "count")),
            COMMETHOD([], HRESULT, "Item",
                      (["in"], c_uint, "index"), (["out"], POINTER(POINTER(IMMDevice)), "device")),
        )  # fmt: skip

    class IMMDeviceEnumerator(IUnknown):
        _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
        _methods_ = (
            COMMETHOD([], HRESULT, "EnumAudioEndpoints",
                      (["in"], c_uint, "flow"), (["in"], c_uint, "states"),
                      (["out"], POINTER(POINTER(IMMDeviceCollection)), "devices")),
            COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint",
                      (["in"], c_uint, "flow"), (["in"], c_uint, "role"),
                      (["out"], POINTER(POINTER(IMMDevice)), "device")),
        )  # fmt: skip

    _com.cache = {
        "enumerator": IMMDeviceEnumerator,
        "volume": IAudioEndpointVolume,
        "clsid": GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}"),
        "name_key": PROPERTYKEY(GUID("{A45C254E-DF1C-4EFD-8020-67D146A850E0}"), 14),
    }
    return _com.cache


def _friendly_name(device) -> str:
    try:
        return device.OpenPropertyStore(0).GetValue(_com()["name_key"]).text or ""
    except Exception:
        return ""


def device_id(device) -> str:
    """Windows' id for an audio device ("{0.0.0.00000000}.{...}"); "" if it can't tell."""
    import ctypes

    try:
        pointer = device.GetId()
    except Exception:
        return ""
    try:
        return ctypes.wstring_at(pointer) if pointer else ""
    finally:
        ctypes.windll.ole32.CoTaskMemFree(ctypes.c_void_p(pointer))


def default_device(flow: int = RENDER):
    """The default speakers (or microphone) as a COM device. COM must be initialized."""
    import comtypes

    com = _com()
    devices = comtypes.CoCreateInstance(com["clsid"], com["enumerator"], comtypes.CLSCTX_ALL)
    return devices.GetDefaultAudioEndpoint(flow, 0)


def same_device(friendly: str, wanted: str) -> bool:
    """Is this Windows device the one called `wanted` in Abdoh's microphone list (cut short)?"""
    return bool(wanted) and friendly[:NAME_LIMIT].strip() == wanted[:NAME_LIMIT].strip()


class Endpoint:
    """One speaker or microphone: its name, volume (0 to 100) and mute switch."""

    def __init__(self, flow: int, name: str = ""):
        """The default device of this kind, or the one called `name` (if it's there)."""
        if sys.platform != "win32":
            raise AudioError("The volume can only be changed on Windows for now.")
        try:
            import comtypes

            try:
                comtypes.CoInitialize()
            except OSError:
                pass  # this thread already uses COM another way
            com = _com()
            devices = comtypes.CoCreateInstance(
                com["clsid"], com["enumerator"], comtypes.CLSCTX_ALL
            )
            device = None
            if name:
                found = devices.EnumAudioEndpoints(flow, ACTIVE)
                for i in range(found.GetCount()):
                    candidate = found.Item(i)
                    if same_device(_friendly_name(candidate), name):
                        device = candidate
                        break
            if device is None:
                device = devices.GetDefaultAudioEndpoint(flow, 0)
            self.name = _friendly_name(device)
            interface = device.Activate(com["volume"]._iid_, comtypes.CLSCTX_ALL, None)
            self._volume = interface.QueryInterface(com["volume"])
        except Exception as e:
            raise AudioError(f"Windows' volume control isn't available: {e}") from e

    def volume(self) -> int:
        return round(self._volume.GetMasterVolumeLevelScalar() * 100)

    def set_volume(self, percent: float) -> int:
        percent = max(0, min(100, round(percent)))
        self._volume.SetMasterVolumeLevelScalar(percent / 100, None)
        return percent

    def muted(self) -> bool:
        return bool(self._volume.GetMute())

    def set_muted(self, muted: bool) -> None:
        self._volume.SetMute(1 if muted else 0, None)


def speaker() -> Endpoint:
    return Endpoint(RENDER)


def microphone(name: str = "") -> Endpoint:
    return Endpoint(CAPTURE, name)
