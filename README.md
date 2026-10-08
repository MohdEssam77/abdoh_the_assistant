# Abdoh

A simple, voice-first personal assistant for your laptop. Say "Hey Abdoh" and a request:
Abdoh runs your own commands (open a link, open an app, tell the time), and with an Anthropic
API key it can answer questions and translate or summarize what's on your screen. It replies by
voice and lives in the background with one plain window.

Speech recognition runs offline on your machine (Vosk for the wake word, Whisper for requests).
Only Claude requests go over the network.

## 1. Install

You need **Python 3.11 or newer** and a microphone.

```
git clone https://github.com/MohdEssam77/abdoh_the_assistant.git
cd abdoh_the_assistant
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -e .[dev]
```

On Linux you may also need PortAudio, Tk and a speech engine:
`sudo apt install libportaudio2 python3-tk espeak-ng`.

## 2. Download the models

```
python scripts/download_models.py
```

This downloads the small offline wake word model (about 40 MB) into `models/`. The Whisper
speech model downloads itself the first time Abdoh starts (about 150 MB for `base`).

## 3. Run

```
python -m abdoh run              # opens Abdoh's window and starts listening
python -m abdoh run --minimized  # starts with the window hidden
python -m abdoh run --headless   # no window at all (Ctrl+C to quit)
```

On first run Abdoh creates `config.yaml` and `commands.yaml` from the example files. Try:

- "Good morning Abdoh"
- "Hey Abdoh, what time is it"

The window shows what Abdoh is doing (status, Claude connection, recent history). You can type
requests (they go through the same commands and Claude as voice), pause listening, edit or reload
commands, turn voice replies off, and set your Claude API key.

Closing the window only hides it; Abdoh keeps listening. Bring it back by saying
"Abdoh, show window" or running `python -m abdoh run` again. Quit from the window's **Abdoh** menu.

### Voice controls

- "Abdoh, stop listening": Abdoh ignores everything until "Abdoh, start listening"
- "Abdoh, reload commands": re-reads `commands.yaml` (it also reloads automatically on change)
- "Abdoh, show window": brings the window back

## 4. Connect Claude (optional)

Abdoh can answer any question with Claude. A Claude.ai subscription can't be used from code, so
you need an **Anthropic API key** from https://console.anthropic.com.

Either click **Set Claude key** in the window, or:

```
copy .env.example .env          # Windows (cp on macOS / Linux); then set ANTHROPIC_API_KEY=sk-ant-...
python -m abdoh claude-check    # verifies the key with a tiny request
```

Then you can say:

- "Abdoh, what's the capital of Japan?"
- "Abdoh, translate what's on my screen" (into `translate_target`, default English), or
  "translate my screen to Arabic"
- "Abdoh, summarize my screen"

Abdoh says "One sec..." while Claude works. The model is set in `config.yaml` (`claude.model`).
Without a key, everything else still works and Abdoh tells you Claude isn't connected.

## 5. Your commands

Edit `commands.yaml` (or click **Edit commands**). Each command has trigger phrases and actions
that run in order. Don't include "Abdoh" in triggers; the wake word is removed before matching.
Small transcription mistakes are tolerated. Changes are picked up automatically.

```yaml
- name: good_morning
  triggers: ["good morning"]
  actions:
    - say: "Good morning! Here's your playlist."
    - open_url: "https://www.youtube.com/watch?v=REPLACE_ME"

- name: open_vscode
  triggers: ["open code", "open vs code"]
  actions:
    - open_app: "Visual Studio Code"

- name: what_day
  triggers: ["what day is it", "what's the date"]
  actions:
    - say: "Today is {date}."

- name: backup
  triggers: ["back up my notes"]
  actions:
    - run: "robocopy C:\\notes D:\\backup\\notes /MIR"
    - say: "Backup started."
```

| Action | What it does |
|---|---|
| `say: <text>` | Speaks the text. `{time}` and `{date}` are filled in. |
| `open_url: <url>` | Opens the link in your default browser. |
| `open_app: <name or path>` | Opens an app, e.g. "Visual Studio Code", "notepad", or a full path. |
| `run: <shell command>` | Runs a command. Off by default: set `allow_run: true` in `config.yaml`. |

If the file has a mistake, Abdoh says "Your commands file has an error" and keeps using the last
working version. Check your commands without speaking:

```
python -m abdoh list-commands
python -m abdoh test-command "good morning abdoh"
```

## 6. Start at login

```
python scripts/install_autostart.py     # run with the Python where abdoh is installed
python scripts/uninstall_autostart.py
```

Abdoh then starts at login with its window hidden. Only one copy ever runs.

- **Windows:** a Task Scheduler task "Abdoh" running `pythonw -m abdoh run --minimized` (no console
  window). Creating logon tasks needs admin rights on many PCs; without them the script adds Abdoh
  to your user's startup programs instead (`HKCU\...\Run`), which works the same way.
- **macOS:** `~/Library/LaunchAgents/com.abdoh.agent.plist` (restarted if it crashes, not after Quit).
- **Linux:** `~/.config/systemd/user/abdoh.service`, enabled with `systemctl --user enable --now abdoh`.

## Configuration

`config.yaml` (created from `config.example.yaml`; set `ABDOH_HOME` to keep these files elsewhere):

| Key | Default | Meaning |
|---|---|---|
| `wake_words` | `["abdoh", "hey abdoh"]` | Words removed from requests before matching |
| `wake_word_aliases` | `["abdo", "ab doe", "abdul", ...]` | What the wake word engine listens for (see Troubleshooting) |
| `whisper_model` | `base` | `base` is faster, `small` is more accurate |
| `language` | `en` | Whisper language hint (`null` = auto-detect) |
| `match_threshold` | `85` | How closely speech must match a trigger (0-100) |
| `silence_seconds` | `1.0` | Pause that ends a request |
| `max_record_seconds` | `10` | Longest request |
| `tts_rate` | `175` | Speaking speed |
| `allow_run` | `false` | Allow `run:` actions |
| `claude.model` | `claude-sonnet-4-5` | Claude model id |
| `claude.translate_target` | `English` | Default language for screen translation |
| `claude.voice_reply_max_sentences` | `4` | Keeps spoken answers short |
| `log_file` | `~/.abdoh/abdoh.log` | Log file |

## Troubleshooting

**Abdoh doesn't wake up.** "Abdoh" isn't a word in the offline wake word model, so Abdoh listens
for similar-sounding words. Run `python -m abdoh calibrate`, say "Abdoh" five times, and add the
words it prints to `wake_word_aliases` in `config.yaml`. Then `python -m abdoh listen-once`
should print your request.

**Abdoh wakes up by itself.** False wake-ups are checked against the Whisper transcript and
ignored silently (you'll see "Ignoring false wake-up" in the log). If it still reacts too often,
remove short or common words from `wake_word_aliases`.

**No microphone / mic permission.** Check your OS privacy settings allow microphone access for
Python (Windows: Settings → Privacy & security → Microphone, "Let desktop apps access your
microphone"; macOS: System Settings → Privacy & Security → Microphone for Terminal/Python). If the
mic is unplugged, Abdoh retries every 5 seconds.

**Screen translate/summarize says the screenshot is black.** On macOS, give Terminal (or Python)
**Screen Recording** permission in System Settings → Privacy & Security, then restart Abdoh.

**Claude doesn't answer.** Run `python -m abdoh claude-check`. Check the key in `.env` and that
`claude.model` in `config.yaml` is a model your key can use.

**Edit commands opens nothing on Windows.** If no app is associated with `.yaml` files, Abdoh
opens Notepad.

**See what's happening.** Logs are in `~/.abdoh/abdoh.log`. For more detail, including timing
for each stage (recording, transcription, reply), run `python -m abdoh -v run`.

## Development

```
ruff check . --fix && ruff format . && pytest -q
```

Unit tests never need a microphone, speakers, network or API key. See `ABDOH_EPIC.md` for the plan
and `CLAUDE.md` for working rules.

## Known issues

None.
