# EPIC 8: A richer board, a week of conversations, and a choice of models

> **For Claude Code:** This file is your source of truth for the eighth epic. Epics 1 to 7 are
> done; their architecture and the ground rules of `ABDOH_EPIC_5.md`, `ABDOH_EPIC_6.md` and
> `ABDOH_EPIC_7.md` (section 5 of each) still apply unless this file changes them. Work through
> the stories **in order** and follow the working rules in `CLAUDE.md` exactly. Keep everything
> **simple**.
>
> **Start here:** on the first story branch, your first commit changes the first paragraph of
> `CLAUDE.md` to name `ABDOH_EPIC_8.md` as the current source of truth (epics 1 to 7 done), and
> adds this file (`docs: epic 8 plan`). Then read sections 2, 4 and 5 before writing code.

---

## 1. Goal

Abdoh 0.12 plays roles with a board, controls the lamps and connects to Claude, an Anthropic
key or OpenRouter. The owner now wants:

1. **A board that can draw and show.** Explaining theoretical computer science, the board
   couldn't draw a state machine: Claude said "a real drawing may not render, so here's an ASCII
   version". The board must draw automata, state machines, graphs and trees, flowcharts and
   simple charts, and show **pictures**: a photo of a dish when Abdoh acts as a chef, a drawing
   Claude makes, or (with an OpenRouter key) a picture made by an AI model.
2. **The board as a PDF.** At the end of a session, "save the board" (or a button) keeps
   everything the board showed as a PDF.
3. **A week of conversations.** Abdoh keeps what was said for 7 days, as text on this computer.
   "Yesterday we talked about my lamps, what did we decide?" finds that conversation. After 7
   days it's deleted and forgotten.
4. **Advanced settings: a choice of models.** Abdoh installs the recommended models as today
   (Parakeet v3 on the processor, its full version on a suitable graphics card, Piper voices).
   Under **Settings → Advanced**, people who want to can switch the speech recognition model
   and the voice model. Each choice says in a line what it's good at: languages, size, whether
   it uses the graphics card, faster or more accurate than the recommended one. Switching
   downloads the new model and deletes the one it replaces.

### Non-goals (for now)
- TikZ on the board (section 3 says why; Graphviz draws the same automata).
- Image generation without an OpenRouter key (Claude itself can't make pictures; it can draw
  them as SVG).
- Keeping conversations longer than 30 days, or searching them by meaning (no embeddings, no
  vector database; Claude asks with words, Abdoh finds the words).
- Speech and voice models that need PyTorch or CUDA (section 3).
- A new wake word model.

---

## 2. What was checked (2026-11-25)

| Question | Result |
|---|---|
| What the board draws today | `ui/web/board.js`: a small Markdown renderer (headings, lists, bold, tables, code blocks; everything as text, never HTML) and LaTeX math through KaTeX 0.19.1 (`vendor/katex`, 609 KB with fonts, offline, `trust` off). No diagrams, no pictures. Claude's prompt (`roles/acting.py`, `BOARD`) offers Markdown and math only, so on 2026-11-24 it drew a DFA in ASCII |
| Graphviz in the window | `@viz-js/viz`: Graphviz compiled to WebAssembly with a small JS wrapper, MIT, about 2.3 MB ([depscope](https://depscope.dev/pkg/npm/@viz-js/viz), [repo](https://github.com/mdaines/viz-js)). DOT is how automata are usually written (`doublecircle` for accepting states, labelled edges). **Checked (story 97):** 3.31.0, `dist/viz-global.js` 1.3 MB with the WebAssembly inside; draws in the app's window (pywebview serves the page over its own local http server, so nothing is loaded from `file://`) |
| Mermaid | Flowcharts, state, sequence and class diagrams, timelines, pie and XY charts; MIT. **Checked (story 97):** 12.3.0, `dist/mermaid.min.js` 5.4 MB, one file; draws in the window with `securityLevel: "strict"` and `htmlLabels: false` (no HTML in its SVG) |
| Real Claude with the new `BOARD` (story 97) | "Show me on the board a DFA for binary numbers divisible by 3": a heading, the transition rule in LaTeX, then the automaton in ```` ```dot ```` (`rankdir=LR`, `doublecircle` q0, an invisible start node), explained after it. No ASCII |
| TikZ | TikZJax runs a whole TeX engine compiled to WebAssembly in the page for every drawing: big and slow for a board that writes as it talks. Not chosen; Claude writes DOT as fluently as TikZ |
| Photos without a key | Openverse (WordPress; Creative Commons images, including Wikimedia Commons and Flickr) answers anonymous searches; anonymous limits are low, reported as 20 requests a minute and 200 a day, with HTTP 429 past them ([docs](https://wordpress.github.io/openverse-api/reference/api/authentication_and_throttling.html)). Each result has its license and creator for a credit line. Wikimedia Commons' own API: **not checked** (story 98 step 1) |
| Picture search, measured (story 98) | "margherita pizza": Wikimedia Commons 0.9 s, relevant, free licenses (CC BY, CC BY-SA), a 1280 px thumbnail; Openverse 14.8 s, and some results non-commercial; anonymous limits 20 a minute, 200 a day (its own headers). **Chosen:** Commons first, Openverse when Commons has nothing. Real Claude as a chef asked for "authentic Roman spaghetti carbonara with guanciale and pecorino", which Commons doesn't find: Abdoh also tries it without filler words and in shorter runs (found in 2.8 s), and Claude is asked for two to four words |
| Pictures made by AI | Claude only writes text, so it can't make photos, but it can draw SVG. OpenRouter has image models (Gemini image, FLUX, ...), through `/api/v1/images` or chat completions with `modalities: ["image", "text"]` ([docs](https://openrouter.ai/docs/guides/overview/multimodal/image-generation)); the key the owner can now add works for them. Prices per picture differ per model (story 99 step 1) |
| AI pictures, measured (story 99) | `GET /api/v1/images/models` (public): 71 picture models, one free (Recraft V4.1 Flash V2). Prices per picture from `/images/models/<id>/endpoints`: FLUX 3 Klein $0.008 (768) and $0.009 (1k), Recraft V4.1 Flash $0.007, Gemini 3.1 Flash Lite Image and GPT Image 2 per token ($0.00003, about $0.039 a 1K picture). `POST /api/v1/images` returns `data[].b64_json`, `usage.cost`. Credit: a normal key reads its own `limit_remaining` (`GET /key`; null without a limit); the account balance (`GET /credits`) needs a management key. Not enough credit: 402 (nothing charged); a key's limit: 403. **Decided:** no switch, AI pictures work with an OpenRouter key; the picture model sits under the key in the Claude card (not Advanced); FLUX 3 Klein at 1K by default. **Not tried with a real key** (none here) |
| A PDF without a window | Edge is on every Windows 11 PC. Tried on the owner's laptop: `msedge.exe --headless --disable-gpu --no-pdf-header-footer --print-to-pdf=board.pdf board.html` made a 38 KB PDF of a page with an SVG drawing, without a window. **Checked (story 100):** a real board drawn in the window (a DFA in Graphviz, a Mermaid flowchart, a table, KaTeX math, `\ce{}` chemistry, a Commons photo with its credit, code) printed by Abdoh's code: 456 KB in 1.5 s, KaTeX's fonts load from the app's folder, everything as on the page. Edge runs with its own profile folder, never the user's |
| How much text a week of conversations is | From the owner's logs: 2026-11-24, a heavy day (lamp tests, a lesson), 266 lines and 52,091 characters (about 52 KB); 2026-11-25 so far, 3,188 characters. A week is well under 1 MB. Abdoh's log already keeps every "You:" and "Abdoh:" line (`daemon.py`), but the log rotates and isn't meant to be read back |
| What Claude remembers today | Claude Code keeps one conversation for up to 40 turns (`MAX_TURNS`) or until 10 idle minutes; with an API or OpenRouter key, only the previous exchange within 60 s (`followup_seconds`). `memory.yaml` keeps facts and lessons, not conversations |
| Speech recognition models today | Parakeet TDT 0.6B v3 through `onnx-asr`: int8 on the processor (640 MB, bundled), the full model on a graphics card through DirectML (2.4 GB, downloaded, `audio/gpu_model.py`). Whisper (`faster-whisper`: base.en 141 MB, small, medium) for languages Parakeet lacks. Parakeet v2 (English only, 631 MB) is still supported (`PARAKEET_V2`) |
| What `onnx-asr` can load | Parakeet v2 and v3, Canary v1, v2, 180M Flash and 1B Flash, GigaAM (Russian), Whisper (ONNX exports), Wav2Vec2 CTC, Zipformer ([README](https://github.com/istupakov/onnx-asr), [usage](https://istupakov.github.io/onnx-asr/usage/)). Every one of them runs on onnxruntime, so on DirectML too. **To check:** which `onnx-asr` version Abdoh ships has which, and DirectML with each |
| How the open models compare (English word error rate, lower is better; snapshots of the Open ASR Leaderboard, which differ by date) | Parakeet TDT v2 6.02 %, Parakeet TDT v3 6.32 %, Canary 1B Flash 6.35 %, Whisper large-v3 7.44 %; ahead of them, much bigger and not on ONNX: Granite Speech 4.1 2B 5.33 %, Qwen3-ASR 1.7B 5.40 %, Canary-Qwen 2.5B 5.63 % ([Gladia](https://www.gladia.io/blog/best-open-source-speech-to-text-models), [benchmarklist](https://benchmarklist.com/benchmarks/open_asr_leaderboard/), [ThinkScribe](https://thinkscribe.ai/en/blog/open-speech-recognition-models-2026)). Parakeet is the fastest for its accuracy |
| Qwen3-ASR | Apache 2.0, 30 languages (Arabic to check). Only community ONNX exports; the 0.6B runs in real time on a small CPU (RTF 0.71 on an Intel N100) ([model](https://huggingface.co/Daumee/Qwen3-ASR-0.6B-ONNX-CPU)). Needs its own runner code: a later idea |
| Voices: what's there besides Piper | **Pocket TTS** (Kyutai): English, French, German, Portuguese, Italian, Spanish, Dutch; made for the processor (2 cores, about 6 times faster than real time on a MacBook Air M4); voice cloning from one WAV file; code MIT, weights' license listed as MIT in some places and CC-BY-4.0 on the model card ([repo](https://github.com/kyutai-labs/pocket-tts), [page](https://kyutai-labs.github.io/pocket-tts/)); ONNX exports are community-made ([German](https://huggingface.co/Phoonnx/pockettts-de-kyutai-unicode), [seven languages](https://github.com/kyutai-labs/pocket-tts/issues/345)). **Kokoro-82M**: Apache 2.0, much-liked English, also Spanish, French, Italian, Portuguese, Hindi, Japanese, Chinese; **no German** in the standard voices (only community fine-tunes, quality disputed: [issue](https://github.com/hexgrad/kokoro/issues/186), [German ONNX](https://huggingface.co/Godelaune/Kokoro-82M-ONNX-German-Martin)); about a second per sentence on a laptop CPU. **Chatterbox Multilingual** (23 languages) needs PyTorch and a GPU. XTTS-v2 and F5-TTS weights are non-commercial: not for a public app ([AssemblyAI](https://www.assemblyai.com/blog/free-open-source-text-to-speech), [localaimaster](https://localaimaster.com/blog/best-local-tts-models)) |
| What a model switch has to delete | Downloaded models live in `%APPDATA%\Abdoh\models` (the owner's: the GPU Parakeet 2,432 MB, Piper voices 121 MB). The processor Parakeet and the first Piper voices are **inside the app** (the installer): they can't be deleted, only not loaded |

---

## 3. Tech stack changes (decided; don't change without a reason)

| Concern | Choice | Why |
|---|---|---|
| Diagrams | **Graphviz** (`@viz-js/viz`, MIT) for DOT: automata, state machines, graphs, trees. **Mermaid** (MIT) for flowcharts, sequence and class diagrams, timelines, pie and XY charts. Both vendored in `ui/web/vendor`, loaded the first time a board needs them | Offline; Claude writes both well. Not TikZ (a TeX engine per drawing) |
| Claude's own drawings | ```` ```svg ```` on the board: drawn after a strict allowlist sanitizer in `board.js` (shapes, paths, text, groups, gradients; no scripts, no `foreignObject`, no event attributes, no outside links) | Geometry, a sketch of a pan, a plot: Claude draws SVG well. The board must never run what Claude writes |
| More LaTeX | KaTeX's `mhchem` extension (chemistry), from the KaTeX release already vendored | Cheap; same safety |
| Photos | Abdoh's own search: **Openverse** (no key), Wikimedia Commons if story 98 step 1 finds it better. Downloaded by Python (https only, an image type, at most 5 MB), kept in `<app_dir>/board/`, shown with a credit line (creator, license) | No key needed; licensed images; the page never loads from the internet |
| AI pictures | OpenRouter's image models with the owner's OpenRouter key, off unless chosen in Settings (it costs credit) | One key the owner already has |
| PDF | Edge headless `--print-to-pdf` of a board page Abdoh writes; saved in `Documents\Abdoh\Boards`. If Edge is missing: the window's print dialog ("Microsoft Print to PDF") | Edge is on every Windows 11 PC; nothing to install |
| Conversations | `<app_dir>/conversations/YYYY-MM-DD.jsonl`, one line per exchange; files older than `conversation_days` (default 7) deleted at start and every night | Text, under 1 MB a week; readable; easy to delete |
| Finding an old conversation | `ACTION recall: <what> \| <when>`: Abdoh searches the files (words, with `rapidfuzz`, already a dependency) and gives Claude the best matches in a second turn (like `ACTION look`) | Works with Claude Code, an API key and OpenRouter alike; Claude never gets the whole week, only what it asked for |
| Models | A **catalog** (`abdoh/models.py`): for each speech recognition and voice model, its files, size, languages, license, whether it can use the graphics card, and a one-line description. The recommended ones are as today | One place for Settings, the downloader and the loaders |
| New speech recognition models | Only what `onnx-asr` runs: Parakeet v2, Canary 1B v2, Canary 180M Flash (and Whisper as today) | No new runtime: onnxruntime with DirectML, as today |
| New voices | **Pocket TTS** and **Kokoro**, through ONNX on onnxruntime, if story 105 step 1 finds working exports and acceptable licenses | Pocket TTS speaks German, Kokoro has the best English; both run on the processor |

New dependencies: none in Python unless story 105 needs one (a one-line reason in the commit, as `CLAUDE.md` says). New vendored page libraries: Graphviz and Mermaid.

---

## 4. How it works

### 4.1 Diagrams on the board

- Claude writes a fenced block on the board, as it already writes code:
  ```` ```dot ```` (a Graphviz graph), ```` ```mermaid ```` or ```` ```svg ````. `board.js` draws it
  as a picture in the card instead of showing the code (a "Show the code" toggle shows the
  source). A block that doesn't draw (a mistake in the DOT) shows the code with a small "couldn't
  draw this" note, never an error page.
- `BOARD` in `roles/acting.py` tells Claude what it can draw and when to: automata and state
  machines in DOT (`rankdir=LR`, `doublecircle` for accepting states, an invisible start node
  with an arrow), flowcharts and timelines in Mermaid, anything else (geometry, a sketch, a
  function's graph) in SVG, chemistry with `\ce{...}`. One drawing per board piece, explained
  after it like everything else.
- The libraries load the first time a board needs them (they're big), from `vendor/`, offline.
- The typist (`Typist`) writes text out word by word; a drawing appears whole once its block is
  complete.

### 4.2 Pictures on the board

- On the board Claude writes a line `[picture: margherita pizza]` (a search) or
  `[picture: https://...]` (a link it found with web search). The page asks Abdoh for it
  (`board_picture`); Abdoh searches Openverse (or fetches the link: https only, an image type,
  at most 5 MB), keeps the file in `<app_dir>/board/` and gives the page a local address. The
  picture shows with its credit line ("Photo: Jane Doe, CC BY 2.0"). Nothing found: a small
  note, and Claude is told (so it can say so).
- With **AI pictures** on (Settings → Advanced, needs an OpenRouter key), `[picture: draw: a
  cozy kitchen at night, watercolour]` asks the chosen OpenRouter image model. It's labelled
  "Made by AI".
- `BOARD` says when pictures help (a chef showing a dish, a plant, a place) and to describe what
  should be in the picture, not to show pictures of real private people.
- `<app_dir>/board/` is emptied with the conversations (7 days), unless a PDF kept them.

### 4.3 The board as a PDF

- The Act as page has **Save as PDF**. Claude also has `ACTION board_pdf` ("save the board",
  and it may offer it at the end of a lesson).
- The page sends the board as it shows it (text, math, drawn SVGs, pictures as local files) to
  Abdoh; Abdoh writes one HTML page (KaTeX's CSS and fonts beside it), runs Edge headless to
  print it, saves `Documents\Abdoh\Boards\<role> <date> <time>.pdf`, and says where ("Saved the
  board as a PDF in Documents, Abdoh, Boards").
- No Edge: the window's print dialog opens on the board.

### 4.4 A week of conversations

- When a turn ends (`router`), Abdoh appends one line to today's file: the time, what the
  owner said, what Abdoh answered, the mode and the role if any, and the board text of that
  answer. Typed requests too. Not what Abdoh says by itself (reminders, timers).
- At start and every night, files older than `conversation_days` (7; 0 turns it off) are
  deleted, and the pictures folder with them.
- Memory is off (the Memory page switch): nothing is kept, as for facts.
- `BOARD`-like note for Claude (`brain.py`): "Conversations of the last 7 days are kept. When
  the user refers to an earlier one (yesterday we talked about..., what did I ask you on
  Monday), write `ACTION recall: <what> | <when>`." Abdoh reads `<when>` (today, yesterday, a
  weekday, "last week", a date; nothing means the whole week), finds the exchanges that match
  `<what>` best (with the one before and after each), at most about 4,000 characters, and asks
  Claude again with them, like a look at the screen. Found nothing: Claude is told that, and
  says so.
- The Memory page gets the switch **Keep conversations for 7 days** and **Conversations since
  <the oldest day kept>**: each day with how many exchanges; a day can be opened, deleted, or
  everything forgotten. It says plainly: "Kept on this computer for 7 days.
  Claude sees a part only when you ask about an earlier conversation."

### 4.5 Settings → Advanced: models

- A collapsed **Advanced** card at the end of Settings: "For people who like to choose their
  models. The recommended ones work well for most people."
- **Speech recognition**: a list of the catalog's models that fit the chosen languages, each
  with a line: languages, download size, "uses your graphics card" or "processor only", and how
  it compares with the recommended one ("more accurate English, slower", "smaller and faster,
  less accurate"). The recommended one is marked. Choosing one downloads it in the background
  (progress as for voices), switches when it's ready, and deletes the model it replaced if it
  was downloaded (never what's inside the app). **Back to recommended** undoes it all.
- **Voice**: the same for the natural voice: Piper (recommended), Pocket TTS, Kokoro, each per
  language it has; and the Windows voice as today.
- `config.yaml` keeps the choice (`speech_model`, `voice_model`); empty means recommended.
- The GPU Parakeet works as today: downloaded once on a suitable card.

---

## 5. Ground rules for this epic

1. **Section 5 of epics 5, 6 and 7 still apply.**
2. **The board never runs what Claude writes.** Drawings go through Graphviz, Mermaid
   (`securityLevel: "strict"`) or the SVG allowlist; pictures are local files Abdoh fetched. No
   `innerHTML` with Claude's text.
3. **Licenses fit a public app.** Libraries and models shipped or downloaded by default must
   allow it (MIT, Apache 2.0, BSD, CC-BY with credit; Piper's GPL as today). Credits go in
   `LICENSE` notes and the About text. No non-commercial weights.
4. **Conversations stay on this computer** and are deleted after `conversation_days`; Claude
   gets only what `ACTION recall` found.
5. **Models are never deleted while in use**, and nothing inside the installed app is deleted.
6. **Tests stay offline and silent:** a fake Openverse, fake Edge, fake downloads, fake Claude.
   Diagram drawing is checked in the page with the demo bridge (screenshots, as in epic 7).
7. **Real checks on the owner's laptop** before each story is merged: a DFA drawn, a picture
   shown, a PDF opened, a conversation recalled, a model switched and back.

---

## 6. Stories

### Story 97: Diagrams on the board (`story/97-board-diagrams`)

1. **Check first:** the current `@viz-js/viz` and Mermaid versions, their sizes, and that both
   draw from `file://` in WebView2 (pywebview); note the results in section 2.
2. Vendor them (`ui/web/vendor/viz`, `vendor/mermaid`), loaded on first use.
3. `board.js`: ```` ```dot ````, ```` ```mermaid ````, ```` ```svg ```` (allowlist sanitizer) and
   `\ce{}`; "Show the code"; a note when a drawing fails.
4. `BOARD` in `roles/acting.py`: what to draw how, with a DFA example in DOT.
5. Tests: the SVG sanitizer (scripts, event attributes, `foreignObject`, outside links removed);
   the prompt; the demo bridge has a board with each kind.
6. **With the owner:** "act as my theoretical computer science professor, show me a DFA for
   binary numbers divisible by 3", a Turing machine, a flowchart.

### Story 98: Pictures on the board (`story/98-board-pictures`)

1. **Check first:** Openverse's anonymous search and terms today; Wikimedia Commons' search;
   pick one (or Openverse with Commons as a fallback).
2. `abdoh/pictures.py`: search, fetch (https, image type, 5 MB), keep in `<app_dir>/board/`,
   credit line.
3. `[picture: ...]` on the board; `AppApi.board_picture`; the picture and its credit in the card.
4. `BOARD`: when and how to ask for a picture.
5. Tests with a fake Openverse: found, not found, too big, not an image, 429.
6. **With the owner:** "act as a chef, show me what a good carbonara looks like".

### Story 99: Pictures made by AI (`story/99-ai-pictures`)

1. **Check first:** OpenRouter's image models, the route each uses, their prices, and how a
   key's remaining credit is read.
2. Settings → Advanced: **AI pictures** (off), the image model, its price per picture.
3. `[picture: draw: ...]` with the OpenRouter key: Abdoh checks the credit first; enough, it
   makes the picture and shows it ("Made by AI"); not enough or no key, Claude is told why and
   says so, offering a drawing or a photo instead.
4. Tests with a fake OpenRouter: made, too little credit, no key, off.
5. **With the owner:** one picture, and its cost on OpenRouter.

### Story 100: The board as a PDF (`story/100-board-pdf`)

1. **Check first:** a board page with KaTeX math, a Graphviz drawing and a picture, printed by
   Edge headless; KaTeX's fonts in the PDF.
2. `abdoh/board_pdf.py`: the page's board → one HTML page → Edge → `Documents\Abdoh\Boards`.
3. **Save as PDF** on the Act as page; `ACTION board_pdf`; the print dialog without Edge.
4. Tests with a fake Edge (the command line, the file name, Edge missing).
5. **With the owner:** a lesson, "save the board", open the PDF.

### Story 101: A week of conversations (`story/101-conversations`)

1. `abdoh/conversations.py`: append, read a day, delete old days, forget all.
2. The router writes each finished turn; memory off writes nothing.
3. `keep_conversations` (on) and `conversation_days` (7) in config; the switch **Keep
   conversations for 7 days** on the Memory page; cleaning at start and every night.
4. Memory page: **Conversations since <the oldest day kept>** (days, open, delete, forget all).
5. Tests: what's kept and what isn't (reminders, memory off), deleting after 7 days, sizes.

Done: kept in the daemon when a reply ends (it has what was said, spoken or typed, and the
board text of that reply); a turn Claude found wasn't meant for Abdoh isn't kept. A day is kept
while it's at most `conversation_days` old (today and the 7 before it), cleaned an hour apart by
the housekeeping thread (the first time 30 s after start) and when a new day's file starts.
Tests never touch the real folder (`conftest.py` redirects it). From source the data folder is
the checkout: `/conversations/` and `/board/` are in `.gitignore`.

### Story 102: Remembering earlier conversations (`story/102-recall`)

1. `ACTION recall: <what> | <when>`: reading `<when>`, finding the best exchanges, the second
   turn with them (like `look`).
2. The note for Claude in `brain.py` (only with memory on and `conversation_days` > 0).
3. Tests: yesterday, a weekday, last week, nothing found, the 4,000-character cap; Claude Code,
   API key and OpenRouter.
4. **With the owner:** talk about something, ask about it the next day.

Done, checked with real Claude (Claude Code) through the real router on seeded conversations:
"yesterday you explained an automaton, how many states?" (the lesson said DFA, never
automaton), "what name did we pick for my cat on Monday?", "did we talk about carbonara this
week?": all three right, 3 to 4 s each. Two things the first try showed: Claude worked out the
date aloud ("Monday was 2026-11-23."), so `<when>` is now the user's own words (yesterday, on
Monday, 3 days ago, German too) and Abdoh reads them; and matching words alone missed synonyms,
so when none match, Claude gets the latest exchanges of those days and judges. Not tried with an
API key or OpenRouter (none here); the router asks every brain the same way, as for `look`.

### Story 103: Settings → Advanced: the model catalog (`story/103-model-catalog`)

1. `abdoh/models.py`: the catalog with today's models (Parakeet v3 processor and graphics card,
   Parakeet v2, Whisper sizes, Piper, the Windows voice), and which is recommended.
2. Download with progress, switch when ready, delete the replaced download; **Back to
   recommended**.
3. Settings → **Advanced** (collapsed) with the two lists and their one-line descriptions.
4. `speech_model`, `voice_model` in config (empty: recommended); upgrade keeps old configs as
   they are.
5. Tests with fake downloads: switching, deleting, never deleting what's in use or inside the
   app, back to recommended.
6. **With the owner:** switch to Parakeet v2 and back.

Done. The switch is live, without a restart: the new model loads while the old one keeps
listening, then takes over (`Daemon.use_transcriber`; on a graphics card it moves there as
usual). Downloads are pinned to a revision and checked (`abdoh/download.py`), and each folder
Abdoh downloads gets a `.abdoh-download` marker: only such folders are ever deleted, never the one
in use or chosen, never the app's own or the graphics card model. The voice is still
`tts_engine` (Piper or Windows, a restart as before), so no `voice_model` key: story 105 adds its
voices there. Checked for real in a temporary Abdoh folder: Whisper base (150 MB) downloaded and
checksum-checked in 16 s while Parakeet v3 kept working, switched, transcribed a Piper recording
("Hey Abdo, what is the weather like in Sarpurkan tomorrow?", 0.9 s), and back to recommended
deleted it. A dev checkout's `models/` counts as inside the app: a Whisper or Parakeet v2 found
there is used without downloading.

### Story 104: More speech recognition models (`story/104-speech-models`)

1. **Check first:** with the `onnx-asr` Abdoh ships, load and time on the owner's laptop
   (processor and graphics card): Canary 1B v2, Canary 180M Flash, Whisper large-v3 and
   large-v3-turbo (ONNX exports through `onnx-asr`, or `faster-whisper` on the processor),
   Qwen3-ASR (0.6B, 1.7B) and Moonshine. Note speed, memory and a few German and English test
   sentences in section 2.
2. Add the ones that fit Abdoh's runtime to the catalog, with honest one-line descriptions
   (including "needs a strong computer" where it does), even if the owner's laptop is too weak.
3. Tests with fake models.
4. **Tell the owner** which ones run well on his laptop, to try.

Done. Measured on the owner's laptop (Intel Core i7-13650HX, 20 threads, 16 GB, RTX 3050 6 GB;
`onnx-asr` 0.12.0, `onnxruntime-directml` 1.24.4, `faster-whisper` 1.2.1). Four English and four
German sentences said by Piper (lessac, thorsten), each recognized twice; per request, memory
after loading, and word mistakes on that clear speech (numbers as words or digits and the names
Abdoh and Saarbrücken not counted):

| Model | Per request | Memory | Mistakes EN / DE | Added |
|---|---|---|---|---|
| Parakeet v3 int8, as Abdoh runs it now (onnx-asr's default providers: DirectML first) | 0.54 s | 0.4 GB | 2.6 / 2.6 % | (recommended) |
| Parakeet v3 int8 on the processor only | 0.31 s | 0.8 GB | 0 / 0 % | not changed, see below |
| Canary 180M Flash int8 (processor) | 0.6 to 0.7 s | 0.4 GB | 7.7 / 5.3 % | yes |
| Canary 180M Flash full, on the RTX 3050 (DirectML) | fails (a Reshape node) | | | no |
| Canary 1B v2 int8 (processor) | 1.0 to 1.1 s | 1.2 GB | 2.6 / 2.6 % | yes |
| Whisper large-v3 turbo (CTranslate2 int8, 4 threads / 10 threads) | 7.2 s / 5.3 s | 0.95 GB | 0 / 0 % | yes, "needs a strong computer" |
| Whisper large-v3 (4 / 10 threads) | 6.2 to 7.4 s / 6.4 s | 1.7 GB | 2.6 / 0 % | yes, "needs a strong computer" |

- Canary must be told the language (it has no detection), so it's offered only when one language
  is chosen; its compact version fails on DirectML, so Abdoh runs it on the processor explicitly.
- Whisper large models process 30 seconds of audio for every request on the processor:
  accurate, but 5 to 7 seconds a request on this laptop. Whisper now uses half the processor's
  threads (4 to 8) instead of faster-whisper's 4. The turbo comes from
  `deepdml/faster-whisper-large-v3-turbo-ct2` (faster-whisper's own name for it points at a repo
  that's gone).
- **Not added:** Qwen3-ASR (only a community ONNX export, `Daumee/Qwen3-ASR-0.6B-ONNX-CPU`,
  that needs its own runner code; not `onnx-asr`), Moonshine (not in `onnx-asr`, needs its own
  package, and its open models are English-first and less accurate than Parakeet). Both stay
  later ideas.
- **Found on the way, not changed:** with `onnxruntime-directml`, the compact Parakeet that
  should run "on the processor" runs through DirectML first; on this laptop the processor alone
  is faster (0.31 s against 0.54 s) but holds 0.4 GB more RAM. Here the graphics card model is
  used anyway (`use_gpu`), so it only matters with that switched off; worth a decision later.
- Checked for real through Abdoh's own code: German only, Canary 180M Flash chosen, downloaded
  and switched in 22 s, "Stell einen Timer auf zwölf Minuten und mach die Lampe blau.", and back
  to recommended deleted it.
- **For the owner to try:** Canary 1B v2 and Canary 180M Flash run well (about a second or less)
  with one language chosen; Parakeet v2 for English only; Whisper base and small run, slower;
  the large Whispers work but are too slow on this laptop for talking.

### Story 105: More voices (`story/105-voices`)

1. **Check first:** Pocket TTS and Kokoro ONNX exports on the owner's laptop: speed on the
   processor, German (Pocket TTS) and English quality, and the weights' licenses.
2. `speech/` adapters for the ones that pass, behind the same `Speaker` interface as Piper
   (pause, stop, the language per sentence, speed).
3. Into the catalog, per language.
4. Tests with fake models.
5. **With the owner:** listen to each in English and German, and pick.

Done for Kokoro; Pocket TTS not added. Checked on the owner's laptop:

| | Kokoro 82M (`onnx-community/Kokoro-82M-v1.0-ONNX`) | Pocket TTS (`KevinAHM/pocket-tts-onnx`) |
|---|---|---|
| License | Apache 2.0 | CC-BY-4.0 (voices from `kyutai/pocket-tts-without-voice-cloning`, not gated) |
| Languages | English (American, British); no German | English, German, French, Italian, Portuguese, Spanish |
| Runs with | onnxruntime, phonemes from Piper's espeak-ng: nothing new installed | its own runner (`pocket_tts_onnx.py`, ~700 lines) plus `sentencepiece` and `safetensors` |
| Speed (4 s of speech) | full model 0.7 s on the processor; quantized 2.4 s; DirectML fails (ConvTranspose) | not measured (below) |
| Heard back by Parakeet | every word of three sentences, three voices | |

- **Kokoro is in.** `speech/kokoro_voice.py`; its voices (`kokoro:af_heart`, ...: Heart, Bella,
  Michael, Fenrir American; Emma, George British) are English voice choices of the natural voice,
  so the Piper speaker plays them (blocks, pause, stop, speed) and the Windows voice speaks while
  the 330 MB download runs, with its progress bar. Settings → Advanced → Voice: **Kokoro for
  English**. Real check through `make_voice` in a temporary folder: the backup voice spoke
  first, Kokoro downloaded in 33 s (progress 0 to 99%), then said "Your twelve minute timer is
  done, and the desk lamp is blue now." (4.1 s of speech in 1.7 s with the first load), heard back
  word for word. Samples to compare with Piper's lessac: `%TEMP%\abdoh-voices\listen`.
- **Pocket TTS is not in.** Its ONNX export needs the code from the model repository to run, and
  running code downloaded from a model repository was stopped by the permission check, rightly:
  it isn't Abdoh's code and wasn't reviewed. Adding it means writing Abdoh's own runner (the flow
  model's state handling, the Mimi decoder, the voice state files), reviewed and tested like the
  rest, and two new packages (or reading `tokenizer.json` with `tokenizers` and safetensors with
  numpy). A story of its own, if the owner wants German beyond Piper's.

### Story 106: Release 0.13.0 (`story/106-release`)

1. Version `0.13.0`; README (the board's drawings and pictures, PDFs, conversations, Advanced
   settings, model credits); the download page.
2. Build and run the packaged app in isolation; check the vendored libraries are inside.
3. **Ask the owner** before tagging. Then merge, tag, watch the build, check the release and
   the download link.

Prepared, not released (the owner asked to finish the epic without releasing, 2026-11-25). The
README was updated story by story. Step 2 done: `scripts/build_app.py` builds (PyInstaller
6.22.3, `dist/Abdoh` 1.08 GB); inside are Graphviz (`viz-global.js`), Mermaid, KaTeX with mhchem
and the new pages, and the new modules (`conversations`, `recall`, `models`, `download`,
`board_pdf`, `pictures`, `speech.kokoro_voice`); run in a temporary `ABDOH_HOME`, `--version` and
`list-commands` work (exit code 0). Left for the release: the version `0.13.0` (one line,
`src/abdoh/__init__.py`, as for 0.12.0), the download page (`docs/index.html`), the tag.

### After a friend's test (2026-11-25): stories 107 to 109

A friend ran 0.12.0 on his laptop (the same Realtek mic array, an RTX GPU, people in the room)
and sent his logs; he also opened GitHub issues #1 and #2.

### Story 107: "Stop listening", and people talking nearby (`story/107-stop-listening`)

What the logs showed: every word or two heard over a reply ("Well.", "pain", "LinkedIn.", from
people in the room or Abdoh's own echo) stopped it and went to Claude, whose answer was cut off
by the next scrap: a chain of half replies. "Uh okay you can stop now", "yeah, just shut up,
shut up" and "um you can stop listening" weren't understood as stopping, so Claude answered
them. Stopping with the window or the hotkey didn't drop what was being heard at that moment,
and neither did pausing; after "you've reached your usage limit" Abdoh listened for more and
said the limit again to the room. While paused, a wake word set off by talk still chimed.

1. Stopping in any words (`local_skills.stop_request`): "stop listening" (pauses) and "stop" /
   "shut up" (ends the conversation), with the "uh okay", "please", "now" and the name around
   them. Over a reply, or right after one without the wake word, it's enough that one sentence
   says only that, or that "stop listening" / "shut up" is anywhere in it; after the wake word
   all of it must be (so "how do I make my laptop stop listening" is still a question).
2. "Stop listening" says nothing: Abdoh pauses at once; the window shows how to get it back
   ("Abdoh, start listening", "you can listen again", "wake up"). In a lesson it ends the
   lesson's listening only, the role stays (as Claude's `ACTION listen: off` did).
3. While paused, a wake word makes no chime, no "unclear" sound and lowers nothing.
4. A word or two over a reply that asks nothing ("well", "do you") lets Abdoh carry on, unless
   it comes within 3 s of your request, before any of the answer (the end of your sentence).
5. Stop (window, tray, hotkey) or pause while Abdoh hears you over a reply: what it heard is
   dropped, and nothing queued is answered once paused.
6. No listening for more after Claude couldn't answer (a usage limit, no connection).
7. After a faint or fair wake word, Claude is told a lone word or scrap that asks nothing isn't
   for it ("Tracy." got "Hi Tracy, I'm Abdoh.").

Done: `tests/test_stop_listening.py` (the friend's own words from the log); README.

---

## 7. The owner's decisions (2026-11-25)

- **AI pictures: keep (story 99).** When a role is asked for an AI picture, Abdoh first checks
  the OpenRouter key's remaining credit (and that a picture model is chosen): enough, it makes
  the picture and shows it; not enough (or no key), Claude says so plainly ("Your OpenRouter
  credit is too low for a picture, about $0.04 is needed") and offers a drawing or a photo.
- **Conversations: a switch.** "Keep conversations for 7 days" on the **Memory** page (on by
  default, under the Memory switch). The saved conversations are on the Memory page too, under
  **Conversations since <the oldest day kept>**.
- **Models: also Whisper large-v3, Whisper large-v3-turbo, Qwen3-ASR and Moonshine**, if they
  fit Abdoh's runtime (onnxruntime), even when the owner's laptop is too weak for some: other
  people have stronger computers. Each one's line says what it needs. Story 104 tells the owner
  which run well on his laptop, to try.
- **Anything that downloads shows its progress** (a bar with the percentage), and the UI stays
  clear: no squeezed rows, no cut-off text, checked with screenshots at each story.

## 8. Things only the owner can do

- Every "With the owner" step above, on the laptop, with Abdoh running from source.
- Listening to the voices (story 105) and judging the German.
- Say when a release should be published.

## 9. Later ideas (not in this epic)

- Qwen3-ASR (Arabic and 30 languages, very accurate) once there's a maintained ONNX runner.
- Chatterbox Multilingual or other PyTorch voices for people with an NVIDIA card.
- Voice cloning (Pocket TTS can speak in a voice from one recording): Abdoh in your own voice.
- Saving boards automatically with the conversation, to open again later.
- Everything in epic 7's section 8 (browser control, Abdoh from the phone, ...).
