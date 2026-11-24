"""Smart lamps (WiZ) over a fake network: no lamps, sockets or Wi-Fi needed."""

import json

import pytest
from test_local_skills import FakeComputer

from abdoh.commands.actions import ActionError, claude_action, system_action
from abdoh.lights import PORT, Lamps, Wiz, setting
from abdoh.local_skills import LocalSkills
from abdoh.system_skills import Done


class Network:
    """Lamps on a pretend network: {mac: ip}. Records what each lamp was told."""

    def __init__(self, lamps, silent=(), modules=None):
        self.lamps = dict(lamps)  # mac -> ip
        self.silent = set(silent)  # ips that never answer
        self.modules = dict(modules or {})  # mac -> WiZ module name (a colour bulb if not given)
        self.told: list[tuple[str, str, dict]] = []  # (ip, method, params)
        self.state = {}

    def socket(self, broadcast=False, bind=""):
        return Socket(self)


class Socket:
    def __init__(self, network):
        self.network = network
        self.inbox = []

    def settimeout(self, seconds):
        pass

    def sendto(self, data, address):
        ip, port = address
        assert port == PORT
        message = json.loads(data)
        method, params = message["method"], message["params"]
        targets = (
            list(self.network.lamps.items())
            if ip == "255.255.255.255"
            else [(m, i) for m, i in self.network.lamps.items() if i == ip]
        )
        for mac, lamp_ip in targets:
            if lamp_ip in self.network.silent:
                continue
            if method == "getSystemConfig":  # what it can do: a read, not recorded
                module = self.network.modules.get(mac, "ESP24_SHRGBC_01")
                answer = {"method": method, "result": {"mac": mac, "moduleName": module}}
                self.inbox.append((json.dumps(answer).encode(), lamp_ip))
                continue
            self.network.told.append((lamp_ip, method, params))
            if method == "getPilot":
                result = {"mac": mac, "state": True, "dimming": 80, "temp": 4000}
                result.update(self.network.state.get(mac, {}))
            else:
                self.network.state[mac] = params
                result = {"success": True}
            self.inbox.append((json.dumps({"method": method, "result": result}).encode(), lamp_ip))

    def recvfrom(self, size):
        if not self.inbox:
            raise TimeoutError
        data, ip = self.inbox.pop(0)
        return data, (ip, PORT)

    def close(self):
        pass


def lamps_on(tmp_path, network):
    return Lamps(tmp_path / "lamps.json", Wiz(network.socket))


@pytest.mark.parametrize(
    "said, params",
    [
        ("off", {"state": False}),
        ("on", {"state": True}),
        ("40%", {"dimming": 40, "state": True}),
        ("30 percent", {"dimming": 30, "state": True}),
        ("red", {"r": 255, "g": 0, "b": 0, "state": True}),
        ("blue 30%", {"dimming": 30, "r": 0, "g": 0, "b": 255, "state": True}),
        ("warm white", {"temp": 2700, "state": True}),
        ("cool white 100%", {"dimming": 100, "temp": 6500, "state": True}),
        ("3000k", {"temp": 3000, "state": True}),
        ("dim", {"dimming": 30, "state": True}),
        ("5%", {"dimming": 10, "state": True}),  # the lowest a WiZ lamp goes
    ],
)
def test_what_you_say_becomes_a_setting(said, params):
    assert setting(said) == params


@pytest.mark.parametrize(
    "said, params",
    [
        ("party", {"sceneId": 4, "speed": 100, "state": True}),
        ("disco", {"sceneId": 4, "speed": 100, "state": True}),
        ("scene ocean slow", {"sceneId": 1, "speed": 50, "state": True}),
        ("fireplace 40%", {"dimming": 40, "sceneId": 5, "speed": 100, "state": True}),
        ("club, very fast", {"sceneId": 26, "speed": 200, "state": True}),
        ("party speed 150", {"sceneId": 4, "speed": 150, "state": True}),
        ("cozy", {"sceneId": 6, "speed": 100, "state": True}),
        ("golden white", {"sceneId": 30, "speed": 100, "state": True}),  # a scene, not "white"
        ("dim to warm", {"sceneId": 40, "speed": 100, "state": True}),  # not "dim"
        ("daylight", {"temp": 6500, "state": True}),  # alone: the white
        ("scene daylight", {"sceneId": 12, "speed": 100, "state": True}),
        ("warm white scene", {"sceneId": 11, "speed": 100, "state": True}),
        ("#ff8800 50%", {"dimming": 50, "r": 255, "g": 136, "b": 0, "state": True}),
        ("sky blue", {"r": 90, "g": 190, "b": 255, "state": True}),
        ("hot pink", {"r": 255, "g": 20, "b": 140, "state": True}),
        ("candle white", {"temp": 2200, "state": True}),
    ],
)
def test_scenes_speeds_and_more_colours(said, params):
    assert setting(said) == params


def test_strict_takes_only_what_it_understands():
    assert setting("set it to the party scene, fast, at 60 percent", strict=True) == {
        "dimming": 60, "sceneId": 4, "speed": 160, "state": True
    }  # fmt: skip
    with pytest.raises(ActionError):
        setting("blue like in the ocean film", strict=True)
    assert setting("blue like in the ocean film")["sceneId"] == 1  # Claude's: not strict


def test_a_lamp_says_what_it_can_do():
    from abdoh.lights import COLOUR, DIMMABLE, PLUG, WHITE, lamp_kind

    assert lamp_kind("ESP24_SHRGBC_01") == COLOUR  # the owner's bulb
    assert lamp_kind("ESP01_SHTW1C_31") == WHITE
    assert lamp_kind("ESP01_SHDW1C_31") == DIMMABLE
    assert lamp_kind("ESP10_SOCKET_06") == PLUG
    assert lamp_kind("") == ""


def test_each_kind_of_lamp_gets_what_it_can_take():
    from abdoh.lights import COLOUR, DIMMABLE, PLUG, WHITE, fit

    red = setting("red 40%")
    assert fit(COLOUR, red) == red and fit("", red) == red
    assert fit(WHITE, red) == {"dimming": 40, "temp": 2200, "state": True}  # warm, like red
    assert fit(WHITE, setting("blue"))["temp"] == 6500
    assert fit(DIMMABLE, red) == {"dimming": 40, "state": True}
    assert fit(PLUG, red) == {"state": True}
    assert fit(WHITE, setting("party")) is None  # no Party scene on a white-only lamp
    assert fit(WHITE, setting("candlelight")) == {"sceneId": 29, "speed": 100, "state": True}
    assert fit(WHITE, setting("off")) == {"state": False}


def test_all_lamps_each_as_far_as_it_can(tmp_path):
    network = Network(
        {"aa": "10.0.0.1", "bb": "10.0.0.2"}, modules={"bb": "ESP01_SHTW1C_31"}
    )  # a colour bulb and a white-only one, on the owner's stand
    lamps = lamps_on(tmp_path, network)
    lamps.find_new()
    assert [lamp.kind for lamp in lamps.all()] == ["colour", "white"]  # kept in lamps.json
    network.told.clear()
    assert lamps.set("all", "red") == ["Lamp", "Lamp 2"]
    assert dict((ip, p) for ip, _, p in network.told)["10.0.0.2"] == {"temp": 2200, "state": True}
    network.told.clear()
    assert lamps.set("all", "party") == ["Lamp"]  # the white one has no Party
    with pytest.raises(ActionError, match="Lamp 2 doesn't have that scene"):
        lamps.set("lamp 2", "party")


def test_lamps_are_put_back_as_they_were(tmp_path):
    network = Network({"aa": "10.0.0.1", "bb": "10.0.0.2"})
    lamps = lamps_on(tmp_path, network)
    lamps.find_new()
    network.state["aa"] = {"state": True, "sceneId": 11, "temp": 2700, "dimming": 100}
    network.state["bb"] = {"state": False, "temp": 4000, "dimming": 80}
    lamps.keep_for_later()
    lamps.set("all", "party")
    lamps.keep_for_later()  # once: the first one counts
    network.told.clear()
    assert lamps.put_back() is True
    assert [(ip, p) for ip, _, p in network.told] == [
        ("10.0.0.1", {"state": True, "dimming": 100, "sceneId": 11}),
        ("10.0.0.2", {"state": False, "dimming": 80, "temp": 4000}),
    ]
    assert lamps.put_back() is False  # nothing kept any more


class Later:
    """A timer that fires when the test says."""

    made: list = []

    def __init__(self, seconds, function):
        self.seconds, self.function, self.cancelled = seconds, function, False
        Later.made.append(self)

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True

    def fire(self):
        if not self.cancelled:
            self.function()


def test_try_shows_it_for_a_few_seconds_then_puts_it_back(tmp_path):
    network = Network({"aa": "10.0.0.1"})
    Later.made = []
    lamps = Lamps(tmp_path / "lamps.json", Wiz(network.socket), timer=Later)
    lamps.find_new()
    network.state["aa"] = {"state": True, "sceneId": 11, "temp": 2700, "dimming": 100}
    lamps.preview("all", "red")
    lamps.preview("all", "party")  # tried again: back to how it was before the first try
    first, second = Later.made
    assert first.cancelled and second.seconds == 4.0
    network.told.clear()
    second.fire()
    assert network.told == [
        ("10.0.0.1", "setPilot", {"state": True, "dimming": 100, "sceneId": 11})
    ]
    network.state["aa"] = {"state": False}  # switched off since
    lamps.preview("all", "blue")  # a new try notes the lamps again
    assert lamps._before_preview["aa"]["state"] is False


def test_the_app_gets_the_choices():
    from abdoh.lights import options

    choices = options()
    assert ["red", "#ff0000"] in choices["colours"]
    party = next(s for s in choices["scenes"] if s["name"] == "Party")
    candle = next(s for s in choices["scenes"] if s["name"] == "Candlelight")
    assert party["kinds"] == ["colour"] and candle["kinds"] == ["colour", "white", "dimmable"]


def test_nonsense_is_not_a_setting():
    with pytest.raises(ActionError):
        setting("what is it")


def test_lamps_are_found_and_named(tmp_path):
    network = Network({"aa": "192.168.1.41", "bb": "192.168.1.42"})
    lamps = lamps_on(tmp_path, network)
    found = lamps.find_new()
    assert [(lamp.name, lamp.ip) for lamp in found] == [
        ("Lamp", "192.168.1.41"),
        ("Lamp 2", "192.168.1.42"),
    ]
    lamps.rename("aa", "Desk lamp")
    assert [lamp.name for lamp in lamps.all()] == ["Desk lamp", "Lamp 2"]
    network.lamps["aa"] = "192.168.1.77"  # the router gave it a new address
    lamps.find_new()
    assert lamps.all()[0].ip == "192.168.1.77" and lamps.all()[0].name == "Desk lamp"


def test_lamps_are_looked_for_from_each_address(tmp_path):
    """Windows sends a plain broadcast out of one adapter (WSL's, say): ask from each."""
    network = Network({"aa": "192.168.0.87"})
    bound = []

    def socket(broadcast=False, bind=""):
        bound.append(bind)
        if bind == "10.9.9.9":
            raise OSError("that adapter is gone")
        return Socket(network)

    wiz = Wiz(socket, addresses=lambda: ["172.24.192.1", "10.9.9.9", "192.168.0.93"])
    assert wiz.find(seconds=0.1) == [("192.168.0.87", "aa")]  # once, though asked twice
    assert bound == ["172.24.192.1", "10.9.9.9", "192.168.0.93"]


def test_a_lamp_that_only_takes_the_wiz_apps_controls(tmp_path):
    """Newer firmware with "verified control" on: reads work, changes are refused, and Abdoh
    says what to switch (not "is it switched on?", and without looking for it again)."""
    from abdoh.lights import REFUSED

    network = Network({"aa": "192.168.0.87"})
    lamps = lamps_on(tmp_path, network)
    lamps.find_new()

    class Strict(Socket):
        def sendto(self, data, address):
            if json.loads(data)["method"] == "getPilot":
                return super().sendto(data, address)
            network.told.append((address[0], "setPilot", {}))
            error = {"code": -32602, "message": "Invalid params", "sigTs": 1795527727}
            answer = {"method": "setPilot", "env": "pro", "error": error, "hmac": "x"}
            self.inbox.append((json.dumps(answer).encode(), address[0]))

    lamps.wiz = Wiz(lambda broadcast=False, bind="": Strict(network))
    network.told.clear()
    with pytest.raises(ActionError) as refused:
        lamps.set("all", "red")
    assert str(refused.value) == REFUSED
    assert [method for _, method, _ in network.told] == ["setPilot"]  # no search, no retry


def test_the_app_finds_names_and_tries_lamps(tmp_path):
    """Settings → Lamps, and the "Try" button of the lamp pickers in commands and modes."""
    from abdoh.config import Config
    from abdoh.events import Bus
    from abdoh.ui.api import AppApi, UiState

    network = Network({"aa": "10.0.0.1"}, modules={"aa": "ESP01_SHTW1C_31"})
    api = AppApi(Bus(), UiState(), Config(app_dir=tmp_path), lamps=lamps_on(tmp_path, network))
    found = api.find_lamps()
    assert found["ok"] and found["lamps"][0]["kind"] == "white" and found["options"]["scenes"]
    assert api.rename_lamp("aa", "Desk lamp")["lamps"][0]["name"] == "Desk lamp"
    network.told.clear()
    refused = api.try_lamp("Desk lamp", "scene party")  # no Party on a white-only lamp
    assert refused["ok"] is False and "doesn't have that scene" in refused["error"]
    assert api.try_lamp("Desk lamp", "candlelight 40%")["ok"] is True
    assert [t for t in network.told if t[1] == "setPilot"] == [
        ("10.0.0.1", "setPilot", {"dimming": 40, "sceneId": 29, "speed": 100, "state": True})
    ]


def test_a_lamp_goes_back_to_its_scene_white_or_colour():
    from abdoh.lights import _as_it_was

    # A real WiZ bulb in the app's "Warm white" preset reports the scene and a temp
    real = {"mac": "444f8eaf098a", "state": True, "sceneId": 11, "temp": 2700, "dimming": 100}
    assert _as_it_was(real) == {"state": True, "dimming": 100, "sceneId": 11}
    white = {"state": True, "sceneId": 0, "temp": 4000, "dimming": 80}
    assert _as_it_was(white) == {"state": True, "dimming": 80, "temp": 4000}
    blue = {"state": True, "r": 0, "g": 0, "b": 255, "dimming": 50}
    assert _as_it_was(blue) == {"state": True, "dimming": 50, "r": 0, "g": 0, "b": 255}
    assert _as_it_was({"state": False}) == {"state": False}


def test_setting_one_lamp_or_all(tmp_path):
    network = Network({"aa": "10.0.0.1", "bb": "10.0.0.2"})
    lamps = lamps_on(tmp_path, network)
    lamps.find_new()
    lamps.rename("aa", "Desk lamp")
    network.told.clear()
    assert lamps.set("desk", "red") == ["Desk lamp"]
    assert network.told == [("10.0.0.1", "setPilot", {"r": 255, "g": 0, "b": 0, "state": True})]
    network.told.clear()
    assert lamps.set("all", "off") == ["Desk lamp", "Lamp 2"]
    assert {ip for ip, _, _ in network.told} == {"10.0.0.1", "10.0.0.2"}
    with pytest.raises(ActionError, match="called kitchen"):
        lamps.set("kitchen", "on")


def test_a_lamp_that_moved_is_found_again(tmp_path):
    network = Network({"aa": "10.0.0.1"})
    lamps = lamps_on(tmp_path, network)
    lamps.find_new()
    network.lamps["aa"] = "10.0.0.9"  # it moved, and nobody looked for lamps since
    lamps.set("lamp", "on")
    assert network.told[-1] == ("10.0.0.9", "setPilot", {"state": True})
    assert lamps.all()[0].ip == "10.0.0.9"


def test_a_lamp_that_is_switched_off_at_the_wall_says_so(tmp_path):
    network = Network({"aa": "10.0.0.1"})
    lamps = lamps_on(tmp_path, network)
    lamps.find_new()
    network.silent.add("10.0.0.1")
    with pytest.raises(ActionError, match="didn't answer"):
        lamps.set("lamp", "on")


def test_no_lamps_yet(tmp_path):
    with pytest.raises(ActionError, match="no lamps yet"):
        lamps_on(tmp_path, Network({})).set("all", "on")


# ----- by voice, in commands and modes, and from Claude -----


def test_a_sentence_that_mentions_the_lamp_is_left_for_claude(tmp_path):
    computer = FakeComputer()
    network = Network({"aa": "10.0.0.1"})
    computer.lamps = lamps_on(tmp_path, network)
    computer.lamps.find_new()
    skills = LocalSkills(computer)
    network.told.clear()
    assert skills.handle("the lamp is too bright in the ocean film", "") is None
    assert skills.handle("lamp party fast", "") == Done("Lamp: party fast.")
    assert network.told == [("10.0.0.1", "setPilot", {"sceneId": 4, "speed": 160, "state": True})]


@pytest.fixture
def home(tmp_path):
    network = Network({"aa": "10.0.0.1", "bb": "10.0.0.2"})
    computer = FakeComputer()
    computer.lamps = lamps_on(tmp_path, network)
    computer.lamps.find_new()
    computer.lamps.rename("aa", "Desk lamp")
    network.told.clear()
    return LocalSkills(computer), network


@pytest.mark.parametrize(
    "said, ips, params",
    [
        ("turn off the lamp", {"10.0.0.1", "10.0.0.2"}, {"state": False}),
        ("lights on", {"10.0.0.1", "10.0.0.2"}, {"state": True}),
        ("turn the desk lamp blue", {"10.0.0.1"}, {"r": 0, "g": 0, "b": 255, "state": True}),
        ("dim the lights to 30", {"10.0.0.1", "10.0.0.2"}, {"dimming": 30, "state": True}),
        ("make the light warm", {"10.0.0.1", "10.0.0.2"}, {"temp": 2700, "state": True}),
        ("desk lamp 50 percent", {"10.0.0.1"}, {"dimming": 50, "state": True}),
    ],
)
def test_lamps_by_voice(home, said, ips, params):
    skills, network = home
    reply = skills.handle(said, said)
    assert isinstance(reply, Done)
    assert {ip for ip, _, _ in network.told} == ips
    assert all(p == params for _, _, p in network.told)


def test_questions_about_lamps_are_left_for_claude(home):
    skills, network = home
    assert skills.handle("what colour is the lamp") is None
    assert network.told == []


def test_without_lamps_lights_are_left_for_claude():
    skills = LocalSkills(FakeComputer())
    assert skills.handle("turn off the lights") is None


def test_night_light_and_light_mode_are_not_lamps(home):
    skills, network = home
    themes = []
    skills.computer.set_dark_mode = themes.append
    skills.handle("switch to light mode")
    assert themes == [False] and network.told == []


def test_the_lamp_action(home):
    skills, network = home
    system_action("lamp", "desk lamp | warm white 60%", skills.computer)
    assert network.told == [("10.0.0.1", "setPilot", {"dimming": 60, "temp": 2700, "state": True})]
    network.told.clear()
    claude_action("lamp", "all | off", skills.computer)
    assert len(network.told) == 2
    with pytest.raises(ActionError, match="aren't available"):
        system_action("lamp", "on", FakeComputer())
