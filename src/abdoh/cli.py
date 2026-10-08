"""Command-line entry point: `python -m abdoh <command>`."""

import argparse
import logging

from abdoh import __version__
from abdoh.config import Config, load_config, setup_logging


def cmd_say(cfg: Config, args: argparse.Namespace) -> int:
    from abdoh.speech.tts import Pyttsx3Speaker

    Pyttsx3Speaker(cfg.tts_rate).say(args.text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="abdoh", description="Abdoh, your voice assistant.")
    parser.add_argument("--version", action="version", version=f"abdoh {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("say", help="speak some text")
    p.add_argument("text")
    p.set_defaults(func=cmd_say)

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
