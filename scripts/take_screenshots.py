"""Refresh the app screenshots on the download page (docs/*.png).

Renders the app's page with made-up demo data (index.html?demo) in headless Microsoft Edge, in
light and dark. No Abdoh, microphone or account needed. Usage: python scripts/take_screenshots.py
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "src" / "abdoh" / "ui" / "web" / "index.html"
SHOTS = {"app": "home", "modes": "modes"}  # docs/<name>-<theme>.png -> the app's page
EDGE = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]


def find_edge() -> str | None:
    found = next((str(p) for p in EDGE if p.is_file()), None)
    return found or shutil.which("msedge") or shutil.which("chromium") or shutil.which("chrome")


def main() -> int:
    edge = find_edge()
    if edge is None:
        print("Microsoft Edge (or Chrome) wasn't found.")
        return 1
    with tempfile.TemporaryDirectory() as profile:
        for name, page in SHOTS.items():
            for theme in ("light", "dark"):
                out = ROOT / "docs" / f"{name}-{theme}.png"
                url = f"{PAGE.as_uri()}?demo&page={page}&theme={theme}"
                subprocess.run(
                    [edge, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                     # no fade-in animations: the shot would catch the messages half-visible
                     "--force-prefers-reduced-motion",
                     f"--user-data-dir={profile}", "--force-device-scale-factor=2",
                     "--window-size=1100,690", "--virtual-time-budget=4000",
                     f"--screenshot={out}", url],
                    check=True, capture_output=True,
                )  # fmt: skip
                print(f"Saved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
