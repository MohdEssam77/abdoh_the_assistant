# Abdoh

A simple, voice-first personal assistant for your laptop. Say "Hey Abdoh" (or press
Ctrl+Alt+Space) and a request: Abdoh runs your own commands (open a link, open an app, tell the
time), handles everyday things by itself (timers, volume and music, opening any app), and sends
everything else to Claude, using your Claude subscription through Claude Code. It replies by
voice and lives in the system tray.

Speech recognition runs offline on your machine (openWakeWord or Vosk for the wake word, Whisper
for requests). Only Claude requests go over the network.

**Just want to use it?** Download `Abdoh-Setup.exe` from the download page (`docs/index.html`,
see section 6), install it, and follow the short setup. No Python or terminal needed. The rest
of this README is for running Abdoh from source.

## Setup checklist

1. Install Abdoh and download the models (sections 1 and 2).
2. Make sure Claude Code is signed in with your Claude account: `python -m abdoh claude-check`
   (section 4).
3. Train your "Hey Abdoh" wake word in Google Colab and save it as `models/hey_abdoh.onnx`
   (section 2). Until then the hotkey works without any wake word.
4. Put your own links and apps in `commands.yaml`, e.g. replace `REPLACE_ME` in `good_morning`
   (section 5).
5. `python -m abdoh install --login` to add Abdoh to the Start Menu and start it at login
   (section 6). Restart your computer and check that the tray icon appears and Abdoh answers.

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

This downloads into `models/` the two small openWakeWord feature models (about 2 MB), the Vosk
wake word model (about 40 MB, a fallback), and the **Parakeet** speech recognition model (about
630 MB; English, the most accurate). It also copies the trained "Hey Abdoh" wake word model from
`assets/` if you don't have your own. Whisper models (used when you speak other languages)
download themselves the first time they're used.

### Train your "Hey Abdoh" wake word (recommended)

The general-purpose Vosk model doesn't know the word "Abdoh", so out of the box Abdoh listens for
similar words and sometimes misses you or wakes up by itself. A custom openWakeWord model fixes
that, and it's lighter. Training is free and takes under an hour, with no setup on your computer:

1. Open the official openWakeWord training notebook in Google Colab:
   https://colab.research.google.com/drive/1q1oe2zOyZp7UsB3jJiQ1IFn8z5YfjwEb?usp=sharing
2. Enter your wake phrase. It is spoken by a synthetic voice, so spell it the way it sounds
   ("hey abdo" or "hey ab doe") and use the notebook's sample playback to check that it sounds
   like you saying "Hey Abdoh".
3. Run the notebook and download the `.onnx` model it produces.
4. Save it as `models/hey_abdoh.onnx` (or point `wake_word_model` in `config.yaml` at it).
5. Restart Abdoh. The window shows `Wake word: openWakeWord (hey_abdoh)`.

If it misses you, lower `wake_word_threshold` (e.g. 0.4); if it wakes up by itself, raise it
(e.g. 0.6). Keep "abdoh" in `wake_words`: Abdoh checks the transcript for it, which filters out
the occasional false wake-up before anything is sent to Claude.

## 3. Run

```
python -m abdoh run              # starts Abdoh in the system tray and starts listening
python -m abdoh run --show       # same, with the window open
python -m abdoh run --headless   # no window or tray icon at all (Ctrl+C to quit)
```

On first run Abdoh creates `config.yaml` and `commands.yaml` from the example files. Try:

- "Good morning Abdoh"
- "Hey Abdoh, what time is it"
- "Hey Abdoh, play Bohemian Rhapsody on YouTube" (starts the top video)
- Press **Ctrl+Alt+Space** and say "what time is it" (no wake word needed)

**The tray icon** shows Abdoh's state by color: green = listening, blue = thinking or speaking,
gray = paused, red = a problem. Click it to open the window; right-click for the menu: pause or
resume listening, stop speaking, voice replies on/off, edit commands, start at login, and quit.

**The hotkey** (`Ctrl+Alt+Space`, set `hotkey` in `config.yaml`) works from any app: press it
and talk, no wake word needed (it works even while listening is paused). Press it while Abdoh
is talking to stop it. Windows only for now.

**The window** is a modern app (light or dark, following Windows). **Home** shows what Abdoh is
doing and the conversation. Type a request (it goes through the same commands and Claude as
voice), press the round **Talk** button (same as the hotkey; it becomes a stop button while
Abdoh is busy), turn the **Wake word** off to stop listening for it, or turn **Voice replies**
off. Closing the window only hides it; Abdoh keeps listening. Bring it back from the tray, by
saying "Abdoh, show window", or by running `python -m abdoh run` again. Quit from the tray menu.

The first time it opens, a short **setup** checks that Abdoh hears your microphone (with a live
level meter), lets you pick a voice, connects your Claude, and shows how to talk to Abdoh. Skip
it any time; **Settings → Run setup again** brings it back.

The window uses Microsoft WebView2, which comes with Windows 10 and 11. Without it, Abdoh falls
back to its old, simple window.

### Voice controls

- "Abdoh, stop listening": Abdoh ignores everything until "Abdoh, start listening" (or the hotkey)
- "Abdoh, reload commands": re-reads `commands.yaml` (it also reloads automatically on change)
- "Abdoh, show window": brings the window back

## 4. Connect Claude (optional)

Anything that isn't one of your commands goes to Claude. Abdoh uses **your Claude subscription**
(Pro or Max) through **Claude Code**, so there's nothing to pay for beyond your plan:

The easy way: open **Settings** in Abdoh's window. The **Claude** card shows whether you're
connected and with which plan. **Install Claude Code** runs Anthropic's official installer in a
window you can watch (for you only, no admin rights). **Sign in with Claude** opens Claude Code's
own sign-in, which finishes in your browser; the card updates by itself when you're done.
**Test** asks Claude one word. Abdoh never sees your password or your Claude login: it only
asks Claude Code whether it's signed in. Each person who uses Abdoh connects their own Claude.

Claude's **free plan doesn't include Claude Code**. Without Pro, Max, Team or Enterprise, paste
an API key from the Claude Console into the same card (pay as you go, kept only on this
computer), or use Abdoh without Claude: commands, timers, apps, media and YouTube all work.

By hand:

1. Have Claude Code installed and signed in with your Claude account. Abdoh finds it on your
   `PATH`, in `~/.local/bin`, or inside the VS Code extension. If it's somewhere else, set
   `claude.code_path` in `config.yaml`.
2. Check it:

   ```
   python -m abdoh claude-check    # shows e.g. "Claude: Pro subscription (Claude Code)" and asks one tiny question
   ```

Then you can say:

- "Abdoh, what's the capital of Japan?"
- "Abdoh, open the Python website" (Claude can open web pages and installed apps for you)
- "Abdoh, put on some relaxing jazz" (Claude can start YouTube videos too)
- "Abdoh, what's the weather in Cairo today?" (Claude can search the web; turn this off with
  `claude.allow_web: false`)
- "Abdoh, translate what's on my screen" (into `translate_target`, default English), or
  "translate my screen to Arabic"
- "Abdoh, summarize my screen"
- "Abdoh, how many files are in my Downloads?", "make a folder called Taxes in my Documents and
  move the PDFs from Downloads into it", "convert the photos on my desktop to PNG" (Claude can
  work with your files, see below)

**Your files.** Claude can find, read, create, move, rename and convert files in your user
folder (including a Desktop or Documents folder that OneDrive moved), running PowerShell when it
needs to. Before it deletes or overwrites anything, it says what it will do and asks; just
answer "yes" (no wake word needed). Deleted files go to the Recycle Bin. Abdoh can mishear you,
so listen to what Claude says it's about to do. `claude.allow_files: false` turns this off.

**Make it instant next time.** When Claude did something for you ("open the Python website"),
say **"Abdoh, remember that"** (or "remember that as python time"). Abdoh adds it to
`commands.yaml` as a normal command, so next time it happens instantly, without Claude. The rest
of your file is left as it is.

**Follow-up questions.** Within a minute of an answer you can follow up ("and what about
tomorrow?"); Abdoh gives Claude the previous question and answer. Change the window with
`claude.followup_seconds` (0 turns it off).

**When Claude asks you something** ("Which city?"), just answer: after a question Abdoh plays
the listening chime and listens for about 5 seconds, no wake word needed. If you say nothing, it
goes back to waiting for "Hey Abdoh". This only happens after spoken requests, not typed ones;
`claude.listen_after_question: false` turns it off.

Abdoh plays a soft tick while Claude works and starts speaking as soon as the first sentence of
the answer arrives. Each request runs Claude Code from its own folder (`~/.abdoh/claude`) with
only the tools Abdoh allows and your Claude Code settings and plugins ignored, and nothing is
added to your Claude Code history. Links Claude opens must be web links (`http`/`https`), and
apps are opened by name from your installed apps. With `allow_files: false`, Claude can't touch
your files or run commands.
Your Claude plan's usage limits apply; if you hit one, Abdoh tells you when it resets.

**No subscription?** Abdoh can use an Anthropic API key from https://console.anthropic.com
instead: click **Set Claude key** in the window (or put `ANTHROPIC_API_KEY=...` in `.env`, see
`.env.example`). Claude Code is used first when it's installed; set `claude.backend: api` to
always use the key.

Without Claude, everything else still works and Abdoh tells you Claude isn't connected.

## 5. Your commands

Open the window's **Commands** page (or **Commands** in the tray menu). Each command has the
phrases you say and the actions Abdoh runs, in order: say something, open a website or an app,
play on YouTube, press a media key, start a timer, or run a program. Click a command to change
it, **Try it** to run it now, **New command** to add one, or **Templates** to start from a
ready-made one (good morning, focus time, Google search, directions, ...). Abdoh checks every
command before saving it, and uses it right away.

The commands live in `commands.yaml`, which you can also edit by hand. Don't include "Abdoh" in
triggers; the wake word is removed before matching. Small transcription mistakes are tolerated.
Changes are picked up automatically.

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

# {slots} catch whatever you say in that spot: "search youtube for lo-fi beats"
- name: youtube_search
  triggers: ["search youtube for {query}"]
  actions:
    - open_url: "https://www.youtube.com/results?search_query={query}"

- name: youtube_play
  triggers: ["play {query} on youtube"]
  actions:
    - play_youtube: "{query}"

- name: focus
  triggers: ["focus mode"]
  actions:
    - media: play_pause
    - timer: "25 minutes"
    - say: "Focus mode on."

- name: backup
  triggers: ["back up my notes"]
  actions:
    - run: "robocopy C:\\notes D:\\backup\\notes /MIR"
    - say: "Backup started."
```

| Action | What it does |
|---|---|
| `say: <text>` | Speaks the text. `{time}`, `{date}` and your `{slots}` are filled in. |
| `open_url: <url>` | Opens the link in your default browser (`{slots}` are made safe for links). |
| `open_app: <name or path>` | Opens an app, e.g. "Visual Studio Code", "notepad", or a full path. |
| `play_youtube: <words>` | Plays the top YouTube video for those words (about a second to find it). If none is found, opens the search results. |
| `media: <key>` | Presses a media key: `play_pause`, `next`, `previous`, `volume_up`, `volume_down`, `mute`. |
| `timer: <duration>` | Starts a timer, e.g. `"25 minutes"`; Abdoh tells you when it's done. |
| `run: <shell command>` | Runs a command. Off by default: set `allow_run: true` in `config.yaml`. Can't use `{slots}`. |

Every trigger of a command must have the slots its actions use. A trigger without slots that
matches exactly wins over one with slots.

### What Abdoh does by itself

These work instantly, without Claude (your own commands still come first):

- Timers: "Abdoh, set a timer for 10 minutes", "cancel the timer"
- Volume and music: "volume up", "turn it down", "mute", "pause", "play", "next song",
  "previous song"
- "Abdoh, lock my computer"
- "Abdoh, open {any installed app}", e.g. "open calculator", "open chrome", "open vs code". If no
  installed app matches, the request goes to Claude (so "open YouTube" still works).

Media keys, locking and opening installed apps are Windows-only for now.

If the file has a mistake, Abdoh says "Your commands file has an error" and keeps using the last
working version. Check your commands without speaking:

```
python -m abdoh list-commands
python -m abdoh test-command "good morning abdoh"
```

## 6. Install it like an app

```
python -m abdoh install            # adds "Abdoh" to the Start Menu, with its own icon
python -m abdoh install --login    # ...and starts it at login, in the tray
python -m abdoh uninstall          # removes both
```

Run these with the Python where Abdoh is installed (the `.venv`). The shortcut starts Abdoh
with `pythonw` (no console window) and opens its window; if Abdoh is already running, it just
shows the window.

You can also turn start at login on and off with **Start at login** in the tray menu, or with
the scripts (they do the same):

```
python scripts/install_autostart.py
python scripts/uninstall_autostart.py
```

Only one copy of Abdoh ever runs.

- **Windows:** a Task Scheduler task "Abdoh" running `pythonw -m abdoh run --minimized` (no console
  window). Creating logon tasks needs admin rights on many PCs; without them the script adds Abdoh
  to your user's startup programs instead (`HKCU\...\Run`), which works the same way.
- **macOS:** `~/Library/LaunchAgents/com.abdoh.agent.plist` (restarted if it crashes, not after Quit).
- **Linux:** `~/.config/systemd/user/abdoh.service`, enabled with `systemctl --user enable --now abdoh`.

### A standalone Abdoh.exe (Windows)

To get an app folder that runs without Python (for example to copy to another PC):

```
pip install -e .[build]
python scripts/build_app.py        # about 3 minutes; creates dist/Abdoh/Abdoh.exe
```

The folder (about 550 MB) contains Abdoh and the models in your `models/` folder (the
openWakeWord files, your `hey_abdoh.onnx`, the Vosk fallback, and the Whisper speech model, so
nothing downloads on the first start). Double-click `Abdoh.exe` to start it. It keeps your
`config.yaml`, `commands.yaml` and `.env` in `%APPDATA%\Abdoh` (created on first start), and a
model you put in `%APPDATA%\Abdoh\models` is used instead of the bundled one. `Abdoh.exe install`
adds the built app to the Start Menu.

### The installer and releases (Windows)

`Abdoh-Setup.exe` is a normal Windows installer: it installs Abdoh for the current user (no admin
rights), adds it to the Start Menu, can add a desktop shortcut and start Abdoh at sign-in, and
comes with an uninstaller (your settings in `%APPDATA%\Abdoh` are kept). To build it yourself,
install [Inno Setup 6](https://jrsoftware.org/isdl.php), then:

```
pip install -e .[build]
python scripts/build_installer.py   # builds the app, then dist/Abdoh-Setup.exe
```

**To publish a release**, bump `__version__` in `src/abdoh/__init__.py` (for example to
`0.3.1`), commit, then tag and push it:

```
git tag v0.3.1
git push origin v0.3.1
```

GitHub Actions (`.github/workflows/release.yml`) runs the tests, builds `Abdoh-Setup.exe` on
Windows and publishes it as a GitHub Release. The download page and the app's update check
always point at the latest release. To bundle a trained wake word model, upload it somewhere
(for example as an asset of a release) and set the repository variable `WAKE_WORD_URL` to its
download link.

Abdoh checks for a new release once a day (Settings → **Check for updates**; it only asks
GitHub for the latest version number) and shows a **Download** button when there is one.

### The download page

`docs/index.html` is Abdoh's download page: a **Download for Windows** button that always gets
the latest release's `Abdoh-Setup.exe`, what Abdoh does, how to connect your own Claude, and a
FAQ (SmartScreen, requirements, plans, privacy, uninstalling). To put it online with GitHub
Pages: repository **Settings → Pages → Deploy from a branch**, branch `main`, folder `/docs`.
It's then at `https://mohdessam77.github.io/abdoh_the_assistant/`. Refresh its screenshots with
`python scripts/take_screenshots.py` (they use the app's demo data). If the releases move to
another repository, change `REPO` at the bottom of the page and in `src/abdoh/updates.py`.

## How fast and how light

Measured on my laptop (Windows 11), from the end of your speech to the start of Abdoh's reply:

| | Version 1 | Now |
|---|---|---|
| "What time is it" (a command) | about 3 s | about 1.3 s |
| A question for Claude (first words) | API key only; waited for the whole answer | about 3.3 s |
| Start-up | about 9 s | about 2.5 s |
| Memory while idle | about 410 MB | about 320 MB with your openWakeWord model (410 MB with Vosk) |
| CPU while idle | about 2% of one core | about 1.5% of one core |

Where the time goes for a command: 0.6 s to be sure you stopped talking (`silence_seconds`),
about 0.5 s to transcribe (Whisper `base.en`), and 0.1 s to start speaking. Claude adds about
2 s to start Claude Code and get the first sentence; the rest of the answer is spoken while it
arrives. To make commands snappier, try `silence_seconds: 0.5`, or `whisper_model: tiny` (about
0.25 s faster to transcribe, a bit less accurate). Most of the memory is Whisper's speech engine
(about 170 MB whatever the model size).

Developers can measure this themselves without a microphone:
`python scripts/measure_latency.py "Hey Abdoh, what time is it?"`.

## Configuration

Most of these are on the window's **Settings** and **Permissions** pages, which save to
`config.yaml` and keep its comments. Changes apply right away; the hotkey, wake words, speech
model and language need a restart (the Settings page offers a **Restart now** button).

`config.yaml` (created from `config.example.yaml`; set `ABDOH_HOME` to keep these files elsewhere):

| Key | Default | Meaning |
|---|---|---|
| `wake_words` | `["abdoh", "hey abdoh", "ya abdoh"]` | What you say to wake Abdoh; removed from requests before matching |
| `wake_word_model` | `models/hey_abdoh.onnx` | Your openWakeWord model; without it, Vosk is used |
| `wake_word_threshold` | `0.4` | openWakeWord: higher means fewer false wake-ups |
| `hotkey` | `ctrl+alt+space` | Press to talk without the wake word, or to stop a reply (`""` = off) |
| `wake_word_aliases` | `["abdo", "ab doe", "abdul", ...]` | Vosk only: similar words it listens for (see Troubleshooting) |
| `languages` | `["en"]` | What you speak to Abdoh. English only uses Parakeet (fastest, most accurate); with more languages (e.g. `["en", "ar"]`) Whisper is used and Abdoh answers in the language you spoke |
| `speech_engine` | `auto` | `auto`, `parakeet` (English only) or `whisper` (lighter: about 700 MB less memory, more mistakes) |
| `whisper_model` | `small` | Whisper size for other languages: `base` (fast), `small`, `medium` (slow) |
| `match_threshold` | `85` | How closely speech must match a trigger (0-100) |
| `silence_seconds` | `0.6` | Pause that ends a request (detected by voice activity, not loudness) |
| `max_record_seconds` | `10` | Longest request |
| `tts_rate` | `175` | Speaking speed |
| `tts_voice` | `""` | A Windows voice's name; empty means the default voice |
| `mic_device` | `""` | A microphone's name; empty means Windows' default microphone |
| `allow_run` | `false` | Allow `run:` actions |
| `check_updates` | `true` | Look for a new version once a day |
| `setup_done` | `false` | The first-start setup was finished or skipped |
| `claude.backend` | `auto` | `auto` (Claude Code if installed, else API key), `code`, `api`, or `off` |
| `claude.code_path` | `""` | Where `claude.exe` is; empty means find it automatically |
| `claude.code_model` | `""` | Claude Code model (e.g. `sonnet`); empty means your Claude Code default |
| `claude.model` | `claude-opus-5-5` | Model when using an API key |
| `claude.effort` | `low` | How hard Claude thinks; `low` answers fastest |
| `claude.allow_web` | `true` | Let Claude search the web (Claude Code) |
| `claude.allow_files` | `true` | Let Claude work with the files in your user folder and run PowerShell; it asks before deleting or overwriting (Claude Code) |
| `claude.folders` | `[]` | Only these folders for Claude's file work; empty means your whole user folder |
| `claude.allow_screen` | `true` | Let Claude look at your screen when you ask (translate, summarize) |
| `claude.actions` | all five | What Claude may do: `open_url`, `open_app`, `play_youtube`, `media`, `timer` |
| `claude.instructions` | `""` | Your own instructions, sent to Claude with every request |
| `claude.timeout_seconds` | `120` | Give up on an answer after this long |
| `claude.followup_seconds` | `60` | A question this soon after an answer can follow up on it (0 = off) |
| `claude.listen_after_question` | `true` | When Claude asks you something, listen for your answer without the wake word |
| `claude.translate_target` | `English` | Default language for screen translation |
| `claude.voice_reply_max_sentences` | `4` | Keeps spoken answers short |
| `log_file` | `~/.abdoh/abdoh.log` | Log file |

## Troubleshooting

**Abdoh doesn't wake up.** The window's `Wake word:` line shows which engine is used. With your
openWakeWord model, lower `wake_word_threshold`. With Vosk (no model yet), which doesn't know the
word "Abdoh": run `python -m abdoh calibrate`, say "Abdoh" five times, and add the words it
prints to `wake_word_aliases`, or better, train a model (see section 2). Either way,
`python -m abdoh listen-once` should print your request.

**Abdoh wakes up by itself.** False wake-ups are checked against the Whisper transcript and
ignored silently (you'll see "Ignoring false wake-up" in the log). If it still reacts too often,
raise `wake_word_threshold` (openWakeWord) or remove short or common words from
`wake_word_aliases` (Vosk).

**The tray icon is red and the status says "the speech recognition model couldn't be loaded".**
Voice input is off because the Whisper model is missing or broken (an interrupted download
leaves an empty `model.bin`); typing still works. From source, run
`python scripts/download_models.py`; with the installed app, install the latest version. If you
changed the speech model in Settings, delete its folder in
`%USERPROFILE%\.cache\huggingface\hub` (`models--Systran--faster-whisper-...`) and restart
Abdoh to download it again. The log (Settings → Open logs) has the details.

**Abdoh chimes, then nothing happens** (or it says "Your microphone may be muted"). It didn't
hear you. Abdoh uses your default microphone: on Windows open Settings → System → Sound →
Input, choose the microphone you talk into, make sure it isn't muted, and set its volume to
about 80%. A webcam's microphone is often the default.

**You can't hear Abdoh.** It speaks through your default speakers with the Windows voice. Check
that the window says **Voice replies: On** and that your volume is up, then try
`python -m abdoh say "Hello"`.

**No microphone / mic permission.** Check your OS privacy settings allow microphone access for
Python (Windows: Settings → Privacy & security → Microphone, "Let desktop apps access your
microphone"; macOS: System Settings → Privacy & Security → Microphone for Terminal/Python). If the
mic is unplugged, Abdoh retries every 5 seconds.

**Screen translate/summarize says the screenshot is black.** On macOS, give Terminal (or Python)
**Screen Recording** permission in System Settings → Privacy & Security, then restart Abdoh.

**Claude doesn't answer.** Run `python -m abdoh claude-check`. If it says Claude Code isn't
signed in, open Claude Code and sign in with your Claude account (`claude auth status` shows the
current login). If Claude Code isn't found, set `claude.code_path`. With an API key instead,
check the key in `.env` and that `claude.model` is a model your key can use.

**Edit commands opens nothing on Windows.** If no app is associated with `.yaml` files, Abdoh
opens Notepad.

**See what's happening.** Logs are in `~/.abdoh/abdoh.log`. For more detail, including timing
for each stage (recording, transcription, reply), run `python -m abdoh -v run`.

## Development

```
ruff check . --fix && ruff format . && pytest -q
```

Unit tests never need a microphone, speakers, network, API key or Claude Code. `ABDOH_EPIC_2.md`
is the current plan (`ABDOH_EPIC.md`, v1, is done) and `CLAUDE.md` has the working rules.

Developer scripts:

- `scripts/measure_latency.py`: time from the end of a spoken request to Abdoh's reply.
- `scripts/check_wakeword.py`: checks Abdoh's openWakeWord code against the official package
  (needs `pip install openwakeword`).
- `scripts/build_app.py`: builds `dist/Abdoh/Abdoh.exe` (needs `pip install -e .[build]`).

## Known issues

- **Memory while idle is about 320 MB**, more than the 250 MB goal: Whisper's speech engine
  (CTranslate2) takes about 170 MB by itself, even with the smallest model.
- **Speech on macOS and Linux is untested with pyttsx3 2.99.** On Windows that version cut
  every reply off, so Abdoh now uses the Windows voice directly there; macOS and Linux still go
  through pyttsx3.
- **The installer isn't code-signed**, so Windows SmartScreen warns the first time ("Windows
  protected your PC": click **More info → Run anyway**). Signing needs a paid certificate.
- TODO(blocked): **downloads aren't public yet.** The GitHub repository is private, so its
  releases (and a GitHub Pages download page) can't be reached by other people. Make the
  repository public, or publish the releases from a separate public repository.
- TODO(blocked): **the "Hey Abdoh" wake word model isn't trained yet.** Training happens in Google
  Colab with your Google account (section 2). Until `models/hey_abdoh.onnx` exists, Abdoh uses
  the Vosk fallback, which doesn't know the word "Abdoh": it misses some wake-ups and wakes up on
  similar words (those are ignored after transcription). The hotkey (`Ctrl+Alt+Space`) works
  without any wake word.
