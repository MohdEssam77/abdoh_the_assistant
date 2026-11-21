from pathlib import Path

import pytest

from abdoh.claude import setup
from abdoh.claude.brain import NOT_CONNECTED, BrainError
from abdoh.claude.setup import (
    NEW_CONSOLE,
    SetupError,
    check_connection,
    claude_state,
    install_claude_code,
    set_api_key,
    sign_in,
    sign_out,
)
from abdoh.config import ClaudeConfig, Config, load_config
from abdoh.events import Bus
from abdoh.ui.api import AppApi, UiState

EXE = Path("C:/Users/me/.local/bin/claude.exe")


def state(cfg=None, exe=EXE, info=None):
    return claude_state(cfg or Config(), find=lambda configured: exe, status=lambda e: info)


PRO = {"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "pro"}


def test_nothing_connected():
    s = state(exe=None)
    assert (s["installed"], s["connected"], s["using"]) == (False, False, None)
    assert s["summary"] == "Not connected."


def test_signed_in_with_a_plan():
    s = state(info=PRO)
    assert s["connected"] is True and s["using"] == "code" and s["plan"] == "pro"
    assert s["summary"] == "Connected with your Pro plan."


def test_installed_but_not_signed_in():
    s = state(info={"loggedIn": False})
    assert s["installed"] is True and s["connected"] is False
    assert "not signed in" in s["summary"]


def test_signed_in_with_a_console_account():
    s = state(info={"loggedIn": True, "authMethod": "console"})
    assert s["summary"] == "Connected with your Claude Console account."


def test_api_key_when_claude_code_is_missing():
    s = state(Config(anthropic_api_key="sk-ant-x"), exe=None)
    assert s["using"] == "api" and s["connected"] is True and s["has_api_key"] is True
    assert "sk-ant" not in str(s)  # never shown


def test_backend_choices():
    assert state(Config(claude=ClaudeConfig(backend="off")), info=PRO)["summary"] == (
        "Claude is turned off."
    )
    api_only = Config(claude=ClaudeConfig(backend="api"), anthropic_api_key="sk-ant-x")
    assert state(api_only, info=PRO)["using"] == "api"


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))


def test_install_runs_anthropics_installer_in_a_visible_window():
    popen = Recorder()
    install_claude_code(popen, platform="win32")
    ((args, kwargs),) = popen.calls
    assert args[0] == "powershell.exe" and "-NoExit" in args
    assert "irm https://claude.ai/install.ps1 | iex" in args[-1]
    assert kwargs["creationflags"] == NEW_CONSOLE
    with pytest.raises(SetupError, match="code.claude.com"):
        install_claude_code(popen, platform="linux")


def test_sign_in_opens_claude_codes_own_sign_in(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    popen = Recorder()
    sign_in(EXE, popen)
    ((args, kwargs),) = popen.calls
    assert "& $env:ABDOH_CLAUDE auth login" in args[-1]
    assert kwargs["env"]["ABDOH_CLAUDE"] == str(EXE)
    assert "ANTHROPIC_API_KEY" not in kwargs["env"]  # sign in with the account, not a key
    assert kwargs["creationflags"] == NEW_CONSOLE


def test_sign_out():
    run = Recorder()
    sign_out(EXE, run)
    assert run.calls[0][0] == [str(EXE), "auth", "logout"]


def test_api_key_is_checked_saved_and_removed(app_dir):
    cfg = load_config(app_dir)
    with pytest.raises(SetupError, match="sk-ant-"):
        set_api_key(cfg, "hello")
    set_api_key(cfg, "  sk-ant-abc123  ")
    assert load_config(app_dir).anthropic_api_key == "sk-ant-abc123"
    set_api_key(cfg, "")
    assert load_config(app_dir).anthropic_api_key is None


class FakeBrain:
    name = "Claude Code"

    def __init__(self, reply=None, error=None):
        self.reply, self.error = reply, error

    def stream(self, prompt, image=None):
        if self.error:
            raise self.error
        yield self.reply

    def close(self):
        self.closed = True


def test_check_connection():
    assert check_connection(Config(), make=lambda cfg: None) == {
        "ok": False,
        "error": NOT_CONNECTED,
    }
    brain = FakeBrain(" OK ")
    ok = check_connection(Config(), make=lambda cfg: brain)
    assert ok == {"ok": True, "reply": "OK", "via": "Claude Code"}
    assert brain.closed  # no Claude Code process left running after the test
    limit = check_connection(Config(), make=lambda cfg: FakeBrain(error=BrainError("Limit.")))
    assert limit == {"ok": False, "error": "Limit."}


# ----- through the app -----


class FakeSetup:
    SetupError = setup.SetupError

    def __init__(self, exe=EXE, fail=False):
        self.exe = exe
        self.fail = fail
        self.done = []

    def find_claude_code(self, configured):
        return self.exe

    def claude_state(self, cfg):
        return {"connected": True, "summary": "Connected with your Pro plan."}

    def _do(self, name, *args):
        if self.fail:
            raise setup.SetupError(f"{name} failed")
        self.done.append((name, *args))

    def install_claude_code(self):
        self._do("install")

    def sign_in(self, exe):
        self._do("sign_in", exe)

    def sign_out(self, exe):
        self._do("sign_out", exe)

    def set_api_key(self, cfg, key):
        self._do("key", key)

    def check_connection(self, cfg):
        return {"ok": True, "reply": "OK", "via": "Claude Code"}


def requests(bus):
    out = []
    while (message := bus.next_request(timeout=0)) is not None:
        out.append(message)
    return out


def app(app_dir, **kwargs):
    bus = Bus()
    fake = FakeSetup(**kwargs)
    return AppApi(bus, UiState(), load_config(app_dir), claude_setup=fake), bus, fake


def test_app_connects_claude(app_dir):
    api, bus, fake = app(app_dir)
    assert api.claude_status()["summary"] == "Connected with your Pro plan."
    assert api.install_claude() == {"ok": True}
    assert api.claude_sign_in() == {"ok": True}
    assert api.claude_test()["reply"] == "OK"
    assert requests(bus) == []  # nothing changed yet
    assert api.claude_sign_out() == {"ok": True}
    assert api.set_api_key("sk-ant-x") == {"ok": True}
    api.refresh_claude()
    assert requests(bus) == [("settings_changed", None)] * 3  # Krekos reconnects each time
    assert [d[0] for d in fake.done] == ["install", "sign_in", "sign_out", "key"]


def test_app_explains_problems(app_dir):
    api, bus, _ = app(app_dir, exe=None)
    assert api.claude_sign_in() == {"ok": False, "error": "Install Claude Code first."}
    assert api.claude_sign_out()["ok"] is False
    failing, bus, _ = app(app_dir, fail=True)
    assert failing.install_claude() == {"ok": False, "error": "install failed"}
    assert failing.set_api_key("x") == {"ok": False, "error": "key failed"}
    assert requests(bus) == []


# ----- your claude.ai connectors -----


def test_connectors_show_which_ones_claude_may_use():
    from abdoh.claude.setup import connectors

    cfg = Config()
    found = [{"name": "Gmail", "status": "connected"}, {"name": "Notion", "status": "failed"}]
    state = connectors(cfg, find=lambda path: Path("claude.exe"), listing=lambda exe: found)
    assert state["available"] and state["url"].startswith("https://claude.ai/")
    assert state["connectors"] == [
        {"name": "Gmail", "status": "connected", "on": True},
        {"name": "Notion", "status": "failed", "on": False},
        {"name": "Google Calendar", "status": "not connected", "on": True},  # turn it on there
    ]


def test_connectors_need_claude_code():
    from abdoh.claude.setup import connectors

    state = connectors(Config(), find=lambda path: None, listing=lambda exe: [])
    assert state["available"] is False and "Claude Code" in state["reason"]
