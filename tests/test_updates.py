import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from abdoh import __version__, autostart
from abdoh.config import load_config
from abdoh.events import Bus
from abdoh.ui.api import AppApi, UiState
from abdoh.updates import ASSET, check_for_update, is_newer, latest_release, version_tuple

ROOT = Path(__file__).resolve().parents[1]


def release(tag="v0.4.0", asset=True, **extra):
    data = {
        "tag_name": tag,
        "html_url": f"https://github.com/x/y/releases/tag/{tag}",
        "assets": [{"name": ASSET, "browser_download_url": f"https://dl/{tag}/{ASSET}"}]
        if asset
        else [],
    }
    return {**data, **extra}


def test_versions():
    assert version_tuple("v0.3.1") == (0, 3, 1)
    assert version_tuple("1.2") == (1, 2)
    assert version_tuple("nightly") == ()
    assert is_newer("v0.4.0", "0.3.0")
    assert is_newer("0.3.10", "0.3.9")
    assert is_newer("1.0", "0.9.9")
    assert not is_newer("0.3.0", "0.3.0")
    assert not is_newer("0.3", "0.3.0")
    assert not is_newer("garbage", "0.3.0")


def test_latest_release_with_the_installer():
    assert latest_release(lambda url: release()) == {
        "version": "0.4.0",
        "url": "https://github.com/x/y/releases/tag/v0.4.0",
        "download": f"https://dl/v0.4.0/{ASSET}",
        "size": 0,
    }
    data = release()
    data["assets"][0].update(size=12, digest="sha256:ABC123")
    found = latest_release(lambda url: data)
    assert (found["size"], found["sha256"]) == (12, "abc123")  # what the download must be


def test_latest_release_without_the_installer_links_the_page():
    assert latest_release(lambda url: release(asset=False))["download"].endswith("/v0.4.0")


@pytest.mark.parametrize(
    "data", [release(draft=True), release(prerelease=True), release(tag="nightly"), {}]
)
def test_unusable_releases_are_ignored(data):
    assert latest_release(lambda url: data) is None


def test_offline_or_private_repo_is_quiet():
    def fail(url):
        raise OSError("HTTP Error 404: Not Found")

    assert latest_release(fail) is None


def test_check_asks_at_most_once_a_day(tmp_path):
    asked = []
    clock = [1000.0]

    def fetch(url):
        asked.append(url)
        return release("v9.0.0")

    state = tmp_path / "update.json"
    first = check_for_update("0.3.0", fetch, state, now=lambda: clock[0])
    assert first["version"] == "9.0.0" and len(asked) == 1
    clock[0] += 3600
    assert check_for_update("0.3.0", fetch, state, now=lambda: clock[0])["version"] == "9.0.0"
    assert len(asked) == 1  # remembered
    check_for_update("0.3.0", fetch, state, now=lambda: clock[0], force=True)
    assert len(asked) == 2
    clock[0] += 25 * 3600
    check_for_update("0.3.0", fetch, state, now=lambda: clock[0])
    assert len(asked) == 3


def test_no_update_when_current_or_broken_state(tmp_path):
    state = tmp_path / "update.json"
    state.write_text("{not json")
    assert check_for_update("9.0.0", lambda url: release("v9.0.0"), state) is None
    assert json.loads(state.read_text())["latest"]["version"] == "9.0.0"


# ----- in the app -----


def test_app_update_check(app_dir):
    calls = []

    def check(force=False):
        calls.append(force)
        return {"version": "9.0.0", "url": "https://page", "download": "https://dl"}

    cfg = load_config(app_dir)
    api = AppApi(Bus(), UiState(), cfg, check_for_update=check)
    result = api.check_update()
    assert result == {
        "available": True,
        "current": __version__,
        "version": "9.0.0",
        "url": "https://page",
        "download": "https://dl",
        "installing": {"state": "idle"},
    }
    api.save_settings({"check_updates": False})
    assert api.check_update() == {"available": False, "current": __version__}
    assert api.check_update(True)["available"] is True  # "Check now" still works
    assert calls == [False, True]


def test_app_update_check_when_up_to_date(app_dir):
    api = AppApi(Bus(), UiState(), load_config(app_dir), check_for_update=lambda force: None)
    assert api.check_update() == {"available": False, "current": __version__}


# ----- the installer and the release workflow -----


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_tag_must_match_the_version():
    build = load_script("build_installer")
    build.check_tag("0.3.0", "v0.3.0")
    build.check_tag("0.3.0", "main")  # not a release
    with pytest.raises(SystemExit, match="doesn't match"):
        build.check_tag("0.3.0", "v0.3.1")


def test_finding_inno_setup(tmp_path):
    build = load_script("build_installer")
    iscc = tmp_path / "ISCC.exe"
    iscc.write_text("")
    assert build.find_iscc({"ISCC": str(iscc)}, which=lambda name: None) == iscc
    assert build.find_iscc({}, which=lambda name: "C:/tools/iscc.exe") == Path("C:/tools/iscc.exe")


def test_installer_is_per_user_and_matches_start_at_sign_in():
    iss = (ROOT / "installer" / "abdoh.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in iss
    assert "OutputBaseFilename=Abdoh-Setup" in iss and f"{ASSET}" == "Abdoh-Setup.exe"
    assert autostart.RUN_KEY in iss and f'ValueName: "{autostart.TASK_NAME}"' in iss
    assert '"run --minimized"' not in iss and "run --minimized" in iss


def test_release_workflow_builds_and_publishes():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text())
    triggers = workflow.get("on") or workflow.get(True)  # YAML 1.1 reads "on" as true
    assert triggers["push"]["tags"] == ["v*"]
    steps = workflow["jobs"]["windows"]["steps"]
    runs = " ".join(str(s.get("run", "")) for s in steps)
    assert "pytest" in runs and "build_installer.py" in runs and "download_models.py" in runs
    publish = next(s for s in steps if "action-gh-release" in str(s.get("uses", "")))
    files = publish["with"]["files"].split()
    assert files[0] == f"dist/{ASSET}"
    # Older versions' update checks look for their own installer's name: the same file.
    assert files[1:] == ["dist/Krekos-Setup.exe", "dist/Xanthos-Setup.exe"]
    assert f"Copy-Item dist/{ASSET} dist/Krekos-Setup.exe" in runs
    assert f"Copy-Item dist/{ASSET} dist/Xanthos-Setup.exe" in runs
    assert "WAKE_WORD_URL" not in str(steps)  # the model is in the repo, not downloaded


# ----- installing it from the app ("Install now") -----


class Response:
    def __init__(self, data: bytes):
        self.data, self.at, self.headers = data, 0, {"Content-Length": str(len(data))}

    def read(self, size):
        chunk = self.data[self.at : self.at + size]
        self.at += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def opener(data):
    asked = []

    def open_(request, timeout=0):
        asked.append(request.full_url)
        return Response(data)

    open_.asked = asked
    return open_


INSTALLER = b"MZ" + b"x" * 3_000_000  # a few chunks
SHA = __import__("hashlib").sha256(INSTALLER).hexdigest()


def test_the_installer_is_downloaded_and_checked(tmp_path):
    from abdoh.updates import download

    shown = []
    target = tmp_path / "Abdoh-Setup-9.0.0.exe"
    got = download("https://dl/x.exe", target, len(INSTALLER), SHA, shown.append, opener(INSTALLER))
    assert got == target and target.read_bytes() == INSTALLER
    assert shown[-1] == 100 and shown == sorted(shown) and not (tmp_path / "x.part").exists()
    again = opener(INSTALLER)
    download("https://dl/x.exe", target, len(INSTALLER), SHA, opener=again)
    assert again.asked == []  # already here and right: not downloaded twice


@pytest.mark.parametrize("size, sha", [(5, SHA), (len(INSTALLER), "0" * 64)])
def test_a_download_that_doesnt_match_is_thrown_away(tmp_path, size, sha):
    from abdoh.updates import BROKEN, UpdateError, download

    target = tmp_path / "Abdoh-Setup.exe"
    with pytest.raises(UpdateError, match=BROKEN):
        download("https://dl/x.exe", target, size, sha, opener=opener(INSTALLER))
    assert not target.exists() and list(tmp_path.iterdir()) == []


def test_the_helper_installs_quietly_after_abdoh_closes_and_starts_it(tmp_path):
    from abdoh.updates import helper_script

    script = helper_script(tmp_path / "Abdoh-Setup-9.0.0.exe", tmp_path, exe=tmp_path / "Abdoh.exe")
    text = script.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line and not line.startswith(("@", "rem"))]
    assert lines[0].startswith("ping")  # Abdoh closes first
    assert "/wait" in lines[1] and "/VERYSILENT" in lines[1] and "/SUPPRESSMSGBOXES" in lines[1]
    assert str(tmp_path / "Abdoh-Setup-9.0.0.exe") in lines[1] and "/LOG=" in lines[1]
    assert str(tmp_path / "Abdoh.exe") in lines[2] and "run --show" in lines[2]  # then again


def test_the_helper_outlives_abdoh():
    from abdoh.updates import BREAKAWAY, launch

    calls = []

    def popen(args, creationflags=0, **kw):
        calls.append(creationflags)
        if len(calls) == 1 and BREAKAWAY:
            raise OSError("access denied")  # a job that doesn't allow breaking away

    launch(Path("x.cmd"), popen)
    assert calls[-1] and (len(calls) == 2 or not BREAKAWAY)


def test_installing_downloads_hands_over_and_closes(tmp_path):
    from abdoh.updates import Updater

    statuses, started, ready = [], [], []

    def fetch(url, target, size=0, sha256="", on_progress=lambda p: None):
        on_progress(50)
        on_progress(100)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"MZ")
        return target

    updater = Updater(statuses.append, lambda: ready.append(True), tmp_path, frozen=True,
                      fetch=fetch, start=started.append)  # fmt: skip
    first = updater.install({"version": "9.0.0", "download": "https://dl/Abdoh-Setup.exe"})
    assert first["state"] == "downloading"
    updater._thread.join(5)
    assert [s["state"] for s in statuses][-1] == "installing" and ready == [True]
    assert started and started[0].name == "install-update.cmd"
    assert any(s.get("percent") == 50 for s in statuses)


def test_installing_from_source_or_without_an_installer_says_why(tmp_path):
    from abdoh.updates import FROM_SOURCE, NOT_AN_INSTALLER, Updater

    release = {"version": "9.0.0", "download": "https://dl/Abdoh-Setup.exe"}
    assert Updater(folder=tmp_path, frozen=False).install(release)["error"] == FROM_SOURCE
    page = {"version": "9.0.0", "download": "https://github.com/x/y/releases/tag/v9.0.0"}
    assert Updater(folder=tmp_path, frozen=True).install(page)["error"] == NOT_AN_INSTALLER


def test_a_failed_download_is_said_and_can_be_tried_again(tmp_path):
    from abdoh.updates import BROKEN, UpdateError, Updater

    tries = []

    def fetch(*args, **kwargs):
        tries.append(1)
        raise UpdateError(BROKEN)

    statuses = []
    updater = Updater(statuses.append, folder=tmp_path, frozen=True, fetch=fetch)
    release = {"version": "9.0.0", "download": "https://dl/Abdoh-Setup.exe"}
    updater.install(release)
    updater._thread.join(5)
    assert statuses[-1] == {"state": "failed", "version": "9.0.0", "error": BROKEN}
    updater.install(release)
    updater._thread.join(5)
    assert len(tries) == 2


def test_the_window_installs_and_abdoh_closes(app_dir, monkeypatch):
    from abdoh.ui import api as module

    monkeypatch.setattr(module, "UPDATE_CLOSE_SECONDS", 0)
    bus = Bus()
    latest = {"version": "9.0.0", "download": "https://dl/Abdoh-Setup.exe", "url": "https://page"}
    api = AppApi(bus, UiState(), load_config(app_dir), check_for_update=lambda force: latest)
    job = api._update_job()
    job.frozen = True
    job._fetch = lambda url, target, **kw: target
    job._start = lambda script: None
    job.folder = app_dir / "update"
    assert api.install_update()["state"] == "downloading"
    job._thread.join(5)
    for _ in range(100):
        request = bus.next_request(timeout=0.05)
        if request == ("quit", None):
            break
    else:
        raise AssertionError("Abdoh didn't close for the installer")
    assert api.update_status()["state"] == "installing"
    api2 = AppApi(bus, UiState(), load_config(app_dir), check_for_update=lambda force: None)
    assert api2.install_update()["error"] == "You already have the latest version."
