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

## Development

```
ruff check . --fix && ruff format . && pytest -q
```

See `ABDOH_EPIC.md` for the plan and `CLAUDE.md` for working rules.

## Known issues

None yet.
