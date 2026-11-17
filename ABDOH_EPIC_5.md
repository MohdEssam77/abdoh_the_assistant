# EPIC 5: Abdoh that listens while it talks, sees your screen, and runs your PC in modes

> **For Claude Code:** This file is your source of truth for the fifth epic. Epics 1 to 4 are
> done; their architecture still applies unless this file changes it. Work through the stories
> **in order** and follow the working rules in `CLAUDE.md` exactly. Keep everything **simple**.
>
> **Start here:** on the first story branch, your first commit changes the first paragraph of
> `CLAUDE.md` to name `ABDOH_EPIC_5.md` as the current source of truth (epics 1 to 4 done), and
> adds this file (`docs: epic 5 plan`). Then read sections 2, 3 and 5 before writing code: they
> hold facts that were measured on the owner's laptop, and rules about tests that make sound or
> change his screens.

---

## 1. Goal

Abdoh 0.4 hears well and answers fast. The owner now wants it to behave more like a person in
the room and to control more of the computer:

1. **Stop when I start talking.** While Abdoh is explaining something, the owner should not need
   the wake word to interrupt. As soon as Abdoh hears him talk, it stops and listens to what he
   is saying.
2. **Look at my screen whenever I ask.** Not only "translate my screen": any request such as
   "look at the screen and tell me what's there" sends a screenshot to Claude with the question.
3. **Modes.** "Hey Abdoh, movie mode" turns monitors 1 and 3 off and keeps monitor 2 on. "Work
   mode" turns all three on, sets the brightness to the maximum, plays jazz and opens VS Code.
   Modes are made in the app, switched by voice, from the window and from the tray, and "back to
   normal" undoes what a mode changed.
4. **More control of the laptop.** Commands and modes can turn monitors on and off, switch the
   speakers, change the theme and the power mode, press keys, wait, close and move windows; and
   Abdoh understands these directly by voice ("turn off monitor 3", "switch to headphones").
5. **More that makes it a flexible assistant** (the owner asked for ideas): schedules for modes,
   a shutdown timer, clipboard and folder skills, lower the computer's sound while Abdoh listens,
   night light.

### Non-goals (for now)
- Clicking, scrolling or reading other apps' controls (computer use). Abdoh presses keys and
  moves windows; it does not operate apps.
- Remembering where every window was and putting it back.
- Wi-Fi and Bluetooth switches (they can disconnect the owner's keyboard, mouse or headset; they
  need WinRT). See "Later ideas".
- macOS and Linux versions of the new system controls. Everything new is Windows-first and sits
  behind interfaces, as before; elsewhere it says politely that it only works on Windows.

---

## 2. What was checked on the owner's laptop (2026-11-16)

Everything below was run for real (silently, read-only or as a no-op) before this plan was
written. Build on it; don't re-discover it. The probe code is in the appendices.

| Question | Result |
|---|---|
| Can we capture what the speakers play (to cancel Abdoh's own voice from the mic)? | `sounddevice` 0.5.6 (PortAudio 19.7) lists **no loopback devices**. A WASAPI loopback client made with `comtypes` works: `IAudioClient.Initialize` accepted 16 kHz mono 16-bit with `LOOPBACK \| AUTOCONVERTPCM \| SRC_DEFAULT_QUALITY` on the default speakers (mix format: 48 kHz stereo float). Packets are 10 ms. **When nothing is playing, no packets arrive at all** (0 in 3 s); while a stream is open (even a silent one) they arrive continuously (1105 packets, 11.05 s of audio in 11.0 s). Appendix A |
| Which echo canceller? | A hand-written numpy filter (frequency-domain Kalman/NLMS) needed 2 to 6 s to reach 15 to 25 dB. **WebRTC's AEC3** (through `livekit`'s `rtc.AudioProcessingModule`) gave **about 40 dB from the first second**, also with a distorting speaker and with other sound playing, at 0.6% of real time. On the cleaned signal the voice detector fired on **0.0%** of Abdoh's own speech (on the raw microphone: about 70%) and found the user after **0.23 to 0.26 s** (0.65 s when the user was 10 dB quieter than the echo and the speaker distorted). After cancellation the recognizer heard the user's words; from the raw mic it transcribed Abdoh's own voice. Simulation only (a synthetic room); see story 37 for the real-room check |
| Other packages for echo cancellation | `aec-audio-processing` (0.9 MB, one unknown maintainer: not trusted enough to ship), `speexdsp`/`webrtc-audio-processing` (no Windows wheels). `livekit` 1.3.0: Apache-2.0, `win_amd64` wheel 10.9 MB (27 MB unpacked, `livekit/rtc/resources/livekit_ffi.dll`), needs `protobuf`, `types-protobuf`, `aiofiles`, `numpy` |
| Can the Windows voice pause and resume? | `SpVoice.Pause()` is slow: speech went on for about a second. **`Speak("", PURGE)` stops in 17 ms**, and `voice.Status.InputWordPosition` / `InputWordLength` give the character position of the word being spoken (polling works through `comtypes` dynamic dispatch). So: stop = purge and remember the position; resume = speak `text[position:]`. Appendix E |
| Can a Claude Code reply be interrupted without losing the conversation? | Yes. Writing `{"type":"control_request","request_id":"<id>","request":{"subtype":"interrupt"}}` to stdin got `{"type":"control_response","response":{"subtype":"success",...}}` and then a `result` line with `"subtype":"error_during_execution","is_error":true` **0.03 s later**. The process stayed up and the next message was answered with full memory of the conversation, including the interrupted reply. Appendix D |
| Monitors | Three, through Windows' CCD API (`QueryDisplayConfig`): the laptop panel (`\\.\DISPLAY1`, internal, 1920x1080 at -3840,0, no friendly name), **HP 32f** (`\\.\DISPLAY5`, 1920x1080 at -1920,0) and **C34H89x** (`\\.\DISPLAY6`, 3440x1440 at 0,0, primary). GDI numbers are 1, 5, 6 (two graphics adapters), so they are **not** the numbers the owner sees. `SetDisplayConfig` with `SDC_VALIDATE` returned 0 (would work) for "all on", for each monitor alone and for two of three, with both recipes in Appendix B. **Nothing was applied**: applying is untested |
| Monitor identity | `monitorDevicePath` from CCD is stable and equals `unique_id` in `mss`'s monitor list (so screenshots can pick a monitor by it). `mss.mss` prints a deprecation warning: use `mss.MSS` |
| Brightness of external monitors | DDC/CI (`dxva2.GetMonitorBrightness`): **C34H89x** supports it (100 of 0 to 100); **HP 32f does not**; the laptop panel does not (it uses WMI, which already works) |
| Switching the default speakers | The undocumented but long-stable `IPolicyConfig` COM interface works through `comtypes`: `SetDefaultEndpoint(current default, 0)` was accepted and changed nothing. Two outputs exist: `Speakers (Realtek(R) Audio)` (default) and `C34H89x (NVIDIA High Definition Audio)`. Appendix C |
| Power mode | `powrprof.PowerGetEffectiveOverlayScheme` returned `DED574B5-...` (best performance); `PowerSetActiveOverlayScheme` exists. Appendix F |
| Dark mode | `HKCU\...\Themes\Personalize`: `AppsUseLightTheme` = 0 and `SystemUsesLightTheme` = 0 (dark) |
| Night light | Stored in a binary registry value (Appendix H). With night light **off** on Windows 11 build 26200 it is 27 bytes: `43 42 01 00 0a 02 01 00 2a 06 b3 d6 b1 d6 06 2a 2b 0e 05 43 42 01 00 00 00 00 00`. The "on" layout was not observed |
| The window in front | `GetForegroundWindow` + `GetWindowTextW` + `GetWindowRect` work (title and rectangle) |
| The microphone | The default microphone is the Realtek array at 28% in Windows; with nobody talking its level is about 1 of 32768. Blocks are 100 ms through MME (`Microphone` in `audio/mic.py`) |

---

## 3. Tech stack changes (decided; don't change without a reason)

| Concern | Choice | Why |
|---|---|---|
| What the speakers play | Our own **WASAPI loopback capture** with `comtypes` (new `audio/loopback.py`) | No new dependency; `sounddevice` can't do it; it also contains music and videos, not only Abdoh's voice |
| Echo cancellation | **WebRTC AEC3** through `livekit` (`rtc.AudioProcessingModule`), 10 ms frames, 16 kHz mono | Measured: 40 dB at once. New dependency: `livekit>=1.3` (one-line justification in the commit message). Import it lazily; without it voice interruption is simply off |
| Hearing the user during a reply | Silero VAD (already used) on the **cleaned** signal | 0% false alarms on Abdoh's own voice in the simulation |
| Stopping and continuing speech | SAPI purge + word position (no `Pause()`) | Purge takes 17 ms; `Pause()` about a second |
| Stopping Claude | The `interrupt` control request, then keep the process | The conversation survives an interruption |
| Monitors on and off | Windows CCD API (`QueryDisplayConfig` / `SetDisplayConfig`) with `ctypes` (new `displays.py`) | The supported way; validated for this laptop's three monitors |
| Brightness of external monitors | DDC/CI through `dxva2.dll` with `ctypes` | Works on monitors that support it; the laptop panel keeps WMI |
| Default speakers | `IPolicyConfig` with `comtypes` (extend `winaudio.py`) | Verified; what every audio switcher uses |
| Modes | A new `modes.yaml` (same idea as `commands.yaml`), `modes/` package, a Modes page | Modes have settings that are undone, which commands don't |
| Everything else | `ctypes` and the registry | No new dependencies |

---

## 4. How it works

### 4.1 Listening while talking

```
speakers ── WASAPI loopback ──► SpeakerTap (16 kHz, by time) ──┐
                                                               ▼
microphone ─► Microphone.read() ─► listen thread ─► EchoCanceller (WebRTC) ─► cleaned audio
                                        │                                         │
                                        │ wake word (raw audio)                   ▼
                                        │                               VoiceWatch (Silero VAD,
                                        ▼                               "3 of the last 5 frames")
                              wait_for_trigger(...) ◄──── "voice" ────────────────┘
                                        │
      "voice" while a reply is running: ▼
        1. speaker.pause()            (purge now, remember the word)
        2. record what you say        (cleaned pre-roll + until you stop)
        3. transcribe and decide:
             nothing / "okay", "right"   → speaker.resume()      (Abdoh goes on)
             "stop", "wait", "thanks"    → stop the reply, say nothing
             anything else               → stop the reply (Claude: interrupt, conversation kept)
                                           and handle it as the next request
```

The listen thread **owns the microphone at all times** and never blocks while Abdoh answers:
replies run on their own thread (typed requests already do). That removes the separate
wake-word watcher thread from epic 4: the listen loop itself hears the wake word, the hotkey
flag and the user's voice during a reply.

### 4.2 The screen

```
"look at my screen", "what's this error?"        Claude writes  ACTION look: <what for>
        │ (clear screen words)                            │ (it needs to see to answer)
        ▼                                                 ▼
  screenshot of the monitor with the window in front  ◄───┘
  + the window's title  +  your own words   ──►  Claude  ──►  spoken answer
```

### 4.3 Modes and system controls

```
commands.yaml ─┐                         ┌─ Computer (computer.py)
modes.yaml ────┼─► actions (actions.py) ─┤     displays.py   monitors on/off, DDC brightness
voice skills ──┤                         │     winaudio.py   volume, default speakers
Claude ACTIONs ┘                         │     desk.py       theme, power, keys, windows, clipboard
                                         └─ ModeEngine (modes/engine.py)
                                              settings: remember → apply → restore ("back to normal")
                                              actions:  run in order
```

A mode has **settings** (things with a state: which monitors are on, brightness, volume,
speakers, theme, power mode, night light, and three of Abdoh's own switches) and **actions**
(things that just happen: open an app, play music, say something). Before a mode changes a
setting for the first time, the engine remembers its value. "Back to normal" puts every
remembered value back.

---

## 5. Ground rules for this epic

1. **Tests that make sound or change the screens need the owner.** `scripts/echo_check.py`
   (plays a sentence through the speakers), anything that applies a monitor layout, night light
   and the default-speaker switch must only be run after asking him in the chat and getting a
   yes for that run. Unit tests never do any of it (fakes only, as always). If he isn't
   available, finish everything else and leave a `TODO(blocked):` note (working rule 9).
2. **Never leave him without a screen.** Every script or manual test that applies a monitor
   layout must put the previous layout back by itself after at most 15 seconds, whatever
   happens (a `try/finally` and a timer). Abdoh refuses a layout with no monitor on. Tell the
   owner beforehand that **Win+P** also brings screens back.
3. **Privacy stays as promised.** The loopback capture and the microphone watch run in memory
   only; nothing is saved or sent. Screenshots go to Claude only when the owner asked about the
   screen (or pointed at something on it), and Abdoh says or shows that it is looking.
4. **Claude never gets**: typing, key presses, closing apps, shutdown or restart. Web content
   must not be able to reach those through a prompt injection.
5. **Codebase facts that bite** (learned in epics 3 and 4):
   - `tests/conftest.py` has an autouse fixture that hides this checkout's `models/` from tests.
     Anything that looks for bundled files must go through `Config.resolve`.
   - The page may only call `AppApi` methods that exist **and** have a demo twin in
     `ui/web/bridge.js` (tests check both, by scanning for `call("name"`, `App.api.name(` and
     `act(button, "name"`). pywebview exposes public attributes, so `AppApi` keeps everything
     else in `_underscore` names.
   - New settings need: a `Config`/`ClaudeConfig` field, a commented line in
     `config.example.yaml`, `_RANGES`/`_CHOICES`/`LABELS` in `settings.py`, `RESTART_KEYS` if
     they only apply at start, and `apply_settings` in the daemon if they apply live.
   - `CLAUDE_ACTIONS` (config) must equal the keys of `ACTION_HELP` (reply.py). New Claude
     actions for existing users go through `NEW_ACTIONS` and a higher `CONFIG_VERSION`.
   - Check every UI change in headless Edge with the demo data (`index.html?demo&page=...`,
     see `scripts/take_screenshots.py`), light and dark.
   - The packaged app can differ from the dev environment (0.3.0 shipped broken that way).
     Before a release, build it and run `dist\Abdoh\Abdoh.exe` with a fake `USERPROFILE` and
     `ABDOH_HOME`, and read its log. New packages with data files or DLLs go into `COLLECT` in
     `scripts/build_app.py` (`livekit` does).
6. **Releases:** bump the version and tag only when the owner says so (story 43).

---

## 6. Stories

### Story 37: Stop when I start talking (`story/37-voice-interrupt`)

**What the owner gets:** while Abdoh thinks or talks, he just starts speaking. Abdoh goes quiet
within about half a second and listens. If he only coughed or said "okay", it carries on from
the word where it stopped. If he said something, that becomes the next request, and Claude
still remembers the conversation. The wake word and the hotkey keep working as before.

#### 37.1 Measure the real room first (needs the owner: it makes sound)

Write `scripts/echo_check.py` before anything else. It must:
1. Start `SpeakerTap` and the microphone, speak two test sentences with the normal Windows voice
   at the current volume, and feed both streams through `EchoCanceller` exactly as the app will
   (37.3).
2. Print: the lag between the two streams (GCC-PHAT, Appendix G), the echo level at the
   microphone (dBFS), the attenuation after cancellation (dB, per second), and how often the
   voice detector fired on Abdoh's own speech with each sensitivity preset.
3. Optionally (`--talk`): ask the owner to say a sentence over Abdoh's voice and print how long
   detection took.

**Targets:** at least 20 dB attenuation after the first second, and no detector firing on
Abdoh's own speech with the medium preset. If the targets are missed at 100% volume, try 60%
and write what you found into the README's known issues; the two-step design (pause, then
decide) is there to forgive a detector that fires too easily.

#### 37.2 `src/abdoh/audio/loopback.py`: `SpeakerTap`

- Captures the **default render device** (console role) as 16 kHz mono int16 with the COM code
  in Appendix A, on its own daemon thread (`abdoh-speakers`), polling `GetNextPacketSize` every
  10 ms. `comtypes.CoInitialize()` on that thread.
- It turns packets into **one continuous stream in time**. Keep a ring of the last 3 seconds
  and the time of the next sample to write. When a packet arrives later than expected by more
  than 30 ms (nothing was playing, so Windows sent nothing), fill the gap with zeros. Packets
  flagged `AUDCLNT_BUFFERFLAGS_SILENT` (0x2) are zeros too.
- `window(end_time: float, samples: int) -> bytes`: the `samples` that end at `end_time`
  (`time.perf_counter()` clock), zeros where there is no data.
- `level() -> int`: the loudest sample of the last 200 ms (for "is the computer playing sound?",
  story 42).
- When the default speakers change (a mode can switch them) or the device is invalidated
  (`AUDCLNT_E_DEVICE_INVALIDATED`), reopen: compare the default device id every 2 seconds.
- `start()`, `stop()`, `available` (False after a failure; log once). On non-Windows:
  unavailable.
- Tests use `FakeTap` (plays back given samples by time). Don't unit test the COM code.

#### 37.3 `src/abdoh/audio/echo.py`: `EchoCanceller`

- Wraps `livekit.rtc.AudioProcessingModule(echo_cancellation=True, high_pass_filter=True,
  noise_suppression=False, auto_gain_control=False)` (Appendix G). Imported lazily;
  `echo_available()` is False if `livekit` can't be imported.
- `clean(mic_block: bytes, speaker_block: bytes) -> bytes`: both blocks are the same length, a
  multiple of 320 bytes (10 ms). For each 10 ms: **first** `process_reverse_stream(speaker
  frame)`, **then** `process_stream(mic frame)`; return the processed mic frames joined.
  Always one speaker frame, then one mic frame, strictly alternating. Feeding ten speaker frames
  and then ten mic frames makes the echo's delay swing by 90 ms inside every block and ruins
  the cancellation.
- The caller picks the speaker block for a mic block: the 100 ms of the tap that end at the mic
  block's time. Smooth that time, because block arrival jitters: keep `t`; for each block
  `t += 0.1`, then `t += 0.1 * (arrival - t)`; use `tap.window(t, 1600)`. The echo then lags the
  reference by a steady amount (the microphone's own latency), which AEC3 finds by itself.
  Call `set_stream_delay_ms` once with the lag measured by `echo_check.py` if it helps
  (the simulation worked with the true value, 140 ms).
- `reset()` makes a fresh module (after the speakers changed).
- Tests: a fake module records the call order (alternating), sizes and bytes passed through.

#### 37.4 `src/abdoh/audio/bargein.py`: `VoiceWatch`

One object the daemon feeds with every microphone block while a reply is running.

- `feed(block: bytes, arrival: float) -> bool`: cleans the block (tap + canceller), appends the
  cleaned audio to a pre-roll ring (the last 1.0 s), runs its **own** `SileroVad` instance on
  the cleaned audio in 512-sample frames and returns True when the rule fires. After firing it
  stays quiet until `rearm()`.
- The rule, on 32 ms frames. A frame is *hot* when its speech probability reaches `p` **and**
  its RMS is at least `max(3 x noise floor, -60 dBFS)`. The noise floor follows the frame RMS
  down at once and up by 1% per frame.

  | `voice_interrupt_sensitivity` | fires when | `p` |
  |---|---|---|
  | `high` | 2 of the last 3 frames are hot | 0.4 |
  | `medium` (default) | 3 of the last 5 | 0.5 |
  | `low` | 5 of the last 6 | 0.6 |

  (Medium is the rule that was measured: 0.23 to 0.26 s, no false alarms in the simulation.)
- `pre_roll() -> bytes`: the cleaned audio from 0.5 s before the rule fired until now.
- `clean(block, arrival) -> bytes`: just the cleaning, for the recording that follows.
- `idle()`: called when no reply is running: forget the VAD state and the frame history (keep
  the noise floor).
- `available`: False when the tap or the canceller is missing; then `feed` always returns False.
- Tests with `FakeTap`, a fake canceller (subtracts the reference) and a fake VAD: each preset
  fires when it should, never on echo alone, not twice without `rearm()`, the pre-roll has the
  right length, and `idle()` clears the history.

#### 37.5 Pausing and continuing speech (`speech/tts.py`)

- `Speaker` gets `pause() -> bool` (default: `stop()` and return False: "stopped, can't
  continue") and `resume() -> None` (default: nothing).
- `_VoiceThread` gets `_pause` and `_resume` events. `SapiSpeaker._speak`:
  - in the polling loop also read `voice.Status.InputWordPosition` into `self._position`
    (Appendix E);
  - when `_pause` is set: purge, keep `self._position`, then wait for `_resume` (speak
    `text[self._position:]` and go on polling) or `_stop` (return). `say()` keeps blocking
    its caller during the pause, so the reply thread simply waits;
  - `pause()` returns True only while a text is being spoken.
- `FakeSpeaker` records `pauses` and `resumes`. `Pyttsx3Speaker` keeps the default.
- Tests with `FakeSapiVoice` (give it a `Status` with a word position that advances per poll):
  pause purges and nothing more is spoken until resume; resume speaks the rest of the same
  text from the word position; stop during a pause ends `say()`; pause when silent is False.

#### 37.6 Interrupting Claude without losing the conversation (`claude/code.py`)

- In `ClaudeCodeBrain._ask`, when the generator is closed early (the `finally` with
  `finished == False` and no error): instead of `_retire(session)`, call `_interrupt(session)`:
  write the control request from Appendix D, then read stdout lines until the `result` line.
  Guard it with the same kill-timer pattern as the reply timeout (3 seconds). If the result
  arrives: `_rest(session)` (the conversation stays). If not: `_retire(session)` and warm up, as
  today.
- An error or a timeout still retires the session, as today.
- Tests with `FakeProc`: early close writes the control request and keeps the process for the
  next question; a process that doesn't answer the interrupt is killed and replaced; the next
  `stream()` works in both cases.

#### 37.7 The daemon: replies on their own thread (`daemon.py`, `audio/listener.py`)

This is the delicate part. Read `Daemon._listen_once`, `handle_text`, `_listen_for_more`,
`_watch_for_wake_word` and `listen_for_request` first.

1. `wait_for_trigger(read, engine, should_stop, pressed, observe=None)`: for every block, call
   `observe(block)` (if given) before `engine.detect(block)`; if it returns True, return
   `"voice"`.
2. `listen_for_request(..., observe=None, on_voice=None)`: passes `observe` down; on the
   `"voice"` trigger returns `on_voice(mic)`.
3. In `_listen_once`, a spoken request no longer calls `handle_text` directly. It starts
   `_start_reply(text)`: a daemon thread `abdoh-reply` that runs `handle_text(text,
   voice=True)` and, in a `finally`, sets `self._reply_done` and `self._wake_listener`.
   `self._reply_done` is cleared when a reply starts. Add `Daemon.wait_idle(timeout) -> bool`
   (waits for the running reply, used by tests, the CLI and `scripts/measure_latency.py`).
4. `should_stop` for the listen loop also returns True when `_wake_listener` is set. The next
   `_listen_once` clears it and, if `_awaiting_answer` is set, does the follow-up listening as
   today. Nothing else about follow-up listening changes.
5. Delete `_watch_for_wake_word` and its use in `handle_text`. The listen loop now hears the
   wake word during every reply; `_on_wake` already stops a reply that is running when
   `wake_word_interrupts` is on. Keep that behavior for the Vosk fallback **off** (only a
   trusted engine may interrupt: check `engine.trusted` in `_on_wake`).
6. `_observe(block)`: if `cfg.voice_interrupts` and the watch is available and a reply is
   running (`_handle_lock.locked()`): `return self._voice_watch.feed(block, time.perf_counter())`.
   Otherwise `self._voice_watch.idle()` and False.
7. `_heard_voice(mic) -> str` (the `on_voice` callback), in this order:
   1. `can_resume = self.speaker.pause()`; emit status `Listening to you...`; no chime.
   2. Record: `self._voice_watch.pre_roll()` + `record_until_silence(...)` reading cleaned
      blocks (`self._voice_watch.clean(mic.read(), now)`), with the normal VAD, `silence_seconds`
      and `max_record_seconds`, and `wait_seconds=1.0`.
   3. Transcribe. `kind = interruption_kind(text)` (below).
   4. `"nothing"` or `"backchannel"`: if `can_resume`, `self.speaker.resume()`, put the status
      back, `self._voice_watch.rearm()`, return `""`. If it can't resume, treat it as `"stop"`.
   5. `"stop"`: `self.stop_speaking()`; return `""`.
   6. `"request"`: remember `earlier = self._request_text if not self._spoke else ""` (he kept
      talking while Abdoh was still thinking: it was one request); `self.stop_speaking()`;
      `self._reply_done.wait(5)`; return `f"{earlier} {text}".strip()`. Mark it like a hotkey
      request so it is handled even while the wake word is paused.
   `handle_text` stores the request it is working on in `self._request_text`.
8. `interruption_kind(text)` lives in `local_skills.py` next to `_DONE`:
   - `"nothing"`: empty, or only fillers (`uh`, `um`, `hmm`, `mm`, `ah`, `er`).
   - `"backchannel"`: the whole text is one of `okay`, `ok`, `yeah`, `yes`, `yep`, `right`,
     `i see`, `got it`, `sure`, `uh huh`, `mm hmm`, `mhm`, `wow`, `nice`, `cool`, `really`,
     `oh`, `alright`, `go on`, `continue`, `keep going`.
   - `"stop"`: matches `_DONE`, or one of `wait`, `hold on`, `one second`, `one moment`,
     `enough`, `thats enough`, `be quiet`, `quiet`, `shut up`, `stop talking`, `stop it`,
     `okay stop`, `pause`.
   - `"request"`: everything else.
9. `Daemon.create` builds one `SpeakerTap` (started), one `EchoCanceller` and one
   `VoiceWatch`, all optional: if any is unavailable, log one line and carry on without voice
   interruption. `stop()` stops the tap.
10. Existing tests call `_listen_once` and then check what was said. Add `daemon.wait_idle()`
    where needed; behavior must otherwise stay the same. All 654 existing tests must pass.

#### 37.8 Settings and words

- `voice_interrupts: true` and `voice_interrupt_sensitivity: "medium"` (`low | medium | high`),
  both applied live.
- Settings → Conversation: a switch **"Stop when I start talking"** ("Abdoh goes quiet as soon
  as it hears you and listens. Works best with headphones or a moderate speaker volume.") and a
  select **Sensitivity** (Low, Medium, High) shown when the switch is on. If the feature is
  unavailable, show why in one line instead ("Not available on this computer").
- README: a paragraph under "Talking with Abdoh", and a privacy line (what the speakers play is
  only used in memory to cancel it from the microphone).

#### 37.9 Tests for the flow (fakes only)

In `tests/test_interrupt.py`, with a fake watch whose `feed` fires on a chosen block:
- talking during a reply pauses the speaker, and a real sentence stops the reply, interrupts the
  brain (fake brain records `close`/interrupt) and is handled next;
- "okay" resumes the reply and nothing is sent anywhere;
- "wait" stops the reply and nothing is sent;
- talking while Abdoh is still thinking joins both parts into one request;
- a typed request's reply can be interrupted the same way;
- with `voice_interrupts: false`, or an unavailable watch, nothing is fed and replies run as
  before;
- the wake word still interrupts a reply (trusted engine) and not with the Vosk fallback;
- follow-up listening still starts after a reply ends.

**Done when:** the tests above pass, `scripts/echo_check.py` has been run with the owner and
its numbers are in the README (or a `TODO(blocked):` says it wasn't), and a live run shows a
Claude reply being interrupted by a new typed-in "fake voice" request with the conversation
kept (the `interrupt` path against the real Claude Code).

---

### Story 38: Look at my screen (`story/38-look-at-screen`)

**What the owner gets:** "look at my screen and tell me what's there", "what does this error
mean?", "read this to me", "which of these should I click?" Abdoh takes a picture of the
monitor he is working on and Claude answers about it.

1. **Which screen** (`claude/screen.py`):
   - `capture_screen(which="active", grab=...)`. `"active"`: the monitor that holds the window
     in front (`GetForegroundWindow` → `MonitorFromWindow` → `GetMonitorInfoW`; match it to the
     `mss` monitor with the same left/top; if there is no window, the primary monitor).
     `"all"`: `monitors[0]`. A monitor id (`monitorDevicePath`) picks that monitor (story 39
     adds "screen 2" and names on top of this).
   - Use `mss.MSS`. Raise `MAX_SIDE` to 2000 so text on a 3440-pixel monitor stays readable.
   - `front_window() -> tuple[str, str]`: the title of the window in front and its program
     name (`GetWindowThreadProcessId` → `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` →
     `QueryFullProcessImageNameW`, file name without `.exe`). Empty strings if unknown.
   - Both behind injectable functions; tests never touch the screen.
2. **Recognizing the request** (`claude/skills.py`): `wants_screen(request: str) -> str | None`
   returns `"active"`, `"all"` or None. It matches the normalized request against patterns, at
   least:
   - `(look at|check|see|read|describe|explain|watch) (my|the|this) (screen|display|monitor|window|page)`
   - `whats (on|in) (my|the|this) (screen|display|monitor|window)`, `what is on my screen`
   - `what (do you|can you) see`, `can you see (my screen|this)`, `what am i looking at`
   - `(my|the|this) screen` together with a question or command word (`what`, `why`, `how`,
     `which`, `where`, `who`, `tell`, `help`, `fix`, `find`, `explain`, `read`)
   - `all (my )?(screens|monitors|displays)` → `"all"`
   Translate and summarize keep their own, older rules and prompts.
3. **The prompt** (`skills.SCREEN_PROMPT`): the user's own words, then: `The screenshot shows
   their {which} screen. The window in front is "{title}" ({program}).` (leave the sentence out
   when unknown) and `Answer what they asked about it in a few spoken sentences. If text matters,
   quote the important part exactly.` For requests that start with `read` (`read this`, `read it
   to me`, `read my screen`): `Read the main text aloud as it is written; for this reply you may
   use up to twelve sentences.`
4. **Claude can ask to look** (`claude/reply.py`, `claude/brain.py`, `router.py`):
   - A new action outside `CLAUDE_ACTIONS`: `LOOK = "look"` with the help line
     `ACTION look: <what you need to see>   (takes a picture of the user's screen and shows it
     to you; use it when they point at something on screen: "this", "here", "that error")`.
     It is offered in the system prompt, and accepted by `speakable(..., allowed=...)`, only
     when `claude.allow_screen` is on. Add one sentence to the prompt: `When you use look, say
     one short sentence first and nothing else; you will get the picture and can then answer.`
   - `Router._stream`: when the `look` action arrives, remember it. When that first stream
     ends: emit the activity `Looking at your screen` (the daemon shows it and says it aloud if
     nothing was said), capture, and continue with `brain.stream(skills.LOOK_FOLLOW_UP, image)`
     in the same generator (`Here is the screenshot you asked for. ... Now answer the user's
     last request.`). At most one look per request; a second `look` is ignored.
5. **Router order:** translate → summarize → `wants_screen` → Claude. With `allow_screen` off,
   all of them answer `SCREEN_OFF` as today.
6. **Activity:** every capture emits the `activity` event `Looking at your screen`.
7. **Permissions page:** change the text of the screen switch to: "Look at your screen when you
   ask, or when you point at something on it ("what does this error mean?"). Abdoh always tells
   you when it looks. The picture is sent to Claude."
8. **Tests:** `wants_screen` (a table of phrases that should and shouldn't match, including
   "screen" inside unrelated requests such as "turn off the screen", which must not match once
   story 39 exists: keep `turn (on|off)`, `brightness`, `screenshot` out); monitor choice with
   fake monitors and a fake window; the prompt text with and without a window title; the read
   variant; the look action: first stream, capture, second stream, sentences in order; look
   ignored when `allow_screen` is off; only one look per request; the API brain gets the image
   directly.

**Done when:** the tests pass and a live check with the real Claude Code answers a question
about a screenshot of the active monitor (ask the owner first: a screenshot of his screen goes
to Claude).

---

### Story 39: Control more of the computer (`story/39-system-controls`)

Everything here is reachable three ways: as an **action** in commands and modes, as a **voice
skill** (instant, in `local_skills.py`), and through `Computer` (so tests use fakes).

#### 39.1 `src/abdoh/displays.py`

- The CCD structures and calls from Appendix B (they are verified: keep the size asserts).
- `Display` (dataclass): `id` (monitorDevicePath), `number`, `name`, `nickname`, `internal`,
  `active`, `primary`, `rect` (left, top, width, height; None when off).
- A **registry** in `<app_dir>/displays.json`: `[{"id", "number", "name", "nickname"}]`. A
  monitor seen for the first time gets the next free number; number new ones in the order of
  their GDI names (`\\.\DISPLAY1` before `\\.\DISPLAY5`), which gives this laptop: 1 the laptop
  screen, 2 HP 32f, 3 C34H89x. Numbers never change by themselves afterwards (a monitor that is
  off keeps its number). Names: the friendly name, or `Laptop screen` for an internal panel
  (output technology `0x80000000`, 6, 11 or 13), or `Monitor`.
- `Displays` (class; `backend` injectable for tests):
  - `list() -> list[Display]`: every connected monitor, on or off, in number order.
  - `set_active(wanted: set[str]) -> list[Display]`: exactly these ids on, the rest off.
    Refuse an empty set (`ActionError("At least one screen has to stay on.")`). Recipe in
    Appendix B: reserve the sources of monitors that stay on, give each newly turned-on monitor
    a free source on its own adapter, mark the chosen paths active with invalid mode indexes,
    try `SDC_APPLY | SDC_TOPOLOGY_SUPPLIED | SDC_ALLOW_PATH_ORDER_CHANGES`, and if that fails
    `SDC_APPLY | SDC_USE_SUPPLIED_DISPLAY_CONFIG | SDC_ALLOW_CHANGES | SDC_SAVE_TO_DATABASE`.
    Then poll `list()` for up to 3 seconds until the active set matches. A failure is an
    `ActionError("Windows didn't accept that screen layout.")`. If nothing would change, do
    nothing.
  - `find(spoken: str) -> list[Display]`: numbers (`2`, `two`, `second`), `laptop` / `built in`
    / `internal`, nicknames, names (`hp` finds `HP 32f`, `samsung` won't find `C34H89x`: only
    what is in the name or nickname), several joined by `and` or commas, `all`.
  - `rename(id, nickname)`, `renumber(ids_in_order)`.
  - `brightness(display)` / `set_brightness(display, percent)` through DDC/CI
    (`GetPhysicalMonitorsFromHMONITOR`, `GetMonitorBrightness`, `SetMonitorBrightness`,
    `DestroyPhysicalMonitors`; map HMONITOR → GDI name → display). Returns None / False when
    the monitor doesn't support it.
- `Computer.set_brightness(percent, display=None)`: all screens that are on: the internal one
  through WMI (existing code in `desk.py`), the others through DDC/CI. Returns the percent if at
  least one screen took it, else the existing `NO_BRIGHTNESS` error. `Computer.brightness()`:
  the first screen that can tell.
- **Applying a layout was never run.** The first real apply is a manual test with the owner
  (rule 5.2): a script `scripts/display_check.py` that lists the monitors, applies "only
  monitor N" for 8 seconds and restores the previous set in a `finally`.

#### 39.2 `winaudio.py`: the default speakers

- Add `GetId` to `IMMDevice` and the `IPolicyConfig` interface (Appendix C).
- `outputs() -> list[tuple[str, str, bool]]` (name, id, is default), `default_output() -> str`
  (id), `set_default_output(device_id)` for roles 0 (console) and 1 (multimedia); leave the
  communications role alone.
- `Computer.audio_outputs()`, `Computer.set_audio_output(spoken) -> str` (the chosen name;
  match by words in the name with `rapidfuzz`, `headphones` / `headset` / `speakers` as plain
  words; `ActionError` when nothing matches or two match equally).

#### 39.3 `desk.py`: theme, power, keys, windows, folders, clipboard

- `dark_mode() -> bool`, `set_dark_mode(on)`: both DWORDs under
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize`, then broadcast
  `WM_SETTINGCHANGE` with `"ImmersiveColorSet"` (`SendMessageTimeoutW`, `HWND_BROADCAST`).
- `power_mode() -> str`, `set_power_mode(name)`: `best_performance | balanced | efficiency`
  (Appendix F). Unknown GUID reads as `balanced`.
- `sleep()` (`powrprof.SetSuspendState(0, 0, 0)`), `screens_off()` (`SendMessageW(HWND_BROADCAST,
  WM_SYSCOMMAND, SC_MONITORPOWER, 2)`: all screens sleep until a key or the mouse moves),
  `shutdown(seconds, restart=False)` (`shutdown.exe /s|/r /t N`), `cancel_shutdown()`
  (`shutdown.exe /a`).
- `press_keys(text)`: `"ctrl+shift+esc"`, several combinations separated by commas or spaces
  (`"win+d, alt+tab"`). Parse with the tables in `hotkey.py` (`MODIFIERS`, `KEYS`), plus
  `f1`-`f24`, `printscreen`, and single letters and digits; a key without a modifier is allowed
  here (`f11`). Send with the existing `_send_keys`: modifiers down in order, key down and up,
  modifiers up in reverse. `parse_keys` raises `ValueError` with a readable message.
- Windows of other programs: `app_windows(name) -> list[handle]` (`EnumWindows`, visible,
  non-empty title, matched against the program name and the title, fuzzy);
  `close_app(name) -> int` (`PostMessageW(WM_CLOSE)` to each: the program may still ask to
  save); `focus_app(name)` (restore if minimized, press and release Alt, then
  `SetForegroundWindow`); `move_window(handle_or_front, display_rect, how)` with `how` in
  `maximized | left | right | keep` (restore, `SetWindowPos` into the monitor's work area, then
  maximize or half the area).
- `open_folder(name)`: `downloads`, `documents`, `desktop`, `pictures`, `music`, `videos`,
  `screenshots` (use `user_folders()` from `claude/code.py`, add Music and Videos there);
  `newest_file(folder) -> Path | None` for "open my last download".
- Clipboard: `get_clipboard() -> str` and `set_clipboard(text)` (`OpenClipboard`,
  `CF_UNICODETEXT`; retry a few times, the clipboard can be busy).
- All behind `Computer` methods with the same names, so `LocalSkills` and the actions only talk
  to `Computer`.

#### 39.4 New actions (commands, modes; `commands/registry.py`, `commands/actions.py`)

| Action | Value | Example |
|---|---|---|
| `displays` | `all`, `only <screens>`, `<screens> off`, `<screens> on` (screens: numbers or names, joined by commas or `and`) | `displays: "only 2"` |
| `brightness` | `0-100`, optionally `on <screen>` | `brightness: "100"` |
| `audio_output` | words from a speaker's name | `audio_output: "C34H89x"` |
| `dark_mode` | `on`, `off`, `toggle` | `dark_mode: "on"` |
| `power_mode` | `best_performance`, `balanced`, `efficiency` | `power_mode: "balanced"` |
| `power` | `sleep`, `lock`, `screens_off` | `power: "screens_off"` |
| `keys` | key combinations | `keys: "win+shift+s"` |
| `wait` | a duration up to 60 seconds | `wait: "2 seconds"` |
| `close_app` | a program's name | `close_app: "Spotify"` |
| `focus_app` | a program's name | `focus_app: "Chrome"` |
| `window` | `<program or this> to <screen> [maximized\|left\|right]`, or `minimize`, `maximize`, `restore`, `close`, `desktop`, `switch` | `window: "Chrome to 2 maximized"` |
| `mode` | a mode's name, or `normal` (story 40) | `mode: "Work"` |

`registry._check_slots` checks the form only (the screens don't have to exist): the `displays`
grammar, the fixed words, `parse_keys`, the `wait` limit. `{slots}` are not allowed in `keys`
and `close_app` (like `run`). Update the help headers in `commands/store.py` and
`commands.example.yaml`. Shutdown and restart are **not** actions.

#### 39.5 New voice skills (`local_skills.py`)

Patterns on the normalized request, in the style of the existing ones. At least:
- **Screens:** `turn off (monitor|screen|display) <screens>`, `turn on ...`, `turn off the other
  (monitors|screens)` (keep the one with the window in front), `(use )?only (monitor )?<screens>`,
  `just the laptop screen`, `(turn on )?all (the )?(monitors|screens|displays)( on)?`, `which
  (monitors|screens) are on`, `list my (monitors|screens)`. Replies: `Screen 2 is off.`, `All
  three screens are on.`, `Only the HP 32f is on.`
- **Speakers:** `switch (the )?(sound|audio)( output)? to <name>`, `(use|switch to) (the )?
  (headphones|headset|speakers|<name>)`, `play (the )?sound (on|through) <name>`, `(whats|what
  is) my (audio|sound) output`.
- **Theme:** `(switch to |turn on |enable )?(dark|light) (mode|theme)`.
- **Power:** `go to sleep`, `sleep (the |my )?(computer|pc|laptop)`, `turn off the screens?`,
  `screens off`, `(best )?performance (power )?mode`, `(power|battery) saver( mode)?`,
  `balanced power( mode)?`, `shut ?down( the (computer|pc|laptop))?( in <duration>)?`,
  `restart( the (computer|pc|laptop))?`, `cancel the (shutdown|restart)`.
- **Windows and programs:** `(close|quit|exit) <program>`, `(switch|go) to <program>`, `show
  <program>`, `move (this|it|<program>)( window)? to (monitor|screen)? <screen>`, `put (this|it)
  on the (other|next|laptop) screen`, `snap (this )?(window )?(to the )?(left|right)`.
  `<program>` must be found among the open windows, otherwise the request goes on to Claude
  (so "close the door" isn't mine).
- **Folders:** `open (my |the )?(downloads|documents|desktop|pictures|music|videos|screenshots)
  ( folder)?`, `open my (last|latest|newest) (download|screenshot)`.
- **Clipboard:** `copy that` (Abdoh's last reply; `Copied.`), `(read|whats in) my clipboard`,
  `what did i copy` (speak up to 300 characters, then "and more").
- **Clipboard for Claude** (`router.py`): when a request that goes to Claude mentions
  `clipboard`, `what i copied` or `the text i copied`, append `The user's clipboard contains:
  """<up to 4000 characters>"""` to the prompt. Only then.

**Asking first.** Shutting down and restarting need a yes. `LocalSkills` keeps one pending
action with a 60-second life: "shut down" answers `Shut down the computer? Say yes to go
ahead.`; the next request `yes` / `yeah` / `do it` / `go ahead` / `confirm` runs it
(`shutdown(20)`: "Shutting down in 20 seconds. Say cancel the shutdown to stop it."), anything
else cancels it (`Okay, I won't.`). A shutdown **with a delay** of a minute or more needs no
yes ("shut down in 30 minutes" is the sleep timer for movies). In `handle_text`, a spoken
request whose **string** reply ends with a question mark also listens for the answer (today
only Claude's replies do).

A new setting `allow_power: true` ("Abdoh may put the computer to sleep, shut it down or
restart it when you ask") gates sleep, shutdown and restart; the Permissions page gets the
switch in the "Your commands" card.

#### 39.6 Tests

`tests/test_displays.py` (a fake backend with three monitors: listing and numbering, the
registry file, numbers that survive a monitor being off, `find` for every form, `set_active`
choosing sources, refusing an empty set, no call when nothing changes, the fallback recipe,
the poll); `tests/test_system_actions.py` (every new action through `run_action` with a fake
computer, validation errors with readable messages); additions to `test_local_skills.py`
(every skill above, things that must **not** match, the yes/no flow, `allow_power` off);
`test_desk.py` (`parse_keys`, theme registry values with a fake registry, power mode names).

**Done when:** the tests pass, and with the owner present `scripts/display_check.py` has turned
one monitor off and on again on his laptop.

---

### Story 40: Modes (`story/40-modes`)

#### 40.1 The file: `<app_dir>/modes.yaml`

```yaml
- name: Movie                      # unique, case does not matter
  icon: film                       # optional: one of the names in modes/model.py ICONS
  phrases: ["movie night"]         # optional extra phrases; "<name> mode" always works
  settings:                        # optional; each one is undone by "back to normal"
    displays: [2]                  # exactly these screens on (numbers or names), or "all"
    brightness: 70                 # 0-100, every screen that supports it
    volume: 60                     # 0-100
    audio_output: "C34H89x"        # words from a speaker's name
    dark_mode: true
    power_mode: balanced           # best_performance | balanced | efficiency
    night_light: true              # story 42
    wake_word: false               # false: Abdoh stops listening for the wake word in this mode
    voice_replies: true
    follow_up: false               # keep listening after a reply
  actions:                         # optional; run in order after the settings (same as commands)
    - open_app: "Netflix"
    - say: "Enjoy the movie."
  exit_actions:                    # optional; run when the mode ends
    - media: play_pause
  schedule: ["weekdays 09:00"]     # story 42
```

The owner's own examples, as they should work when this story is done:

```yaml
- name: Movie
  settings: {displays: [2]}
- name: Work
  settings: {displays: all, brightness: 100}
  actions:
    - play_youtube: "jazz music"
    - open_app: "Visual Studio Code"
```

#### 40.2 `src/abdoh/modes/`

- `model.py`: `Mode` (frozen dataclass: `name`, `icon`, `phrases`, `settings` dict, `actions`,
  `exit_actions`, `schedule`), `SETTINGS` (the ten keys above, in apply order: `displays`,
  `audio_output`, `volume`, `brightness`, `dark_mode`, `power_mode`, `night_light`,
  `wake_word`, `voice_replies`, `follow_up`), `ICONS`, `parse_modes(data) -> list[Mode]`
  raising `ModesFileError` with messages like the commands file's (`mode 'Movie': brightness
  must be a number from 0 to 100.`). Actions are validated with the same code as commands
  (extract it from `parse_commands`; no `{slots}` in modes).
- `store.py`: `ModesStore` (`load`, `save(mode, old_name)`, `delete(name)`, atomic, validated
  before writing, a help header; copy the shape of `commands/store.py`) and `TEMPLATES`:
  Movie (`volume: 60`, `dark_mode: true`), Work (`power_mode: best_performance`, actions: open
  an app), Night (`brightness: 30`, `volume: 30`, `dark_mode: true`), Focus (`follow_up: false`,
  actions: `timer: 25 minutes`, `say`), Presentation (`dark_mode: false`, `brightness: 100`,
  `voice_replies: false`). Templates never set `displays` (they are different on every PC).
- `engine.py`: `ModeEngine(store, controls, run_actions, state_path)`.
  - `controls`: an object with, per setting key, `capture(key) -> snapshot`, `apply(key,
    value)`, `restore(key, snapshot)`. The real one (`ModeControls`, in the daemon module or
    next to it) maps to `Computer` and the daemon:

    | key | capture | apply | restore |
    |---|---|---|---|
    | `displays` | numbers that are on | `Displays.set_active` | the same |
    | `audio_output` | default output id | `set_audio_output` | `set_default_output(id)` |
    | `volume` | (percent, muted) | `set_volume` | both |
    | `brightness` | {screen number: percent} for screens that can tell | all screens | each screen |
    | `dark_mode`, `power_mode`, `night_light` | current value | set | set |
    | `wake_word` | `not daemon.paused` | `daemon.set_paused(not value)` | the same |
    | `voice_replies` | `daemon.voice_enabled` | set it and emit `voice` | the same |
    | `follow_up` | `cfg.follow_up_seconds` | 6 or 0, **in memory only** | the number |

  - `activate(name) -> str`:
    1. find the mode (`ActionError("You don't have a mode called X.")`);
    2. if another mode is on: run its `exit_actions`; for every remembered setting that the new
       mode does **not** set: restore it and forget it;
    3. for each setting of the new mode, in `SETTINGS` order: if nothing is remembered for it
       yet, `capture` it; then `apply`. A failing setting doesn't stop the rest: collect the
       messages;
    4. set `current`, save the state, emit the change, run the mode's `actions`;
    5. return `"Movie mode."`, or `"Movie mode, but <first problem>"`.
  - `deactivate() -> str`: no mode on → `"No mode is on."`. Otherwise run `exit_actions`,
    restore every remembered setting (displays first), clear, save, emit; `"Back to normal."`
  - `current` (name or None), `names()`.
  - State in `<app_dir>/mode_state.json`: `{"current": "Movie", "remembered": {...}}`, written
    atomically after every change, read at start. At start, if a mode is on, re-apply only its
    three Abdoh switches (`wake_word`, `voice_replies`, `follow_up`): Windows keeps the rest by
    itself. A state file that names a deleted mode is cleared.
  - Activating the mode that is already on applies it again (cheap, and it fixes drift).

#### 40.3 Voice, actions, router

- Router order becomes: remember → built-ins → **modes** → commands → local skills → screen →
  Claude. Modes come before commands and built-in skills on purpose: a mode called "Dark" or
  "Performance" wins over the built-in theme and power phrases.
- Phrases for a mode `X` (matched with the existing `match()` scoring and `match_threshold`):
  `X mode`, `X mode on`, `(switch|go|change) to X mode`, `(turn on|activate|start|enable|set)
  X mode`, plus the mode's own `phrases`. Ending: `(exit|leave|end|stop|quit|turn off|disable)
  (X|the|this) mode`, `X mode off`, `(go )?back to normal`, `normal mode`. Questions: `(which|
  what) mode (am i in|is on)`, `(what|which) modes do i have`, `list my modes`.
- The action `mode: "<name>"` / `mode: "normal"` for commands, modes' own actions (a mode can
  hand over to another; guard against loops: at most one hand-over per activation) and, in
  story 42, Claude.
- The daemon creates the engine after `Computer`; `router.modes = engine`. A new event
  `("mode", name or "")` goes to the UI and the tray. The tray tooltip shows `Abdoh: Listening
  (Movie mode)`.

#### 40.4 `AppApi`

`modes()` → `{ok, modes, templates, current, displays, outputs, icons}` (displays and outputs
so the editor can offer them), `save_mode(mode, old_name)`, `delete_mode(name)`,
`activate_mode(name)` → `{ok, message, displays_changed}`, `end_mode()`, `displays()`,
`rename_display(id, nickname)`, `reorder_displays(ids)`, `identify_displays()`. Activation runs
through the Bus (`("mode", name)` request) so it happens on a daemon thread, not on the UI
thread; the result comes back as a `history` line and the `mode` event.

#### 40.5 Tests

`tests/test_modes.py` with a fake `controls` that records calls and holds values:
- the owner's two examples: Movie turns screens 1 and 3 off; Work turns all on, sets the
  brightness and runs both actions in order;
- Movie → back to normal restores the screens exactly;
- Movie → Work: what Movie changed and Work doesn't set is restored first; Work → back to
  normal returns to the state from before Movie;
- a failing setting doesn't stop the others and is mentioned in the reply;
- the state file survives a restart; a deleted mode clears it; Abdoh's switches are re-applied
  at start;
- `follow_up` never reaches `config.yaml`;
- parsing and validation errors; the store never writes an invalid file; templates are valid;
- phrases: every form above activates or ends the right mode; a mode named Dark beats the theme
  skill; unknown mode names fall through;
- `exit_actions` run on leaving and on switching.

**Done when:** the tests pass, and with the owner present "movie mode" and "work mode" from a
hand-written `modes.yaml` have switched his monitors by a typed request.

---

### Story 41: The Modes page (`story/41-modes-page`)

- **Sidebar:** `Modes` between Home and Commands (a layers icon).
- **Page:** the title, one line of explanation, a **Back to normal** button (enabled when a
  mode is on), **New mode** and **Templates** buttons, and a grid of cards. A card shows the
  icon, the name, small chips that summarize it ("Only screen 2", "Volume 60%", "Dark", "+2
  actions"), and a **Turn on** button; the mode that is on has an "On" tag and an accent
  border. Clicking the card opens the editor.
- **Editor** (wide modal):
  1. Name, and an icon picker (the `ICONS` list as small buttons).
  2. "Say" chips (extra phrases); under them, in muted text: `"<name> mode" always works`.
  3. **In this mode**: one row per setting, each with a "Don't change" state:
     - *Screens*: a small drawing of the monitors (rectangles scaled from their positions; ones
       that are off in a dashed row below), each with its number, name and a switch; an
       **Identify** button; the note "At least one screen stays on".
     - *Brightness*, *Volume*: sliders with a "Don't change" checkbox.
     - *Speakers*: a select of the outputs. *Theme*: Dark / Light. *Power*: three options.
     - *Abdoh*: wake word, voice replies, keep listening (each On / Off / Don't change).
  4. **Then do** and **When the mode ends**: the action rows from the Commands page. Move
     `actionRows` and its `ACTIONS` table from `commands.js` into `app.js` so both pages share
     them.
  5. Footer: Delete, Cancel, **Try it**, Save. Try it saves, activates, and if the screens
     changed shows "Keep these screens?" with a 15-second countdown: **Keep** or **Go back**
     (and going back by itself at zero, which calls `end_mode`).
- **Identify:** `identify_displays()` opens, for 3 seconds, a small frameless always-on-top
  pywebview window in the middle of every screen that is on, with its number and name in large
  type (`webview.create_window(..., frameless=True, on_top=True, x=, y=, width=, height=)`),
  then destroys them.
- **Your screens** (a section at the bottom of the page): the list of known monitors with
  number, name, an editable nickname ("Left", "TV"), whether it is on, and up/down buttons to
  renumber. This is where "monitor 2" gets its meaning.
- **Home:** a chip in the top bar, `Mode: Movie` (hidden when no mode is on); clicking it offers
  the modes and "Back to normal".
- **Tray:** a `Modes` submenu (each mode, a check mark on the one that is on, "Back to normal").
  pystray menus can be built from a callable; rebuild when the `mode` event or the modes file
  changes.
- **Commands page:** the new actions from story 39 with fitting inputs: *Screens* (check boxes
  for the known monitors and "All"), *Speakers* (select), *Theme*, *Power mode*, *Power*
  (selects), *Press keys*, *Wait*, *Close a program*, *Switch to a program*, *Window* (text
  with a placeholder that shows the form), *Mode* (select of the modes and "Normal").
- **Demo data** in `bridge.js` for every new method (three monitors, two outputs, three modes),
  and check the page and the editor in headless Edge, light and dark.
- **Tests:** `AppApi` methods with fakes (including that activation goes through the Bus); the
  tray submenu; the page-and-API agreement tests keep passing.

**Done when:** the owner can make his Movie and Work modes in the window without touching a
file, try them, and switch them from the window, the tray and by voice.

---

### Story 42: More for modes and for listening (`story/42-extras`)

1. **Schedules.** `schedule: ["daily 23:00", "weekdays 09:00", "sat,sun 10:30"]` (days:
   `daily`, `weekdays`, `weekends`, or `mon`..`sun` joined by commas; 24-hour time). A small
   scheduler thread in the engine checks every 20 seconds and activates a mode when its minute
   comes; it remembers the last minute it fired so nothing fires twice, and it does not catch
   up on times that passed while Abdoh was off. The editor gets a "At a time" row (a time and
   day chips). Tests with a fake clock.
2. **Claude can use the new controls.** Add `mode`, `displays`, `audio_output` and `dark_mode`
   to `CLAUDE_ACTIONS` and `ACTION_HELP`, to `NEW_ACTIONS` under a new `CONFIG_VERSION`, and to
   the Permissions page (a card "System settings Claude may change"). When they are allowed,
   the system prompt also lists `The user's modes: Movie, Work.` and `Their screens: 1 Laptop
   screen, 2 HP 32f (TV), 3 C34H89x.` so Claude can turn "put the film on the big one" into
   `ACTION displays: only 3`. (`same_setup` already restarts the Claude session when the prompt
   changes.) Never `keys`, `close_app`, `type`, `power`.
3. **Quieter while Abdoh listens.** `duck_while_listening: true`: when a request recording
   starts (wake word, hotkey, follow-up, an interruption) and `SpeakerTap.level()` shows the
   computer is playing sound, lower the master volume to 30% of its value until the recording
   ends, then put it back (only if it still has the lowered value: the owner may have changed
   it). A switch in Settings → Conversation ("Turn the computer's sound down while Abdoh
   listens"). Tests with fakes: lowered and restored, not restored when changed meanwhile, not
   lowered when silent or when the setting is off.
4. **Night light (best effort; needs the owner once).** `desk.night_light()` /
   `set_night_light(on)` through the registry value in Appendix H. Before writing any code that
   changes it: ask the owner to switch night light on in Windows' settings and read the value
   again, so both layouts are known for his build. Write only when the current bytes match a
   layout you know; otherwise raise `ActionError("I can't switch the night light on this
   version of Windows.")` and open `ms-settings:nightlight`. Then: the mode setting
   `night_light`, the action `night_light: on|off`, the voice skill `turn (on|off) (the )?night
   light` / `night light (on|off)`, and a Night template that uses it. If the owner isn't
   available, ship the settings-page fallback and a `TODO(blocked):` note.
5. **Tests** for each part; the README sections for modes, the new skills and the new settings.

**Done when:** a scheduled mode fires with a fake clock, Claude switches a mode in a live check,
and the volume ducks in a test with fakes.

---

### Story 43: Release 0.5.0 (`story/43-release`)

1. Version `0.5.0`; README (new sections, the configuration table, known issues); the download
   page (`docs/index.html`: modes, "stop when you talk", "look at my screen"; refresh the
   screenshots with `scripts/take_screenshots.py`, add one of the Modes page).
2. `scripts/build_app.py`: `livekit` in `COLLECT`. Build, then run the packaged app in
   isolation (rule 5.5) and check the log: the tap started, the canceller loaded, no errors.
3. **Ask the owner** before tagging. When he says yes: merge, tag `v0.5.0`, push the tag, watch
   the release build, check the release and the download link.

---

## 7. Things only the owner can do

- Be there (and say yes) for the tests that make sound, change his screens or the night light.
- Tell Abdoh which monitor is which once: the app numbers them 1 (laptop), 2 (HP 32f), 3
  (C34H89x). If his "monitor two" is the other one, he swaps them under **Your screens**.
- Say when 0.5.0 should be published.

## 8. Later ideas (not in this epic)

- Wi-Fi and Bluetooth switches, connecting a named Bluetooth device.
- Feeding the cleaned signal to the wake word too, so "Hey Abdoh" works over a loud film (in the
  simulation the canceller also muffled the user's voice when other sound was loud and
  constant: measure before enabling).
- A hotkey per mode; a mode when Abdoh starts; modes that react to events (a monitor plugged
  in, on battery).
- Window layouts per mode. A more natural (neural) voice. Speech recognition on the GPU.

---

## Appendix A: capturing what the speakers play (verified)

```python
LOOPBACK, AUTOCONVERT, SRC_QUALITY, SILENT = 0x00020000, 0x80000000, 0x08000000, 0x2

class WAVEFORMATEX(Structure):
    _pack_ = 1
    _fields_ = [("wFormatTag", c_ushort), ("nChannels", c_ushort), ("nSamplesPerSec", c_ulong),
                ("nAvgBytesPerSec", c_ulong), ("nBlockAlign", c_ushort),
                ("wBitsPerSample", c_ushort), ("cbSize", c_ushort)]

class IAudioClient(IUnknown):
    _iid_ = GUID("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")
    _methods_ = (
        COMMETHOD([], HRESULT, "Initialize", (["in"], c_uint, "mode"), (["in"], c_ulong, "flags"),
                  (["in"], c_longlong, "buffer"), (["in"], c_longlong, "period"),
                  (["in"], POINTER(WAVEFORMATEX), "format"), (["in"], c_void_p, "session")),
        COMMETHOD([], HRESULT, "GetBufferSize", (["out"], POINTER(c_uint), "frames")),
        COMMETHOD([], HRESULT, "GetStreamLatency", (["out"], POINTER(c_longlong), "latency")),
        COMMETHOD([], HRESULT, "GetCurrentPadding", (["out"], POINTER(c_uint), "frames")),
        COMMETHOD([], HRESULT, "IsFormatSupported", (["in"], c_uint, "mode"),
                  (["in"], POINTER(WAVEFORMATEX), "format"), (["out"], POINTER(c_void_p), "closest")),
        COMMETHOD([], HRESULT, "GetMixFormat", (["out"], POINTER(POINTER(WAVEFORMATEX)), "format")),
        COMMETHOD([], HRESULT, "GetDevicePeriod", (["out"], POINTER(c_longlong), "default"),
                  (["out"], POINTER(c_longlong), "minimum")),
        COMMETHOD([], HRESULT, "Start"), COMMETHOD([], HRESULT, "Stop"), COMMETHOD([], HRESULT, "Reset"),
        COMMETHOD([], HRESULT, "SetEventHandle", (["in"], c_void_p, "event")),
        COMMETHOD([], HRESULT, "GetService", (["in"], POINTER(GUID), "iid"),
                  (["out"], POINTER(POINTER(IUnknown)), "service")),
    )

class IAudioCaptureClient(IUnknown):
    _iid_ = GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")
    _methods_ = (
        COMMETHOD([], HRESULT, "GetBuffer", (["out"], POINTER(POINTER(c_ubyte)), "data"),
                  (["out"], POINTER(c_uint), "frames"), (["out"], POINTER(c_ulong), "flags"),
                  (["out"], POINTER(c_ulonglong), "position"), (["out"], POINTER(c_ulonglong), "qpc")),
        COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], c_uint, "frames")),
        COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], POINTER(c_uint), "frames")),
    )

# device: the default render endpoint, from winaudio's enumerator: GetDefaultAudioEndpoint(0, 0)
client = device.Activate(IAudioClient._iid_, CLSCTX_ALL, None).QueryInterface(IAudioClient)
wanted = WAVEFORMATEX(1, 1, 16000, 32000, 2, 16, 0)            # PCM, mono, 16 kHz, 16 bit
client.Initialize(0, LOOPBACK | AUTOCONVERT | SRC_QUALITY, 2_000_000, 0, byref(wanted), None)
capture = client.GetService(IAudioCaptureClient._iid_).QueryInterface(IAudioCaptureClient)
client.Start()
while running:                                                  # every 10 ms
    while capture.GetNextPacketSize():
        data, n, flags, _position, _qpc = capture.GetBuffer()
        samples = (np.zeros(n, np.int16) if flags & SILENT else
                   np.ctypeslib.as_array(cast(data, POINTER(c_int16)), shape=(n,)).copy())
        capture.ReleaseBuffer(n)
```

Copy the samples before `ReleaseBuffer`. No packets at all means silence.

## Appendix B: monitors through CCD (structures verified; applying is untested)

```python
QDC_ALL_PATHS, QDC_ONLY_ACTIVE_PATHS, PATH_ACTIVE, MODE_IDX_INVALID = 1, 2, 1, 0xFFFFFFFF
SDC_TOPOLOGY_SUPPLIED, SDC_USE_SUPPLIED_DISPLAY_CONFIG, SDC_VALIDATE, SDC_APPLY = 0x10, 0x20, 0x40, 0x80
SDC_SAVE_TO_DATABASE, SDC_ALLOW_CHANGES, SDC_ALLOW_PATH_ORDER_CHANGES = 0x200, 0x400, 0x2000
INTERNAL = {0x80000000, 6, 11, 13}

class LUID(Structure):        _fields_ = [("LowPart", c_uint32), ("HighPart", c_int32)]
class PathSource(Structure):  _fields_ = [("adapterId", LUID), ("id", c_uint32),
                                          ("modeInfoIdx", c_uint32), ("statusFlags", c_uint32)]
class Rational(Structure):    _fields_ = [("Numerator", c_uint32), ("Denominator", c_uint32)]
class PathTarget(Structure):  _fields_ = [("adapterId", LUID), ("id", c_uint32), ("modeInfoIdx", c_uint32),
                                          ("outputTechnology", c_uint32), ("rotation", c_uint32),
                                          ("scaling", c_uint32), ("refreshRate", Rational),
                                          ("scanLineOrdering", c_uint32), ("targetAvailable", c_int32),
                                          ("statusFlags", c_uint32)]
class PathInfo(Structure):    _fields_ = [("sourceInfo", PathSource), ("targetInfo", PathTarget), ("flags", c_uint32)]
class Point(Structure):       _fields_ = [("x", c_int32), ("y", c_int32)]
class SourceMode(Structure):  _fields_ = [("width", c_uint32), ("height", c_uint32),
                                          ("pixelFormat", c_uint32), ("position", Point)]
class ModeUnion(Union):       _fields_ = [("sourceMode", SourceMode), ("raw", c_byte * 48)]
class ModeInfo(Structure):    _fields_ = [("infoType", c_uint32), ("id", c_uint32), ("adapterId", LUID), ("u", ModeUnion)]
class DeviceInfoHeader(Structure): _fields_ = [("type", c_uint32), ("size", c_uint32), ("adapterId", LUID), ("id", c_uint32)]
class SourceName(Structure):  _fields_ = [("header", DeviceInfoHeader), ("viewGdiDeviceName", c_wchar * 32)]   # type 1
class TargetName(Structure):  _fields_ = [("header", DeviceInfoHeader), ("flags", c_uint32),                 # type 2
                                          ("outputTechnology", c_uint32), ("edidManufactureId", c_uint16),
                                          ("edidProductCodeId", c_uint16), ("connectorInstance", c_uint32),
                                          ("monitorFriendlyDeviceName", c_wchar * 64),
                                          ("monitorDevicePath", c_wchar * 128)]
assert (sizeof(PathInfo), sizeof(ModeInfo), sizeof(TargetName)) == (72, 64, 420)
```

- Listing: `GetDisplayConfigBufferSizes(flags, &nPaths, &nModes)`, then `QueryDisplayConfig(flags,
  &nPaths, paths, &nModes, modes, None)`; on error 122 (the layout changed in between) try again.
  `QDC_ONLY_ACTIVE_PATHS` gives the monitors that are on, with positions
  (`modes[path.sourceInfo.modeInfoIdx].u.sourceMode`). `QDC_ALL_PATHS` (92 paths here) gives every
  possible source-target pair: a monitor is connected when `targetInfo.targetAvailable` is set;
  group by `(adapterId, target id)`.
- Names: `DisplayConfigGetDeviceInfo` with a `TargetName` header `(2, sizeof, target adapterId,
  target id)` and a `SourceName` header `(1, sizeof, source adapterId, source id)`.
- A monitor's identity is its `monitorDevicePath`. **Never store adapter LUIDs**: they change
  when Windows restarts.
- Turning monitors on and off, validated with `SDC_VALIDATE` for every combination tried:

```python
chosen, used = [], set()
for target in wanted:                       # monitors that are already on first
    paths = by_target[target]
    path = next((p for p in paths if p.flags & PATH_ACTIVE), None)
    if path is None:                        # turn it on: a source of its adapter that is free
        path = next(p for p in paths if (luid(p.sourceInfo.adapterId), p.sourceInfo.id) not in used)
    used.add((luid(path.sourceInfo.adapterId), path.sourceInfo.id))
    copy = PathInfo.from_buffer_copy(path)
    copy.flags = PATH_ACTIVE
    copy.sourceInfo.modeInfoIdx = copy.targetInfo.modeInfoIdx = MODE_IDX_INVALID
    chosen.append(copy)
array = (PathInfo * len(chosen))(*chosen)
err = user32.SetDisplayConfig(len(chosen), array, 0, None,
                              SDC_APPLY | SDC_TOPOLOGY_SUPPLIED | SDC_ALLOW_PATH_ORDER_CHANGES)
if err:                                     # this set of monitors was never used: let Windows choose
    err = user32.SetDisplayConfig(len(chosen), array, 0, None,
                                  SDC_APPLY | SDC_USE_SUPPLIED_DISPLAY_CONFIG | SDC_ALLOW_CHANGES
                                  | SDC_SAVE_TO_DATABASE)
```

With `SDC_TOPOLOGY_SUPPLIED` Windows takes resolutions and positions from what it remembers for
that set of monitors, which is why the screens come back where the owner had them. Replace
`SDC_APPLY` with `SDC_VALIDATE` to ask "would this work?" without changing anything.

DDC/CI brightness: `EnumDisplayMonitors` → for each HMONITOR `GetMonitorInfoW` (`szDevice` is the
GDI name, to match with the source name) → `dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR` →
`GetPhysicalMonitorsFromHMONITOR` (array of `{HANDLE, WCHAR[128]}`) → `GetMonitorBrightness(h,
&min, &cur, &max)` / `SetMonitorBrightness(h, value)` → `DestroyPhysicalMonitors`.

## Appendix C: switching the default speakers (verified with a no-op)

```python
class IPolicyConfig(IUnknown):
    _iid_ = GUID("{F8679F50-850A-41CF-9C72-430F290290C8}")
    _methods_ = (unused("GetMixFormat"), unused("GetDeviceFormat"), unused("ResetDeviceFormat"),
                 unused("SetDeviceFormat"), unused("GetProcessingPeriod"), unused("SetProcessingPeriod"),
                 unused("GetShareMode"), unused("SetShareMode"), unused("GetPropertyValue"),
                 unused("SetPropertyValue"),
                 COMMETHOD([], HRESULT, "SetDefaultEndpoint", (["in"], c_wchar_p, "device"), (["in"], c_uint, "role")),
                 unused("SetEndpointVisibility"))
POLICY_CONFIG = GUID("{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}")
policy = comtypes.CoCreateInstance(POLICY_CONFIG, IPolicyConfig, CLSCTX_ALL)
policy.SetDefaultEndpoint(device_id, 0)     # 0 console, 1 multimedia, 2 communications
```

`IMMDevice` needs two more methods after `OpenPropertyStore`: `GetId` (`["out"],
POINTER(c_wchar_p)`) and `GetState` (`["out"], POINTER(c_uint)`). Device ids look like
`{0.0.0.00000000}.{92dfafdb-89e4-43bf-b650-50e48f67f1ce}`.

## Appendix D: interrupting Claude Code (verified live, Claude Code 2.1.325)

```
stdin  → {"type":"control_request","request_id":"abdoh-1","request":{"subtype":"interrupt"}}
stdout ← {"type":"control_response","response":{"subtype":"success","request_id":"abdoh-1","response":{"still_queued":[]}}}
stdout ← {"type":"result","subtype":"error_during_execution","is_error":true,"result":null,...}   (0.03 s later)
```

Other lines can come in between (`assistant`, `user`); read until the `result` line. The process
keeps running and the next user message is answered with the whole conversation in mind,
including what it had said before the interruption.

## Appendix E: the Windows voice: where it is, stop, continue (verified)

```python
voice.Speak(text, SVSF_ASYNC | SVSF_IS_NOT_XML)
while not voice.WaitUntilDone(POLL_MS):
    status = voice.Status
    position, length = status.InputWordPosition, status.InputWordLength   # characters into `text`
voice.Speak("", SVSF_ASYNC | SVSF_PURGE_BEFORE_SPEAK)    # silent after 17 ms
voice.Speak(text[position:], SVSF_ASYNC | SVSF_IS_NOT_XML)   # continues from that word
```

`voice.Pause()` and `voice.Resume()` exist but act about a second late: don't use them.

## Appendix F: power mode

`powrprof.PowerGetEffectiveOverlayScheme(byref(guid))` and `PowerSetActiveOverlayScheme(byref(guid))`
(both return 0 on success), with a `comtypes.GUID`:

| Name | GUID |
|---|---|
| `best_performance` | `{DED574B5-45A0-4F42-8737-46345C09C238}` |
| `balanced` | `{00000000-0000-0000-0000-000000000000}` |
| `efficiency` | `{961CC777-2547-4F9D-8174-7D86181B8A7A}` |

## Appendix G: echo cancellation with WebRTC through `livekit` (verified in a simulation)

```python
from livekit import rtc
apm = rtc.AudioProcessingModule(echo_cancellation=True, high_pass_filter=True,
                                noise_suppression=False, auto_gain_control=False)
apm.set_stream_delay_ms(140)                      # the lag of the echo behind the reference
for i in range(frames):                           # 10 ms each: 160 samples, int16 bytes
    apm.process_reverse_stream(rtc.AudioFrame(speaker_bytes[i], 16000, 1, 160))
    frame = rtc.AudioFrame(mic_bytes[i], 16000, 1, 160)
    apm.process_stream(frame)                     # changes frame.data in place
    cleaned = bytes(frame.data)
```

`rtc.AudioProcessingModule` has exactly three methods: `process_stream`, `process_reverse_stream`
and `set_stream_delay_ms`. Results of the simulation (Abdoh's voice through a simulated room, the
echo as loud as the user unless noted, a real accented speaker as the user):

| Case | Attenuation of Abdoh's voice | Detector fires on Abdoh's own voice | User found after (medium rule) |
|---|---|---|---|
| clean speaker | 36 to 44 dB from the first second | 0.0% | 0.26 s |
| user 10 dB quieter than the echo | 40 to 45 dB | 0.0% | 0.24 s |
| speaker distorting | 38 to 44 dB | 0.0% | 0.26 s |
| quieter and distorting | 36 to 43 dB | 0.0% | 0.65 s |
| other constant sound playing too | 37 to 42 dB | 0.0% | missed (the user's voice was muffled too) |

Finding the lag between two streams (for `echo_check.py`), GCC-PHAT:

```python
n = 1 << int(np.ceil(np.log2(len(far) + len(mic))))
cross = np.fft.rfft(mic, n) * np.fft.rfft(far, n).conj()
lag = int(np.argmax(np.fft.irfft(cross / (np.abs(cross) + 1e-9), n)[: int(0.4 * 16000)]))
```

## Appendix H: night light (only read so far)

`HKCU\Software\Microsoft\Windows\CurrentVersion\CloudStore\Store\DefaultAccount\Current\`
`default$windows.data.bluelightreduction.bluelightreductionstate\`
`windows.data.bluelightreduction.bluelightreductionstate`, value `Data` (`REG_BINARY`).

Off, Windows 11 build 26200, 27 bytes:
`43 42 01 00 0a 02 01 00 2a 06 b3 d6 b1 d6 06 2a 2b 0e 05 43 42 01 00 00 00 00 00`

Bytes 10 to 14 are a time stamp (it changes on every switch). On older builds the "on" value
has two more bytes (`10 00`) inside the inner block and a length byte that is 2 higher; that
must be confirmed on this build by reading the value while night light is on (story 42).
