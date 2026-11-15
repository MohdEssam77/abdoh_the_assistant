# EPIC 3: Abdoh for everyone, a downloadable desktop app

> **For Claude Code:** This file is your source of truth for the third epic. `ABDOH_EPIC.md` (v1)
> and `ABDOH_EPIC_2.md` are done; their architecture still applies unless this file changes it.
> Work through the stories **in order** and follow the working rules in `CLAUDE.md` exactly.
> Keep everything **simple**.

---

## 1. Goal

Abdoh works well for me, but it is still set up through YAML files and a terminal. This epic
turns it into an app anyone on Windows can use:

1. **Download and install** it from a web page ("Download for Windows"), with a normal installer.
   No Python, no terminal.
2. A **modern app window**: talk or type to Abdoh, see the conversation, and change everything
   with forms instead of files.
3. **Your own commands** (the repeated things you do every day) added and edited in the app; they
   are the same commands as in `commands.yaml`.
4. **Settings and permissions**: what Abdoh may do on your computer, and your own instructions
   for how it behaves.
5. **Your own Claude**: each person connects their own Claude account or API key. Nobody uses
   mine.
6. A **first-start setup** that checks the microphone and the voice and connects Claude, and the
   app tells you when a new version is out.

### Non-goals (for now)
- macOS and Linux installers. The code keeps working there; only the Windows app is packaged.
- Code signing. An unsigned installer gets Windows' SmartScreen warning ("More info → Run
  anyway"); a certificate costs money. Documented on the download page.
- Installing updates silently. The app shows that a new version exists and links to it.
- Accounts, cloud sync, telemetry, or any server of our own.

---

## 2. Connecting Claude: the rules we follow

Read on 2026-11-15 at code.claude.com/docs/en/legal-and-compliance and /setup:

- A product may **run the unmodified Claude Code** as long as every person signs in with **their
  own** Claude subscription or API key, and the usage is billed to them. Abdoh does exactly
  this: it runs the installed `claude` binary (story 13 of epic 2).
- Sign-in must go through **Anthropic's own flow**. Abdoh never shows its own "Log in with
  Claude" screen and never reads, stores or passes on Claude account credentials or tokens. It
  opens `claude auth login` (Claude Code's own browser sign-in) and checks `claude auth status`.
- **The free Claude plan does not include Claude Code.** Free users can add an API key from the
  Claude Console (pay as you go), or use Abdoh without Claude: commands, timers, apps, media and
  YouTube all work locally.
- Shipping a product that runs Claude Code means the developer agrees to Anthropic's Commercial
  Terms.
- We may say in plain text that Abdoh works with Claude Code, but not use Anthropic's or Claude's
  names or logos as our branding, or suggest Anthropic made or endorses Abdoh.

---

## 3. Tech stack changes (decided; don't change without a reason)

Everything from epics 1 and 2 stays unless replaced here.

| Concern | Choice | Why |
|---|---|---|
| App window | **pywebview 6** showing local HTML, rendered by Windows' built-in **WebView2** (Edge) | A modern UI with plain web tech in a native window; WebView2 ships with Windows 10/11. The tkinter window stays as a fallback if it's missing |
| UI code | Plain HTML, CSS and JavaScript in `src/abdoh/ui/web/`; no framework, no build step | Simple; nothing to install for UI work |
| Page ↔ Abdoh | pywebview's `js_api`: one Python class (`AppApi`) with small methods; the page polls `events()` | One narrow, testable bridge; the page has no logic beyond showing things |
| Writing `config.yaml` | Re-rendered from `config.example.yaml` as a template, so its comments stay | Still readable for people who edit by hand; no new dependency |
| Writing `commands.yaml` | Validated with `parse_commands`, then `yaml.safe_dump` under the usual help header | A bad command can never reach the file |
| Installer | **Inno Setup 6** (build time only): per-user install, no admin rights, with an uninstaller | Free and standard |
| Releases | **GitHub Actions** on a `v*` tag: PyInstaller + Inno Setup on `windows-latest`, `Abdoh-Setup.exe` attached to a GitHub Release | No local build tools needed; repeatable |
| Download page | Static HTML in `docs/`, served by **GitHub Pages** | Free, no server |
| Update check | GitHub's "latest release" API, at most once a day, can be turned off | No update server |

---

## 4. How it works

```
Abdoh.exe
 ├─ main thread:   pywebview window (src/abdoh/ui/web)  ⇄  AppApi (src/abdoh/ui/api.py)
 │                   the page polls api.events() and calls api.* methods
 ├─ tray thread:   pystray icon (show window, pause, voice, quit)
 └─ daemon threads (unchanged): listen loop, UI requests, timers
        ▲ requests ("text", "listen", "settings_changed", ...)   │ events ("status", "history", ...)
        └────────────────────────── Bus ─────────────────────────┘

AppApi also uses, directly:
  settings.py         read and save config.yaml (keeps comments), what needs a restart
  commands/store.py   list, save, delete commands (validated), templates
  claude/setup.py     Claude Code installed? signed in? plan? open sign-in, sign out, API key
  updates.py          is there a newer release?
```

The daemon stays the only thing that listens, speaks and acts. The page asks for things over the
Bus (like the tray and the old window), and gets data (settings, commands, Claude status) from
AppApi.

---

## 5. Stories

### Story 24: Settings and commands stores (`story/24-settings-store`)
- `src/abdoh/settings.py`: `settings_view(cfg)` (the values the app shows), `save_settings(app_dir,
  changes)` (checks names and types, writes `config.yaml` from the template keeping its comments,
  returns the new Config), `restart_needed(old, new)` (which changed settings need a restart).
- New settings: `mic_device`, `tts_voice`, `check_updates`, `setup_done`, `claude.allow_screen`,
  `claude.actions`, `claude.folders`, `claude.instructions` (all with today's behavior as default).
- `src/abdoh/commands/store.py`: `CommandsStore` with `load()`, `save(command, old_name)`,
  `delete(name)`, and `TEMPLATES` (ready-made commands to start from).
- **Done when:** tests show comments survive a save, bad values are refused with a readable
  message, and an invalid command never reaches the file.

### Story 25: The new app window (`story/25-app-window`)
- The pywebview window: a sidebar (Home, Commands, Permissions, Settings) and the **Home** page:
  status, a big Talk button (same as the hotkey), the conversation, a box to type, Stop, Pause
  listening, Voice replies. Light and dark, following Windows. Closing hides it to the tray.
- `src/abdoh/ui/api.py` (`AppApi`); a new Bus request `listen`.
- Falls back to the tkinter window if pywebview or WebView2 is missing.
- The page also opens in a normal browser with demo data (`index.html?demo`), for design work.
- **Done when:** AppApi is unit tested with a fake bus, and `python -m abdoh run --show` opens the
  new window and works end to end.

### Story 26: Commands page (`story/26-commands-page`)
- A searchable list; a form to add or edit a command: name, trigger phrases (with `{blanks}`),
  actions (type and value, add, remove, reorder); delete; **Try it**; a gallery of templates.
- Validation errors are shown in the form.
- **Done when:** the AppApi command methods are tested and a saved command works by voice right
  away, without a restart.

### Story 27: Settings and permissions (`story/27-settings-permissions`)
- **Settings:** voice replies; voice and speed, with a test; microphone choice with a live level
  meter (it warns when the mic is silent and opens Windows' sound settings); wake words and
  sensitivity; hotkey; speech model; start at login; updates; open the data folder and the log.
- **Permissions:** what Claude may do (search the web; work with files, and in which folders;
  look at the screen; open links; open apps; media and volume; timers; YouTube), whether your
  commands may run programs, and **your instructions for Abdoh** (sent to Claude every time).
- Enforced in the router, the actions and the Claude backends; the system prompt only offers the
  allowed actions.
- Changes apply right away when possible; otherwise the page says a restart is needed and offers
  a Restart button.
- **Done when:** tests cover each permission being enforced, live changes, and the restart list.

### Story 28: Connect your Claude (`story/28-connect-claude`)
- A Claude card: status (signed in, with the plan; not signed in; Claude Code not installed; API
  key), **Install Claude Code** (Anthropic's official installer in a visible PowerShell window),
  **Sign in** (`claude auth login` in a visible window, finished in the browser), **Sign out**,
  **Use an API key** or remove it, **Test**.
- Explains the plans, including that the free plan doesn't include Claude Code.
- **Done when:** `src/abdoh/claude/setup.py` is tested with fake runners and Abdoh never handles
  Claude account credentials.

### Story 29: First-start setup (`story/29-first-start`)
- Welcome → Microphone (choose, level meter) → Voice (test) → Claude (connect or skip) → How to
  talk to Abdoh → Done. It can be skipped and opened again from Settings.
- **Done when:** it shows once on a new install (`setup_done`), and its API calls are tested.

### Story 30: Installer, releases and updates (`story/30-installer`)
- `installer/abdoh.iss`: per-user install to `%LOCALAPPDATA%\Programs\Abdoh`, Start Menu,
  optional desktop shortcut, optional start at sign-in, uninstaller (your settings in
  `%APPDATA%\Abdoh` are kept).
- `scripts/build_installer.py`; `.github/workflows/release.yml`: pushing a `v*` tag builds
  `Abdoh-Setup.exe` and attaches it to a GitHub Release.
- The version lives in one place (`abdoh.__version__`). The app checks for a newer release at
  most once a day and shows a banner with a download button.
- **Done when:** the update check and version comparison are tested, and the README explains how
  to make a release.

### Story 31: Download page (`story/31-download-page`)
- `docs/index.html` for GitHub Pages: a **Download for Windows** button (the latest release's
  installer), what Abdoh does, how it works, "your Claude, your account", privacy, FAQ
  (SmartScreen, requirements, plans), footer. Light and dark, phone width, no external scripts.
- **Done when:** the page links to the latest release, and the README says how to turn on Pages.

---

## 6. Things only the owner can do
- **Make the download public.** The GitHub repo is private, so release downloads and GitHub Pages
  need either a public repo or a separate public repo for releases.
- Turn on GitHub Pages (Settings → Pages → "Deploy from a branch", `main`, `/docs`).
- Agree to Anthropic's Commercial Terms before distributing an app that runs Claude Code.
- Optional later: a code signing certificate to remove the SmartScreen warning.
