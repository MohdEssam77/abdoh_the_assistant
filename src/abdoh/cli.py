"""Command-line entry point: `python -m abdoh <command>`."""

import argparse
import logging
import os
import sys
import threading

from abdoh import __version__
from abdoh.config import Config, load_config, setup_logging


def cmd_say(cfg: Config, args: argparse.Namespace) -> int:
    from abdoh.speech.tts import make_speaker

    make_speaker(cfg.tts_rate).say(args.text)
    return 0


def cmd_calibrate(cfg: Config, args: argparse.Namespace) -> int:
    from abdoh.audio.listener import calibrate
    from abdoh.audio.mic import Microphone

    with Microphone() as mic:
        calibrate(mic, cfg.resolve(cfg.vosk_model), times=args.times)
    return 0


def cmd_listen_once(cfg: Config, args: argparse.Namespace) -> int:
    from abdoh.audio.listener import listen_for_request
    from abdoh.audio.mic import Microphone
    from abdoh.audio.stt import load_transcriber
    from abdoh.audio.vad import load_vad
    from abdoh.audio.wakeword import load_wake_engine
    from abdoh.speech.tts import make_speaker

    engine = load_wake_engine(cfg)
    print(f"Wake word: {engine.label}")
    transcriber = load_transcriber(cfg)
    transcriber.transcribe(b"\0\0" * 1600)  # load the model before listening
    with Microphone() as mic:
        print('Listening... say "Hey Abdoh" and a request.')
        speaker = make_speaker(cfg.tts_rate)
        text = listen_for_request(mic, engine, transcriber, speaker, cfg, vad=load_vad())
    print(text)
    return 0


def cmd_test_command(cfg: Config, args: argparse.Namespace) -> int:
    from abdoh.claude.brain import make_brain
    from abdoh.commands.registry import CommandRegistry
    from abdoh.computer import Computer
    from abdoh.router import Router

    registry = CommandRegistry(cfg.commands_path)
    if registry.error:
        print(f"Your commands file has an error: {registry.error}")
    router = Router(
        cfg,
        registry,
        brain=make_brain(cfg),
        on_thinking=lambda: print("Abdoh: (thinking...)"),
        computer=Computer(),
    )
    reply = router.handle(args.text)
    if isinstance(reply, str):
        print(f"Abdoh: {reply or '(done)'}")
    else:
        for sentence in reply:  # Claude's answer, as it arrives
            print(f"Abdoh: {sentence}", flush=True)
    return 0


def cmd_list_commands(cfg: Config, args: argparse.Namespace) -> int:
    from abdoh.commands.registry import CommandRegistry

    registry = CommandRegistry(cfg.commands_path)
    if registry.error:
        print(f"Your commands file has an error: {registry.error}")
    print(f"Commands from {registry.path}:")
    for c in registry.commands:
        print(f"  {c.name}: {', '.join(repr(t) for t in c.triggers)}")
    return 0


def cmd_run(cfg: Config, args: argparse.Namespace) -> int:
    from abdoh.daemon import Daemon
    from abdoh.events import Bus
    from abdoh.instance import InstanceLock, ask_running_instance_to_show
    from abdoh.power import keep_full_speed

    keep_full_speed()  # Windows slows down apps without a visible window; Abdoh lives there
    lock = InstanceLock()
    if not lock.acquire():
        shown = ask_running_instance_to_show()
        print("Abdoh is already running." + (" Showing its window." if shown else ""))
        return 0
    window = tray = None
    if not args.headless:
        window, tray = _make_ui(cfg, args)
    bus = window.bus if window else Bus(ui_attached=False)
    lock.serve(on_show=lambda: bus.emit("show"))
    restart = False
    try:
        if window is None:
            daemon = Daemon.create(cfg, bus)
            _start_hotkey(cfg, daemon)
            threading.Thread(target=daemon.serve_requests, daemon=True).start()
            print('Abdoh is listening. Say "Hey Abdoh" and a request. Press Ctrl+C to quit.')
            try:
                daemon.run()
            except KeyboardInterrupt:
                daemon.stop()
            return 0

        started: list[Daemon] = []

        def background() -> None:
            daemon = Daemon.create(cfg, bus)
            started.append(daemon)
            api = getattr(window, "api", None)
            if api is not None:
                api._attach(daemon)  # the app window's microphone level meter
            _start_hotkey(cfg, daemon)
            threading.Thread(target=daemon.serve_requests, daemon=True).start()
            daemon.run()

        threading.Thread(target=background, name="abdoh-daemon", daemon=True).start()
        if tray:
            tray.start()
            if sys.stderr is not None and not args.show:
                print("Abdoh is running in the system tray. Click its icon to open the window.")
        try:
            window.mainloop()
        except KeyboardInterrupt:
            pass
        restart = getattr(window, "restart_requested", False)
        for daemon in started:
            daemon.stop()
        if tray:
            tray.stop()
        return 0
    finally:
        lock.release()
        if restart:
            _start_again()


def _start_again() -> None:
    """Start a new Abdoh once this one has let go of its lock (the window's Restart button)."""
    import subprocess

    from abdoh.autostart import launch_command

    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    subprocess.Popen(launch_command(show=True), close_fds=True, creationflags=flags)


def _make_ui(cfg: Config, args: argparse.Namespace):
    """The window and the tray icon. With a tray icon the window starts hidden unless --show."""
    from abdoh.events import Bus

    log = logging.getLogger(__name__)
    bus = Bus()
    tray = None
    try:
        from abdoh.ui.tray import Tray

        tray = Tray(bus)
    except Exception as e:
        log.warning("No tray icon (%s); showing the window instead.", e)
    try:
        hidden = args.minimized or (tray is not None and not args.show)
        return _make_window(bus, cfg, hidden, tray), tray
    except Exception as e:  # e.g. no display available
        log.warning("No window (%s); running headless.", e)
        return None, None


def _make_window(bus, cfg: Config, hidden: bool, tray):
    """The app window, or the simple tkinter window if WebView2 (or pywebview) is missing."""
    from abdoh.ui.app import webview2_available

    log = logging.getLogger(__name__)
    if webview2_available():
        try:
            from abdoh.ui.app import WebWindow

            return WebWindow(bus, cfg, start_hidden=hidden, tray=tray)
        except Exception as e:
            log.warning("The app window isn't available (%s); using the simple window.", e)
    else:
        log.warning("Microsoft WebView2 isn't installed; using the simple window.")
    from abdoh.ui.window import Window

    return Window(bus, start_hidden=hidden, tray=tray)


def _start_hotkey(cfg: Config, daemon) -> None:
    if not cfg.hotkey:
        return
    from abdoh.hotkey import Hotkey

    try:
        Hotkey(cfg.hotkey, daemon.push_to_talk).start()
    except ValueError as e:
        logging.getLogger(__name__).warning("Hotkey %r not used: %s", cfg.hotkey, e)


def cmd_claude_check(cfg: Config, args: argparse.Namespace) -> int:
    from abdoh.claude.brain import NOT_CONNECTED, BrainError, make_brain

    brain = make_brain(cfg)
    if brain is None:
        print(NOT_CONNECTED)
        return 1
    print(f"Claude: {brain.status()}")
    try:
        reply = "".join(brain.stream("Reply with just the word OK.")).strip()
    except BrainError as e:
        print(e)
        return 1
    finally:
        brain.close()
    print(f"Claude is connected. Reply: {reply}")
    return 0


def cmd_install(cfg: Config, args: argparse.Namespace) -> int:
    from abdoh.shortcut import install

    try:
        for line in install(login=args.login):
            print(line)
    except Exception as e:
        print(f"Could not install: {e}")
        return 1
    return 0


def cmd_uninstall(cfg: Config, args: argparse.Namespace) -> int:
    from abdoh.shortcut import uninstall

    for line in uninstall():
        print(line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="abdoh", description="Abdoh, your voice assistant.")
    parser.add_argument("--version", action="version", version=f"abdoh {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("run", help="start Abdoh (in the system tray)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--show", action="store_true", help="open the window right away")
    mode.add_argument("--minimized", action="store_true", help="start with the window hidden")
    mode.add_argument("--headless", action="store_true", help="no window or tray icon at all")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("say", help="speak some text")
    p.add_argument("text")
    p.set_defaults(func=cmd_say)

    p = sub.add_parser("calibrate", help="print what the wake word engine hears for 'Abdoh'")
    p.add_argument("--times", type=int, default=5)
    p.set_defaults(func=cmd_calibrate)

    p = sub.add_parser("listen-once", help="wait for the wake word, then print the transcript")
    p.set_defaults(func=cmd_listen_once)

    p = sub.add_parser("test-command", help="match text to a command and run it (no voice)")
    p.add_argument("text")
    p.set_defaults(func=cmd_test_command)

    p = sub.add_parser("list-commands", help="list the commands in commands.yaml")
    p.set_defaults(func=cmd_list_commands)

    p = sub.add_parser("claude-check", help="check the Claude connection with a tiny request")
    p.set_defaults(func=cmd_claude_check)

    p = sub.add_parser("install", help="add Abdoh to the Start Menu (Windows)")
    p.add_argument("--login", action="store_true", help="also start Abdoh at login")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("uninstall", help="remove the Start Menu shortcut and start at login")
    p.set_defaults(func=cmd_uninstall)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None and getattr(sys, "frozen", False):
        args = parser.parse_args(["run", "--show"])  # double-clicking Abdoh.exe
    if args.command is None:
        parser.print_help()
        return 0
    cfg = load_config()
    # pythonw (used for autostart) has no console: sys.stdout/stderr are None there, which
    # crashes libraries that print progress bars (e.g. the first Whisper model download).
    console = sys.stderr is not None
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115
    setup_logging(cfg, console=console, level=logging.DEBUG if args.verbose else logging.INFO)
    return args.func(cfg, args)
