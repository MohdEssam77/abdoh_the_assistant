"""Build Abdoh as a Windows app: dist/Abdoh/Abdoh.exe (one folder, no console window).

Needs PyInstaller:  pip install -e .[build]
Bundles the example files and the models in models/ (openWakeWord feature models, the trained
wake word, and the Parakeet speech model, so nothing downloads on the first start). Run
scripts/download_models.py first.
Usage: python scripts/build_app.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLED_MODELS = [
    "openwakeword",
    "hey_abdoh.onnx",
    "parakeet-tdt-0.6b-v3",  # speech recognition: no download on the first start
    "piper/en_US-lessac-medium.onnx",  # the natural English voice (others download when needed)
    "piper/en_US-lessac-medium.onnx.json",
]
# Packages with data files or native libraries PyInstaller doesn't find on its own.
COLLECT = [
    "faster_whisper",
    "ctranslate2",
    "onnxruntime",
    "_sounddevice_data",
    "pystray",
    "webview",
    "onnx_asr",
    "livekit",  # the echo canceller: livekit/rtc/resources/livekit_ffi.dll
    "piper",  # the natural voice: espeakbridge.pyd and espeak-ng-data
]
HIDDEN = ["pyttsx3.drivers", "pyttsx3.drivers.sapi5", "comtypes.stream"]


def main() -> int:
    import PyInstaller.__main__

    sys.path.insert(0, str(ROOT / "src"))
    from abdoh.shortcut import make_icon

    build = ROOT / "build"
    icon = make_icon(build / "abdoh.ico")
    sep = ";" if sys.platform == "win32" else ":"
    data = [
        (ROOT / "config.example.yaml", "."),
        (ROOT / "commands.example.yaml", "."),
        (ROOT / "src" / "abdoh" / "ui" / "web", "abdoh/ui/web"),  # the app window's page
        (ROOT / "src" / "abdoh" / "phone" / "web", "abdoh/phone/web"),  # the phone's page
    ]
    for name in BUNDLED_MODELS:
        path = ROOT / "models" / name
        if path.exists():
            data.append(
                (path, f"models/{name}" if path.is_dir() else str(Path("models", name).parent))
            )
        elif name == "hey_abdoh.onnx" and (ROOT / "assets" / name).exists():
            data.append((ROOT / "assets" / name, "models"))  # the one kept in the repo
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
