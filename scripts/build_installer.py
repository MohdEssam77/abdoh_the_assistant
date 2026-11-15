"""Build Abdoh's Windows installer: dist/Abdoh-Setup.exe.

Builds the app with PyInstaller (scripts/build_app.py), then packs it with Inno Setup 6
(installer/abdoh.iss). Needs Inno Setup 6 (https://jrsoftware.org/isdl.php); ISCC.exe is found
in its usual folders, on PATH, or in the ISCC environment variable.

Usage: python scripts/build_installer.py [--skip-app]   (--skip-app reuses dist/Abdoh)
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ISS = ROOT / "installer" / "abdoh.iss"
SETUP = ROOT / "dist" / "Abdoh-Setup.exe"


def iscc_candidates() -> list[Path]:
    folders = [
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs"),
    ]
    return [Path(folder) / "Inno Setup 6" / "ISCC.exe" for folder in folders]


def find_iscc(env=os.environ, which=shutil.which) -> Path | None:
    configured = env.get("ISCC")
    if configured and Path(configured).is_file():
        return Path(configured)
    on_path = which("iscc")
    if on_path:
        return Path(on_path)
    return next((p for p in iscc_candidates() if p.is_file()), None)


def app_version() -> str:
    sys.path.insert(0, str(ROOT / "src"))
    from abdoh import __version__

    return __version__


def check_tag(version: str, ref: str) -> None:
    """A release tag (v1.2.3) must match the app's version, or the update check gets confused."""
    if ref.startswith("v") and ref != f"v{version}":
        raise SystemExit(
            f"Tag {ref} doesn't match Abdoh's version {version} (src/abdoh/__init__.py)."
        )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    version = app_version()
    check_tag(version, os.environ.get("GITHUB_REF_NAME", ""))
    if "--skip-app" not in args:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_app.py")], check=True)
    iscc = find_iscc()
    if iscc is None:
        print("Inno Setup 6 wasn't found. Install it from https://jrsoftware.org/isdl.php")
        print("(or set the ISCC environment variable to ISCC.exe), then run this again.")
        return 1
    subprocess.run([str(iscc), f"/DAppVersion={version}", str(ISS)], check=True)
    print(f"Built {SETUP} (Abdoh {version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
