"""Smart lamps: WiZ bulbs and lamps, over your home Wi-Fi, without the cloud.

WiZ lamps listen for small JSON messages on UDP port 38899 on the home network:
`{"method": "getPilot", "params": {}}` answers with the lamp's state (and its MAC address), and
`{"method": "setPilot", "params": {...}}` changes it: `state` (on/off), `dimming` (10-100),
`r`/`g`/`b` (a colour) or `temp` (white, 2200-6500 K), or `sceneId` (one of the WiZ app's
presets). Lamps are found by broadcasting from each of the computer's addresses (Windows would
send a plain broadcast out of just one network adapter, maybe WSL's); each is
remembered in <app_dir>/lamps.json by its MAC address, with the name you gave it ("desk lamp"),
and found again if its IP address changes. If no lamp answers, turn on "Allow local
communication" in the WiZ app's settings.

Checked with a real WiZ bulb (2026-11-24): getPilot answers {"mac", "rssi", "state",
"sceneId", "temp", "dimming", ...}.
"""

import json
import logging
import re
import socket
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from abdoh.commands.actions import ActionError

log = logging.getLogger(__name__)

PORT = 38899
BROADCAST = "255.255.255.255"
FIND_SECONDS = 2.0
ANSWER_SECONDS = 0.6
TRIES = 3  # UDP can lose a message: send again
WARM, NEUTRAL, COOL = 2700, 4000, 6500
COLOURS = {
    "red": (255, 0, 0), "orange": (255, 110, 0), "yellow": (255, 210, 0),
    "green": (0, 255, 0), "teal": (0, 200, 160), "cyan": (0, 255, 255),
    "blue": (0, 0, 255), "purple": (140, 0, 255), "violet": (140, 0, 255),
    "pink": (255, 60, 160), "magenta": (255, 0, 255),
}  # fmt: skip
WHITES = {
    "warm white": WARM, "warm": WARM, "cozy": WARM, "soft white": WARM,
    "white": NEUTRAL, "neutral white": NEUTRAL, "natural white": NEUTRAL,
    "cool white": COOL, "cool": COOL, "cold white": COOL, "daylight": COOL, "bright white": COOL,
}  # fmt: skip
ALL = {"all", "both", "every", "everything", "lamps", "lights", "the lamps", "the lights"}
# Said for "the lamp" when you have one, or for all of them.
GENERIC = {"lamp", "light", "the lamp", "the light", "my lamp", "my light", ""}


@dataclass
class Lamp:
    name: str
    mac: str
    ip: str


def setting(text: str) -> dict:
    """What you want a lamp to do, as setPilot params: "off", "on", "40%", "red", "warm white",
    "blue 30%", "3000k", "dim", "bright". Raises ActionError."""
    words = " ".join(text.lower().replace("percent", "%").split())
    params: dict = {}
    if re.search(r"\boff\b", words):
        return {"state": False}
    level = re.search(r"(\d{1,3})\s*%", words)
    if level:
        params["dimming"] = max(10, min(100, int(level[1])))
    elif re.search(r"\b(?:dim|dimmer|low|darker)\b", words):
        params["dimming"] = 30
    elif re.search(r"\b(?:bright|brighter|full|max)\b", words):
        params["dimming"] = 100
    kelvin = re.search(r"\b(\d{4})\s*k\b", words)
    if kelvin:
        params["temp"] = max(2200, min(6500, int(kelvin[1])))
    else:
        for name in sorted(WHITES, key=len, reverse=True):
            if re.search(rf"\b{name}\b", words):
                params["temp"] = WHITES[name]
                break
        else:
            for name, (r, g, b) in COLOURS.items():
                if re.search(rf"\b{name}\b", words):
                    params.update(r=r, g=g, b=b)
                    break
    if not params and not re.search(r"\bon\b", words):
        raise ActionError(f"I don't know how to make a lamp {text.strip()}.")
    params["state"] = True
    return params


class Wiz:
    """Talks to WiZ lamps. `make_socket()` gives a UDP socket and `addresses()` this
    computer's IPv4 addresses (fakes in tests)."""

    def __init__(self, make_socket=None, addresses=None):
        self._make_socket = make_socket or _udp_socket
        self._addresses = addresses or (_local_addresses if make_socket is None else _anywhere)

    def send(self, ip: str, method: str, params: dict | None = None) -> dict:
        """Send one message to the lamp at `ip` and return its answer's "result"."""
        message = json.dumps({"method": method, "params": params or {}}).encode()
        sock = self._make_socket()
        try:
            for _ in range(TRIES):
                sock.sendto(message, (ip, PORT))
                try:
                    data, _ = sock.recvfrom(4096)
                except (TimeoutError, OSError):
                    continue
                answer = json.loads(data.decode("utf-8", "replace"))
                if "error" in answer:
                    raise ActionError(f"The lamp said no ({answer['error']}).")
                return answer.get("result") or {}
        finally:
            sock.close()
        raise ActionError("The lamp didn't answer.")

    def find(self, seconds: float = FIND_SECONDS) -> list[tuple[str, str]]:
        """The lamps on your network: [(ip, mac)]. Asked from each of this computer's
        addresses: the answers wait in each socket while the one before is read."""
        message = json.dumps({"method": "getPilot", "params": {}}).encode()
        sockets = []
        found: dict[str, str] = {}
        try:
            for address in self._addresses():
                try:
                    sock = self._make_socket(broadcast=True, bind=address)
                    for _ in range(2):
                        sock.sendto(message, (BROADCAST, PORT))
                except OSError:
                    log.debug("Couldn't look for lamps from %s", address, exc_info=True)
                    continue
                sockets.append(sock)
            for sock in sockets:
                sock.settimeout(seconds / len(sockets))
                while True:
                    try:
                        data, (ip, _) = sock.recvfrom(4096)
                    except (TimeoutError, OSError):
                        break
                    try:
                        mac = (json.loads(data.decode()).get("result") or {}).get("mac")
                    except ValueError:
                        continue
                    if mac:
                        found[mac] = ip
        finally:
            for sock in sockets:
                sock.close()
        return [(ip, mac) for mac, ip in found.items()]


def _as_it_was(before: dict) -> dict:
    """setPilot params for a lamp's earlier state (getPilot's answer): one of a scene (the
    WiZ app's presets report a temp too), a white or a colour, never a mix."""
    params: dict = {"state": bool(before.get("state", True))}
    if before.get("dimming"):
        params["dimming"] = before["dimming"]
    if before.get("sceneId"):
        params["sceneId"] = before["sceneId"]
    elif before.get("temp"):
        params["temp"] = before["temp"]
    elif any(before.get(k) for k in ("r", "g", "b")):
        params.update({k: int(before.get(k) or 0) for k in ("r", "g", "b")})
    return params


def _udp_socket(broadcast: bool = False, bind: str = ""):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        if broadcast:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        if bind:
            sock.bind((bind, 0))  # the broadcast goes out of this address's network adapter
    except OSError:
        sock.close()
        raise
    sock.settimeout(ANSWER_SECONDS)
    return sock


def _local_addresses() -> list[str]:
    """This computer's IPv4 addresses (Wi-Fi, Ethernet, WSL's adapter...), or [""] for any."""
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return _anywhere()
    ips = dict.fromkeys(str(info[4][0]) for info in infos)
    return [ip for ip in ips if not ip.startswith(("127.", "169.254."))] or _anywhere()


def _anywhere() -> list[str]:
    return [""]


class Lamps:
    """Your lamps, by the names you gave them (<app_dir>/lamps.json)."""

    def __init__(self, path: Path, wiz: Wiz | None = None):
        self.path = Path(path)
        self.wiz = wiz or Wiz()
        self._lock = threading.Lock()

    def all(self) -> list[Lamp]:
        try:
            entries = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [Lamp(**{k: e.get(k, "") for k in ("name", "mac", "ip")}) for e in entries]

    def _save(self, lamps: list[Lamp]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([asdict(lamp) for lamp in lamps], indent=2), "utf-8")

    def find_new(self) -> list[Lamp]:
        """Look for lamps on the network: new ones are added (named "Lamp 2" and so on), known
        ones get their current IP address. Returns all your lamps."""
        with self._lock:
            lamps = self.all()
            known = {lamp.mac: lamp for lamp in lamps}
            for ip, mac in self.wiz.find():
                if mac in known:
                    known[mac].ip = ip
                else:
                    lamp = Lamp(f"Lamp {len(lamps) + 1}" if lamps else "Lamp", mac, ip)
                    lamps.append(lamp)
                    known[mac] = lamp
            self._save(lamps)
            return lamps

    def rename(self, mac: str, name: str) -> None:
        name = " ".join(name.split())
        if not name:
            raise ActionError("Give the lamp a name.")
        lamps = self.all()
        for lamp in lamps:
            if lamp.mac == mac:
                lamp.name = name
        self._save(lamps)

    def forget(self, mac: str) -> None:
        self._save([lamp for lamp in self.all() if lamp.mac != mac])

    def pick(self, which: str) -> list[Lamp]:
        """The lamps `which` names: one by its name, "all", or "the lamp" (all of them)."""
        lamps = self.all()
        if not lamps:
            raise ActionError("You have no lamps yet. Find them in Settings, under Lamps.")
        words = " ".join(which.lower().split())
        if words in ALL or words in GENERIC:
            return lamps
        for lamp in lamps:
            name = lamp.name.lower()
            if words in (name, f"the {name}", f"my {name}"):
                return [lamp]
        for lamp in lamps:  # "desk" for "desk lamp"
            if re.search(rf"\b{re.escape(words)}\b", lamp.name.lower()):
                return [lamp]
        raise ActionError(f"You don't have a lamp called {which.strip()}.")

    def set(self, which: str, how: str) -> list[str]:
        """Change the lamps `which` names. Returns their names."""
        params = setting(how)
        lamps = self.pick(which)
        for lamp in lamps:
            self._send(lamp, "setPilot", params)
        return [lamp.name for lamp in lamps]

    def command(self, text: str) -> None:
        """The lamp action: "desk lamp | warm white 60%", "all | off", or just "off"."""
        which, _, how = text.rpartition("|")
        self.set(which.strip() or "all", how.strip())

    def blink(self, mac: str) -> None:
        """Show which lamp is which: a short flash of colour, then back as it was."""
        lamp = next((lamp for lamp in self.all() if lamp.mac == mac), None)
        if lamp is None:
            raise ActionError("That lamp isn't known.")
        before = self._send(lamp, "getPilot")
        self._send(lamp, "setPilot", {"state": True, "r": 0, "g": 120, "b": 255, "dimming": 100})
        threading.Timer(1.5, self._restore, args=(lamp, before)).start()

    def _restore(self, lamp: Lamp, before: dict) -> None:
        params = _as_it_was(before)
        try:
            self._send(lamp, "setPilot", params)
        except ActionError:
            log.debug("Couldn't put the lamp back", exc_info=True)

    def _send(self, lamp: Lamp, method: str, params: dict | None = None) -> dict:
        try:
            return self.wiz.send(lamp.ip, method, params)
        except ActionError:
            # Its IP address may have changed (the router gave it another one): find it again.
            moved = {mac: ip for ip, mac in self.wiz.find()}
            if lamp.mac not in moved or moved[lamp.mac] == lamp.ip:
                raise ActionError(f"{lamp.name} didn't answer. Is it switched on?") from None
            lamp.ip = moved[lamp.mac]
            self._save([lamp if lamp.mac == other.mac else other for other in self.all()])
            return self.wiz.send(lamp.ip, method, params)
