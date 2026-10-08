"""Command-line entry point: `python -m abdoh <command>`."""

import argparse
import logging

from abdoh import __version__
from abdoh.config import Config, load_config, setup_logging


def cmd_say(cfg: Config, args: argparse.Namespace) -> int:
    from abdoh.speech.tts import Pyttsx3Speaker

    Pyttsx3Speaker(cfg.tts_rate).say(args.text)
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
    from abdoh.audio.stt import Transcriber
    from abdoh.audio.wakeword import VoskWakeWord
    from abdoh.speech.tts import Pyttsx3Speaker

    engine = VoskWakeWord(cfg.resolve(cfg.vosk_model), cfg.wake_words + cfg.wake_word_aliases)
    transcriber = Transcriber(cfg.whisper_model, cfg.language)
    transcriber.transcribe(b"\0\0" * 1600)  # load the model before listening
    with Microphone() as mic:
        print('Listening... say "Hey Abdoh" and a request.')
        text = listen_for_request(mic, engine, transcriber, Pyttsx3Speaker(cfg.tts_rate), cfg)
    print(text)
    return 0


def cmd_test_command(cfg: Config, args: argparse.Namespace) -> int:
    from abdoh.commands.actions import ActionError, run_actions
    from abdoh.commands.matcher import match
    from abdoh.commands.registry import CommandRegistry

    registry = CommandRegistry(cfg.commands_path)
    if registry.error:
        print(f"Your commands file has an error: {registry.error}")
    found = match(args.text, registry.commands, cfg.match_threshold, cfg.wake_words)
    if not found:
        print("No command matched.")
        return 1
    command, score = found
    print(f"Matched {command.name!r} (score {score:.0f})")
    try:
        for line in run_actions(command, cfg.allow_run):
            print(f"Abdoh: {line}")
    except ActionError as e:
        print(f"Abdoh: {e}")
        return 1
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

    daemon = Daemon.create(cfg)
    print('Abdoh is listening. Say "Hey Abdoh" and a request. Press Ctrl+C to quit.')
    try:
        daemon.run()
    except KeyboardInterrupt:
        daemon.stop()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="abdoh", description="Abdoh, your voice assistant.")
    parser.add_argument("--version", action="version", version=f"abdoh {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("run", help="start Abdoh")
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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    cfg = load_config()
    setup_logging(cfg, console=True, level=logging.DEBUG if args.verbose else logging.INFO)
    return args.func(cfg, args)
