# EPIC 10: Abdoh on your phone

> **For Claude Code:** This file is your source of truth for the tenth epic. Epics 1 to 9 are
> done; their architecture and the ground rules of `ABDOH_EPIC_5.md` to `ABDOH_EPIC_9.md`
> (section 5 of each) still apply unless this file changes them. Work through the stories
> **in order** and follow the working rules in `CLAUDE.md` exactly. Keep everything **simple**.
>
> **Start here:** on the first story branch, the first commit changes the first paragraph of
> `CLAUDE.md` to name `ABDOH_EPIC_10.md` as the current source of truth (epics 1 to 9 done), and
> adds this file (`docs: epic 10 plan`).

---

## 1. Goal

Abdoh 0.13.3 (plus stories 135 to 138: installing updates from the app, naming the AI in use,
quiet screenshots) runs on the owner's laptop. The owner wants to reach it from the phone
(2026-11-27): talk or type to Abdoh from anywhere, hear and read its answers on the phone, and
have it act on the laptop (lamps, apps, modes, music) as if they had asked at the desk.

How (the owner chose it on 2026-11-27):

1. **A home-screen web app.** Abdoh serves a small page made for phones. On the iPhone it is
   added with Share → Add to Home Screen (Android: Install app) and then opens like an app. No
   App Store, one page for iPhone and Android, plain HTML, CSS and JavaScript like the window.
2. **Tailscale for the connection.** Tailscale (free) puts the phone and the laptop in one
   private network, at home or anywhere. `tailscale serve` gives the laptop a real HTTPS address
   in that network (`https://<laptop>.<tailnet>.ts.net`), which the phone needs for the
   microphone and for installing the page. Nothing is open to the internet.
3. **Paired phones only.** Settings → Phone shows a QR code with a one-time code; the phone that
   scans it gets its own key. Every request needs that key. The owner can remove a phone.

### Non-goals (for now)
- Notifications on the phone (timers, reminders, "Codoh is done"): they need Web Push (a new
  package, and on the iPhone only for home-screen apps). Later.
- Codoh from the phone; watching the laptop's screen from the phone; the board on the phone.
- A wake word on the phone, or listening while the phone is locked (a web app can't).
- Reaching Abdoh without Tailscale (no relay server, no open port, no Telegram bot).
- Waking a sleeping laptop.

---

## 2. What was checked (2026-11-27)

| Question | Result |
|---|---|
| Tailscale Serve | `tailscale serve --bg --https=443 http://127.0.0.1:<port>` shares a local web server over HTTPS, only inside the tailnet ("Funnel" would open it to the internet; not used). With `--bg` it keeps running and comes back after a reboot. `tailscale serve --https=443 off` turns off only that one; `tailscale serve reset` clears all of them (not used: the owner may share other things). Only `http://127.0.0.1` targets are supported. Forwarding a port needs no administrator rights |
| HTTPS in the tailnet | Must be allowed once in Tailscale's admin console (MagicDNS and HTTPS certificates). When it isn't, `tailscale serve` prints a `https://login.tailscale.com/...` link to allow it and waits. The laptop's name becomes public in Certificate Transparency logs (Tailscale's own warning) |
| Tailscale's state | `tailscale status --json`: `BackendState` (`Running`, `NeedsLogin`, `Stopped`, ...), `Self.DNSName` (`laptop.tail1234.ts.net.`), `CertDomains`. The format "may change": Abdoh reads only these and copes with them missing |
| Speech recognition for the phone | `Transcriber.transcribe(audio)` takes 16 kHz mono 16-bit audio. The phone records with the Web Audio API and sends exactly that, so nothing new is needed to read phone audio (no AAC/MP4 decoding) |
| Abdoh's voice for the phone | The natural voices (Piper, Kokoro) make the audio as numbers before playing it (`synthesize_audio`, `_synthesize`), so a sentence can be turned into a WAV file with Python's `wave`. The Windows voice can't easily: then the phone speaks with its own voice (`speechSynthesis`) |
| A web server in Abdoh | Python's `http.server.ThreadingHTTPServer` is enough (one person, a few requests). No new package |
| The QR code | Nothing in Abdoh makes QR codes. `segno` (BSD, pure Python, no dependencies, about 300 KB) makes an SVG: the one new dependency of this epic |
| iPhone home-screen apps (known behaviour, not tried here: no iPhone) | They keep their own storage, apart from Safari: the phone's key must be saved inside the installed app. Without a `start_url` in the manifest the iPhone opens the address it was added from, so the pairing link (with its code) is what the app opens first. The microphone works in home-screen apps (iOS 14.3 and later); sound can only start after a tap. If the app opens without the code, the page falls back to "scan the code again" |

---

## 3. Design

### 3.1 The phone server (`abdoh/phone/`)

- `phone/devices.py`: the paired phones in `~/.abdoh/phones.json`: `[{id, name, key_hash,
  added, seen}]`, the key itself never stored (SHA-256). Pairing codes: random (128 bits),
  one use, 30 minutes, kept in memory only.
- `phone/hub.py`: what the phone sees and asks. It listens to the bus (a new `Bus.listen`) and
  keeps the last 300 events with numbers; the page asks for the events after the last one it
  has and waits up to 25 seconds for new ones (long polling: works through Tailscale's proxy,
  on a flaky mobile network, and the page never misses one). Today's conversation, the status,
  the AI's name and the mode are kept so a page that opens late shows it all.
- `phone/server.py`: `ThreadingHTTPServer` on **127.0.0.1 only** (`phone_port`, default
  47811). Static files from `phone/web/`; the API under `/api/`. The request handling is a plain
  function (`PhoneApp.handle(method, path, headers, body)`), so tests need no sockets.
  - `POST /api/pair {code, name}` → `{key}` (no key needed for this one).
  - With `Authorization: Bearer <key>`: `GET /api/state`, `GET /api/events?after=N`,
    `POST /api/text {text, speak}`, `POST /api/voice` (raw 16 kHz audio, up to 60 s),
    `POST /api/stop`, `GET /api/audio/<id>` (a reply's sentence as WAV, kept 10 minutes),
    `POST /api/control {kind, value}` (story 143), `POST /api/forget` (unpair this phone).
  - No settings, keys, permissions, memory editing or Codoh: the phone can ask Abdoh things,
    and Claude's permissions apply as on the laptop.
  - Headers: `Cache-Control: no-store` for the API, a strict Content-Security-Policy
    (`default-src 'self'`), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.
- Settings: `phone: false` (off until the owner turns it on) and `phone_port: 47811`. The
  server starts and stops with the switch, without a restart.

### 3.2 Requests from the phone (daemon)

- The hub asks the daemon with the bus request `("phone", {"text", "speak"})`; voice is
  transcribed first (on the hub's thread, with the daemon's transcriber).
- `handle_text(text, phone=True)`: everything as for a typed request, but the reply goes to the
  phone: each sentence `_speak` would say becomes the event `("phone_say", text)`; nothing is
  played on the laptop, no ticking, no ducking, no listening afterwards. "One moment" fillers
  and "Searching the web" become the phone's status line. Actions run on the laptop.
- The conversation line is `You (phone): ...`; the window shows it with a small phone mark.
- The hub turns each `phone_say` sentence into audio (when the phone asked for speech and the
  voice is a natural one) on one worker thread, in order, and sends `say {text, audio}`.
- A question from Abdoh ("Shut down the computer?") also sends `question {text}`: the phone
  shows Yes and No buttons.

### 3.3 Tailscale (`phone/tailscale.py`)

- `find()`: `tailscale.exe` on PATH or in `C:\Program Files\Tailscale\`.
- `state()`: installed, running, signed in, the address, HTTPS allowed (from `tailscale status
  --json`), and whether Abdoh's serve is on (`tailscale serve status --json`).
- `share(port)`: `tailscale serve --bg --https=443 http://127.0.0.1:<port>` with a time limit;
  a `login.tailscale.com` link in its output means HTTPS must be allowed first: the link is
  returned and the command stopped. `unshare()`: `tailscale serve --https=443 off`.
- Every command runs without a window (`CREATE_NO_WINDOW`), with a time limit.

### 3.4 Settings → Phone (window)

One card, in order:
1. **Use Abdoh from your phone** (the switch).
2. **Tailscale**: what's missing, one step at a time: "Get Tailscale" (tailscale.com/download),
   "Open Tailscale and sign in", "Allow HTTPS for your Tailscale network" (the link), "Share
   Abdoh in your Tailscale network" (runs `share`), then the address. **Check again**.
3. **Pair a phone**: a QR code (and the link to copy) and the steps: "On your phone: install
   Tailscale and sign in with the same account, turn it on, scan this code with the camera,
   then tap Share → Add to Home Screen and open Abdoh from there." The code works once, for 30
   minutes.
4. **Your phones**: name, added, last used, Remove.
5. A note: "The laptop must be on and awake. Plugged in, let it never sleep:" and a button to
   Windows' power settings.

### 3.5 The phone page (`phone/web/`)

- `index.html`, `phone.css` (the window's colours, light and dark by the phone's setting),
  `phone.js`, `manifest.webmanifest` (no `start_url`, see 2), `sw.js` (keeps the page itself
  for a quick start; never the API), icons (180, 192, 512 px).
- First start: `#pair=<code>` in the address. In the installed app (or after "Use it in the
  browser"), it pairs, keeps the key in `localStorage`, and removes the code from the address.
  In Safari on the iPhone it first says how to add it to the Home Screen (the key must be made
  inside the app). No key and no code: "Scan the code in Abdoh's Settings → Phone again."
- The page: a header with Abdoh's name and a dot (laptop online, busy, offline), the
  conversation (today's, as in the window, with the replies appearing sentence by sentence),
  and at the bottom a text box, a send button and a big microphone button (tap to talk, tap to
  send; Cancel). While Abdoh answers: Stop. A "Speak replies" switch and "Unpair this phone"
  in a small menu.
- Offline (laptop asleep, Tailscale off): "Can't reach your computer. Is it on and awake, with
  Tailscale on?" and it tries again by itself.

### 3.6 Quick controls (story 143)

A row above the text box: the modes (and Normal), play/pause, next, volume down/up, lock the
computer. They use the same code as the window and the tray (`mode` request, the media and
volume actions, `power` lock), with the same permissions.

---

## 4. Ground rules for this epic

1. Unit tests never start a real server socket, never run Tailscale, never use the microphone
   or speakers: `PhoneApp.handle` directly, a fake `run` for Tailscale, fake transcribers and
   voices.
2. One new dependency: `segno` (QR codes, see 2). Nothing else.
3. The server listens on 127.0.0.1 only. Every API call but pairing needs a paired phone's key;
   tests check that a missing, wrong or removed key gets 401 and changes nothing.
4. Every new page and card is checked in light and dark in demo mode (the window's `?demo`, the
   phone page's `?demo`), with screenshots at phone size, before its story is merged. No visible
   console windows while checking (the owner noticed them once).
5. Not released: the version stays 0.13.3 until the owner says to release.

---

## 5. Stories

### Story 139: The phone server (`story/139-phone-server`)
1. This file, and `CLAUDE.md` naming it (`docs: epic 10 plan`).
2. `Bus.listen`; `phone/devices.py`, `phone/hub.py`, `phone/server.py` (3.1); settings `phone`
   and `phone_port` (config, example config, settings view); starting and stopping with the
   switch.
3. The daemon's phone requests (3.2): the reply to the phone, nothing on the laptop's speakers,
   `You (phone):` in the conversation.
4. Tests: pairing (once, expiry, wrong code), keys (missing, wrong, removed), events after N and
   waiting, text requests reaching the daemon, the reply as `phone_say`, nothing spoken.

### Story 140: Tailscale and Settings → Phone (`story/140-phone-settings`)
`phone/tailscale.py` (3.3) with a fake `run`; `AppApi.phone_*`; the card (3.4) with the QR code
(`segno`); demo data and screenshots.

### Story 141: The phone page (`story/141-phone-page`)
The page (3.5): pairing, the conversation, typing, status, Stop, offline; the manifest, service
worker and icons; a demo mode; screenshots at phone size in light and dark.

### Story 142: Talking from the phone (`story/142-phone-voice`)
Recording on the phone (Web Audio, 16 kHz), `/api/voice` → transcription → the request;
replies in Abdoh's voice (`render` on the natural voices → WAV) or the phone's own; "Speak
replies".

### Story 143: Quick controls and answers (`story/143-phone-controls`)
3.6, the Yes/No buttons for Abdoh's questions, the phone mark in the window's conversation.

### Story 144: Docs (`story/144-phone-docs`)
GUIDE.md (a Phone section: setup step by step, privacy, known issues), README (one line), the
Catalog (a "Your phone" feature), this file's results. No release.

---

## 6. The owner's decisions (2026-11-27)
- The phone uses a home-screen web app served by Abdoh, reached through Tailscale.
- Replies to the phone play on the phone only; the laptop stays quiet (proposed, not objected).
- Notifications come later (they need Web Push).

## 7. Things only the owner can do
- Install Tailscale on the laptop and the phone, sign in with the same account on both, and
  allow HTTPS for the tailnet when Settings → Phone asks.
- Scan the QR code, add Abdoh to the Home Screen, and try it away from home (mobile data).
