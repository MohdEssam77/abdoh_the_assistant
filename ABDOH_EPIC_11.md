# ABDOH_EPIC_11: Everything from the phone

Epic 10 (stories 139 to 146) put Abdoh on the owner's phone: a home-screen web app reached
through Tailscale, typing, talking, a hands-free call, quick controls. This epic makes the phone
a full way to use Abdoh, as the owner asked on 2026-11-28:

> I should be able to ask Abdoh to do anything from the phone, and if I ask it to show me
> feedback, it should be able to show me a stream of what it is doing. Control and give
> instructions to Codoh from the phone and see what it is doing in real time. Tell it to
> explain something on the board and see the board on my phone. If I ask it to open something,
> it should show me what it opened. If I need a document from the laptop, ask Abdoh to find it
> and give it to me so I can download it on my phone. And more examples that you can think of.
> Then go through the phone feature again and make sure there are no bugs, and open a PR with
> the details and screenshots; I'll merge it, then we release.

Not released by this epic: the owner merges the PR, then says when to release.

---

## 1. What the phone gets

1. **Steps, live.** While Abdoh works on a phone request, the phone shows each step as it
   happens: "Searching the web: weather in Berlin", "Reading CV.pdf", "Running a command",
   "Opened Spotify", "Asked Codoh: add a dark mode". When the answer is done they fold into a
   "4 steps" line under it, which opens again with a tap.
2. **The screen.** After Abdoh opens something for a phone request (an app, a website, a
   video), the phone gets a picture of the computer's screen a moment later, so the owner sees
   what it opened. Claude can also show the screen when asked ("what's on my screen?", "show
   me"): `ACTION show_screen`. The controls get **See the screen**, any time.
3. **Files to the phone.** "Find my CV and send it to me": Claude finds the file (it may already
   look through the owner's files) and writes `ACTION send_file: <full path>`. The phone gets a
   card with the file's name, size and kind, **Open** (the phone's own viewer, with its Share
   and Save to Files) and **Download**. Only files where Claude may work (Settings → AI: the
   home folder or the folders chosen there), at most 1 GB, each link for an hour.
4. **Files from the phone.** A paperclip in the composer: a photo or a file goes to the
   computer (into `Downloads\From your phone`), and Abdoh is told about it with the message:
   "what's in this photo?", "put this on the board and explain it", "save it to my desktop".
   At most 100 MB.
5. **The clipboard both ways.** In the controls: **Get the computer's clipboard** (shown, with
   Copy) and **Send to the computer's clipboard** (what was typed there).
6. **The board.** What Abdoh writes on the board for a phone request shows on the phone,
   written out live the same way as in the window (code, math, tables, drawings, pictures), in
   a Board view that opens by itself the first time and from a card in the chat after that.
   Claude may use the board for any phone request when seeing beats hearing ("explain merge
   sort on the board"), not only in a role; the laptop's window doesn't jump up for it.
7. **Codoh.** A Codoh view on the phone: its chats (running ones first), a chat's messages,
   tool cards and answers live, a box to send it instructions (queued while it works, as on
   the page), **Stop**, approval cards (Allow, Always, Deny) and question cards, and a new chat
   in one of its folders. When the phone sent the latest message, Codoh's "needs you" and
   "done" notices go to the phone, not out loud on the laptop.

Ideas for later (not in this epic): notifications on the phone (Web Push), the laptop's camera,
remote control of the mouse and keyboard.

## 2. Design

### 2.1 Claude knows when the user is on the phone
- With the phone switch on, the system prompt gets a PHONE section: a message that starts with
  `(From the phone)` comes from the owner's phone; they read and hear the answer there; they
  can't see the computer. It says what's only for the phone: the board (rules as for a role's
  board, shortened), `ACTION send_file: <full path>`, `ACTION show_screen: <why>`, and that a
  file they sent from the phone comes as `(They sent a file from the phone: <path>)`.
- The router tags phone requests and allows `send_file` and `show_screen` only for them.

### 2.2 Steps (story 147)
- Claude Code's stream already says when a tool starts (`on_tool(name)`); its `assistant`
  events carry the tool's input. A new `on_step(name, input)` turns that into a short line
  (`steps_text`): "Searching the web: <query>", "Reading <file name>", "Looking for <pattern>",
  "Running <command, cut>", "Writing <file name>". The router reports every action it runs
  (`on_action(kind, arg)`: "Opened Spotify", "Desk lamp: warm white").
- During a phone request the daemon emits `phone_step`; the hub sends
  `{"type": "step", "text", "for"}`. The page keeps the steps of the reply being made and
  shows them under the typing dots, then folded under the answer.

### 2.3 Media from the computer (stories 148, 149)
- Screenshots, files and board pictures reach the phone as **links with a secret in them**
  (`/media/<32 hex characters>`): an `<img>` and a link opened in the phone's viewer can't send
  the phone's key, and the secret is as strong (128 bits), only valid for an hour, and only
  inside the owner's tailnet. The hub keeps them (`MediaStore`): images in memory (at most 40),
  files as paths, streamed from disk in pieces (never read whole).
- `{"type": "image", "id", "caption", "for"}` and `{"type": "file", "id", "name", "size",
  "kind", "for"}` events; both are also kept in the hub's state (the last 30) with where they
  fall in the conversation, so a page that opens later shows them in place.
- Screens: `claude/screen.grab("active")`, scaled to 1600 px at most, JPEG. After an `open_app`,
  `open_url` or `play_youtube` action in a phone request: one picture, 2.5 s after the reply's
  last action (the app needs a moment). `ACTION show_screen` takes one at once. The controls'
  **See the screen** asks `/api/screen`.
- Uploads: `POST /api/upload?name=...` with the file as the body, streamed to disk (100 MB at
  most), saved under `Downloads\From your phone` with a name that doesn't overwrite anything;
  then the request goes on as a phone request with the note.

### 2.4 The board (story 150)
- The hub keeps the board's cards (`board` events: `{id, text}`, `None` to clear) and pictures
  (`board_picture`, their data stored as media links instead of data: URLs), and sends
  `{"type": "board", "card"}` and `{"type": "board_picture", ...}`.
- The page serves the window's own `board.js` and its `vendor/` (KaTeX, Mermaid, Graphviz) from
  `ui/web`, so the phone draws exactly what the window draws. Graphviz needs
  `'wasm-unsafe-eval'` in the page's Content-Security-Policy.
- `daemon._on_board` doesn't bring the window up for a phone request.

### 2.5 Codoh (story 151)
- The phone server calls the app's one Codoh (`codoh.manager.shared`): `/api/codoh` (state),
  `/api/codoh/chat?id=&since=`, and POST `/api/codoh/send`, `/stop`, `/answer`, `/new`. Reading
  a chat from the phone doesn't count as the window looking at it (`look=False`).
- `send(..., by_phone=True)` marks the chat as the phone's: its notices go to the phone
  (`phone_codoh` → `{"type": "codoh", "chat", "text"}`), not out loud. A Codoh request Abdoh
  makes for a phone request (`ACTION codoh`) is the phone's too.

### 2.6 Safety
- Everything still needs a paired phone; media links are secrets that expire.
- `send_file` only sends files inside the folders Claude may work in, never Abdoh's own data
  folder (keys, paired phones), and refuses folders and missing files.
- Uploads never overwrite and never leave their folder (the name is cleaned).

## 3. Stories

### Story 147: Steps, live (`story/147-phone-steps`)
2.1 and 2.2, tests (the step lines, the events in order, the PHONE section and tag).

### Story 148: The screen on the phone (`story/148-phone-screen`)
The media store and links, screenshots after opening, `ACTION show_screen`, **See the screen**,
the image viewer on the page.

### Story 149: Files both ways, and the clipboard (`story/149-phone-files`)
`ACTION send_file`, file cards; uploads; the clipboard in the controls.

### Story 150: The board on the phone (`story/150-phone-board`)
2.4 and the Board view.

### Story 151: Codoh on the phone (`story/151-phone-codoh`)
2.5 and the Codoh view.

### Story 152: A review of the whole phone feature (`story/152-phone-review`)
Read all of `abdoh/phone`, the phone parts of the daemon and the page again, looking for bugs;
fix what's found, with tests.

### Story 154: The board as a PDF on the phone (`story/154-phone-board-pdf`)
The owner, after reading the PR: "can the user download the board as a PDF?" A **Save as PDF**
button on the phone's board, and asking in any words from the phone ("send me the board as a
PDF", "can I keep this?"), with or without a role: `ACTION board_pdf` is allowed for phone
requests. The laptop's window makes the PDF as it always does (it works hidden in the tray too:
closing only hides it), but for the phone it neither opens it nor says where it went; the
daemon sends it as a file card (`phone_file`), or what went wrong as a note.

### Story 155: The screen live, and the right screen (`story/155-phone-live-screen`)
After 0.14.0, the owner: pictures came of the main screen, not where WhatsApp was moved ("open
it on my second screen"), "open WhatsApp" (a built-in skill, no Claude) sent none, and they
want to watch it live, also on a call ("open the camera and show me": the call to the side, the
screen live). Now (`phone/live.py`):
- what the built-in skills and the user's commands do is reported like Claude's actions
  (`Router._note_done`), so steps and pictures come for them too;
- a picture is of the screen where the app's window is, once it has opened (2.5 s) or settled
  after moving (1 s), with which screen it is ("Screen 2 · mid screen", Abdoh's numbers and
  names from displays.json);
- the screen live: a thread looks at the chosen screen (or the one in use: "follow") about 5
  times a second, twice a second while nothing moves, and sends a frame only when it changed
  (a 48 x 27 grey sketch is compared), stopping 8 s after nobody watches; the phone asks for
  the next frame after the one it has (`/api/live?screen=&after=`, 204 for "nothing new");
- after something is opened or moved for a phone request, its screen goes live on the phone
  by itself; `ACTION show_screen: live`; See the screen is live; the live view's Picture goes
  into the conversation;
- on a call, the call becomes a bar on top of the live screen (it goes on; the bar brings it
  back, mutes or ends it).
Checked on the owner's three screens: the right numbers and names, frames of 43 to 71 KB in 40
to 90 ms, VS Code's and Brave's pictures on their screens, and the real page showing it live
through the real server.

### Story 153: Docs and the PR (`story/153-phone-docs`)
GUIDE.md, the Catalog, this file's results, screenshots (demo data, light and dark), and one PR
from `epic/11-phone` to `main` for the owner to merge.

## 4. Ground rules
- Branches: `epic/11-phone` from `main`; each story's branch from it, merged back with
  `--no-ff`; the PR is the epic branch. No release.
- No new dependencies (everything here is the standard library, Pillow and mss, which Abdoh
  already has).
- Tests never need a microphone, speakers, network, a screen or Tailscale: screenshots, files
  and Codoh are faked.

## 5. Results (2026-11-28)

All eight stories are on `epic/11-phone` (147 to 154; 154 was added after the owner read the
PR), for the owner to merge with one PR; not released (still 0.13.3, with stories 135 to 146 also
waiting).

- **Built:** 1. to 7. of section 1, as designed in section 2. Claude learns about the phone in
  the system prompt (PHONE, with the file part only when it may work with files) and from the
  `(From the phone)` tag on every prompt of a phone request.
- **Checked here, for real:** the real phone server over a real local connection (a 3 MB upload
  streamed to disk and the connection going on after it, byte ranges, the clipboard, a file
  sent with a request, an unpaired upload refused); the real page against the real server and
  its Content-Security-Policy, with the board's Mermaid and Graphviz drawings, KaTeX and a
  board picture drawn, a picture of the screen and a file card; a real board PDF made by Edge
  for the phone (not opened on the laptop, its path sent on). Everything else in the demo
  (screenshots in light and dark) and in 2050 tests.
- **Reviews:** a read of the whole phone feature (stories 139 to 151) found 8 bugs, among them
  Codoh's notices going to the wrong phone (or none), a photo not going with a voice message,
  Yes and No taking a waiting photo along, and the Codoh view polling twice. A second,
  independent review of the epic found 10 more, among them a phone request losing its context
  outside the plain way to Claude ("translate this" with a photo translated the screen), the
  phone's actions dropped after looking at the screen, board pictures expiring after an hour,
  two phones getting each other's events, and two uploads with one name sharing a temporary
  file. All are fixed, each with a test.
- **Not tried:** a real iPhone and a real Tailscale network (none here), so not: the phone's
  microphone, its viewer for files, Share to Files, Wake Lock, how loud a call needs you to be.
