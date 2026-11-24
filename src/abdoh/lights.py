"""Smart lamps: WiZ bulbs and lamps, over your home Wi-Fi, without the cloud.

WiZ lamps listen for small JSON messages on UDP port 38899 on the home network:
`{"method": "getPilot", "params": {}}` answers with the lamp's state (and its MAC address), and
`{"method": "setPilot", "params": {...}}` changes it: `state` (on/off), `dimming` (10-100),
`r`/`g`/`b` (a colour) or `temp` (white, 2200-6500 K), or `sceneId` (one of the WiZ app's
presets). Lamps are found by broadcasting from each of the computer's addresses (Windows would
send a plain broadcast out of just one network adapter, maybe WSL's); each is
remembered in <app_dir>/lamps.json by its MAC address, with the name you gave it ("desk lamp"),
and found again if its IP address changes.

Checked with a real WiZ bulb (2026-11-24, firmware 1.29.0): getPilot answers {"mac", "rssi",
"state", "sceneId", "temp", "dimming", ...}; every setting here worked. Newer firmware answers
with "env": "pro" and an "hmac", and refuses changes ("Invalid params", -32602) unless the
WiZ app allows all controls (Settings, Security) or they are signed with the home's key, which
Abdoh doesn't do yet.
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
PREVIEW_SECONDS = 4.0  # "Try" in the lamp dialog: then the lamps go back
TRIES = 3  # UDP can lose a message: send again
WARM, NEUTRAL, COOL = 2700, 4000, 6500
CANDLE = 2200  # the warmest a WiZ white goes
COLOURS = {
    "red": (255, 0, 0), "crimson": (220, 20, 60), "rose": (255, 60, 110),
    "coral": (255, 95, 70), "salmon": (255, 130, 110), "peach": (255, 160, 110),
    "orange": (255, 110, 0), "amber": (255, 150, 0), "gold": (255, 190, 0),
    "yellow": (255, 220, 0), "lime": (170, 255, 0), "green": (0, 255, 0),
    "mint": (80, 255, 170), "teal": (0, 200, 160), "turquoise": (0, 230, 210),
    "cyan": (0, 255, 255), "sky blue": (90, 190, 255), "blue": (0, 0, 255),
    "royal blue": (50, 80, 255), "indigo": (80, 0, 255), "purple": (140, 0, 255),
    "violet": (170, 60, 255), "lavender": (190, 150, 255), "magenta": (255, 0, 255),
    "pink": (255, 60, 160), "hot pink": (255, 20, 140),
}  # fmt: skip
WHITES = {
    "warm white": WARM, "warm": WARM, "soft white": WARM, "candle white": CANDLE,
    "white": NEUTRAL, "neutral white": NEUTRAL, "natural white": NEUTRAL,
    "cool white": COOL, "cool": COOL, "cold white": COOL, "daylight": COOL, "bright white": COOL,
}  # fmt: skip
# The WiZ app's own scenes (sceneId), as pywizlight lists them; Rhythm, Alarm and the custom
# and sync ones are left out. Some move (Party, Ocean...): `speed` (10-200) sets how fast.
SCENES = {
    "ocean": 1, "romance": 2, "sunset": 3, "party": 4, "fireplace": 5, "cozy": 6, "forest": 7,
    "pastel colors": 8, "wake up": 9, "bedtime": 10, "warm white": 11, "daylight": 12,
    "cool white": 13, "night light": 14, "focus": 15, "relax": 16, "true colors": 17,
    "tv time": 18, "plant growth": 19, "spring": 20, "summer": 21, "fall": 22, "deep dive": 23,
    "jungle": 24, "mojito": 25, "club": 26, "christmas": 27, "halloween": 28,
    "candlelight": 29, "golden white": 30, "pulse": 31, "steampunk": 32, "diwali": 33,
    "white": 34, "snowy sky": 36, "dim to warm": 40,
}  # fmt: skip
SCENE_NAMES = {number: name for name, number in SCENES.items()}
SCENE_WORDS = {
    **{name: name for name in SCENES},
    "disco": "party", "cosy": "cozy", "pastel colours": "pastel colors", "autumn": "fall",
    "true colours": "true colors", "candle light": "candlelight", "plantgrowth": "plant growth",
    "wake-up": "wake up", "dim-to-warm": "dim to warm", "deepdive": "deep dive",
}  # fmt: skip
# Said alone, these are a white, not the scene of the same name ("scene daylight" is the scene).
WHITE_FIRST = {"warm white", "cool white", "daylight", "white"}
# Which scenes a white-only lamp has (pywizlight's TW_SCENES, DW_SCENES; not Alarm).
WHITE_SCENES = {6, 9, 10, 11, 12, 13, 14, 15, 16, 18, 29, 30, 31, 32, 33, 40}
DIMMABLE_SCENES = {9, 10, 14, 29, 31, 32, 34}
NORMAL_SPEED = 100
SPEEDS = {"very slow": 20, "slowly": 50, "slow": 50, "fast": 160, "quick": 160, "very fast": 200}
# What a lamp can do, from the WiZ module name ("ESP24_SHRGBC_01": colour).
COLOUR, WHITE, DIMMABLE, PLUG = "colour", "white", "dimmable", "plug"
KIND_NAMES = {
    COLOUR: "colours and whites", WHITE: "whites only", DIMMABLE: "brightness only",
    PLUG: "on and off only",
}  # fmt: skip
# Words that may be left over in "set the desk lamp to the party scene, fast, at 60 percent".
_FILLER = {
    "and", "with", "at", "to", "a", "the", "in", "please", "scene", "mode", "colour", "color",
    "brightness", "speed", "light", "lights", "lamp", "lamps", "now", "it", "turn", "make", "set",
    "switch", "put", "change", "of", "on",
}  # fmt: skip
# A lamp whose WiZ app only allows its own ("verified") controls refuses changes with these.
REFUSED_CODES = {-32602, -32605}
REFUSED = (
    "The lamp only takes commands from the WiZ app. In the WiZ app, go to Settings, then "
    "Security, and allow all controls."
)
ALL = {"all", "both", "every", "everything", "lamps", "lights", "the lamps", "the lights"}
# Said for "the lamp" when you have one, or for all of them.
GENERIC = {"lamp", "light", "the lamp", "the light", "my lamp", "my light", ""}


class LampRefused(ActionError):
    """The lamp answered, but said no: asking again (or elsewhere) won't help."""


@dataclass
class Lamp:
    name: str
    mac: str
    ip: str
    kind: str = ""  # colour, white, dimmable or plug ("" until Abdoh has asked it)


def _words(name: str) -> str:
    return r"\b" + r"[\s-]+".join(map(re.escape, name.split())) + r"\b"


def _take(pattern: str, text: str) -> tuple[re.Match | None, str]:
    """The first match of `pattern` in `text`, and the text without it."""
    found = re.search(pattern, text)
    if found is None:
        return None, text
    return found, f"{text[: found.start()]} {text[found.end() :]}"


def setting(text: str, strict: bool = False) -> dict:
    """What you want a lamp to do, as setPilot params: "off", "on", "40%", "red", "#ff8800",
    "warm white", "blue 30%", "3000k", "dim", "bright", "party", "scene ocean slow",
    "fireplace 40%". `strict`: nothing else may be in it (a sentence that just mentions a
    lamp isn't one). Raises ActionError."""
    words = " ".join(text.lower().replace("percent", "%").replace(",", " ").split())
    rest = words
    params: dict = {}
    off, rest = _take(r"\boff\b", rest)
    level, rest = _take(r"(\d{1,3})\s*%", rest)
    if level:
        params["dimming"] = max(10, min(100, int(level[1])))
    # A scene: "scene X" or "X scene" (any), or its name alone (unless that's also a white)
    scene = None
    for word in sorted(SCENE_WORDS, key=len, reverse=True):
        name = SCENE_WORDS[word]
        found, after = _take(rf"\bscene\s+{_words(word)}|{_words(word)}\s+scene\b", rest)
        if found is None and name not in WHITE_FIRST:
            found, after = _take(_words(word), rest)
        if found is not None:
            scene, rest = SCENES[name], after
            break
    if scene is not None:
        params["sceneId"] = scene
        speed, rest = _take(r"\bspeed\s+(\d{1,3})\b", rest)
        if speed:
            params["speed"] = max(10, min(200, int(speed[1])))
        else:
            for word in sorted(SPEEDS, key=len, reverse=True):
                found, rest = _take(rf"\b{word}\b", rest)
                if found:
                    params["speed"] = SPEEDS[word]
                    break
            else:  # a lamp keeps the last scene's speed: "fireplace" after "ocean slow"
                params["speed"] = NORMAL_SPEED
    else:
        kelvin, rest = _take(r"\b(\d{4})\s*k\b", rest)
        hex_colour, rest = _take(r"#([0-9a-f]{6})\b", rest)
        if kelvin:
            params["temp"] = max(2200, min(6500, int(kelvin[1])))
        elif hex_colour:
            value = hex_colour[1]
            params.update(r=int(value[0:2], 16), g=int(value[2:4], 16), b=int(value[4:6], 16))
        else:
            for name in sorted(WHITES, key=len, reverse=True):
                found, rest = _take(_words(name), rest)
                if found:
                    params["temp"] = WHITES[name]
                    break
            else:
                for name in sorted(COLOURS, key=len, reverse=True):
                    found, rest = _take(_words(name), rest)
                    if found:
                        params["r"], params["g"], params["b"] = COLOURS[name]
                        break
    dim, rest = _take(r"\b(?:dim|dimmer|low|darker)\b", rest)
    bright, rest = _take(r"\b(?:bright|brighter|full|max)\b", rest)
    if "dimming" not in params:  # "dim it to 30%": the number
        if dim:
            params["dimming"] = 30
        elif bright:
            params["dimming"] = 100
    on = re.search(r"\bon\b", words)
    leftover = [w for w in rest.split() if w not in _FILLER]
    if strict and leftover:
        raise ActionError(f"I don't know how to make a lamp {text.strip()}.")
    if off:
        return {"state": False}
    if not params and not on:
        raise ActionError(f"I don't know how to make a lamp {text.strip()}.")
    params["state"] = True
    return params


def describe(pilot: dict) -> str:
    """How a lamp is now (getPilot's answer) in the words setting() reads: "off",
    "scene party speed 160 80%", "warm white 60%", "3000k", "#ff8800 40%"."""
    if not pilot.get("state"):
        return "off"
    level = f" {pilot['dimming']}%" if pilot.get("dimming") else ""
    scene = pilot.get("sceneId")
    if scene in SCENE_NAMES:
        speed = pilot.get("speed")
        fast = f" speed {speed}" if speed and speed != NORMAL_SPEED else ""
        return f"scene {SCENE_NAMES[scene]}{fast}{level}"
    temp = pilot.get("temp")
    if temp:
        named = {CANDLE: "candle white", WARM: "warm white", NEUTRAL: "neutral white"}
        named[COOL] = "cool white"
        return f"{named.get(temp) or f'{temp}k'}{level}"
    rgb = [int(pilot.get(k) or 0) for k in ("r", "g", "b")]
    if any(rgb):
        return "#{:02x}{:02x}{:02x}".format(*rgb) + level
    return f"on{level}"


def lamp_kind(module: str) -> str:
    """What a lamp can do, from its WiZ module name (getSystemConfig's moduleName): the part
    after the first "_" says it, like pywizlight reads it. "" if it can't tell."""
    parts = str(module or "").upper().split("_")
    if len(parts) < 2:
        return ""
    part = parts[1]
    if "RGB" in part:
        return COLOUR
    if "TW" in part:
        return WHITE
    if "SOCKET" in part:
        return PLUG
    return DIMMABLE


def fit(kind: str, params: dict) -> dict | None:
    """`params` as a lamp of this kind can take them, or None if it can't at all (a scene it
    doesn't have). A colour on a white-only lamp becomes the nearest white: warm for red and
    orange, cool for blue. An unknown kind ("") gets them as they are."""
    params = dict(params)
    if not kind or kind == COLOUR or not params.get("state"):
        return params
    if kind == PLUG:
        return {"state": True}
    scene = params.get("sceneId")
    if scene is not None and scene not in (WHITE_SCENES if kind == WHITE else DIMMABLE_SCENES):
        return None
    if "r" in params:
        r, b = params.pop("r"), params.pop("b")
        params.pop("g", None)
        if kind == WHITE:
            params["temp"] = CANDLE if r > b else COOL
    if kind == DIMMABLE:
        params.pop("temp", None)
    return params


def options() -> dict:
    """For the app's lamp pickers: the colours (as #rrggbb), the whites and the scenes, with
    which kinds of lamp have each scene."""
    return {
        "colours": [[name, "#{:02x}{:02x}{:02x}".format(*rgb)] for name, rgb in COLOURS.items()],
        "whites": [["candle", CANDLE], ["warm", WARM], ["neutral", NEUTRAL], ["cool", COOL]],
        "scenes": [
            {
                "id": number,
                "name": "TV time" if name == "tv time" else name[:1].upper() + name[1:],
                "kinds": [COLOUR]
                + ([WHITE] if number in WHITE_SCENES else [])
                + ([DIMMABLE] if number in DIMMABLE_SCENES else []),
            }
            for name, number in SCENES.items()
        ],
        "kinds": KIND_NAMES,
        # For reading a setting back into a picker the way setting() reads it
        "scene_words": SCENE_WORDS,
        "white_first": sorted(WHITE_FIRST),
        "white_names": WHITES,
        "speeds": SPEEDS,
        "filler": sorted(_FILLER),
    }


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
                error = answer.get("error")
                if error:
                    code = error.get("code") if isinstance(error, dict) else None
                    log.info("The lamp at %s said no to %s: %s", ip, method, error)
                    if method == "setPilot" and code in REFUSED_CODES:
                        raise LampRefused(REFUSED)
                    raise LampRefused(f"The lamp said no ({error}).")
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
        if before.get("speed"):
            params["speed"] = before["speed"]
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

    def __init__(self, path: Path, wiz: Wiz | None = None, timer=threading.Timer):
        self.path = Path(path)
        self.wiz = wiz or Wiz()
        self._lock = threading.Lock()
        self._timer = timer
        self._preview = None  # the timer that ends a "Try"
        self._before_preview: dict | None = None

    def all(self) -> list[Lamp]:
        try:
            entries = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        keys = ("name", "mac", "ip", "kind")
        return [Lamp(**{k: str(e.get(k) or "") for k in keys}) for e in entries]

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
                if not known[mac].kind:
                    known[mac].kind = self._ask_kind(known[mac])
            self._save(lamps)
            return lamps

    def _ask_kind(self, lamp: Lamp) -> str:
        """What the lamp can do (colours, whites...), from its WiZ module name."""
        try:
            config = self.wiz.send(lamp.ip, "getSystemConfig")
        except ActionError:
            return ""
        kind = lamp_kind(config.get("moduleName", ""))
        log.info("%s is a WiZ %s (%s)", lamp.name, kind or "lamp", config.get("moduleName"))
        return kind

    def _kind(self, lamp: Lamp) -> str:
        """The lamp's kind, asked once and kept in lamps.json."""
        if not lamp.kind:
            lamp.kind = self._ask_kind(lamp)
            if lamp.kind:
                with self._lock:
                    self._save([lamp if lamp.mac == o.mac else o for o in self.all()])
        return lamp.kind

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
        for lamp in lamps:  # a lamp's own name first: one called "Lamp" is that one
            name = lamp.name.lower()
            if words in (name, f"the {name}", f"my {name}"):
                return [lamp]
        if words in ALL or words in GENERIC:
            return lamps
        for lamp in lamps:  # "desk" for "desk lamp"
            if re.search(rf"\b{re.escape(words)}\b", lamp.name.lower()):
                return [lamp]
        raise ActionError(f"You don't have a lamp called {which.strip()}.")

    def set(self, which: str, how: str) -> list[str]:
        """Change the lamps `which` names, each as far as it can: a colour on a white-only
        lamp becomes the nearest white, and a scene it doesn't have leaves it alone. Returns
        the names of the lamps changed."""
        params = setting(how)
        lamps = self.pick(which)
        done, cant = [], []
        for lamp in lamps:
            fitted = fit(self._kind(lamp), params)
            if fitted is None:
                cant.append(lamp)
                continue
            self._send(lamp, "setPilot", fitted)
            done.append(lamp.name)
        if cant:
            log.info("Left alone (they don't have that scene): %s", [lamp.name for lamp in cant])
        if not done:
            what = KIND_NAMES.get(cant[0].kind, "")
            raise ActionError(f"{cant[0].name} doesn't have that scene ({what}).")
        return done

    def states(self) -> list[dict]:
        """Each lamp and how it is now ("how", in setting()'s words), for the Lamps page.
        A lamp that doesn't answer (switched off at the wall) has "answers": False; nobody
        waits for a search on the network here."""
        found = []
        for lamp in self.all():
            try:
                how = describe(self.wiz.send(lamp.ip, "getPilot"))
            except ActionError:
                found.append({**asdict(lamp), "how": None, "answers": False})
                continue
            found.append({**asdict(lamp), "kind": self._kind(lamp), "how": how, "answers": True})
        return found

    # ----- before and after: a role or a mode puts the lamps back as they were -----

    def snapshot(self) -> dict[str, dict]:
        """How each lamp that answers is now, by MAC address (plain JSON)."""
        states = {}
        for lamp in self.all():
            try:
                states[lamp.mac] = self._send(lamp, "getPilot")
            except ActionError:
                log.info("%s didn't say how it is", lamp.name)
        return states

    def restore(self, states: dict) -> None:
        """Put the lamps back as a snapshot found them."""
        for lamp in self.all():
            before = (states or {}).get(lamp.mac)
            if not before:
                continue
            try:
                self._send(lamp, "setPilot", _as_it_was(before))
            except ActionError as e:
                log.info("Couldn't put %s back: %s", lamp.name, e)

    def preview(self, which: str, how: str, seconds: float = PREVIEW_SECONDS) -> list[str]:
        """Show a setting for a few seconds ("Try"), then put the lamps back as they were.
        Trying again meanwhile still goes back to how they were before the first try."""
        if self._preview is not None:
            self._preview.cancel()
        elif self._before_preview is None:
            self._before_preview = self.snapshot()
        try:
            names = self.set(which, how)
        finally:
            self._preview = self._timer(seconds, self._end_preview)
            self._preview.daemon = True
            self._preview.start()
        return names

    def _end_preview(self) -> None:
        before, self._before_preview, self._preview = self._before_preview, None, None
        if before:
            self.restore(before)

    _kept: dict | None = None

    def keep_for_later(self) -> None:
        """Note how the lamps are, once, before something (a role) changes them."""
        if self._kept is None:
            self._kept = self.snapshot()

    def put_back(self) -> bool:
        """The lamps as they were at keep_for_later(). False if nothing was kept."""
        kept, self._kept = self._kept, None
        if kept is None:
            return False
        self.restore(kept)
        return True

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
        except LampRefused:
            raise
        except ActionError:
            # Its IP address may have changed (the router gave it another one): find it again.
            moved = {mac: ip for ip, mac in self.wiz.find()}
            if lamp.mac not in moved or moved[lamp.mac] == lamp.ip:
                raise ActionError(f"{lamp.name} didn't answer. Is it switched on?") from None
            lamp.ip = moved[lamp.mac]
            self._save([lamp if lamp.mac == other.mac else other for other in self.all()])
            return self.wiz.send(lamp.ip, method, params)
