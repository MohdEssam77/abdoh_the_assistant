"""Windows' own volume controls (Core Audio): the speakers' and a microphone's volume and mute,
and each app's volume in the volume mixer.

Thin wrappers over COM through comtypes; everything else uses the small `Endpoint` class and
the plain `AppSession` values, which tests replace with fakes.
"""

import logging
import os
import sys
from dataclasses import dataclass

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

    class ISimpleAudioVolume(IUnknown):
        _iid_ = GUID("{87CE5498-68D6-44E5-9215-6DA47EF883D8}")
        _methods_ = (
            COMMETHOD([], HRESULT, "SetMasterVolume",
                      (["in"], c_float, "level"), (["in"], c_void_p, "context")),
            COMMETHOD([], HRESULT, "GetMasterVolume", (["out"], POINTER(c_float), "level")),
            COMMETHOD([], HRESULT, "SetMute",
                      (["in"], c_int, "mute"), (["in"], c_void_p, "context")),
            COMMETHOD([], HRESULT, "GetMute", (["out"], POINTER(c_int), "mute")),
        )  # fmt: skip

    class IAudioSessionControl2(IUnknown):
        _iid_ = GUID("{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}")
        _methods_ = (
            COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(c_int), "state")),
            COMMETHOD([], HRESULT, "GetDisplayName", (["out"], POINTER(c_void_p), "name")),
            unused("SetDisplayName"),
            unused("GetIconPath"),
            unused("SetIconPath"),
            unused("GetGroupingParam"),
            unused("SetGroupingParam"),
            unused("RegisterAudioSessionNotification"),
            unused("UnregisterAudioSessionNotification"),
            # IAudioSessionControl2's own methods
            unused("GetSessionIdentifier"),
            COMMETHOD([], HRESULT, "GetSessionInstanceIdentifier",
                      (["out"], POINTER(c_void_p), "id")),
            COMMETHOD([], HRESULT, "GetProcessId", (["out"], POINTER(c_uint), "pid")),
        )  # fmt: skip

    class IAudioSessionEnumerator(IUnknown):
        _iid_ = GUID("{E2F5BB11-0570-40CA-ACDD-3AA01277DEE8}")
        _methods_ = (
            COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(c_int), "count")),
            COMMETHOD([], HRESULT, "GetSession",
                      (["in"], c_int, "index"),
                      (["out"], POINTER(POINTER(IUnknown)), "session")),
        )  # fmt: skip

    class IAudioSessionManager2(IUnknown):
        _iid_ = GUID("{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}")
        _methods_ = (
            unused("GetAudioSessionControl"),
            unused("GetSimpleAudioVolume"),
            COMMETHOD([], HRESULT, "GetSessionEnumerator",
                      (["out"], POINTER(POINTER(IAudioSessionEnumerator)), "sessions")),
        )  # fmt: skip

    _com.cache = {
        "sessions": IAudioSessionManager2,
        "session": IAudioSessionControl2,
        "app_volume": ISimpleAudioVolume,
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


# ----- each app's volume (the volume mixer) -----

ACTIVE_SESSION = 1  # AudioSessionStateActive: the app is playing sound right now


@dataclass(frozen=True)
class AppSession:
    """One app's sound in the volume mixer, as plain values. `volume` is 0 to 100, relative to
    the speakers' volume (what the mixer's slider shows)."""

    id: str  # the session's instance id: finds it again later
    pid: int
    program: str  # "brave", "spotify" ("" for Windows' system sounds)
    name: str  # what the mixer calls it, when the app named it
    volume: int
    muted: bool
    playing: bool


def _take_string(pointer) -> str:
    import ctypes

    if not pointer:
        return ""
    try:
        return ctypes.wstring_at(pointer)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(ctypes.c_void_p(pointer))


def process_name(pid: int) -> str:
    """The program a process runs ("chrome"), without ".exe"; "" if Windows won't say."""
    if sys.platform != "win32" or not pid:
        return ""
    import ctypes
    from ctypes import wintypes

    process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFO
    if not process:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not ctypes.windll.kernel32.QueryFullProcessImageNameW(
            process, 0, buffer, ctypes.byref(size)
        ):
            return ""
        name = os.path.basename(buffer.value)
        return name[:-4] if name.lower().endswith(".exe") else name
    finally:
        ctypes.windll.kernel32.CloseHandle(process)


def _sessions():
    """(AppSession, ISimpleAudioVolume) for every app on every active output."""
    import comtypes

    try:
        comtypes.CoInitialize()
    except OSError:
        pass  # this thread already uses COM another way
    com = _com()
    devices = comtypes.CoCreateInstance(com["clsid"], com["enumerator"], comtypes.CLSCTX_ALL)
    outputs = devices.EnumAudioEndpoints(RENDER, ACTIVE)
    for d in range(outputs.GetCount()):
        manager = outputs.Item(d).Activate(com["sessions"]._iid_, comtypes.CLSCTX_ALL, None)
        found = manager.QueryInterface(com["sessions"]).GetSessionEnumerator()
        for i in range(found.GetCount()):
            try:
                raw = found.GetSession(i)
                control = raw.QueryInterface(com["session"])
                volume = raw.QueryInterface(com["app_volume"])
                pid = control.GetProcessId()
                session = AppSession(
                    id=_take_string(control.GetSessionInstanceIdentifier()),
                    pid=pid,
                    program=process_name(pid),
                    name=_take_string(control.GetDisplayName()),
                    volume=round(volume.GetMasterVolume() * 100),
                    muted=bool(volume.GetMute()),
                    playing=control.GetState() == ACTIVE_SESSION,
                )
            except Exception:
                log.debug("Skipped an audio session", exc_info=True)
                continue
            yield session, volume


def app_sessions() -> list[AppSession]:
    """Every app in the volume mixer (Windows only; [] elsewhere or if it can't be read)."""
    if sys.platform != "win32":
        return []
    try:
        return [session for session, _ in _sessions()]
    except Exception as e:
        log.warning("Couldn't read the volume mixer: %s", e)
        return []


def set_session_volume(session_id: str, percent: float | None = None, muted=None) -> bool:
    """Change one app's volume (0 to 100) or mute, found by its session id. False if it's gone."""
    if sys.platform != "win32":
        return False
    try:
        for session, volume in _sessions():
            if session.id != session_id:
                continue
            if percent is not None:
                volume.SetMasterVolume(max(0.0, min(1.0, percent / 100)), None)
            if muted is not None:
                volume.SetMute(1 if muted else 0, None)
            return True
    except Exception as e:
        raise AudioError(f"Windows' volume mixer isn't available: {e}") from e
    return False


def speaker() -> Endpoint:
    return Endpoint(RENDER)


def microphone(name: str = "") -> Endpoint:
    return Endpoint(CAPTURE, name)
