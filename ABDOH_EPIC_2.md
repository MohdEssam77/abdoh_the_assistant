# EPIC 2: Abdoh as a light, fast desktop app with Claude through my Pro subscription

> **For Claude Code:** This file is your source of truth for the second epic. `ABDOH_EPIC.md` (v1) is
> done; its architecture still applies unless this file changes it. Work through the stories **in
> order** and follow the working rules in `CLAUDE.md` exactly. Keep everything **simple**.

---

## 1. Goal

Abdoh v1 works (all 11 stories merged), but it is a developer tool: it runs from a terminal, takes
about 3 seconds to answer even a hardcoded command, uses about 400 MB of RAM while idle, and can only
use Claude with a paid API key. This epic turns it into:

1. A **desktop app** that lives in the **system tray**, starts at login, opens from the Start Menu,
   and can be built into a standalone `Abdoh.exe`.
2. **Light:** idle RAM at or below 250 MB, idle CPU below 3% of one core.
3. **Fast:** hardcoded commands and built-in skills start answering about **1 second** after I stop
   talking; Claude starts speaking within about **3 seconds** for simple questions.
4. **More things answered locally**, without Claude: commands with blanks ("open {app}",
   "search YouTube for {query}"), timers, volume, media keys, lock screen, open any installed app.
5. **Claude through my Claude Pro subscription** for everything else, using Claude Code in headless
   mode (`claude -p`). Claude can also *do* things (open links and apps, set timers) and I can say
   **"remember that"** to turn what it did into an instant hardcoded command.
6. A **reliable wake word** ("Hey Abdoh") using **openWakeWord**, plus a **push-to-talk hotkey**.

### Baseline (measured on my laptop, 2026-11-14)

| What | v1 | Target |
|---|---|---|
| Idle RAM (working set) | ~400 MB (Vosk ~130, Whisper ~190, anthropic SDK ~55) | ≤ 250 MB |
| Startup | ~9 s | ≤ 5 s |
| "What time is it" (end of speech → first sound) | ~3 s: 1.0 s fixed silence + 0.45 s Whisper + ~1.5 s new TTS engine per reply | ~1 s |
| Claude reply | "One sec…" spoken *before* the request (~1.5 s), then waits for the whole answer | first words ≤ 3 s |
| Claude Code headless (Pro, `--tools ""`) | first words ~1.8 s, done ~2.5 s | n/a (measured, good enough) |
| Wake word | Vosk can't hear "Abdoh"; 6 false wake-ups in ~3 min of background talk | rare false wake-ups |

### Non-goals (for now)
- No fancy UI. The tray icon and the plain tkinter window are enough.
- No plugin system, no multi-user support, no cloud sync.
- Claude never runs shell commands on its own. (Changed on 2026-11-15, story 23: when you ask,
  Claude may work with your files and run PowerShell, asking before it deletes or overwrites.)
- macOS/Linux keep working for what already works; new desktop features (hotkey, Start Menu, exe
  build) are Windows-first.

---

## 2. Tech stack changes (decided; don't change without a reason)

Everything from v1 stays unless replaced here.

| Concern | Choice | Why |
|---|---|---|
| Claude (subscription) | **Claude Code CLI, headless**: `claude -p --output-format stream-json --include-partial-messages`, signed in with the Pro account | The supported way to use a Claude subscription from a script. A Pro plan includes no API credits |
| Claude (API key, optional) | `anthropic` SDK, **streaming**, imported lazily | Kept for people with an API key |
| Wake word | **openWakeWord models** (`.onnx`) run directly with `onnxruntime` (already installed by faster-whisper). Custom "Hey Abdoh" model from the official training notebook. Vosk stays as the fallback | Accurate custom wake word. The `openwakeword` package itself is *not* a runtime dependency: it imports scipy and scikit-learn (~100 MB RAM) for training-only features |
| End of speech | **Silero VAD** model bundled with faster-whisper (`silero_vad_v6.onnx`), via `onnxruntime` | Knows when you stopped talking, so the wait can be shorter. No new dependency |
| Text-to-speech | `pyttsx3` with **one persistent engine** on its own thread, interruptible. *(Changed 2026-11-15: on Windows the persistent engine is SAPI driven directly through `comtypes`, because pyttsx3 2.99 cut every reply off there.)* | A new engine per reply costs ~1.5 s |
| Earcons (chime) | Generated with numpy, played with `sounddevice` | No sound files, no new dependency |
| Tray icon | **`pystray`** (uses Pillow, already a dependency) | Small, cross-platform tray icon |
| Global hotkey | Win32 `RegisterHotKey` via `ctypes` | No new dependency |
| Standalone build | **PyInstaller**, build-time only (`[build]` extra) | One folder with `Abdoh.exe`, no Python needed |

---

## 3. How it works (architecture)

```
                 ┌──────────────────────── abdoh (tray app) ────────────────────────┐
 hotkey ──────►  │ push-to-talk ─┐                                                   │
 mic ─────────►  │ WakeWord ─────┴─► Recorder (Silero VAD) ─► Transcriber (Whisper)  │
                 │ (openWakeWord; Vosk fallback)                         │ text      │
                 │                                                       ▼           │
                 │                                                    Router         │
                 │      ┌──────────────┬───────────────┬────────────────┼─────────┐ │
                 │      ▼              ▼               ▼                ▼         │ │
                 │   Controls     Your commands   Built-in skills   Claude brain  │ │
                 │ (pause, stop,  (commands.yaml, (timer, volume,   (Claude Code  │ │
                 │  remember…)    {slots})        media, open app,  with Pro, or  │ │
                 │                                lock screen)      API key)      │ │
                 │      └──────────────┴───────────────┴────────────────┘         │ │
                 │                          │ reply: sentences + actions           │
                 │                          ▼                                      │
                 │          Speaker (persistent, interruptible) ──► speakers       │
                 │          Tray icon + window (status, history, typing)           │
                 └──────────────────────────────────────────────────────────────────┘
```

**Router order:**
1. Controls: show window, stop/start listening, reload commands, remember that, stop.
2. Your commands in `commands.yaml` (fuzzy match; triggers with `{slots}` use pattern matching).
3. Built-in skills, all local and instant: timers, volume and media keys, lock screen, open any
   installed app.
4. Screen skills (translate/summarize my screen) → Claude with a screenshot.
5. Anything else → Claude, if connected.
6. Otherwise → "Sorry, I don't know that one yet."

**Claude brain.** One interface, two backends:
- `ClaudeCodeBrain` (default when Claude Code is installed and signed in): runs
  `claude -p --output-format stream-json --verbose --include-partial-messages --safe-mode
  --restricted --no-session-persistence --strict-mcp-config --permission-prompts none
  --system-prompt <Abdoh's prompt> --tools <allowed tools> --allowedTools <allowed tools>`
  in an empty working folder (`~/.abdoh/claude`), with the request on **stdin** (never on the
  command line), `ANTHROPIC_API_KEY` removed from its environment (so the subscription is used),
  and no console window. Allowed tools: `Read` (for screenshots), plus `WebSearch,WebFetch` when
  `claude.allow_web` is on, plus `Write,Edit,Glob,Grep,PowerShell` and `--add-dir <home>` when
  `claude.allow_files` is on (story 23). `--bare` must not be used: it ignores subscription logins.
- `ApiBrain` (when only an API key is set): `anthropic` streaming, effort `low`.
- `claude.backend: auto` picks Claude Code first (it's paid by the subscription), then the API.

**Reply protocol** (both backends). Claude's text is streamed and split as it arrives:
- A line like `ACTION open_url: https://…` is an action, run as soon as the line is complete.
  Claude may use only: `open_url`, `open_app`, `media`, `timer`. Anything else is ignored and logged.
- Everything else is speech: cleaned of markdown and spoken **sentence by sentence** while the
  rest is still arriving.
- The last request and its actions are kept so "remember that" can save them as a command.

**Speaking and interrupting.** One `pyttsx3` engine (on Windows, one SAPI voice) lives on its own
thread for the whole run.
Pressing the hotkey, or **Stop** in the tray or window, stops speech immediately and stops reading
the rest of a streamed reply. (Interrupting by voice is out of scope; see Later.)

---

## 4. The commands file (additions)

Still the v1 format. Two additions:

```yaml
# Triggers can have {slots}; a slot captures the rest of the words at that spot.
- name: youtube_search
  triggers: ["search youtube for {query}"]   # "play {query} on youtube": see story 21
  actions:
    - open_url: "https://www.youtube.com/results?search_query={query}"   # URL-encoded
    - say: "Here's {query} on YouTube."

# New actions (also usable by Claude):
- name: focus
  triggers: ["focus mode"]
  actions:
    - media: play_pause          # play_pause | next | previous | volume_up | volume_down | mute
    - timer: "25 minutes"        # spoken when it's done
```

Supported actions: `say`, `open_url`, `open_app`, `play_youtube` (story 21), `run` (only with
`allow_run: true`), `media`, `timer`. Learned commands ("remember that") are appended at the end
of the file without touching the rest of it.

---

## 5. Config (additions)

```yaml
wake_word_model: "models/hey_abdoh.onnx"   # openWakeWord model; missing → Vosk fallback
wake_word_threshold: 0.5
hotkey: "ctrl+alt+space"                   # push-to-talk and stop speaking; "" turns it off
silence_seconds: 0.6                       # with the VAD, a shorter pause is enough
claude:
  backend: "auto"          # auto | code | api | off
  code_path: ""            # claude.exe; empty = find it (PATH, ~/.local/bin, VS Code extension)
  code_model: ""           # empty = your Claude Code default; or "sonnet", "opus", a full model id
  model: "claude-opus-5-5" # API backend only
  effort: "low"
  allow_web: true          # let Claude search the web (Claude Code backend)
  allow_files: true        # story 23: Claude works with your files (asks before deleting)
  timeout_seconds: 120     # story 23: file jobs take longer than questions
  followup_seconds: 60     # a follow-up within this time gets the previous exchange as context
  listen_after_question: true  # story 22: answer Claude's questions without the wake word
```

When `language` is `en`, Whisper uses the English-only model (`base.en`), which is more accurate at
the same speed.

---

## 6. Working rules

Same as v1, in `CLAUDE.md`. Story branches continue the numbering: `story/11-...`, `story/12-...`.
Every story: tests with fakes (no mic, speakers, network, API key, or Claude Code in unit tests),
`ruff check . --fix && ruff format . && pytest -q` before each commit, merge with `--no-ff`, push.

---

## 7. Stories

### Story 11: Epic 2 bootstrap
- Add this file; point `CLAUDE.md` at it; README "Known issues" lists the real v1 issues.
- Update the default API model to `claude-opus-5-5`.
- **Done when:** the epic is on `main` and the README is honest about v1's state.

### Story 12: Instant voice replies
- `Pyttsx3Speaker`: one engine on a dedicated thread, reused for every reply; `say()` blocks until
  done; `stop()` interrupts the current utterance (via pyttsx3's word callback) and recreates the
  engine if it errored.
- `earcons.py`: short generated tones played without blocking (`thinking`, `listening`, `done`).
- Router no longer speaks "One sec…" before a Claude request: it plays the thinking chime and the
  request starts right away.
- `Daemon.stop_speaking()`; the window gets a **Stop** button.
- **Done when:** tests pass with fakes; replies after the first one start within ~0.15 s.

### Story 13: Quicker listening
- `vad.py`: Silero VAD from faster-whisper's assets, streaming 512-sample windows with carried state.
  `record_until_silence` uses it (speech probability ≥ 0.5) and falls back to RMS energy if the VAD
  can't load. `silence_seconds` default 0.6.
- Whisper uses `<model>.en` when `language: en`, and `without_timestamps=True`.
- Import `anthropic` only when an API brain is created; load nothing heavy before it's needed.
- **Done when:** tests cover VAD end-pointing with a fake VAD; startup is faster; latency logged.

### Story 14: Claude through your Pro subscription
- `claude/brain.py`: `Brain` interface (`stream(prompt, image_png=None) -> Iterator[str]`) and
  `BrainError` (message safe to speak).
- `claude/code.py`: `find_claude_code()` (config path, PATH, `~/.local/bin`, newest VS Code
  extension binary), `code_status()` via `claude auth status` (logged in? plan?), and
  `ClaudeCodeBrain` exactly as in §3. Screenshots are saved into the working folder and read with
  the `Read` tool. Usage-limit events (`rate_limit_event` not `allowed`) become "You've reached
  your Claude usage limit; it resets at 6 PM." Timeouts kill the process.
- `claude/api.py`: `ApiBrain` (streaming, lazy `anthropic` import).
- `claude/reply.py`: the reply protocol from §3 (action lines, sentence splitting, markdown
  cleanup) with an allow-list of actions.
- Router streams Claude replies; the daemon speaks each sentence as it arrives and shows the full
  answer in the history once done.
- Window/tray show `Claude: Pro subscription (Claude Code)`, `Claude: API key`, or `not connected`.
- `python -m abdoh claude-check` reports which backend is used and makes one tiny request.
- **Done when:** tests pass with a fake `claude` process and a fake SDK; manually, "Abdoh, what's
  the capital of Japan" and "summarize my screen" are answered through the subscription, and
  "Abdoh, open the Python website" opens it.

### Story 15: openWakeWord wake word
- `audio/oww.py`: `OpenWakeWord(WakeWordEngine)` running the melspectrogram → embedding →
  wake word ONNX models with `onnxruntime`, 80 ms frames, same math as openWakeWord 0.6
  (checked once against the official package with `scripts/check_wakeword.py`).
- `scripts/download_models.py` also fetches the two openWakeWord feature models.
- `Daemon.create`: use openWakeWord when `wake_word_model` exists, otherwise Vosk (current
  behavior) and log how to train a model. The Whisper "did it really say Abdoh" check stays for
  both engines: it costs little and stops a rare false wake-up from starting a Claude request.
- README: how to train "Hey Abdoh" with the official Google Colab notebook (under an hour) and
  where to put the `.onnx` file; how to tune `wake_word_threshold`.
- **Done when:** tests pass with fake ONNX sessions; the parity check matches the official
  package; with a trained model, "Hey Abdoh" wakes it and background talk doesn't.
  If no model is trained yet: `TODO(blocked)` in README Known issues.

### Story 16: The fast lane (more done locally)
- Slots in triggers (`{name}`), filled into actions (URL-encoded in `open_url`).
- New actions `media` and `timer` (§4), usable in `commands.yaml` and by Claude.
- Built-in skills (router step 3): "set a timer for 5 minutes" / "cancel the timer", "volume
  up/down", "mute", "pause/play the music", "next/previous song", "lock my computer", "open
  {any installed app}" (Start Menu index, cached, fuzzy-matched; falls through to Claude if no app
  matches well).
- **Done when:** tests cover slots, every built-in (with fake key presses and a fake clock), and
  that your own commands still win.

### Story 17: Remember that, and follow-ups
- After Claude ran actions, "remember that" (or "remember that as <phrase>") appends a command to
  `commands.yaml` (trigger = the request or the phrase, actions = what Claude did). The file is
  appended to, never rewritten. Abdoh confirms by voice.
- A request within `followup_seconds` of the last Claude answer gets that exchange as context, so
  "and what about tomorrow?" works.
- **Done when:** tests cover saving (including a file with comments), naming, nothing to remember,
  and follow-up context expiry.

### Story 18: Tray app and push-to-talk
- `ui/tray.py` (pystray): icon colored by status (listening, paused, thinking/speaking, error);
  menu: Show window, Pause/Resume listening, Stop speaking, Voice replies, Edit commands,
  Start at login (checkbox), Quit. Menu items only send requests on the bus.
- `hotkey.py`: `ctrl+alt+space` (configurable) via `RegisterHotKey` on its own thread. Pressing it
  while Abdoh talks stops speech; otherwise it plays the listening chime and records one request
  with no wake word.
- `run` starts in the tray (window hidden unless `--show`); `--headless` unchanged.
- **Done when:** tests cover hotkey parsing, the listen-now path in the daemon, and tray menu
  wiring with fakes; manually, the tray icon works and the hotkey talks to Abdoh.

### Story 19: Install it like an app
- `abdoh install` creates a Start Menu shortcut "Abdoh" (with a generated `.ico`) that runs
  `pythonw -m abdoh run`, and optionally enables start at login; `abdoh uninstall` reverses it.
- Frozen-app support: when running as `Abdoh.exe`, user files (config, commands, `.env`, models,
  logs) live in `%APPDATA%\Abdoh`, created from bundled examples.
- `scripts/build_app.py`: PyInstaller one-folder, windowed build → `dist/Abdoh/Abdoh.exe`.
- **Done when:** the shortcut opens Abdoh in the tray; the built exe starts, listens, and answers
  (manual check); README explains both ways.

### Story 20: Measure and wrap up
- Measure again (RAM, startup, latency per stage) and put the before/after table in the README.
- README: setup checklist, including the steps only I can do (§9).
- Tick this epic's definition of done.
- **Done when:** a fresh clone can be set up from the README alone.

### Added 2026-11-15: ideas from the UdS Operator hackathon project

UdS Operator was a typed agent that drove a browser, files and the shell. Three of its ideas fit
Abdoh without making it heavier:

### Story 21: "Play X on YouTube" plays the video
- `youtube.py`: one request for YouTube's results page (standard library, no API key), read until
  the first search result (`videoRenderer`, so ads and Shorts are skipped).
  `Computer.play_youtube(query)` opens that video, or the results page if none is found
  ("Here are the YouTube results.").
- New action `play_youtube: <what to play>` in `commands.yaml` and for Claude
  (`ACTION play_youtube: …`). The example "play {query} on youtube" command uses it.
- **Done when:** tests cover finding the result (ads/Shorts skipped, split reads), the fallback
  and both kinds of actions with fakes; a live lookup finds the right video in about a second.

### Story 22: Answer Claude's questions without the wake word
- When Claude's reply to a spoken request ends with a question, Abdoh plays the listening chime
  and listens for up to 5 s, as if the hotkey was pressed; the answer goes to Claude with the
  previous exchange as context. Not after typed requests, or when you stopped the reply.
  `claude.listen_after_question: true` (false turns it off).
- **Done when:** tests with a fake mic cover answering without the wake word, and no extra
  listening after a statement, a typed request, a stopped reply, or with the setting off.

### Story 23: Claude can work with your files
- `claude.allow_files: true` (default): Claude Code also gets `Write`, `Edit`, `Glob`, `Grep` and
  `PowerShell` (`Bash` elsewhere), and `--add-dir` for your home folder (plus any of your main
  folders that live outside it). `--restricted` stays on: your settings files are ignored, file
  tools stay inside those folders, and writes to settings and git files are refused.
- The system prompt names your Desktop, Documents, Downloads and Pictures folders (following
  OneDrive), and tells Claude to ask before deleting or overwriting files and to delete to the
  Recycle Bin. With story 22 you just answer "yes".
- `claude.timeout_seconds` default 120 (file jobs take longer than questions).
- **Done when:** tests cover the command line and prompt with and without file access; manually,
  Claude counts, converts and (after asking) deletes test files in a scratch folder.

---

## 8. Later (not part of this epic; don't build)
- Interrupting Abdoh by voice while it talks (needs echo cancellation).
- A nicer local voice (Piper) and Arabic wake word and replies.
- Hotkey and installer for macOS/Linux; auto-update.
- Whisper on onnxruntime (already loaded for the wake word and VAD) or whisper.cpp, to cut
  ~150 MB of idle RAM and reach the 250 MB goal.
- Keep one Claude Code process warm to save ~0.6 s per Claude answer (costs memory).

---

## 9. Steps only I can do
- Train the "Hey Abdoh" wake word model in the Colab notebook and copy the `.onnx` to `models/`.
- Replace `REPLACE_ME` in `commands.yaml` with my real playlist link.
- Check that Claude Code is signed in with my Pro account (`claude auth status`).
- Optional: add an Anthropic API key for the API backend.
- Run `abdoh install`, reboot, and check that Abdoh starts and answers.

---

## 10. Definition of done (whole epic)
- [ ] Abdoh runs as a tray app, starts at login, and opens from the Start Menu.
      Built (tray, `abdoh install`, start at login); the after-reboot check is mine to do.
- [ ] "Hey Abdoh" (openWakeWord) or the hotkey starts a request; false wake-ups are rare.
      Built; waiting for my trained `hey_abdoh.onnx` (the hotkey works without it).
- [x] Hardcoded commands and built-in skills start answering ~1 s after I stop talking.
      Measured 1.25 s plus ~0.1 s to start speaking (was ~3 s).
- [x] Everything else goes to Claude through my Pro subscription, answered by voice, first words
      within ~3 s for simple questions; Claude can open links and apps for me.
      Measured 3.3 s to the first words; most of it is Claude Code itself (~2 s).
- [x] "Remember that" turns what Claude did into an instant command.
- [ ] Idle RAM ≤ 250 MB. Not met: ~320 MB with openWakeWord (was ~410 MB). Whisper's
      CTranslate2 runtime alone is ~170 MB whatever the model size (see Later).
- [x] All tests pass; `main` is pushed and up to date.
