# EPIC: Abdoh: a simple, voice-first personal assistant for my laptop

> **For Claude Code:** This file is your source of truth. Work through the stories **in order**.
> For each story: create a branch, implement, run tests, commit, push, merge to `main`, then move on.
> Follow the "Working rules for Claude Code" section exactly. Keep everything **simple**. If a choice
> adds complexity that isn't required by a story, don't make it.

---

## 1. Goal

Abdoh is a background voice assistant (like a minimal Siri) that:

1. Runs in the background from login, with **one simple window** I can open to see what it's doing,
   type requests, and change basic settings (functional only, not fancy).
2. Listens for its name ("Abdoh" / "Hey Abdoh").
3. Executes **hardcoded commands** defined in a simple, user-editable file
   (e.g. "Good morning Abdoh" → opens a specific YouTube link).
4. Optionally connects to **Claude** (via an Anthropic API key) to handle smarter requests:
   - "Abdoh, translate what's on my screen"
   - "Abdoh, summarize what's on my screen"
   - "Abdoh, <any question>"
5. **Replies with voice**.

### Non-goals (for now)
- No polished or fancy UI. There is **one small, plain window** (Story 8) so I can see what Abdoh
  is doing and interact with it. It only has to work and be easy to use. Don't spend time on
  styling, themes, animations or layout perfection.
- No plugin system, no multi-user support, no cloud sync.
- No always-recording / conversation history beyond a single request.

---

## 2. Tech stack (decided; don't change without a reason)

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Best ecosystem for audio + AI, cross-platform |
| Mic input | `sounddevice` | Simple, cross-platform |
| Wake word | **Vosk** (offline, small English model) with a restricted grammar, behind a `WakeWordEngine` interface | Free, offline, no training needed for a custom name. Porcupine can be added later as an alternative engine |
| Speech-to-text (command) | `faster-whisper` (`base` or `small` model, local) | Accurate, offline, free |
| Text-to-speech | `pyttsx3` (offline) behind a `Speaker` interface | Zero setup; can swap to `edge-tts` later for a nicer voice |
| Command matching | `rapidfuzz` | Tolerates small transcription errors |
| Commands file | `commands.yaml` (PyYAML) | Human-readable and easy to edit by hand |
| Screen capture | `mss` + `Pillow` | Fast, cross-platform |
| Claude | `anthropic` Python SDK, model name configurable | Official SDK, supports images |
| Config / secrets | `config.yaml` + `.env` (`python-dotenv`) | API key never committed |
| Simple UI | `tkinter` (built into Python) | No extra dependency, works on all OSes, good enough for a plain window |
| Tests | `pytest` | Standard |
| Lint/format | `ruff` | One tool, fast |

> **Note on "connecting a Claude account":** a regular Claude.ai subscription can't be used from code.
> Abdoh uses an **Anthropic API key** (from console.anthropic.com), stored in `.env` as
> `ANTHROPIC_API_KEY`. If no key is set, Claude features are disabled and Abdoh says so politely.

---

## 3. How it works (architecture)

```
             ┌─────────────────────────────────────────────┐
             │                 abdoh (daemon)              │
             │                                             │
 mic ──►  WakeWordEngine ──(heard "abdoh")──►  Recorder     │
             │                                   │         │
             │                       record until silence  │
             │                                   ▼         │
             │                           Transcriber (STT) │
             │                                   │ text    │
             │                                   ▼         │
             │                               Router        │
             │                      ┌──────────┴─────────┐ │
             │                      ▼                    ▼ │
             │            CommandRegistry          ClaudeSkills
             │          (commands.yaml)      (screen translate/
             │          open_url, open_app,   summarize, ask)
             │          run, say                 │        │
             │                      └──────┬──────┘        │
             │                             ▼               │
             │                          Speaker (TTS) ──► speakers
             └─────────────────────────────────────────────┘
```

**Wake phrase handling:** the user can say the wake word and the command in one breath
("Good morning Abdoh", "Hey Abdoh, summarize my screen"). So:
- The Vosk listener keeps a rolling ~3 s audio buffer.
- When "abdoh" is detected, Abdoh records until ~1 s of silence (max 10 s), then transcribes
  **buffer + new audio** together with Whisper. This captures words said *before* and *after* the name.
- The router strips the wake word ("abdoh", "hey abdoh") from the text before matching.
- If nothing remains after stripping (the user only said "Abdoh"), Abdoh says "Yes?" and records one more utterance.

**Router order:**
1. Exact/fuzzy match against `commands.yaml` triggers (score ≥ `match_threshold`, default 85).
2. Built-in Claude skills by keyword: contains "translate" + "screen" → translate skill;
   "summarize"/"summary" + "screen" → summarize skill.
3. Otherwise, if Claude is configured → send the question to Claude (short spoken answer).
4. Otherwise → "Sorry, I don't know that one yet."

---

## 4. Project layout

```
abdoh/
├── CLAUDE.md                  # instructions for Claude Code (see §7)
├── ABDOH_EPIC.md              # this file
├── README.md
├── pyproject.toml
├── .env.example               # ANTHROPIC_API_KEY=
├── .gitignore                 # .env, models/, __pycache__, *.log, .venv
├── config.example.yaml        # copied to config.yaml on first run
├── commands.example.yaml      # copied to commands.yaml on first run
├── models/                    # downloaded Vosk/Whisper models (git-ignored)
├── scripts/
│   ├── download_models.py
│   ├── install_autostart.py   # per-OS background setup
│   └── uninstall_autostart.py
├── src/abdoh/
│   ├── __init__.py
│   ├── __main__.py            # `python -m abdoh`
│   ├── cli.py                 # run / test-command / say / list-commands
│   ├── config.py
│   ├── audio/
│   │   ├── mic.py             # mic stream + rolling buffer
│   │   ├── wakeword.py        # WakeWordEngine interface + VoskWakeWord
│   │   ├── recorder.py        # record-until-silence (energy/VAD based)
│   │   └── stt.py             # Transcriber (faster-whisper)
│   ├── speech/
│   │   └── tts.py             # Speaker interface + Pyttsx3Speaker
│   ├── commands/
│   │   ├── registry.py        # load + validate + hot-reload commands.yaml
│   │   ├── matcher.py         # normalize text + rapidfuzz match
│   │   └── actions.py         # open_url, open_app, run, say
│   ├── claude/
│   │   ├── client.py          # thin wrapper over anthropic SDK
│   │   ├── screen.py          # screenshot → downscaled PNG bytes
│   │   └── skills.py          # translate_screen, summarize_screen, ask
│   ├── ui/
│   │   └── window.py          # the one simple tkinter window
│   ├── events.py              # thread-safe event queue between daemon and UI
│   ├── router.py
│   └── daemon.py              # main loop, error recovery, logging
└── tests/
    ├── test_matcher.py
    ├── test_registry.py
    ├── test_actions.py
    ├── test_router.py
    └── test_claude_skills.py  # SDK mocked
```

---

## 5. The commands file (user-facing contract)

`commands.yaml`, the file I edit to add new commands. Must stay this simple:

```yaml
# Each command: one or more trigger phrases, and one or more actions run in order.
# The wake word ("Abdoh" / "Hey Abdoh") is stripped before matching, so don't include it.

- name: good_morning
  triggers: ["good morning"]
  actions:
    - say: "Good morning! Here's your playlist."
    - open_url: "https://www.youtube.com/watch?v=REPLACE_ME"

- name: open_mail
  triggers: ["open my mail", "open email"]
  actions:
    - open_url: "https://mail.google.com"

- name: open_vscode
  triggers: ["open code", "open vs code"]
  actions:
    - open_app: "Visual Studio Code"

- name: what_time
  triggers: ["what time is it", "time"]
  actions:
    - say: "It is {time}."        # supported placeholders: {time}, {date}
```

Supported actions (keep to these four):
- `say: <text>`: speak text (supports `{time}`, `{date}`).
- `open_url: <url>`: open in default browser (`webbrowser.open`).
- `open_app: <name or path>`: open an app (macOS `open -a`, Windows `os.startfile`/`start`, Linux `xdg-open`/`subprocess`).
- `run: <shell command>`: run a command (only if `allow_run: true` in config; off by default).

The file is **hot-reloaded** when it changes (check mtime before each match; no watcher library needed).
Invalid YAML → log the error, keep the last valid version, and say "Your commands file has an error."

---

## 6. Config

`config.yaml`:

```yaml
wake_words: ["abdoh", "hey abdoh"]
vosk_model: "models/vosk-model-small-en-us-0.15"
whisper_model: "base"            # base | small
language: "en"                   # whisper language hint; null = auto
match_threshold: 85
silence_seconds: 1.0
max_record_seconds: 10
tts_rate: 175
allow_run: false
claude:
  model: "claude-sonnet-4-5"     # configurable; use whatever current model I set
  max_tokens: 400
  translate_target: "English"
  voice_reply_max_sentences: 4
log_file: "~/.abdoh/abdoh.log"
```

> Vosk's English model may not recognize "Abdoh" as a word. The VoskWakeWord engine should
> use a grammar with phonetic near-spellings (e.g. `"abdo"`, `"ab doe"`, `"abdul"`) configurable via
> `wake_word_aliases` in config, and Story 3 must include a quick manual calibration step:
> `python -m abdoh calibrate` prints what Vosk hears when I say "Abdoh" 5 times, so I can add the right aliases.

---

## 7. Working rules for Claude Code

Create `CLAUDE.md` in Story 0 with these rules, and follow them:

1. **One branch per story:** `story/<number>-<short-name>` (e.g. `story/04-commands-file`).
2. **Small commits** using Conventional Commits: `feat:`, `fix:`, `test:`, `docs:`, `chore:`, `refactor:`.
   Commit after each meaningful step, not one giant commit per story.
3. **Before every commit:** `ruff check . --fix && ruff format . && pytest -q`. Never commit with failing tests.
4. **When a story's acceptance criteria are met:** push the branch, merge into `main`
   (`git checkout main && git merge --no-ff story/... && git push origin main`), then start the next story.
   If a GitHub remote / `gh` CLI is available, open a PR and merge it instead.
5. **Never commit** `.env`, `config.yaml`, `commands.yaml` (user copies), or anything in `models/`.
6. **Hardware-dependent code** (mic, speakers, screen) must sit behind interfaces so tests use fakes.
   Unit tests must never need a microphone, speakers, network, or API key.
7. **Keep it simple.** No new dependencies beyond §2 without writing a one-line justification in the commit message.
8. Update `README.md` at the end of each story if setup or usage changed.
9. If something is blocked (e.g. OS permission needed), finish everything else, write a `TODO(blocked):`
   note in the README "Known issues" section, and continue to the next story.

---

## 8. Stories

### Story 0: Repo bootstrap
- `git init`, `pyproject.toml` (package `abdoh`, Python ≥3.11, deps from §2, `ruff` + `pytest` as dev deps).
- `.gitignore`, `.env.example`, `config.example.yaml`, `commands.example.yaml`, `CLAUDE.md`, minimal `README.md`.
- `python -m abdoh --help` works.
- **Done when:** `pip install -e .[dev]` and `pytest` (one trivial test) pass; first commit pushed.

### Story 1: Config + logging
- `config.py`: load `config.yaml` (copy from example if missing), load `.env`, expose a typed `Config` dataclass.
- Rotating file log at `log_file` + console log when run in the foreground.
- **Done when:** tests cover defaults, missing file → copied from example, missing API key → `claude_enabled = False`.

### Story 2: Voice output (TTS)
- `Speaker` interface with `say(text)`; `Pyttsx3Speaker` implementation; `FakeSpeaker` for tests (records calls).
- CLI: `python -m abdoh say "hello"`.
- **Done when:** I hear "hello" from the CLI.

### Story 3: Wake word + recording + transcription
- `scripts/download_models.py` downloads the Vosk small English model into `models/` (Whisper downloads itself on first use).
- `mic.py`: 16 kHz mono stream, rolling buffer.
- `wakeword.py`: `WakeWordEngine` interface + `VoskWakeWord` with grammar from `wake_words` + `wake_word_aliases`.
- `recorder.py`: record until `silence_seconds` of low energy or `max_record_seconds`.
- `stt.py`: `Transcriber.transcribe(audio) -> str` using faster-whisper.
- CLI: `python -m abdoh calibrate` (see §6) and `python -m abdoh listen-once` (wait for wake word → print transcript).
- Play a short beep or say "Yes?" only when nothing follows the wake word (don't beep every time; keep it quiet).
- **Done when:** saying "Hey Abdoh, what time is it" prints `hey abdoh what time is it` (approximately).

### Story 4: Commands file + matcher + actions
- `registry.py`: load/validate `commands.yaml` (schema check: name, triggers list, actions list with one known key each), hot-reload by mtime.
- `matcher.py`: lowercase, strip punctuation, strip wake words, then `rapidfuzz` (`token_set_ratio`) against all triggers; best score ≥ threshold wins.
- `actions.py`: the four actions from §5, cross-platform; `run` disabled unless `allow_run`.
- CLI: `python -m abdoh test-command "good morning abdoh"` runs the match + actions **without voice**. `python -m abdoh list-commands`.
- **Done when:** tests cover matching (including typos and wake word at start/end), invalid YAML handling, placeholders; "good morning abdoh" via `test-command` opens the YouTube link.

### Story 5: Router + daemon loop (end-to-end, no Claude yet)
- `router.py`: implements the order in §3 (Claude steps stubbed for now).
- `daemon.py`: loop forever: wake → record → transcribe → route → speak. Catch and log every exception
  so one bad request never kills the daemon; if the mic disappears, retry every 5 s.
- `python -m abdoh run` starts it in the foreground.
- **Done when:** I can say "Good morning Abdoh" and the video opens; unknown phrases get the "I don't know that one yet" reply.

### Story 6: Claude connection
- `claude/client.py`: wrapper with `ask(text, image_png: bytes | None) -> str`; reads `ANTHROPIC_API_KEY`;
  timeouts (20 s), one retry; friendly spoken errors ("I couldn't reach Claude right now").
- System prompt: "You are Abdoh, a voice assistant. Answers are spoken aloud: be brief
  (max N sentences), no markdown, no lists, no emojis."
- `python -m abdoh claude-check` verifies the key with a tiny request.
- **Done when:** with a key, "Abdoh, what's the capital of Japan" is answered by voice; without a key, Abdoh says Claude isn't connected and how to add the key.

### Story 7: Screen skills (translate & summarize)
- `claude/screen.py`: capture the **primary monitor** with `mss`, downscale so the long side ≤ 1600 px, PNG bytes.
- `skills.py`:
  - `translate_screen(target=config.translate_target)`: "Translate the main text visible in this screenshot into {target}. If it's long, give the gist in a few sentences."
  - `summarize_screen()`: "Summarize the main content of this screenshot in a few spoken sentences."
  - Optional target language from speech: "translate my screen **to Arabic**" → parse `to <language>`.
- Router keywords as in §3.
- Say "One sec…" before calling Claude so the user knows it's working.
- macOS: document that Terminal/Python needs **Screen Recording** permission; detect an all-black capture and tell the user.
- **Done when:** tests (mocked SDK + fake screenshot) pass; manually, both skills reply by voice.

### Story 8: Simple window (functional, not fancy)
Goal: a plain window to see what Abdoh is doing and to use it without voice. **It only has to work.**
Use default tkinter widgets, no custom styling, no images, no themes.

- **Threading:** the tkinter window runs on the main thread; the daemon loop runs in a background thread.
  They talk only through `events.py` (two `queue.Queue`s: daemon → UI events, UI → daemon requests).
  The UI polls its queue with `root.after(100, ...)`. Never touch tkinter from the daemon thread.
- **What the window shows (top to bottom):**
  1. Status line: `Listening` / `Paused` / `Thinking…` / `Speaking` / `Error: <short message>`.
  2. Claude status: `Claude: connected` or `Claude: not connected`.
  3. A read-only history box: last ~50 lines like `You: good morning` / `Abdoh: Good morning! …`.
  4. A text box + **Send** button (Enter also sends): typed requests go through the **same router**
     as voice, so I can test commands or ask Claude by typing.
- **Buttons (one row):**
  - **Pause / Resume listening**
  - **Edit commands**: opens `commands.yaml` in the default text editor.
  - **Reload commands**
  - **Voice replies: On/Off** toggle (when off, replies only appear in the history box)
  - **Set Claude key**: a simple dialog (`simpledialog.askstring`, masked input) that saves
    `ANTHROPIC_API_KEY` to `.env` and reconnects without restarting.
- **Closing the window** hides it (`withdraw`) instead of quitting; Abdoh keeps listening.
  Saying "Abdoh, show window" or running `python -m abdoh run` again (second instance asks the first,
  via the lock file + a tiny localhost socket) brings it back. A **Quit** item exists in the window's menu.
- `python -m abdoh run` opens the window; `python -m abdoh run --minimized` starts with it hidden;
  `python -m abdoh run --headless` runs with no window at all (useful for debugging).
- Keep UI code thin: `window.py` only displays events and forwards requests. No logic in the UI.
- **Done when:** I can type "good morning" and the link opens, see voice requests appear in the history,
  pause/resume listening, and set my API key from the window.

### Story 9: Run in the background (autostart)
- `scripts/install_autostart.py` detects the OS and installs (all start with `run --minimized`):
  - **Windows:** a Task Scheduler task "Abdoh" at logon running `pythonw -m abdoh run --minimized` (no console window).
  - **macOS:** `~/Library/LaunchAgents/com.abdoh.agent.plist` with `RunAtLoad` + `KeepAlive`.
  - **Linux:** `~/.config/systemd/user/abdoh.service`, `systemctl --user enable --now abdoh`.
- `uninstall_autostart.py` reverses it.
- Single-instance lock (lock file in `~/.abdoh/`) so two copies never run.
- Voice commands built in: "Abdoh, stop listening" (pauses until "Abdoh, start listening") and "Abdoh, reload commands".
- **Done when:** after reboot, with no app open, "Hey Abdoh, what time is it" gets a spoken answer.

### Story 10: Polish & docs
- README: install, download models, add API key, edit `commands.yaml` (with examples), autostart, troubleshooting (mic permission, screen permission, wake word not detected → run `calibrate`).
- Measure and log latency per stage (wake → transcript → reply) at debug level.
- **Done when:** a fresh clone can be set up by following only the README.

---

## 9. Later (not part of this epic; don't build)
- Nicer voice (`edge-tts` / ElevenLabs), Arabic wake word & replies.
- Porcupine wake word engine for better accuracy.
- Short conversational memory ("and what about tomorrow?").
- Tray icon and a nicer-looking UI.
- Letting Claude add commands to `commands.yaml` by voice.

---

## 10. Definition of done (whole epic)
- [ ] Abdoh starts automatically at login with its window hidden, and keeps listening when the window is closed.
- [ ] The simple window shows status and history, accepts typed requests, and can pause listening and set the Claude key.
- [ ] Hardcoded commands in `commands.yaml` work by voice and can be added without restarting.
- [ ] With an API key: ask anything, translate screen, summarize screen, all answered by voice.
- [ ] Without an API key: everything except Claude features works, with clear spoken feedback.
- [ ] All tests pass; `main` is pushed and up to date.
