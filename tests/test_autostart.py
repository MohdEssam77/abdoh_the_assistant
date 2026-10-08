from pathlib import PurePosixPath as Path

from abdoh.autostart import RUN_ARGS, plist_text, unit_text, windows_command


def test_windows_command_runs_minimized():
    cmd = windows_command()
    assert cmd.endswith("-m abdoh run --minimized")


def test_plist_runs_at_load_and_restarts_only_on_crash():
    text = plist_text("/usr/bin/python3", Path("/home/me/abdoh"))
    assert "<key>RunAtLoad</key>\n  <true/>" in text
    assert "<key>SuccessfulExit</key>\n    <false/>" in text
    for arg in ["/usr/bin/python3", *RUN_ARGS]:
        assert f"<string>{arg}</string>" in text
    assert "<string>/home/me/abdoh</string>" in text


def test_systemd_unit():
    text = unit_text("/usr/bin/python3", Path("/home/me/abdoh"))
    assert "ExecStart=/usr/bin/python3 -m abdoh run --minimized" in text
    assert "WantedBy=default.target" in text
    assert "Restart=on-failure" in text
