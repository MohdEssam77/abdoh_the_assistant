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
    }


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
    assert publish["with"]["files"] == f"dist/{ASSET}"
