# EPIC 9: Codoh, watching the screen, and an Abdoh that knows itself

> **For Claude Code:** This file is your source of truth for the ninth epic. Epics 1 to 8 are
> done; their architecture and the ground rules of `ABDOH_EPIC_5.md` to `ABDOH_EPIC_8.md`
> (section 5 of each) still apply unless this file changes them. Work through the stories
> **in order** and follow the working rules in `CLAUDE.md` exactly. Keep everything **simple**.
>
> **Start here:** on the first story branch, the first commit changes the first paragraph of
> `CLAUDE.md` to name `ABDOH_EPIC_9.md` as the current source of truth (epics 1 to 8 done), and
> adds this file (`docs: epic 9 plan`).

---

## 1. Goal

Abdoh 0.13 (epic 8 and stories 107 to 109, merged but not released) talks, acts, plays roles
with a board, and can answer with Claude Code, an Anthropic key, OpenRouter or the user's
ChatGPT plan. The owner now wants five things (2026-11-26):

1. **Codoh, a coding assistant page.** Like Codex or T3 Code: open a folder, chat with a coding
   model that reads and changes the code and runs commands, and switch between the models of
   the user's subscriptions (Claude through Claude Code, and the ChatGPT plan). Codoh's
   sessions are separate from Abdoh's: none of Abdoh's instructions, actions, memory or tools
   go to the coding model, and none of Codoh's chat goes to Abdoh. It should look great, and
   be easy to understand and use.
2. **Watching the screen live.** "I'm doing something on my screen now, tell me if I do it
   right": Abdoh says it started watching, looks at the screen as the user works, speaks up
   when something goes wrong, and listens to the user without the wake word the whole time.
   "You can stop looking at the screen" (in any words) ends the whole session: no more looking
   and no more listening without the wake word.
3. **ChatGPT when Claude's limit runs out.** With both Claude (Claude Code) and the ChatGPT plan
   connected, Abdoh switches to ChatGPT by itself when Claude's usage limit is reached, says so
   once, and goes back to Claude when the limit resets. Codoh does the same for coding chats.
   (Story 109 left this out on purpose; the owner now asks for it.)
4. **Logs in the app, and an Abdoh that reads its own.** Settings → Advanced shows Abdoh's log.
   Abdoh can read its log when asked ("why did you stop talking just now?", "check your logs,
   did anything go wrong?"), knowing how it is meant to work, and explain what happened.
5. **A Catalog.** One place in the app that explains every feature: what it does, how to use
   it, what to say, where its settings are. Easy, interactive, attractive and modern.

### Non-goals (for now)
- Codoh with an Anthropic or OpenRouter key (only the two subscriptions: Claude Code and the
  ChatGPT plan), with the Codex CLI, or with git worktrees, terminals or pull requests.
- Codoh by voice ("Abdoh, open Codoh" shows the page; coding chats are typed).
- Watching the screen as a video stream (Abdoh sends a picture when the screen changed, a few
  seconds apart), or watching more than one screen at a time.
- Keeping logs longer than today and yesterday (privacy: they hold what the user said).
- Falling back from ChatGPT to Claude, or between API keys.

---

## 2. What was checked (2026-11-26)

| Question | Result |
|---|---|
| Claude Code as a coding engine for a window | Claude Code 2.1.332 (the VS Code extension's copy) in `-p --input-format stream-json --output-format stream-json`: one process per chat, requests as JSON lines on stdin, events on stdout. Started in the project folder with its normal settings, it is plain Claude Code: its own coding system prompt and tools, the user's CLAUDE.md, nothing of Abdoh's |
| Asking the user before a tool runs | With `--permission-prompts host --permission-prompt-tool stdio` and an `initialize` control request first, Claude Code sends `control_request` `can_use_tool` (tool name, input, a description, `tool_use_id`, `permission_suggestions` such as `setMode acceptEdits` for the session) and waits; `control_response` `{behavior: "allow", updatedInput}` runs it, `{behavior: "deny", message}` refuses it. **Checked:** a Write allowed this way created the file; a denied Edit left it as it was. Without the handshake, anything that needs permission is refused at once |
| The plan's models | The `initialize` response lists them with names and descriptions: Default (Opus 5.5), Opus 5.5, Sonnet 5.5, Fable 5.2, Haiku 5.5, each with its effort levels (low to max), and the account's plan ("Claude Pro") |
| Switching model or mode mid-chat | `control_request` `set_model` (`{"model": "haiku"}`) and `set_permission_mode` (`default`, `acceptEdits`, `plan`, `bypassPermissions`) answer `success` and apply to the next reply; no restart. **Checked:** a Write after `set_permission_mode acceptEdits` ran without asking |
| Coming back to a chat | Sessions are saved by Claude Code; a new process with `--resume <session_id>` continues it. **Checked:** after a restart it remembered which file it had created |
| What a change looks like | Edit's input has `file_path`, `old_string`, `new_string`; Write has `file_path`, `content`; the tool result (`tool_use_result`) has `structuredPatch` and `originalFile`. Enough to show a diff in the chat |
| ChatGPT for coding | The plan's Responses API (story 109) takes function tools (`tools: [{type: "function", name, parameters}]`); calls arrive as `function_call` output items with `call_id` and JSON `arguments`, and results go back as `function_call_output` input items. With `store: false` the reasoning is kept with `include: ["reasoning.encrypted_content"]` and sent back with the other items. Abdoh runs the tools itself (read, search, write, edit, run a command), only inside the chosen folder. **Not tried with a real ChatGPT account** (none here) |
| Claude's limit, as Claude Code reports it | A `rate_limit_event` with `status: "rejected"` and `resetsAt` (epoch seconds), or a `result` error mentioning the limit. Abdoh already turns this into "You've reached your Claude usage limit for now. It resets at 8:50 PM." (the friend's log, 2026-11-25) |
| The log | `%APPDATA%\Abdoh\abdoh.log`, `TimedRotatingFileHandler` at midnight with one backup: today's and yesterday's only. Lines: `2026-11-25 20:27:03,112 INFO abdoh.daemon: You: ...`, tracebacks on the lines after |
| Looking at the screen today | `ACTION look` (Claude decides): one picture of the screen in use (`claude/screen.py`, the monitor with the window in front, made smaller), sent back with the request. Claude Code gets it as a file it reads |

---

## 3. Design

### 3.1 Codoh

```
abdoh/codoh/
  store.py     projects (folders) and chats, kept in <app_dir>/codoh/ (JSON, one file a chat)
  claude.py    a Claude Code process for one chat (stream-json, approvals, models, resume)
  chatgpt.py   a ChatGPT chat: the Responses API with Codoh's tools, run by Abdoh
  tools.py     those tools: list, read, search, write, edit, run, only inside the folder
  manager.py   runs chats, keeps what the page shows, approvals, the switch to ChatGPT
ui/web/codoh.js, codoh.css   the page
```

- **Separate from Abdoh.** Codoh never uses Abdoh's brain, prompt, actions, memory or
  conversations. A Claude chat is a Claude Code process in the project folder with Claude
  Code's own prompt; a ChatGPT chat gets a short coding prompt (section 4.1) and Codoh's tools.
  Codoh's chats aren't kept in Abdoh's conversations and aren't in its log beyond one line per
  request ("Codoh: a request in <folder> with <model>").
- **Engines.** "Claude" (Claude Code, the user's Claude plan) and "ChatGPT" (the user's ChatGPT
  plan). The model menu shows the models of each that is connected, grouped by plan, with a
  line about each. Choosing a model of the other plan mid-chat carries the chat over (3.1.3).
- **Permission modes** (one menu, the same words for both engines):
  - *Ask first* (default): reading and searching just happen; every change and every command
    shows an approval card: Allow, Allow for this chat, Deny.
  - *Auto-edit*: changes to files just happen; commands still ask.
  - *Plan only*: nothing is changed; the model reads and proposes a plan.
  - *Full access*: everything just happens (a warning says what that means).
  Claude Code: `default`, `acceptEdits`, `plan`, `bypassPermissions`. ChatGPT: Codoh's own
  rules, the same way.
- **What the page shows.** Each chat is a list of items: the user's messages, the model's
  answers (Markdown, code blocks with a copy button), tool cards (read a file, searched, edited a
  file with its diff, ran a command with its output, all folded by default), approval cards,
  notes (switched model, switched to ChatGPT, stopped), and errors. The page polls for changes
  while a reply is running (each item has a revision number; the page asks for what changed).
- **The folder.** Open a folder (the window's folder dialog); recent folders are kept. The
  header shows the folder's name and path, its git branch and a "N changed" chip that opens a
  Changes panel (`git status` and `git diff` of each file) when git is installed and the folder
  is a repository.

#### 3.1.1 A Claude chat
`claude -p --input-format stream-json --output-format stream-json --verbose
--include-partial-messages --permission-prompts host --permission-prompt-tool stdio
--permission-mode <mode> --model <model> [--effort <level>] [--resume <session id>]`, in the
folder, with Abdoh's `child_env()` (no API key: the plan pays). First an `initialize` request
(its answer gives the models and the plan). Text deltas grow the answer item; `tool_use` blocks
become tool cards, completed by the matching `tool_result` (and `tool_use_result`);
`can_use_tool` becomes an approval card and waits for the user; `result` ends the reply (time,
cost when shown). Stop sends `interrupt`. The process stays open for the chat and is closed
after 15 quiet minutes; the next message starts it again with `--resume`.

#### 3.1.2 A ChatGPT chat
`POST /v1/responses` (story 109's `Session` for the token) with `stream: true`, `store: false`,
`instructions` (4.1), `input` (the chat so far, as Responses items), `tools` (Codoh's tools as
functions), `reasoning: {effort}` and `include: ["reasoning.encrypted_content"]`. Function
calls run one by one (with an approval when the mode asks), their output goes back, and the
loop continues until an answer has no calls, at most 40 rounds a request. The items are saved
with the chat, so it continues after a restart.

Tools (paths are relative to the folder; anything outside it is refused):
`list_files(path, pattern)`, `read_file(path, offset, limit)`, `search(pattern, path, glob)`,
`write_file(path, content)`, `edit_file(path, old_text, new_text, replace_all)`,
`run_command(command, timeout_seconds)` (PowerShell on Windows, in the folder, at most 10
minutes, the output cut to its last 30,000 characters).

#### 3.1.3 Carrying a chat over to the other plan
A chat that moves from Claude to ChatGPT (chosen, or because Claude's limit ran out) gives
ChatGPT a summary of the chat so far, made by Codoh from its own items: the user's messages,
the answers, and one line per tool card ("edited src/app.py", "ran npm test: failed"). Moving
back to Claude starts a new Claude Code session with the same summary. The chat shows a note
where it moved.

### 3.2 ChatGPT when Claude's limit runs out
`claude.fallback` (on by default; a switch in the Claude card, shown when the ChatGPT plan is
connected). `make_brain` wraps Claude Code in a `FallbackBrain` when the switch is on and the
ChatGPT plan may be used. When Claude Code reports the limit before saying anything, the
wrapper answers the same request with ChatGPT, starting with one sentence: "Claude's limit is
used up until 8:50 PM, so your ChatGPT plan answers for now." Until that time every request
goes to ChatGPT (the window's side line says so); then Claude is tried again (unknown reset
time: after 30 minutes). `BrainError` carries `limit` and `resets_at`. Codoh does the same per
chat, with a note in the chat.

### 3.3 Watching the screen (`abdoh/watch.py`)
- **Starting.** Claude decides, like `look`: `ACTION watch: <what the user is doing and what to
  watch for>` (allowed with "Claude may look at your screen" on). Claude's answer says that it
  is watching and that the user can start ("Okay, I'm watching your screen. Go ahead and open
  the settings."). A watch can also start from a role or a follow-up.
- **Looking.** Every `watch_seconds` (default 5) Abdoh takes a small picture of the screen in
  use and compares it with the last one it sent (a 64 × 36 grey thumbnail; a mean difference
  over a small threshold counts as a change). When it changed and nobody is talking (Abdoh isn't
  speaking, answering or recording), the picture goes to the same brain as the conversation,
  with the goal and what Abdoh said during the watch so far: `WATCH_FRAME` (4.2). Claude
  answers `ACTION ignore: fine` when all is well, and otherwise speaks up in one or two short
  sentences (a mistake, a step they missed, the next step when one is done). It may end the
  watch itself when the task is done (`ACTION watch: off`).
- **Listening.** While watching, Abdoh listens without the wake word (like a lesson), and what
  the user says goes to Claude with a fresh picture and a note that Abdoh is watching.
- **Stopping.** "Stop looking at the screen", "stop watching", "you can stop watching me", "I'm
  done, stop watching" (in any words, found without Claude like "stop listening") end the
  session: no more pictures, the wake word again, and Abdoh says "Okay, I stopped watching your
  screen." "Stop listening" ends it too and pauses Abdoh (silently, as in story 107). Claude
  can end it with `ACTION watch: off` for other words. After `watch_minutes` (default 20)
  without the user saying anything, it ends and says so. The window's Home page shows a
  "Watching your screen" chip with a stop button.

### 3.4 Logs (`abdoh/logs.py`)
- `read_logs(cfg, since, level, search, limit)` parses today's and yesterday's file into entries
  (time, level, source, text; a traceback stays with its line) and hides keys and tokens.
- **Settings → Advanced → Log**: the latest entries first, "Problems only" (warnings and errors),
  a search box, Refresh, Copy, Open the log file. Each entry shows time, a level badge, where it
  came from (daemon, Claude, speech...) and the text. "Ask Abdoh what happened" sends a request.
- **Abdoh reads its own log.** `ACTION logs: <what to look for> | <when>` (Claude decides; when:
  just now, the last 10 minutes, today, yesterday; nothing: the last 30 minutes). Abdoh sends
  back the matching entries (warnings and errors always, at most 200 entries) and how the
  features involved are meant to work (from the Catalog, 3.5), and Claude answers from them.
  `claude.allow_logs` (on by default) on the Permissions page.

### 3.5 The Catalog (`abdoh/catalog.py`, `ui/web/catalog.js`)
- The content lives in Python (`catalog.py`: sections and features, each with what it does,
  phrases to say, steps, where to find it, tips, and which setting it depends on), so the page
  and Abdoh (3.4) use the same words, and tests check it names only pages and settings that
  exist.
- A page of its own in the sidebar ("Catalog", a book icon): a big search ("What do you want to
  do?"), section pills, a "Start here" strip (three steps), and feature cards. A card opens to
  show the steps, the phrases (copy, or "Try it" for harmless ones, which sends it to Abdoh), a
  button to the page or setting, and whether it's on right now (memory off, no ChatGPT, ...).
- Abdoh knows the Catalog exists and points to it ("it's all in the Catalog page").

---

## 4. Prompts

### 4.1 Codoh's ChatGPT instructions
"You are Codoh, a coding assistant working in the folder {folder} on the user's {platform}
computer. Use the tools to read, search and change files and to run commands there; never work
outside it. Read before you change; keep changes small and in the project's style; run the
project's tests when there are any. Say briefly what you did at the end. Answer in the user's
language, in Markdown." Plus "Plan only: don't change anything; propose a plan." when that mode
is on.

### 4.2 Watching
- System prompt (with `allow_screen`): "When the user wants you to watch them do something on
  their screen and tell them if they get it right ('watch me do this', 'tell me if I'm doing it
  wrong', 'look at my screen while I...'), write `ACTION watch: <what they're doing and what to
  watch for>`, then say in one short sentence that you're watching now and they can start..."
- `WATCH_FRAME`: "(Watching the user's screen: {goal}. Here is their screen now{window}. What you
  said during the watch: {notes}.) If they're doing fine or nothing new happened, write only the
  line ACTION ignore: fine. If they made a mistake, are about to, or are stuck, say so in one or
  two short sentences, and how to fix it. When the task is done, say so and write ACTION watch:
  off."

### 4.3 Logs
"You can read your own log, Abdoh's record of what it heard, did and why. When the user asks
why you did or didn't do something, whether something went wrong, or to check your logs, write
only the line `ACTION logs: <what to look for> | <when>`. Abdoh sends you the log and how its
features should work; then explain in a few spoken sentences what happened and what the user
can do."

---

## 5. Ground rules for this epic
1. Unit tests never start Claude Code, never call OpenAI, never take a real screenshot and
   never read the real log: fake processes, fake HTTP, fake grabs, temporary folders.
2. Codoh's tools never touch anything outside the chosen folder (tests check `..`, absolute
   paths and links).
3. Nothing new to install: Codoh's page is plain JavaScript and CSS like the others (a small
   Markdown renderer of its own, safe: text only, no HTML from the model).
4. Every new page and card is checked in light and dark in the demo page (`?demo`), with
   screenshots, before its story is merged.
5. Not released: the version stays 0.12.0 until the owner says to release.

---

## 6. Stories

### Story 110: ChatGPT when Claude's limit runs out (`story/110-chatgpt-fallback`)
1. `BrainError(message, limit=False, resets_at=None)`; Claude Code sets them (rate limit event,
   limit errors).
2. `FallbackBrain` (3.2) in `claude/fallback.py`; `make_brain` uses it; `claude.fallback`
   setting (config, settings view, example config).
3. The Claude card: "When Claude's limit runs out, use my ChatGPT plan" (shown when ChatGPT is
   connected); the summary and side line say when ChatGPT answers for Claude.
4. Tests: switching, the one sentence, staying until the reset, going back, no switch after
   words were said, the setting off, ChatGPT not allowed.

### Story 111: Logs in the app, and Abdoh reads its own (`story/111-logs`)
1. `abdoh/logs.py` (3.4): parse, filter, redact; tests with sample logs (tracebacks, both days,
   keys hidden).
2. `AppApi.logs(...)`, `open_log()`; Settings → Advanced → Log (3.4); demo data; screenshots.
3. `ACTION logs` (router, prompt 4.3, `claude.allow_logs` on the Permissions page); the follow-up
   with entries and the features' descriptions (until story 117, from `about()`).
4. Tests: the action, the follow-up's content, the permission off.

### Story 112: Watching the screen (`story/112-watch-screen`)
1. `abdoh/watch.py` (3.3): the session (goal, notes, started, last change), the loop with a
   fake grab and clock, the change test.
2. Router: `ACTION watch` (start, off), the prompt (4.2), the frame follow-up, the user's words
   with a fresh picture while watching, the stop phrases (`local_skills.stop_watching`).
3. Daemon: listening without the wake word while watching, frames only when nobody talks,
   speaking a frame's answer, the end after `watch_minutes`, "stop listening" ends it.
4. Window: the "Watching your screen" chip with a stop button; Settings → Conversation:
   "Watching the screen: look every 3 / 5 / 10 seconds".
5. Tests for each part.

### Story 113: Codoh, Claude chats (`story/113-codoh-claude`)
`codoh/claude.py` (3.1.1) with a fake process: the handshake and models, text, tool cards,
approvals (allow, allow for the chat, deny), set model and mode, stop, resume, the limit, not
signed in, the process dying.

### Story 114: Codoh, ChatGPT chats (`story/114-codoh-chatgpt`)
`codoh/tools.py` and `codoh/chatgpt.py` (3.1.2) with fake HTTP: the tools (and the folder
fence), the loop, approvals per mode, the items kept for the next request, errors (limits,
signed out).

### Story 115: Codoh, chats and folders (`story/115-codoh-chats`)
`codoh/store.py` and `codoh/manager.py`: recent folders, chats (title from the first message,
rename, delete), the page's updates by revision, the git branch and changes, carrying a chat
over (3.1.3), the switch to ChatGPT when Claude's limit runs out. `AppApi.codoh_*`.

### Story 116: Codoh, the page (`story/116-codoh-page`)
The page (3.1): the chats list, the empty state with "Open a folder" and suggestions, the chat
with Markdown, tool cards, diffs and approvals, the composer with the model, mode and effort
menus, Stop, the Changes panel. Demo data in `bridge.js`; screenshots in light and dark, small
and large windows. "Abdoh, open Codoh" shows it.

### Story 117: The Catalog (`story/117-catalog`)
`abdoh/catalog.py` (3.5) for every feature of epics 1 to 9; the page; the logs follow-up uses
it; Abdoh's prompt mentions it; tests check every page, setting and permission it names exists.

### Story 118: Docs (`story/118-docs`)
README (Codoh, watching, logs, the Catalog, the switch to ChatGPT), `docs/index.html`'s feature
list, the memory notes. No release.

### Story 119: Suggestions while watching (`story/119-watch-suggestions`)
Asked for after the epic: "watch the screen while I'm shopping, give me suggestions", and talk
about the items meanwhile. The same watch, with a kind: `ACTION watch: <goal> | mistakes` or
`| suggestions`. Claude picks it from the request (asked for tips, or a task where tips clearly
help, like shopping: suggestions; a form: mistakes only). "Stop suggesting for now" / "you can
suggest things too" go to Claude, which writes `ACTION watch` again with the other kind: the
same watch goes on (its notes, its time, its one look loop). A picture in a suggestions watch
also asks for "a better or cheaper choice, a warning, a useful tip", otherwise
`ACTION ignore: fine`. The chip says "Watching · suggestions on". No setting: the owner and
Claude agreed an on/off switch would add almost nothing, since what you say decides.
- [x] `watch.parse`, `Watch.suggest`, `Watch.change`; the router's kind notes; Claude's prompt.
- [x] One look loop per watch (a change doesn't start a second one).
- [x] "Watch me shop and give me suggestions" is one request (it was split in two).
- [x] The chip, the Catalog card, README.

---

## 6b. Results (2026-11-26)

All stories are merged on `main` (not released: the version is still 0.12.0).

| Story | What was checked |
|---|---|
| 110 ChatGPT when Claude's limit runs out | Fake brains: the switch, the one sentence, until the reset, back to Claude, no switch after words or other errors. Not with a real ChatGPT account |
| 111 Logs | The viewer in light and dark; real Claude Code asked `ACTION logs` by itself for "why did you stop talking a minute ago?" and explained the "shut up" in the log |
| 112 Watching the screen | Real Claude Code on drawn forms: started the watch, caught "31/02/1990" and an email without ".com", stayed quiet once fixed; "stop looking at the screen" ended it locally. Found and fixed: "watch me … and tell me if I get it wrong" was split into two requests |
| 113 Codoh, Claude chats | Real Claude Code: the approval came to Codoh, was allowed, the bug was fixed |
| 114 Codoh, ChatGPT chats | Fake Responses API (tools, approvals per mode, items, errors). Not with a real account |
| 115 Codoh, chats and folders | Fakes, plus real git in a temporary repository. Found and fixed: a repository without commits wasn't recognized |
| 116 Codoh, the page | Demo screenshots (light, dark, a small window, menus, approvals, the Changes panel) and a real run through the page with real Claude Code in a temporary git project |
| 117 The Catalog | 29 features in 9 sections; tests check every page and setting it names; screenshots with the real content |
| 119 Suggestions while watching | Real Claude Code on a drawn shop page: it chose suggestions for "watch while I shop, give me suggestions", pointed out a cheaper, better rated pair unasked, answered "is the one I picked better?", and after "stop suggesting for now" kept watching and stayed quiet; a passport form got mistakes only and caught 31/02. The chip in light and dark |

## 7. The owner's decisions (2026-11-26)
- Codoh is its own page, with its own sessions; Abdoh's context never goes to the coding models.
- Switching to ChatGPT when Claude's limit runs out is wanted (Abdoh and Codoh).
- "Stop looking at the screen" ends the whole watch: looking and listening.
- The log is shown under Settings → Advanced; Abdoh may read it.
- The Catalog may live where it fits best: chosen as its own page in the sidebar.

## 8. Things only the owner can do
- Try Codoh with a ChatGPT Plus or Pro account (the ChatGPT engine isn't tried for real here).
- Try a long screen watch, to see how much of the plan it uses.
