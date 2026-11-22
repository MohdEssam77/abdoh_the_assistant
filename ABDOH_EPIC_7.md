# EPIC 7: Abdoh knows its setup, plays roles, edits itself and remembers you

> **For Claude Code:** This file is your source of truth for the seventh epic. Epics 1 to 6 are
> done; their architecture and section 5 of `ABDOH_EPIC_5.md` and `ABDOH_EPIC_6.md` (ground
> rules) still apply unless this file changes them. Work through the stories **in order** and
> follow the working rules in `CLAUDE.md` exactly. Keep everything **simple**.
>
> **Start here:** on the first story branch, your first commit changes the first paragraph of
> `CLAUDE.md` to name `ABDOH_EPIC_7.md` as the current source of truth (epics 1 to 6 done), and
> adds this file (`docs: epic 7 plan`). Then read sections 2, 4 and 5 before writing code.

---

## 1. Goal

Abdoh 0.8 wakes for its owner, talks naturally, runs modes and sees the screen. The owner now
wants:

1. **Devices that follow Windows.** After undocking, Abdoh still listened to the Lenovo
   camera's microphone, and Settings didn't list the headset. The microphone list, the default
   microphone and the speakers must follow Windows while Abdoh runs, also after sleep.
2. **Modes that know the setup.** A mode made for three screens, switched on with only the
   laptop screen, asks first: "Study mode wants screens 2 and 3, but only your laptop screen is
   connected. Run it on the laptop screen?"
3. **It hears you when you talk to it, and stays out of talk that isn't for it.** No request
   is dropped without a sound, Claude knows how clearly its name was said, and Claude can move
   windows.
4. **Act as.** "Act as my German teacher": Abdoh teaches in German, slowly. "Act as my math
   teacher, look at this": it explains like a teacher. Stopping understands any wording ("no
   need to act anymore", "I'm good, you can stop being my teacher"). What is better seen than
   heard (code, equations, worked steps, word lists) is shown on a **board** on the new Act as
   page.
5. **Abdoh edits itself.** "Make a command called good evening that locks the screen" creates
   it, asking for anything missing. The same for modes and roles. It's in the app next time.
6. **Memory.** Abdoh remembers what it learns about the owner and lessons from its own
   mistakes, and the owner can see, change and delete all of it.

### Non-goals (for now)
- Browser or desktop control like UdS Operator, and reaching Abdoh from the phone (section 8
  keeps the notes).
- A vector database, embeddings, or a hidden "think back on the conversation" call for memory.
- New speech or wake word models.
- A role that survives a restart (a role ends when Abdoh quits).

---

## 2. What was checked (2026-11-22)

| Question | Result |
|---|---|
| Why the microphone list goes stale | `audio/mic.py` lists and opens microphones through `sounddevice`. PortAudio reads the device list **once**, when it starts; `sd.query_devices()` and the default device never change after that. `mic_device: ""` (the owner's setting) means PortAudio's default **as it was at start**. Settings' list (`AppApi.microphones` → `input_devices`) comes from the same list. That is the owner's case: undocked, Settings still showed the Lenovo camera and not the headset |
| What is already live | The speaker list (`winaudio`, COM) and the speaker tap (`audio/loopback.py`, which logged "The default speakers changed" at 11:40). Screens: `Displays.all()` asks Windows (CCD) every time |
| Also stale, by the same cause | Piper (`piper_voice.py`) and the earcons play through `sounddevice`'s default output, which is also the one from start. **Not checked by ear** (story 62 step 1) |
| Reloading PortAudio | `sd._terminate()` then `sd._initialize()` (private, but the usual way) reloads the list. **Tested on the laptop (story 62 step 1):** a reload takes about 30 ms; an input stream open across it breaks (`Invalid stream pointer`, -9988); new input and output streams open fine afterwards; an earcon (`sd.play`) playing during a reload raises nothing. So only when the microphone is closed and Piper isn't playing |
| Microphone names | MME (what `sounddevice` lists) cuts names to 31 characters; Windows has the full name. `winaudio.same_device` already matches the two |
| A mode with missing screens today | Study has `displays: ['2', '3']`. With only the laptop, `Displays.find("2, 3")` finds nothing and the mode says "I don't know which screen '2, 3' is". The laptop screen is **not** turned off (`set_active` never gets an empty set), but the rest of the mode runs anyway, and `window: X to 3` steps fail. Nothing checks first |
| What Claude knows about screens | `brain._screen_names` lists every screen in `displays.json`, i.e. every screen ever seen, not which are connected now |
| Moving windows | The `window` action (`actions.parse_window`: "Chrome to 2 maximized", "minimize") works in commands and modes but is not in `ACTION_HELP`. 2026-11-22 08:56 Claude said "I can't move windows between screens"; 10:27 to 10:30 maximizing WhatsApp took three tries with PowerShell |
| Requests dropped without a sound | 2026-11-22 08:52:19, 11:30:36 and 11:48:17: the wake word fired with the voice check at 1.00, 1.2 to 3.1 s were recorded, and Parakeet returned no words. `_listen_and_answer` then does nothing: no log line, no sound. At 08:52 the owner asked "did you hear what I said before?". Transcripts are logged only at debug level, so why no words came out (a quiet mic, another language, cut off) is unknown |
| Claude choosing to ignore | After every wake word the router adds `WOKEN` (the wake word is often set off by mistake; ignore what isn't for you). At 09:03 a long, unclear sentence (wake 0.58, voice 1.00) was ignored; at 08:37 "What?" and "Well" (voice 0.80) too. The owner judged the 09:03 sentence unclear, will speak more clearly, and does **not** want talk on the phone or in the room taken as requests. So the warning stays, and Claude gets more to judge by |
| Is the speech model ready when the wake word fires? | Parakeet is loaded and warmed once at start (`stt.py`, `warm_up`). Usually a request is transcribed in 0.1 to 0.4 s, but the two slowest of 2026-11-21/22 (1.61 s at 11:30, 0.84 s at 12:25) both came after 35 to 50 minutes of quiet: Windows likely moved the idle model out of memory. Slow transcription delays the reply but loses no words (the recording is complete before transcription starts). **Seen on 2026-11-22 (story 63):** with 2.1 GB of 15.7 GB free (WSL, Brave, VS Code), the idle Abdoh.exe had a 123 MB working set against 1765 MB private memory: Windows had moved most of it, the model included, out of memory. (Timings in the dev venv, onnxruntime 1.30, were about 10 times slower than the app's 1.32 under that memory pressure, so the app's own log is the measure.) |
| Does a smarter "not for me" make waking harder? | No. Waking is decided by the wake word model and the voice check alone; nothing in this epic changes them. Local commands (the time, the music, modes) are never ignored. Only what goes to Claude can be ignored, and the new note makes a clear call more likely to be answered than today |
| Would "Forget my voice" help? | No. Without the voice check Abdoh wakes for anyone saying something like its name, and the router could no longer tell Claude it was the owner |
| Where a role can live | The system prompt is fixed for a Claude Code conversation (`same_setup`); changing it starts a new conversation. The state line (`about.state_line`, sent with every message) can change any time, so the role goes there |
| A German teacher's voice | Piper already picks the voice per sentence (`text_language`): German sentences get the German voice. Speed: `configure(rate=)` → `length_scale` |
| Multi-line content in replies | `reply.py` reads Claude's reply line by line; `ACTION` lines are one line. Code fences are only removed inside one line, so multi-line board content needs its own start and end lines |
| Saving commands and modes | `CommandStore.save/delete` and `ModesStore.save/delete` validate and write (the app uses them); `commands/learn.py` appends a learned command and keeps comments |
| Asking yes first | `SystemSkills._ask` / `answer` (the shut-down question): a plain yes or no answers it; anything else drops the question and is handled as a new request |
| Memory today | Claude Code keeps the conversation for up to 40 turns (`MAX_TURNS`); `claude.instructions` is the only lasting text. Nothing learned about the owner survives |

---

## 3. Tech stack changes (decided; don't change without a reason)

| Concern | Choice | Why |
|---|---|---|
| Noticing device changes | A thread asks Windows (`winaudio`, COM) every 2 s for the default microphone, the default speakers and the connected microphones | No new dependency; the same way `loopback.py` notices new speakers |
| Settings' microphone list | From Windows (`winaudio`), full names | Always current |
| Reopening after a change | Reload PortAudio, then open the microphone again | The only way `sounddevice` sees new devices |
| Roles, memory | `<app_dir>/roles.yaml`, `<app_dir>/memory.yaml` | Like `modes.yaml`: readable, editable, kept on uninstall |
| The board | A small, safe Markdown renderer in the page's own JS (headings, lists, bold, code blocks, tables; all HTML escaped), math in LaTeX drawn by KaTeX | **KaTeX 0.19.1** (MIT), vendored in `ui/web/vendor/katex` (script, CSS, woff2 fonts; works offline), `trust` off. Added after story 66 at the owner's request: Unicode math isn't enough for uni maths |

No new Python dependencies.

---

## 4. How it works

### 4.1 Devices follow Windows

- `DeviceWatch` (`audio/devices.py`) checks every 2 s: the default microphone's id, the default
  speakers' id and the set of connected microphones. On a change it logs it, tells the page
  (`devices`) and tells the daemon.
- The daemon reopens the microphone when the change concerns it: the default changed and
  `mic_device` is `""`, or the chosen microphone left or came back. It waits for a safe moment
  (not recording, not speaking), closes the microphone, reloads PortAudio and opens it again. A
  speakers change also reloads at the next safe moment, so the next reply plays where Windows
  plays.
- "Microphone stopped delivering audio" (sleep, unplugging): each retry reloads first.
- The chosen microphone isn't connected: Abdoh uses the default, and Settings says
  "Jabra Evolve isn't connected; using Microphone Array". When it comes back it is used again.
  The setting itself never changes.
- Settings' list refreshes by itself on `devices`. A saved name cut to 31 characters still
  matches the full name.

### 4.2 Modes know your setup

Before a mode changes anything, `ModeEngine.check(mode)` lists what it needs that isn't there:
screens in `displays` that aren't connected, `audio_output` speakers that aren't connected, and
screens that `window` steps send windows to.

- Nothing missing: as today.
- Something missing, and the mode was switched on by voice, the window or Claude: nothing
  changes yet. Abdoh asks one question, naming the mode, what it wants and what is connected:
  "Study mode wants screens 2 and 3, but only your laptop screen is connected. Run it on the
  laptop screen?"
  - **Yes:** the mode runs with what is there. Connected screens it lists are used; if none of
    them is connected, the screen setting is skipped and the screens stay as they are. Windows
    meant for a missing screen go to the main screen. Missing speakers are skipped. The usual
    done sound.
  - **No:** nothing changes ("Okay, I won't.").
  - **Other wordings:** a plain "yes" or "no" is understood locally (the `SystemSkills`
    pattern). Any other answer goes to Claude with the question: "Abdoh just asked: ... If this
    answers it, write `ACTION answer: yes` or `ACTION answer: no`; otherwise handle it as a new
    request." So "yeah, just use the laptop" works without a phrase list.
- Switched on by its schedule (nobody may be there to answer): runs with what is there and says
  once what it skipped.
- The state line tells Claude which screens are connected and on, with every message: "screens:
  1 laptop (on); 2 HP 32f and 3 C34H89x not connected". The system prompt keeps the numbers and
  names of every known screen (story 68 builds modes for screens that are unplugged right now).

### 4.3 Hearing you right

- **No words heard.** The wake word fired, the speech detector heard at least 0.5 s of speech
  (not counting the quiet around it), and the recognizer returned nothing: Abdoh logs "Heard 1.9 s after the wake word but no words", plays the new
  soft `unclear` sound, says nothing and does **not** listen afterwards (it may have been talk
  on the phone or in the room). If the next request to Claude comes within 60 s, it carries a
  note: "(Just before this, Abdoh heard the user speak but couldn't make out any words.)" So
  "did you hear me?" gets an honest answer. The log line also says how loud the recording was,
  so a quiet microphone shows.
- **Unclear clips** (`keep_unclear_clips`, default off): a switch in Settings → Wake word that
  the owner turns on and off any time. While on, only these "no words" recordings are saved, to
  `<app_dir>/voice/unclear-*.wav`, with the matching log line naming the file. Each clip is
  deleted after one day (checked at start and every hour), and all of them when the switch goes
  off or with "Forget my voice". Never sent anywhere. Temporary: remove it once misses stop
  (section 8).
- **The speech model is always ready.** When the wake word fires, Abdoh warms Parakeet in the
  background (a tiny transcription of silence) while you are still talking, so it is back in
  memory by the time you finish. While idle, the same tiny warm-up runs every few minutes and
  right after the computer wakes from sleep. Log a transcription that takes over 0.6 s.
- **How clearly the name was said.** The wake engine keeps the score and voice-check result of
  the wake-up that started this request. The note after a wake word says so: "Your name was
  heard clearly (0.96), in the user's own voice" or "faintly (0.35)". Bands: clearly ≥ 0.8,
  fairly clearly ≥ 0.5, faintly below. The prompt: a clear wake-up in the user's voice followed
  by a request or a question is meant for you; ignore only what is clearly said to someone else
  or comes from a video or a song. Tune the bands with the owner.
- When Claude ignores something after a wake word, the `unclear` sound plays, so the owner knows
  to say it again if it was meant for Abdoh. Ignoring speech in the follow-up window stays
  silent, as today.
- **Windows.** `ACTION window: <app> to <screen> [maximized | left | right | ...]` or
  `ACTION window: minimize`, the same syntax as in commands, for Claude too.

### 4.4 Act as

A **role** (`roles.yaml`):

```yaml
- name: German teacher
  phrases: [german lesson]        # more ways to start it ("act as <name>" always works)
  instructions: >
    You are my German teacher. I'm a beginner. Speak German slowly and simply, explain new
    words in English, correct my mistakes kindly, and ask me to repeat.
  speed: slow                     # slow | normal | fast: Piper's speed while the role is on
  answers: long                   # short (the usual limit) | normal (5) | long (10 sentences)
  board: true                     # may show things on the board (4.5)
```

- **Starting.** A saved role's phrases and "act as <its name>" start it at once, locally.
  Anything else goes to Claude, which writes `ACTION role: <a saved role's name>` or, for a role
  that isn't saved ("act as a chef"), `ACTION role: <one line describing it>`. An unsaved role
  works the same, and the Act as page offers **Save**. A mode can start a role
  (`settings: role: Math teacher`); the role ends with the mode.
- **While it's on**, the state line carries it: "acting as German teacher: <instructions>;
  answers may be up to 10 sentences; you may use the board". Switching costs nothing (no new
  Claude conversation). Piper speaks at the role's speed; German sentences already get the
  German voice.
- **Stopping.** Claude decides from any wording: "stop acting", "no need to act anymore", "I'm
  good, you can stop being my teacher". It writes `ACTION role: off`. Also the Stop button on
  the Act as page and in the sidebar. No phrase list.
- The sidebar shows the role under the mode. The new **Act as** page lists the roles (new,
  edit, delete, start) and offers three to start from: German teacher, Math teacher,
  Programming teacher.
- Screen and role already work together: "look at this problem" as Math teacher gets a
  teacher's explanation.

### 4.5 The board

- The top of the Act as page, used only while a role with `board: true` is on.
- The state line tells Claude: "You have a board, like a teacher's whiteboard: code, equations,
  worked steps, tables, word lists, anything better seen than heard. Write on it a little at a
  time: one line between a line `[board]` and a line `[/board]`, then say what it means, then
  the next line. Never a whole program at once. Markdown, and LaTeX for math (`$...$`,
  `$$...$$`). The board is shown, never read aloud; speak the explanation and refer to it."
- `reply.py`: lines between the markers go to `on_board(text)`, never to the voice. A reply with
  board content brings Abdoh's window up on the Act as page (where it last was; Claude can move
  it with `window`).
- Written like on a whiteboard (owner's request after story 66): the reply is read only as fast
  as it is spoken, so a line written just before Claude talks about it reaches the page just
  before Abdoh says it. The page writes it out word by word (`Board.Typist`, 40 characters a
  second; never half a formula, table row or `**bold**`), and Abdoh waits as long (at most 3 s
  a line) before speaking on: write a line, explain it, write the next. All the pieces of one
  answer are one card (`{id, text}`, the newest replaced as it grows; pieces join with a line
  break, so a code block can go on across pieces); the window comes up once per card.
- The board keeps the role's items, newest at the bottom, with a Copy button on code. **Clear**
  empties it, and it is cleared when the role ends.
- Rendered with the page's own small Markdown renderer (section 3); everything is escaped.

### 4.5b Keeps listening while a role is on (owner's request after story 66)

- **Why:** in two lessons Abdoh asked a question, then stopped listening. The answer window
  started on an "um" (or a breath, or its own echo), ended at the 0.6 s pause while the owner
  thought, no words came out, and Abdoh silently went back to the wake word.
- Every answer window (`listener._push_to_talk`): a recording with no words in it is listened
  for again (up to 2 more times), logged "Heard a sound but no words; listening again".
- While a role is on, Abdoh keeps listening (`Acting.listening`, on when a role starts): the
  main loop's `wait_for_trigger` gets `hear(block)`, which turns true after 0.3 s of speech in a
  row (the VAD, its own state: `SileroVad.fresh`), never while Abdoh answers nor in the 0.8 s
  after (its own voice). The recording keeps 1 s from before it was noticed, ends after a 1.2 s
  pause and may be 30 s long; no chime. What you said goes to Claude as an aside (it may
  `ACTION ignore` talk meant for someone else). No answer windows meanwhile: you just talk.
- Stopping it in any words: `ACTION listen: off` (Claude decides; the role stays on), and
  `ACTION listen: on` to listen again. The state line says which, and how. The Act as page shows
  it, with a Stop listening / Keep listening button (request `keep_listening`).

### 4.6 Abdoh edits itself

New Claude actions, behind a new permission "Let Abdoh change its own commands, modes and
roles" (`claude.allow_self_edit`, on by default):

```
ACTION save_item: command | {"name": "good_evening", "triggers": ["good evening"], "actions": [...]}
ACTION save_item: mode | {...}
ACTION save_item: role | {...}
ACTION delete_item: command | good_evening
ACTION undo_change: last
```

- The JSON has the same shape as the YAML files. The system prompt carries a short reference
  (about 40 lines): each kind's fields, the actions with one example each, and the user's
  current commands, modes and roles in compact form, so "add Spotify to work mode" can be done.
- Claude asks for what's missing before saving: what starts it, what it does, which screens and
  apps. It fills in names, icons and obvious details itself. Answers already come back without
  the wake word (a `Question`).
- Abdoh checks the item with the same stores the app uses (`CommandStore`, `ModesStore`,
  `RoleStore`), saves it, reloads the commands or modes, refreshes the app's page, and plays the
  done sound with one short sentence: "Saved good evening: it locks the screen." If it doesn't
  pass, Abdoh says why in one sentence.
- App names are checked against the installed apps (`AppIndex`); an unknown one is named back
  ("I can't find an app called Spotfy"). `run:` steps only if `allow_run` is on.
- Before every change the file's previous text is kept; `undo_change` writes it back (the last
  10 changes since Abdoh started). Claude understands "undo that".
- The running Claude conversation is not restarted after a change (Claude knows what it saved);
  the next conversation gets the new list.

### 4.7 Memory

- `memory.yaml`: a list of `{text, kind: fact | lesson, added: date}`. At most 60 entries and
  4000 characters; when it's full, Claude is told to merge or forget something first.
- Claude writes:
  - `ACTION remember: <one short fact>` for lasting things about the user (people, preferences,
    routines, where things are), not passing remarks. Never passwords, keys, card numbers or
    health details unless the user asks for it explicitly.
  - `ACTION lesson: <what works>` after something failed and then worked ("WhatsApp: maximize
    its main window; the first window found is a hidden helper").
  - `ACTION forget: <the entry, as written>`.
- The system prompt carries "What you know about the user" and "Lessons". The running
  conversation isn't restarted for a new entry.
- "What do you know about me?" just works; "forget that" removes it.
- When a lesson exists for something the user asks again, and it took commands to do, Claude
  offers once to save it as a command (4.6).
- A **Memory** page in the window: every entry, edit, delete, add, and a switch
  (`memory: true`). Off: nothing is sent and the memory actions aren't offered.

### 4.8 The new actions at a glance

| Action | Allowed when | Notes |
|---|---|---|
| `window` | In `claude.actions` (a normal switchable action) | `CLAUDE_ACTIONS`, and `NEW_ACTIONS` under the next `CONFIG_VERSION` for existing users |
| `answer` | Abdoh just asked something | Like `ignore`: not a switch in Permissions |
| `role` | Always | Like `look` and `ignore` |
| `remember`, `lesson`, `forget` | `memory` is on | |
| `save_item`, `delete_item`, `undo_change` | `claude.allow_self_edit` is on | |

`about.py` tells Claude about roles, the board, self-editing and memory, so "can you remember
things?" is answered right.

---

## 5. Ground rules for this epic

1. **Section 5 of `ABDOH_EPIC_5.md` and `ABDOH_EPIC_6.md` still apply.**
2. **Claude decides; no phrase lists** for anything that needs understanding: stopping a role,
   an answer to a mode's question that isn't a plain yes or no, what to remember. Fast local
   matching stays only for exact names and phrases the owner saved (like "<name> mode").
3. **Never lose the owner's files.** Every self-edit is validated before writing, keeps
   comments where the store already does, and can be undone. Test with copies of the owner's
   real `commands.yaml` and `modes.yaml`.
4. **Memory stays on this computer**, apart from being sent to Claude with requests like
   everything else in the prompt. Unclear clips never leave the computer and live one day.
5. **Unplugging and sleeping** (story 62) are done by the owner, with Abdoh running from source.
6. **Tests stay offline and silent:** fake device watch, fake PortAudio, fake displays, fake
   Claude output, fake page. No microphone, speakers, screens or Claude in tests.

---

## 6. Stories

### Story 62: Devices follow Windows (`story/62-live-devices`)

1. **Check first** on the laptop with a small script: list microphones with `sounddevice`, plug
   the headset in or out, list again (expect the old list), then `sd._terminate()` +
   `sd._initialize()` and list again. Check what an open stream and Piper playback do across a
   reload. Write the results into section 2.
2. `winaudio`: `microphones()` (id, full name, default) and `default_ids()` (microphone,
   speakers), live.
3. `audio/devices.py`: `DeviceWatch` (4.1), with the clock and the Windows calls injectable.
4. `audio/mic.py`: `reload_devices()` (refuses while a stream is open); `find_input_device`
   matches full and cut names.
5. Daemon: reopen at a safe moment on a change that concerns the microphone; reload before each
   retry after "Microphone stopped delivering audio"; reload after a speakers change at the next
   safe moment. Emit `devices`.
6. Settings: the list from `winaudio.microphones()`, refreshed on `devices`, and the "isn't
   connected; using ..." line. Demo twin in `bridge.js`.
7. Tests: a new default with `mic_device: ""` reopens; the chosen microphone leaving falls back,
   and coming back returns; no reload while a stream is open; names match cut and full.
8. **With the owner:** undock and plug in the headset with Abdoh running; sleep and wake; check
   Settings, that Abdoh hears through the headset, and that it speaks through it.

### Story 63: Hearing you right (`story/63-hearing-you-right`)

1. No words heard (4.3): the log line with the recording's loudness, the `unclear` earcon, no
   words, no listening, and the note for the next Claude request within 60 s.
2. `keep_unclear_clips` (4.3): the Settings switch (and its demo twin in `bridge.js`), saving
   only "no words" recordings, deleting each after one day, all of them when switched off or
   with Forget my voice.
3. The speech model always ready (4.3): warm it in the background at the wake word, every few
   minutes while idle, and after sleep; log slow transcriptions. The warm-up must never hold up
   a real transcription (it shares the transcriber's lock: keep it tiny).
4. The wake engine keeps the last wake-up's score and voice result; the router's note says how
   clearly the name was heard (bands and prompt wording in 4.3). An `ignore` after a wake word
   plays `unclear`.
5. `window` for Claude: `ACTION_HELP`, `CLAUDE_ACTIONS`, `NEW_ACTIONS[10]`,
   `CONFIG_VERSION = 10`.
6. Connected screens in the state line (4.2, last point).
7. Tests: an empty transcript after the wake word plays `unclear` and doesn't listen; the note
   reaches the next request and expires; clips are saved only when the switch is on, only for
   "no words", and deleted after a day and when switched off; the wake word starts a warm-up
   and the idle timer repeats it; the bands; `window` from Claude runs; the state line lists
   connected screens.
8. **With the owner:** a day of normal use with `keep_unclear_clips` on; read the log and listen
   to the clips together (transcription times after long quiet, "no words" lines and their
   loudness, ignores and their bands), and tune the bands and the prompt.

### Story 64: Modes know your setup (`story/64-modes-know-setup`)

1. `ModeEngine.check(mode)` (4.2), from the live screens and speakers.
2. The question; yes and no through the `SystemSkills` pending pattern, and `ACTION answer`
   for other wordings. On yes, run with what is there.
3. Schedules run with what is there and say what was skipped.
4. Tests with fake displays: everything connected → as today; something missing → a question
   and no change; yes → only the connected screens, windows on the main screen; no → nothing;
   another answer → handled as a new request; never zero screens.
5. **With the owner:** Study and Work mode with the monitors unplugged, then plugged in.

### Story 65: Act as (`story/65-act-as`)

1. `roles/` (model, and `RoleStore` like `ModesStore`); `roles.yaml` with a commented example.
2. Starting (local phrases, `ACTION role:`), the state line, speed, answer length, stopping with
   `ACTION role: off`; a mode's `role` setting.
3. The Act as page: list, new (from the three suggestions), edit, delete, start, stop; the
   sidebar line. `AppApi` methods and demo twins in `bridge.js`.
4. Tests: start by phrase and by Claude; an unsaved role; stop from Claude; a mode starts and
   ends a role; speed and answer length reach the speaker and the state line.
5. **With the owner:** German teacher for five minutes; Math teacher with "look at this".

### Story 66: The board (`story/66-board`)

1. **Check first** with the owner: three math replies and two code replies on the board, math
   in Unicode. Readable? If not, KaTeX (decide, and write it into section 3). **Decided after
   the first lessons: KaTeX** (uni maths needs more than Unicode).
2. `reply.py`: `[board]` ... `[/board]` to `on_board`, never spoken, also when the markers
   arrive split across streamed chunks.
3. The board on the Act as page: the Markdown renderer, Copy buttons, Clear, cleared when the
   role ends; the window comes up when the board gets something.
4. The board text in the state line (4.5), only while a role with `board: true` is on.
5. Tests: markers across chunks; nothing on the board is spoken; escaping (no HTML from Claude
   runs); cleared when the role ends.
6. **With the owner:** Programming teacher showing and explaining a short program.

### Story 67: Memory (`story/67-memory`)

1. `memory.py`: load, add, forget, the limits (4.7).
2. `remember`, `lesson` and `forget`; the system prompt sections; `about.py`.
3. The Memory page and the `memory` switch.
4. Tests: add and forget; the limits; off sends nothing and offers no memory actions; the
   prompt carries the never-store rule.
5. **With the owner:** tell it a few things, restart, ask "what do you know about me?"; let a
   task fail and then work, and check the lesson.

### Story 68: Abdoh edits itself (`story/68-edits-itself`)

1. A JSON → item path in each store, reusing its own checks.
2. `save_item`, `delete_item`, `undo_change` (4.6) and the `allow_self_edit` permission.
3. The short reference and the user's current items in the system prompt.
4. The app's pages refresh after a change (`commands`, `modes`, `roles` events).
5. Tests with copies of real files: save, replace, delete, undo; an invalid item changes
   nothing; an unknown app is named back; `run:` refused without `allow_run`; comments kept.
6. **With the owner:** "make a command called good evening that locks the screen"; one with
   something missing; a mode for the three screens made while undocked; "add Spotify to work
   mode"; "undo that".

### Story 69: Release 0.9.0 (`story/69-release`)

1. Version `0.9.0`; README (devices, the modes' question, roles, the board, self-editing,
   memory, configuration table); the download page and screenshots (Act as and Memory pages).
2. Build, run the packaged app in isolation (epic 5 rule 5.5), check the log.
3. **Ask the owner** before tagging. Then merge, tag `v0.9.0`, push, watch the build, and check
   the release (with the old-name installer copies) and the download link.

---

## 7. Things only the owner can do

- Undock, plug the headset in and out, and put the laptop to sleep while Abdoh runs (story 62).
- Use Abdoh normally for a day after story 63 with `keep_unclear_clips` on, so the log and
  the clips show how it hears you.
- Try modes with the monitors unplugged (story 64).
- Try the roles, the board and memory (stories 65 to 67) and self-editing (story 68).
- Start with Abdoh's name and speak clearly when it's meant for Abdoh.
- Say when a release should be published.

## 8. Later ideas (not in this epic)

- **Browser control, like UdS Operator.** UdS Operator (`../UdS_Operator`) was an
  OpenManus-style agent: `browser-use` 0.1.40 with Playwright in a fresh Chromium (not logged
  in), the page's elements as a numbered list, the LLM picking "click 12", called with an API
  key. For Abdoh: Microsoft's Playwright MCP inside Abdoh's Claude Code, attached to the
  owner's own browser (already logged in), always stopping at checkout. To check first: Node.js
  is needed; whether Abdoh's Claude Code flags allow one extra MCP server; Brave; captchas; the
  time (1 to 3 minutes a task) and the Claude usage.
- **Abdoh from the phone.** First a Telegram bot (answers only the owner's account; text and
  voice notes in; text, screenshots, files, camera photos and yes/no buttons out). Later the
  window as an iPhone home-screen app over Tailscale. The laptop must stay awake (no sleep when
  plugged in, closing the lid does nothing). WhatsApp: not recommended (a business account and
  a second number, or the risk of a ban). The camera needs OpenCV and a notice on the laptop
  each time. Bot chats aren't end-to-end encrypted.
- Remove `keep_unclear_clips` once the owner says the misses have stopped.
- A role's own voice; the board for normal replies too.
- The shut-down question answered by Claude in any wording, like the mode question.
- From epic 6: Woof, voice checks for a household, a "that wasn't me" button, Hue and Govee
  lamps, Wi-Fi and Bluetooth switches.
