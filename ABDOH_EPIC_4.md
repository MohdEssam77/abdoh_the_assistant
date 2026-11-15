# EPIC 4: Abdoh that feels like a real assistant

> **For Claude Code:** This file is your source of truth for the fourth epic. Epics 1 to 3 are
> done; their architecture still applies unless this file changes it. Work through the stories
> **in order** and follow the working rules in `CLAUDE.md` exactly. Keep everything **simple**.

## 1. Goal

Abdoh 0.3 works, but talking to it isn't smooth yet: it mishears accented English, rejects a
correct wake-up when the transcript misspells "Abdoh", answers slowly, goes quiet while Claude
works, and forgets the conversation after a minute. This epic makes it **accurate, fast and
fluent**: you talk, it understands, it keeps you posted, and you can keep talking.

### Measured on 2026-11-16 (i7-13650HX laptop)

| What | Before | Choice |
|---|---|---|
| Word errors, Arabic-accented English (40 L2-ARCTIC clips) | Whisper base.en 8.8% (0.73 s) | **Parakeet TDT 0.6b v2: 4.4% (0.59 s)**; Whisper small.en 6.3% (2.07 s) |
| Trained wake word (`hey_abdoh.onnx`) | n/a | fires 0.1 to 0.3 s after "Abdoh"; highest score on 57 other clips: 0.02 |
| Claude Code, first words | 2.1 to 2.8 s (new process per request, any model) | one process kept open: about 1 s from the second request, and it remembers the conversation |
| "Set the volume to 75%" | 18 s (Claude wrote PowerShell) | instant, built in |

## 2. Tech stack changes

| Concern | Choice | Why |
|---|---|---|
| Speech recognition (English) | **NVIDIA Parakeet TDT 0.6b v2** (int8 ONNX, CC-BY-4.0) through the small `onnx-asr` package, on the `onnxruntime` we already ship | Half the errors of Whisper base.en at the same speed. Costs about 630 MB on disk and 730 MB of RAM |
| Speech recognition (other languages) | faster-whisper, multilingual model (`small` by default), only among the languages you chose | Parakeet v2 is English only |
| Wake word | The trained model is trusted: the request is the audio **after** the wake word. No transcript check | The check threw away real wake-ups; the audio before the wake word added noise |
| Claude (subscription) | One `claude -p --input-format stream-json` process kept open per conversation | Faster, and Claude remembers what was said |
| Volume, microphone level | Windows Core Audio through `comtypes` (already a dependency) | Exact volume without key presses; shows and fixes a quiet microphone |
| Voices | SAPI desktop voices plus Windows' OneCore voices, picked by the reply's language | Replies in Arabic (and other languages) are spoken by a voice that can read them |

## 3. Stories

### Story 32: Hearing you right (`story/32-hearing`)
Parakeet for English with Whisper as the fallback and for other languages; a `languages`
setting instead of `language`; quiet audio is levelled before recognition; with the trained
wake word the request is what you say after it (a chime confirms the wake-up); the trained
model ships with Abdoh (`assets/hey_abdoh.onnx`); Settings shows the microphone's Windows volume
and can raise it.
**Done when:** tests cover engine choice, levelling, the new wake flow and language handling.

### Story 33: Faster (`story/33-speed`)
Abdoh opts out of Windows' background throttling; Claude Code stays open between requests
(started ahead of time, restarted when settings change, closed after a quiet while); every
request logs where its time went; Settings offers a faster Claude model.
**Done when:** the session protocol is tested with fake processes and timings appear in the log.

### Story 34: Conversation (`story/34-conversation`)
Claude says a short line before slow work and Abdoh shows what it's doing ("Searching the
web"); if nothing has been said after a few seconds Abdoh says so; after a reply Abdoh keeps
listening for a few seconds (no wake word); saying the wake word interrupts a reply; replies
are spoken in the language you used, with a matching voice.
**Done when:** each behavior is tested with fakes and can be turned off in Settings.

### Story 35: More that Abdoh does by itself (`story/35-skills`)
Exact volume, screen brightness, battery, date and time, quick maths, notes, reminders that
survive a restart, typing what you dictate, screenshots, window controls, "repeat that", "what
can you do". Claude can use the new actions too.
**Done when:** every skill is unit tested through `LocalSkills` with a fake computer.

### Story 36: Release 0.4.0 (`story/36-release`)
Bundle the models, update the README and the download page, tag `v0.4.0`.
