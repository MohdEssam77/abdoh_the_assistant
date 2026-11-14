"""Build Abdoh as a Windows app: dist/Abdoh/Abdoh.exe (one folder, no console window).

Needs PyInstaller:  pip install -e .[build]
Bundles the example files and whatever models are in models/ (openWakeWord feature models, your
hey_abdoh.onnx, the Vosk fallback). Whisper's model still downloads on the first start.
Usage: python scripts/build_app.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLED_MODELS = ["openwakeword", "hey_abdoh.onnx", "vosk-model-small-en-us-0.15"]
# Packages with data files or native libraries PyInstaller doesn't find on its own.
COLLECT = ["faster_whisper", "ctranslate2", "onnxruntime", "vosk", "_sounddevice_data", "pystray"]
HIDDEN = ["pyttsx3.drivers", "pyttsx3.drivers.sapi5", "comtypes.stream"]


def main() -> int:
    import PyInstaller.__main__

    sys.path.insert(0, str(ROOT / "src"))
    from abdoh.shortcut import make_icon

    build = ROOT / "build"
    icon = make_icon(build / "abdoh.ico")
    sep = ";" if sys.platform == "win32" else ":"
    data = [(ROOT / "config.example.yaml", "."), (ROOT / "commands.example.yaml", ".")]
    for name in BUNDLED_MODELS:
        path = ROOT / "models" / name
        if path.exists():
            data.append((path, f"models/{name}" if path.is_dir() else "models"))
        else:
            print(f"Not bundled (not found): models/{name}")
    args = [
        str(ROOT / "scripts" / "abdoh_app.py"),
        "--name=Abdoh",
        "--windowed",
        "--onedir",
        "--noconfirm",
        f"--icon={icon}",
        f"--paths={ROOT / 'src'}",
        f"--distpath={ROOT / 'dist'}",
        f"--workpath={build}",
        f"--specpath={build}",
    ]
    args += [f"--collect-all={pkg}" for pkg in COLLECT]
    args += [f"--hidden-import={mod}" for mod in HIDDEN]
    args += [f"--add-data={src}{sep}{dest}" for src, dest in data]
    PyInstaller.__main__.run(args)
    print(f"Built {ROOT / 'dist' / 'Abdoh' / 'Abdoh.exe'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
