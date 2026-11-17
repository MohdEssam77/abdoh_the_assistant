# Abdoh

A simple, voice-first personal assistant for your laptop. Say "Hey Abdoh" (or press
Ctrl+Alt+Space) and a request: Abdoh runs your own commands (open a link, open an app, tell the
time), handles everyday things by itself (timers, volume and music, opening any app), and sends
everything else to Claude, using your Claude subscription through Claude Code. It replies by
voice and lives in the system tray.

Speech recognition runs offline on your machine (openWakeWord for the wake word, Parakeet and
Whisper for requests). Only Claude requests go over the network.

**Just want to use it?** Download `Abdoh-Setup.exe` from the download page (`docs/index.html`,
see section 6), install it, and follow the short setup. No Python or terminal needed. The rest
of this README is for running Abdoh from source.

## Setup checklist

1. Install Abdoh and download the models (sections 1 and 2).
2. Make sure Claude Code is signed in with your Claude account: `python -m abdoh claude-check`
   (section 4).
3. Say "Hey Abdoh" (or "Ya Abdoh"): the trained wake word model comes with Abdoh. The hotkey
   works without any wake word.
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

This downloads into `models/` the two small openWakeWord feature models (about 2 MB) and the **Parakeet** speech recognition
model (about 630 MB; English, the most accurate). It also copies the trained "Hey Abdoh" wake word model from
`assets/` if you don't have your own. Whisper models (used when you speak other languages)
download themselves the first time they're used.

### The wake word

Abdoh comes with a trained wake word model (`assets/hey_abdoh.onnx`, an openWakeWord model) for
**"Hey Abdoh"** and **"Ya Abdoh"** (also the Arabic يا عبدوه: it listens for the sound, not the
spelling). Say the wake word and keep talking; what you say after it is the request. In the
window, the sidebar shows `Wake word: openWakeWord (hey_abdoh)`.

If it misses you, move **Settings → Sensitivity** to the left (`wake_word_threshold`, e.g.
0.3); if it wakes up by itself, move it right (e.g. 0.6).

**Your own wake word.** Train an openWakeWord model in Google Colab (free, a couple of hours):

1. Open https://colab.research.google.com/github/alfiedennen/openwakeword-colab-2026/blob/main/train_wakeword.ipynb
   (the official notebook no longer runs on Colab). In **Runtime → Change runtime type** pick a
   **T4 GPU** and a **runtime version with Python 3.12**.
2. In cell 10, set `TARGET_PHRASE` to your phrases and `MODEL_NAME`. Use words an English
   dictionary knows ("hey abdo", not "hey abdoh"): the notebook's helper for made-up words is no
   longer downloadable.
3. Run all cells and download the `.onnx` file. Put it in `models/` and set `wake_word_model`
   in `config.yaml` to its path (with the installed app: `%APPDATA%\Abdoh\models\`).
4. Add your phrase to **Settings → Wake words**, so it's removed from what you say.

If the wake word model is missing or can't start, the status says **Hotkey only**: press the
hotkey (or the talk button) to talk to Abdoh, and typing works as always.

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

### Talking with Abdoh

- **Say the wake word and keep going**: "Hey Abdoh, what's the weather tomorrow?" A soft chime
  tells you it woke up. If you only say "Hey Abdoh", it answers "Yes?" and waits.
- **Keep talking**: after Claude answers, Abdoh listens for about six more seconds (one soft
  note), so you can go on without the wake word. Say "thanks" or stay quiet to end it.
- **Just start talking**: while Abdoh explains something, talk and it goes quiet at once and
  listens. "Okay" or "go on" lets it carry on from the same word; "wait" or "thanks" stops it;
  anything else becomes your next request, and Claude still remembers the conversation. If you
  add something while it's still thinking ("What's the weather" ... "in Paris"), both parts are
  one request. Abdoh hears you over its own voice by taking what the speakers play back out of
  the microphone (echo cancellation); that sound is only used in memory, never saved or sent.
  Works best with headphones or the volume not too loud. Under loud music or a film it may not
  hear you: use the wake word or the hotkey then. **How easily your voice stops Abdoh** (Low,
  Medium, High) is in Settings → Conversation. Check how well it works in your room with
  `python scripts/echo_check.py` (it speaks two sentences; `--talk` lets you try talking over it).
- **Interrupt with the wake word**: say "Hey Abdoh" while it's talking (or press the hotkey) to
  stop it and say something new.
- **Other sounds go down while you talk**: from the wake word until Abdoh has answered, every
  other app that is playing (your browser, Spotify, a film) drops to 30% of its volume in the
  Windows volume mixer, then comes back. Abdoh's own voice stays as it is, and an app you turned
  up or down yourself meanwhile keeps your volume.
- **Only today's conversation**: the chat in the window starts empty every day. The log file
  (which also has what you said) keeps today's and yesterday's only.
- **It keeps you posted**: before slow work Claude says so ("Let me look that up"), the window
  shows what it's doing ("Searching the web…"), and after a few quiet seconds Abdoh says it's
  still on it.
- **Other languages**: add the languages you speak in Settings. Abdoh answers in the language
  you used, with a Windows voice for it (add voices in Windows Settings → Time & language →
  Speech; the window tells you when one is missing).

Each of these can be turned off under **Settings → Conversation**.

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

Abdoh keeps one Claude Code conversation open while it runs, so Claude starts answering in
about a second and **remembers what you said** ("what's the capital of Japan?" ... "and how many
people live there?"). The conversation starts over after ten quiet minutes or when you change
Claude's settings; when you stop a reply, Claude stops writing it and still knows what it said. In Settings you can pick a faster Claude model
(**Model**: Haiku answers soonest and uses less of your plan).

Then you can say:

- "Abdoh, what's the capital of Japan?"
- "Abdoh, open the Python website" (Claude can open web pages and installed apps for you)
- "Abdoh, put on some relaxing jazz" (Claude can start YouTube videos too)
- "Abdoh, what's the weather in Cairo today?" (Claude can search the web; turn this off with
  `claude.allow_web: false`)
- Anything about what's on your screen: "what does this error mean?", "which of these should I
  pick?", "read this to me", "what am I looking at?". Claude decides when it needs to see it;
  Abdoh then says "Looking at your screen" and sends a picture of the screen you're using (the
  one with the window in front, not Abdoh's own window) with your question.
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

- **Timers**: "set a timer for 10 minutes", "cancel the timer"
- **Reminders**: "remind me to call my mother in 20 minutes", "remind me at 5:30 pm to leave",
  "remind me tomorrow at 9 to water the plants", "what are my reminders", "cancel my
  reminders". Abdoh says them aloud at their time; they survive a restart.
- **Notes**: "take a note: the door code is 4471", "read my notes", "open my notes" (they're
  lines in `notes.txt` in Abdoh's data folder)
- **Volume**: "set the volume to 70 percent", "volume up", "turn it down", "mute", "unmute",
  "what's the volume"
- **One app's volume** (the Windows volume mixer): "lower the browser", "turn up Spotify",
  "set the browser to 30 percent", "mute Discord", "unmute Discord", "what's playing?".
  "Browser" (or "YouTube") means every web browser.
- **Music**: "pause", "play", "next song", "previous song"
- **Screen**: "set the brightness to 60", "brighter", "dim the screen" (a laptop's own screen),
  "take a screenshot" (saved in Pictures\Screenshots)
- **Quick answers**: "what time is it", "what's the date", "how much battery do I have",
  "what's 15 percent of 80", "what's 12 times 12"
- **Typing**: "type best regards, Sam" types into the app in front
- **Windows**: "minimize this window", "maximize the window", "close this window", "show the
  desktop", "switch window", "lock my computer"
- **Screens**: "turn off monitor 3", "turn off the laptop screen", "only screen 2", "turn off
  the other screens" (keeps the one you're working on), "turn on all the screens", "which
  screens are on", "turn off the screens" (they sleep until you move the mouse). Abdoh numbers
  your monitors the first time it sees them (laptop first) and keeps those numbers; screens come
  back where they were. Try it with `python scripts/display_check.py` (it switches for 8 seconds
  and puts everything back).
- **Speakers**: "switch the sound to the monitor", "use the headphones", "play the sound through
  the speakers", "what's my audio output"
- **Settings**: "dark mode", "light mode", "best performance mode", "battery saver", "balanced
  power mode", "turn on night light", "night light off"
- **Sleep and shutdown**: "go to sleep", "shut down the computer", "restart the computer" (Abdoh
  asks first: just say yes), "shut down in 30 minutes" (no question: it's for later), "cancel the
  shutdown". These can be turned off in Permissions.
- **Programs**: "close Spotify", "switch to Chrome", "move Chrome to screen 2", "move this to the
  other screen", "snap this to the left"
- **Folders**: "open my downloads", "open my latest download", "open the newest screenshot"
- **Clipboard**: "copy that" (Abdoh's last answer), "read my clipboard". Claude gets your
  clipboard only when you mention it ("translate what I copied into French").
- **Apps**: "open {any installed app}", e.g. "open calculator", "open chrome", "open vs code".
  If no installed app matches, the request goes to Claude (so "open YouTube" still works).
- **Talking**: "repeat that", "what can you do", and "thanks" or "never mind" to end a
  conversation

Claude can also set the volume, one app's volume and the brightness, add reminders and take notes when you ask in
your own words ("wake me in half an hour", "jot down that I owe Sam ten euros"); each of these
can be turned off on the Permissions page. Claude can also switch your modes, your screens,
your speakers and dark mode: it knows your modes and your screens by name, so "I'm about to
watch a film" can switch on Movie mode and "put the picture only on the big monitor" turns the
others off. Claude can never type for you, press keys, close programs or shut the computer down.

Your own commands can use `volume: 30`, `app_volume: browser 30`, `brightness: 70` and
`type: some text` as actions too, and these: `displays: only 2`, `audio_output: headphones`,
`dark_mode: on`, `power_mode: balanced`, `power: screens_off`, `keys: win+d`, `wait: 2 seconds`,
`night_light: on`, `close_app: Spotify`, `focus_app: Chrome` and `window: Chrome to 2 maximized`.

These skills are Windows-only for now.

If the file has a mistake, Abdoh says "Your commands file has an error" and keeps using the last
working version. Check your commands without speaking:

```
python -m abdoh list-commands
python -m abdoh test-command "good morning abdoh"
```

### Modes

A mode switches a set of things at once, and puts them back when you're done. Say
"**movie mode**", "**switch to work mode**", and "**back to normal**" (or "exit movie mode") to
undo everything the mode changed. "Which mode am I in?" and "what modes do I have?" work too.

Make modes on the **Modes** page: pick an icon, click the screens to keep on in a drawing of your
desk, set the volume, brightness, speakers, theme and power, and add actions. **Save and try it**
switches it on; if your screens change, Abdoh asks "Keep these screens?" and goes back by itself
after 15 seconds. **Your screens** at the bottom shows Abdoh's numbers for your monitors, lets you
name them ("TV") or renumber them, and **Show the numbers on the screens** puts a big number on
each. The Home page shows the mode that's on (with a way back), and the tray icon has a **Modes**
menu. You can also write modes by hand in `modes.yaml` in Abdoh's data folder:

```yaml
- name: Movie
  settings:            # put back when the mode ends
    displays: [2]      # only screen 2 on ("all" for every screen)
    volume: 60
- name: Work
  settings:
    displays: all
    brightness: 100
  actions:             # run when the mode starts, like a command's
    - play_youtube: "jazz music"
    - open_app: "Visual Studio Code"
```

Settings: `displays`, `brightness`, `volume`, `audio_output`, `dark_mode`, `power_mode`,
`night_light`, and Abdoh's own `wake_word`, `voice_replies` and `follow_up`. Actions: anything a command can do,
plus `exit_actions` for when the mode ends. Switching from one mode to another first puts back
what the new one leaves alone. A mode that is on when Abdoh restarts can still be undone. Your
own commands can switch modes too (`mode: Movie`, `mode: normal`).

**A mode at a time.** A mode can switch on by itself: turn on **At** in the editor and pick a
time and days, or write `schedule: ["daily 23:00", "weekdays 09:00", "sat,sun 10:30"]` (days:
`daily`, `weekdays`, `weekends`, or `mon` to `sun` joined by commas; 24-hour time). Abdoh says
the mode aloud when it starts. Times that passed while Abdoh wasn't running are skipped.

**Night light** (Windows 11) is switched through a setting Windows doesn't document. Abdoh only
changes it when it recognizes how your Windows stores it; otherwise it opens the Night light
settings for you.

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

The folder (about 950 MB) contains Abdoh and the models in your `models/` folder (the
openWakeWord files, your `hey_abdoh.onnx` and the Parakeet speech model, so nothing downloads
on the first start). Double-click `Abdoh.exe` to start it. It keeps your
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

Measured on my laptop (Windows 11, i7-13650HX), 2026-11-16:

| What | Abdoh 0.3 | Abdoh 0.4 |
|---|---|---|
| A built-in skill or one of your commands | about 1 s after you stop talking | the same; the skill itself takes a few milliseconds |
| "Set the volume to 75%" | 18 s (Claude wrote PowerShell) | instant (built in) |
| Claude's first words | 2.1 to 2.8 s | 0.5 to 1.0 s (one Claude Code process stays open) |
| Understanding a 4-second request | 0.7 s (Whisper base.en) | 0.6 s (Parakeet) |
| Word errors on Arabic-accented English | 8.8% | 4.4% |
| Startup | about 5 s | about 6 s |
| Memory while idle | about 320 MB | about 860 MB (Parakeet's model is 630 MB) |
| CPU while idle | about 1.5% of one core | about 1.6% of one core |

Where the time goes for a request: 0.6 s to be sure you stopped talking (`silence_seconds`),
about 0.6 s to understand it, then the answer. Every request logs its own timings (lines
starting with `Timing:` in the log), so you can see which part is slow on your computer.

Short on memory? **Settings → Speech recognition → Quality → Lighter** uses Whisper instead of
Parakeet: about 700 MB less memory, about twice the mistakes.

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
| `wake_word_model` | `models/hey_abdoh.onnx` | Your openWakeWord model; without it, only the hotkey works |
| `wake_word_threshold` | `0.4` | openWakeWord: higher means fewer false wake-ups |
| `hotkey` | `ctrl+alt+space` | Press to talk without the wake word, or to stop a reply (`""` = off) |
| `wake_word_aliases` | `["abdo", "ab doe", "abdul", ...]` | Other spellings speech recognition may write for "Abdoh"; left out of your requests |
| `languages` | `["en"]` | What you speak to Abdoh. English only uses Parakeet (fastest, most accurate); with more languages (e.g. `["en", "ar"]`) Whisper is used and Abdoh answers in the language you spoke |
| `speech_engine` | `auto` | `auto`, `parakeet` (English only) or `whisper` (lighter: about 700 MB less memory, more mistakes) |
| `whisper_model` | `small` | Whisper size for other languages: `base` (fast), `small`, `medium` (slow) |
| `match_threshold` | `85` | How closely speech must match a trigger (0-100) |
| `silence_seconds` | `0.6` | Pause that ends a request (detected by voice activity, not loudness) |
| `max_record_seconds` | `10` | Longest request |
| `follow_up_seconds` | `6` | After Claude answers, keep listening this long without the wake word (0 = off) |
| `wake_word_interrupts` | `true` | Saying the wake word stops a reply (needs the trained wake word model) |
| `voice_interrupts` | `true` | Just start talking to stop a reply (no wake word) |
| `voice_interrupt_sensitivity` | `medium` | `low`, `medium` or `high`: how easily your voice stops a reply |
| `allow_power` | `true` | Abdoh may put the computer to sleep, shut it down or restart it when you ask |
| `duck_others` | `true` | Other apps go quieter while Abdoh listens and answers |
| `duck_percent` | `30` | ... to this share of their own volume |
| `tts_rate` | `175` | Speaking speed |
| `tts_voice` | `""` | A Windows voice's name; empty means the default voice |
| `mic_device` | `""` | A microphone's name; empty means Windows' default microphone |
| `allow_run` | `false` | Allow `run:` actions |
| `check_updates` | `true` | Look for a new version once a day |
| `setup_done` | `false` | The first-start setup was finished or skipped |
| `claude.backend` | `auto` | `auto` (Claude Code if installed, else API key), `code`, `api`, or `off` |
| `claude.code_path` | `""` | Where `claude.exe` is; empty means find it automatically |
| `claude.code_model` | `""` | Claude Code model: `haiku` (fastest), `sonnet`, `opus`; empty means your Claude Code default |
| `claude.model` | `claude-opus-5-5` | Model when using an API key |
| `claude.effort` | `low` | How hard Claude thinks; `low` answers fastest |
| `claude.allow_web` | `true` | Let Claude search the web (Claude Code) |
| `claude.allow_files` | `true` | Let Claude work with the files in your user folder and run PowerShell; it asks before deleting or overwriting (Claude Code) |
| `claude.folders` | `[]` | Only these folders for Claude's file work; empty means your whole user folder |
| `claude.allow_screen` | `true` | Let Claude look at the screen you're using when you ask about it |
| `claude.actions` | all fourteen | What Claude may do: `open_url`, `open_app`, `play_youtube`, `media`, `timer`, `volume`, `brightness`, `app_volume`, `remind`, `note`, `mode`, `displays`, `audio_output`, `dark_mode` |
| `claude.instructions` | `""` | Your own instructions, sent to Claude with every request |
| `claude.timeout_seconds` | `120` | Give up on an answer after this long |
| `claude.followup_seconds` | `60` | API key only: a question this soon after an answer can follow up on it (0 = off). Claude Code remembers the whole conversation by itself |
| `claude.listen_after_question` | `true` | When Claude asks you something, listen for your answer without the wake word |
| `claude.translate_target` | `English` | Default language for screen translation |
| `claude.voice_reply_max_sentences` | `4` | Keeps spoken answers short |
| `log_file` | `~/.abdoh/abdoh.log` | Log file (today's and yesterday's) |

## Troubleshooting

**Abdoh doesn't wake up.** The window's `Wake word:` line shows which engine is used. With your
openWakeWord model, lower `wake_word_threshold`. If it says **Hotkey only**, the model couldn't
start: the log says why. `python -m abdoh listen-once` should print your request.

**Abdoh wakes up by itself.** Raise `wake_word_threshold` (for example to 0.5 or 0.6).

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
- `scripts/display_check.py`: turns all monitors but one off for 8 seconds, then back on.
- `scripts/echo_check.py`: measures how well Abdoh hears you over its own voice in your room
  (it speaks; `--talk` to try talking over it).

## Known issues

- **Talking over Abdoh is weaker under loud sound.** With music or a film playing loudly on the
  speakers, Abdoh may not notice you start talking; the wake word and the hotkey still work.
  Measured on a laptop with its own speakers and microphone: it heard the user within 0.3 s and
  never mistook its own voice for theirs. In a simulated loud room it heard normal speech in
  about 0.3 s; a quiet voice under a loud, distorting speaker took up to 3 s.

- **Memory while idle is about 860 MB**: the Parakeet speech model is big. The Lighter quality
  setting (Whisper) brings it down to about 350 MB.
- **English is the most accurate language.** Other languages use Whisper (`small` by default),
  which is slower and makes more mistakes; `medium` is better if your computer is fast.
- **Replies in other languages need a Windows voice for that language** (Windows Settings → Time
  & language → Speech). Without one, the reply is only shown.
- **Speech on macOS and Linux is untested with pyttsx3 2.99.** On Windows that version cut
  every reply off, so Abdoh now uses the Windows voice directly there; macOS and Linux still go
  through pyttsx3.
- **The installer isn't code-signed**, so Windows SmartScreen warns the first time ("Windows
  protected your PC": click **More info → Run anyway**). Signing needs a paid certificate.
