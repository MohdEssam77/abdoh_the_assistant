# Abdoh

**Download for Windows: [mohdessam77.github.io/abdoh_the_assistant](https://mohdessam77.github.io/abdoh_the_assistant/)**

A voice-first personal assistant for your Windows laptop. Say "Hey Abdoh" (or press
Ctrl+Alt+Space) and ask: Abdoh runs your own commands instantly, handles everyday things by
itself, and sends everything else to Claude on your own Claude plan. It answers by voice and
lives in the system tray.

Speech recognition runs on your computer. Only Claude requests go over the network, through
your own Claude account (or your ChatGPT plan, or an API key).

## What it does

- **Your commands**: "good morning", "focus time": links, apps, timers and more, done at once.
- **Everyday things**: timers, reminders, volume and music, opening apps, screenshots, screens.
- **Claude for everything else**: questions, files, the web, your mail and calendar.
- **Your screen**: "what's this error?", or "watch me fill this in and tell me if I get it wrong".
- **Codoh**: a coding assistant page. Open a folder and let Claude or ChatGPT work on your code,
  by typing or by voice ("make a chat in my portfolio folder and tell it to add a dark mode").
- **Act as**: a German teacher, a math tutor, with a board for code, maths and drawings.
- **Modes and lamps**: "movie mode" switches screens, volume and your WiZ lamps at once.
- **Memory**: it remembers what you tell it, and the week's conversations.
- **Talk naturally**: interrupt it, keep talking without the wake word, "stop listening".

The app's **Catalog** page lists every feature with what to say. [GUIDE.md](GUIDE.md) explains
everything in detail: each feature, configuration, troubleshooting and known issues.

## Run it from source

You need Python 3.11 or newer and a microphone.

```
git clone https://github.com/MohdEssam77/abdoh_the_assistant.git
cd abdoh_the_assistant
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
pip uninstall -y onnxruntime && pip install --no-deps onnxruntime-directml==1.24.4
python scripts/download_models.py
python -m abdoh run --show
```

The onnxruntime swap lets speech recognition use a graphics card; redo it after every
`pip install -e`. Check the Claude connection with `python -m abdoh claude-check`, and add Abdoh
to the Start Menu with `python -m abdoh install --login`. Your commands live in
`commands.yaml` and your settings in `config.yaml` (both made on the first run; the app's pages
edit them for you).

## Development

```
ruff check . --fix && ruff format . && pytest -q
```

Tests never need a microphone, speakers, network, API key or Claude Code. `CLAUDE.md` has the
working rules and `ABDOH_EPIC_9.md` the current plan. `scripts/build_installer.py` builds
`Abdoh-Setup.exe`; pushing a `v*` tag builds and publishes a release (see
[GUIDE.md](GUIDE.md#6-install-it-like-an-app)).

## License

GPL-3.0 or later (see `LICENSE`), because Abdoh includes Piper for its voices. The models,
voices and libraries it comes with keep their own licenses: see
[GUIDE.md](GUIDE.md#license).
