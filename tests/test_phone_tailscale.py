"""Tailscale for the phone (ABDOH_EPIC_10.md, 3.3) and Settings → Phone's API. Tailscale never
runs: a fake `run` and `popen` stand in for it."""

import json
import subprocess
from types import SimpleNamespace

from abdoh.config import load_config
from abdoh.events import Bus
from abdoh.phone.devices import Phones
from abdoh.phone.tailscale import NOT_RUNNING, TOO_SLOW, Tailscale, find
from abdoh.ui.api import AppApi, UiState

STATUS = {
    "BackendState": "Running",
    "Self": {"DNSName": "laptop.tail1234.ts.net.", "HostName": "laptop"},
    "CertDomains": ["laptop.tail1234.ts.net"],
}
SERVE = {
    "TCP": {"443": {"HTTPS": True}},
    "Web": {"laptop.tail1234.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:47811"}}}},
}


class FakeRun:
    def __init__(self, status=STATUS, serve=SERVE, fail=None):
        self.status, self.serve, self.fail = status, serve, fail
        self.calls = []

    def __call__(self, args, timeout=10):
        self.calls.append(args[1:])
        if self.fail:
            raise self.fail
        if args[1:3] == ["status", "--json"]:
            out = self.status if isinstance(self.status, str) else json.dumps(self.status)
        elif args[1:4] == ["serve", "status", "--json"]:
            out = json.dumps(self.serve)
        else:
            out = ""
        return subprocess.CompletedProcess(args, 0, out, "")


class FakeProc:
    def __init__(self, lines, code=0, hang=False):
        self.stdout = iter(lines) if not hang else _Hang(lines)
        self.code = code
        self.killed = False

    def kill(self):
        self.killed = True
        if isinstance(self.stdout, _Hang):
            self.stdout.stop = True

    def wait(self, timeout=None):
        return self.code


class _Hang:
    """Output that stops coming (tailscale waiting for you), until the process is killed."""

    def __init__(self, lines):
        self.lines, self.stop = list(lines), False

    def __iter__(self):
        yield from self.lines
        import time

        while not self.stop:
            time.sleep(0.01)


def tailscale(run=None, proc=None, exe="tailscale.exe"):
    started = []

    def popen(args, **kw):
        started.append((args, kw))
        return proc

    t = Tailscale(exe=exe, run=run or FakeRun(), popen=popen, find=lambda: None)
    t.started = started
    return t


def test_finding_tailscale(tmp_path, monkeypatch):
    assert find(which=lambda name: r"C:\bin\tailscale.exe") == r"C:\bin\tailscale.exe"
    exe = tmp_path / "Tailscale" / "tailscale.exe"
    exe.parent.mkdir()
    exe.write_text("")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    assert find(which=lambda name: None) == str(exe)
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "none"))
    monkeypatch.delenv("ProgramW6432", raising=False)
    assert find(which=lambda name: None, is_file=lambda path: False) is None


def test_not_installed():
    t = Tailscale(exe=None, run=FakeRun(), find=lambda: None)
    assert t.state(47811)["installed"] is False
    assert t.share(47811)["ok"] is False
    assert t.unshare() is False


def test_ready_and_shared():
    state = tailscale().state(47811)
    assert state == READY
    assert tailscale().state(47900)["shared"] is False  # another port: not Abdoh's


def test_signed_out_off_and_not_running():
    out = tailscale(run=FakeRun({"BackendState": "NeedsLogin"})).state(47811)
    assert out["signed_in"] is False and out["error"] == NOT_RUNNING and out["address"] == ""
    off = tailscale(run=FakeRun({**STATUS, "BackendState": "Stopped"})).state(47811)
    assert off["signed_in"] is True and off["running"] is False and "off" in off["error"]
    broken = tailscale(run=FakeRun("failed to connect to local tailscaled")).state(47811)
    assert broken["installed"] and broken["error"] == NOT_RUNNING
    slow = tailscale(run=FakeRun(fail=subprocess.TimeoutExpired("tailscale", 10))).state(47811)
    assert slow["error"] == TOO_SLOW
    no_https = tailscale(run=FakeRun({**STATUS, "CertDomains": None})).state(47811)
    assert no_https["https"] is False


def test_sharing_the_page():
    t = tailscale(proc=FakeProc(["Available within your tailnet:\n", "https://laptop/\n"]))
    assert t.share(47811) == {"ok": True}
    args, kw = t.started[0]
    assert args[1:] == ["serve", "--bg", "--https=443", "http://127.0.0.1:47811"]
    assert kw["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console window


def test_sharing_needs_https_allowed_first():
    lines = ["Serve is not enabled on your tailnet.\n", "To enable, visit:\n",
             "         https://login.tailscale.com/f/serve?node=abc123\n"]  # fmt: skip
    proc = FakeProc(lines, hang=True)
    result = tailscale(proc=proc).share(47811)
    assert result == {"ok": False, "link": "https://login.tailscale.com/f/serve?node=abc123"}
    assert proc.killed  # not left waiting


def test_sharing_fails_or_hangs():
    failed = tailscale(proc=FakeProc(["error: something broke\n"], code=1)).share(47811)
    assert failed == {"ok": False, "error": "Tailscale said: error: something broke"}
    proc = FakeProc([], hang=True)
    assert tailscale(proc=proc).share(47811, wait=0.1) == {"ok": False, "error": TOO_SLOW}
    assert proc.killed


def test_unsharing_only_abdohs():
    run = FakeRun()
    assert tailscale(run=run).unshare() is True
    assert run.calls == [["serve", "--https=443", "off"]]


# ----- Settings → Phone -----


class FakeTailscale:
    def __init__(self, state):
        self._state = state
        self.shares = 0

    def state(self, port):
        return dict(self._state)

    def share(self, port):
        self.shares += 1
        return {"ok": True}

    def unshare(self):
        return True


READY = {"installed": True, "running": True, "signed_in": True, "https": True,
         "address": "https://laptop.tail1234.ts.net", "shared": True, "error": ""}  # fmt: skip


def make_api(tmp_path, ts_state=READY, running=True):
    cfg = load_config(tmp_path)
    phones = Phones(tmp_path / "phones.json")
    api = AppApi(Bus(), UiState(), cfg, check_for_update=lambda force: None)
    service = SimpleNamespace(phones=phones) if running else None
    api._attach(SimpleNamespace(phone=service, phone_error="Port taken"))
    api._tailscale_cli = FakeTailscale(ts_state)
    return api, phones


def test_the_cards_state(tmp_path):
    api, phones = make_api(tmp_path)
    state = api.phone_state()
    assert state["on"] is False and state["error"] == ""  # off: no error shown
    assert state["tailscale"]["shared"] is True and state["phones"] == []
    assert state["download"].startswith("https://tailscale.com")


def test_pairing_a_phone_from_the_card(tmp_path):
    api, phones = make_api(tmp_path)
    result = api.phone_pair()
    assert result["ok"] and result["url"].startswith("https://laptop.tail1234.ts.net/#pair=")
    assert result["qr"].startswith("<svg") and result["minutes"] == 30
    code = result["url"].split("#pair=")[1]
    key = phones.pair(code, "iPhone")
    assert key and api.phone_state()["phones"][0]["name"] == "iPhone"
    removed = api.phone_remove(api.phone_state()["phones"][0]["id"])
    assert removed == {"ok": True, "phones": []}


def test_no_pairing_before_its_ready(tmp_path):
    api, _ = make_api(tmp_path, running=False)
    assert "Turn on" in api.phone_pair()["error"]
    api, _ = make_api(tmp_path, ts_state={**READY, "shared": False})
    assert "Tailscale steps" in api.phone_pair()["error"]


def test_phones_are_listed_while_the_page_is_off(tmp_path):
    first = Phones(tmp_path / "phones.json")
    first.pair(first.new_code(), "iPhone")
    api, _ = make_api(tmp_path, running=False)
    assert [p["name"] for p in api.phone_state()["phones"]] == ["iPhone"]


def test_sharing_from_the_card(tmp_path):
    api, _ = make_api(tmp_path)
    result = api.phone_share()
    assert result["ok"] and result["state"]["tailscale"]["shared"]
    assert api.phone_unshare() == {"ok": True}
