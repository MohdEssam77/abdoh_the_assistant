# Abdoh

A simple, voice-first personal assistant for your laptop. Say "Hey Abdoh" and a command,
and Abdoh runs it (open a link, open an app, tell the time) or asks Claude for smarter requests.

## Setup

Requires Python 3.11+.

```
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -e .[dev]
python -m abdoh --help
```

Download the offline wake word model (Whisper downloads its own model on first use):

```
python scripts/download_models.py
```

## Try it

```
python -m abdoh say "hello"          # test the voice
python -m abdoh calibrate            # see what the wake word engine hears when you say "Abdoh"
python -m abdoh listen-once          # say "Hey Abdoh, what time is it" → prints the transcript
```

"Abdoh" isn't in the offline wake word model's vocabulary, so Abdoh listens for similar-sounding
words (`wake_word_aliases` in `config.yaml`, e.g. "abdo", "ab doe", "abdul"). If it doesn't wake up,
run `calibrate` and add the words it prints to `wake_word_aliases`.

## Configuration

On first run Abdoh copies `config.example.yaml` → `config.yaml` and `commands.example.yaml` →
`commands.yaml` in the project folder (set `ABDOH_HOME` to use another folder). Edit those copies.
For Claude features, copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`.
Logs go to `~/.abdoh/abdoh.log` by default.

## Development

```
ruff check . --fix && ruff format . && pytest -q
```

See `ABDOH_EPIC.md` for the plan and `CLAUDE.md` for working rules.

## Known issues

None yet.
