"""The Catalog: everything Abdoh can do, how to use it, and where its settings are.

One list for two readers: the Catalog page shows it (with whether each feature is on right
now), and Abdoh sends the parts that matter to Claude when it reads its own log, so Claude knows
how a feature is meant to work. Tests check that every page, setting and permission named here
exists.

A feature: id, section, title, icon, line (one sentence), what (a few sentences), say (phrases
to try), steps, where ({page, label, anchor}), tips, needs ("claude", "claude_code", "chatgpt",
"openrouter", "lamps"), setting (a switch that turns it off: "memory", "claude.allow_screen",
or "follow_up_seconds" for a number that is off at 0), try (a harmless phrase the page may send).
"""

from pathlib import Path

from abdoh.config import Config

SECTIONS = [
    {
        "id": "talk",
        "title": "Talking",
        "icon": "mic",
        "line": "Waking it, talking, interrupting, quiet",
    },
    {
        "id": "do",
        "title": "Getting things done",
        "icon": "bolt",
        "line": "Timers, apps, music, volume, windows",
    },
    {
        "id": "claude",
        "title": "Claude, your AI",
        "icon": "sparkles",
        "line": "Answers, the web, files, your plans",
    },
    {
        "id": "screen",
        "title": "Your screen",
        "icon": "eye",
        "line": "Looking at it, and watching you work",
    },
    {
        "id": "roles",
        "title": "Act as & the board",
        "icon": "role",
        "line": "Teachers, coaches, lessons",
    },
    {
        "id": "home",
        "title": "Modes & lamps",
        "icon": "lamp",
        "line": "Set the scene with one phrase",
    },
    {
        "id": "memory",
        "title": "Memory",
        "icon": "memory",
        "line": "What it remembers, and your week",
    },
    {"id": "codoh", "title": "Codoh", "icon": "code", "line": "Your coding assistant"},
    {
        "id": "abdoh",
        "title": "Abdoh itself",
        "icon": "settings",
        "line": "Settings, logs, updates, privacy",
    },
]

START = [
    {
        "title": "Say “Hey Abdoh”",
        "line": "Then ask anything: “what's the weather tomorrow?” Or press Ctrl+Alt+Space, or type on Home.",
        "page": "home",
    },
    {
        "title": "Connect Claude",
        "line": "With your Claude plan (Claude Code), an API key, OpenRouter or your ChatGPT plan, Abdoh answers everything else.",
        "page": "settings",
    },
    {
        "title": "Make it yours",
        "line": "Your own commands, modes for movie night or work, roles like a German teacher, and lamps.",
        "page": "commands",
    },
]

FEATURES: list[dict] = [
    # ----- talking -----
    {
        "id": "wake-word",
        "section": "talk",
        "title": "Wake word and hotkey",
        "icon": "mic",
        "line": "Say “Hey Abdoh”, or press Ctrl+Alt+Space, and talk.",
        "what": "Abdoh listens on this computer for its name. A soft chime says it woke up; then "
        "say what you want. You can pause after “Hey Abdoh”: it waits a few seconds for the rest. "
        "The hotkey works even while Abdoh is paused, and stops a reply too.",
        "say": ["Hey Abdoh, what time is it?", "Hey Abdoh … set a timer for 10 minutes"],
        "steps": [
            "Say “Hey Abdoh” clearly, at a normal volume.",
            "Wait for the soft chime (or just keep talking).",
            "Say your request; a short pause ends it.",
        ],
        "where": {"page": "settings", "label": "Settings → Wake word and hotkey"},
        "tips": [
            "Wakes up by itself? Raise the sensitivity, or teach it your voice.",
            "Doesn't wake? Lower the sensitivity and check the microphone level in Settings.",
        ],
        "try": "What time is it?",
    },
    {
        "id": "voice-check",
        "section": "talk",
        "title": "Only your voice wakes it",
        "icon": "shield",
        "line": "Teach Abdoh your voice, and a video saying its name won't wake it.",
        "what": "Record yourself saying the wake word a few times; afterwards Abdoh checks that "
        "it's you before it wakes. Everything stays on this computer.",
        "say": [],
        "steps": ["Settings → Wake word → Teach it your voice.", "Say “Hey Abdoh” when asked."],
        "where": {"page": "settings", "label": "Settings → Wake word → Teach it your voice"},
        "tips": ["“How sure it must be that it's you” makes it stricter or looser."],
    },
    {
        "id": "keep-talking",
        "section": "talk",
        "title": "Keep talking, without the wake word",
        "icon": "chat",
        "line": "After an answer, Abdoh listens a few more seconds so you can go on.",
        "what": "When Claude answers a question, Abdoh keeps listening for about six seconds (one "
        "soft note). Say the next thing, or “thanks” to end. When Claude asks you something, "
        "just answer.",
        "say": ["… and what about Sunday?", "Thanks, that's all"],
        "steps": ["Ask something.", "Right after the answer, just say the next thing."],
        "where": {
            "page": "settings",
            "label": "Settings → Conversation → Keep listening after a reply",
        },
        "setting": "follow_up_seconds",
        "tips": ["If you were talking to someone else, Claude notices and Abdoh stays quiet."],
    },
    {
        "id": "interrupt",
        "section": "talk",
        "title": "Talk over a reply",
        "icon": "wave",
        "line": "Just start talking: Abdoh goes quiet and listens.",
        "what": "While Abdoh speaks, talk and it stops at once. “Okay” or “go on” lets it carry "
        "on; “wait” stops it; anything else becomes your next request. It hears you over its own "
        "voice with echo cancellation (nothing recorded). A stray word from people nearby lets "
        "it carry on.",
        "say": ["Wait", "Go on", "Actually, make it Paris"],
        "steps": ["While Abdoh talks, just speak."],
        "where": {
            "page": "settings",
            "label": "Settings → Conversation → Stop when I start talking",
        },
        "setting": "voice_interrupts",
        "tips": [
            "Works best with headphones or the volume not too loud.",
            "Stops by itself on loud speakers? Lower “How easily your voice stops Abdoh”.",
        ],
    },
    {
        "id": "quiet",
        "section": "talk",
        "title": "Shut up, stop listening",
        "icon": "pause",
        "line": "“Shut up” ends the conversation; “stop listening” pauses Abdoh.",
        "what": "“Shut up”, “not you”, “you can stop now” (any words) end the conversation "
        "silently. “Stop listening” (“I'll call you when I need you”) pauses Abdoh: it hears "
        "nothing and makes no sound until “Abdoh, start listening”.",
        "say": ["Shut up", "You can stop listening now", "Abdoh, start listening"],
        "steps": [
            "Say it in any words.",
            "To come back: “Abdoh, start listening”, or the switch on Home.",
        ],
        "where": {"page": "home", "label": "Home → the Wake word switch"},
        "tips": ["The hotkey still works while Abdoh is paused."],
    },
    {
        "id": "voice",
        "section": "talk",
        "title": "Voices and languages",
        "icon": "speaker",
        "line": "Natural voices made on this computer, in the language you speak.",
        "what": "Abdoh speaks with natural voices (Piper, or Kokoro for English) and answers in "
        "the language you used. Add your languages in Settings; a voice for a new language "
        "downloads the first time.",
        "say": ["Wie spät ist es?", "Speak slower"],
        "steps": [
            "Settings → Voice: pick a voice and a speed.",
            "Settings → Speech recognition: your languages.",
        ],
        "where": {"page": "settings", "label": "Settings → Voice"},
        "tips": ["Voice replies off (the switch on Home): read answers instead of hearing them."],
    },
    # ----- getting things done -----
    {
        "id": "skills",
        "section": "do",
        "title": "Everyday things, instantly",
        "icon": "bolt",
        "line": "Timers, reminders, volume, apps, music, notes: done at once, without Claude.",
        "what": "Abdoh does the everyday things itself, in a split second, and plays a short "
        "sound instead of talking. Several at once work too: “stop the music and open WhatsApp”.",
        "say": [
            "Set a timer for 10 minutes",
            "Remind me at 5 to call mom",
            "Volume 30",
            "Open Spotify",
            "Next song",
            "Take a note: the door code is 4471",
            "What's 15 percent of 80?",
        ],
        "steps": ["Just ask."],
        "where": {"page": "home", "label": "Home"},
        "tips": [
            "Prefer to hear what it did? Settings → Conversation → When it does something for you."
        ],
        "try": "What's 15 percent of 80?",
    },
    {
        "id": "computer",
        "section": "do",
        "title": "Windows, screens and speakers",
        "icon": "monitor",
        "line": "Move windows, switch screens off, change the speakers, dark mode.",
        "what": "Abdoh numbers your monitors and switches them on and off, moves and maximizes "
        "windows, changes the sound output, dark mode, night light and power modes.",
        "say": [
            "Only screen 2",
            "Move Chrome to screen 1 maximized",
            "Use the headphones",
            "Dark mode",
        ],
        "steps": ["Name your screens on the Modes page (“TV”) to use the names."],
        "where": {"page": "modes", "label": "Modes → Your screens"},
        "tips": ["Screens come back where they were when you turn them on again."],
    },
    {
        "id": "power",
        "section": "do",
        "title": "Sleep, shut down, restart",
        "icon": "power",
        "line": "“Shut down in 30 minutes”, “go to sleep”: Abdoh asks first when it's now.",
        "what": "Abdoh puts the computer to sleep, shuts it down or restarts it when you say so, "
        "and asks first for anything right now. “Cancel the shutdown” takes it back.",
        "say": ["Shut down in 30 minutes", "Cancel the shutdown", "Lock my computer"],
        "steps": ["Say it; answer yes when Abdoh asks."],
        "where": {"page": "permissions", "label": "Permissions → Sleep, shut down and restart"},
        "setting": "allow_power",
        "tips": [],
    },
    {
        "id": "commands",
        "section": "do",
        "title": "Your own commands",
        "icon": "bolt",
        "line": "A phrase you say, and the steps Abdoh does: instantly, without Claude.",
        "what": "Make commands like “good morning” (open the mail, the calendar, the news) on the "
        "Commands page, from a template or your own. Or ask Abdoh to do something and then say "
        "“remember that as good morning”.",
        "say": ["Remember that as music time", "Good morning"],
        "steps": [
            "Commands → New command (or Templates).",
            "Give it a phrase and its steps.",
            "Say the phrase.",
        ],
        "where": {"page": "commands", "label": "Commands"},
        "tips": ["Ask for the same thing twice and Abdoh offers to make it a command."],
    },
    # ----- Claude -----
    {
        "id": "claude",
        "section": "claude",
        "title": "Ask anything",
        "icon": "sparkles",
        "line": "Everything your commands don't cover goes to Claude, with your own plan.",
        "what": "Questions, advice, writing, the weather, recipes: Claude answers in a few spoken "
        "sentences and can do things on the computer for you (open sites, play videos, set "
        "lamps). It searches the web when it needs current information.",
        "say": [
            "What's the weather in Cairo tomorrow?",
            "Put on some relaxing jazz",
            "Explain black holes simply",
        ],
        "steps": [
            "Connect Claude in Settings (your Claude plan, a key, OpenRouter or ChatGPT).",
            "Ask.",
        ],
        "where": {"page": "settings", "label": "Settings → Claude"},
        "needs": "claude",
        "tips": ["Your own instructions for Claude are on the Permissions page."],
        "try": "What's a good name for a grey cat?",
    },
    {
        "id": "plans",
        "section": "claude",
        "title": "Your plans: Claude, keys, ChatGPT",
        "icon": "key",
        "line": "Claude Code with your Claude plan, an API key, OpenRouter, or your ChatGPT plan.",
        "what": "Sign in with your Claude account (through Claude Code), or add an Anthropic or "
        "OpenRouter key, or continue with your ChatGPT plan. Abdoh never sees your passwords; "
        "keys and tokens stay on this computer.",
        "say": [],
        "steps": ["Settings → Claude.", "Pick one, or several: “Use” decides which answers."],
        "where": {"page": "settings", "label": "Settings → Claude"},
        "tips": ["Test shows which one answered."],
    },
    {
        "id": "fallback",
        "section": "claude",
        "title": "ChatGPT when Claude's limit runs out",
        "icon": "swap",
        "line": "With both connected, your ChatGPT plan takes over until Claude's limit resets.",
        "what": "When Claude's usage limit is reached, Abdoh says so once (“Claude's limit is used "
        "up until 8:50 PM, so your ChatGPT plan answers for now”), ChatGPT answers until then, and "
        "Claude comes back by itself. Codoh's chats switch too.",
        "say": [],
        "steps": [
            "Connect your ChatGPT plan in Settings → Claude.",
            "Leave “When Claude's limit runs out” on.",
        ],
        "where": {"page": "settings", "label": "Settings → Claude → When Claude's limit runs out"},
        "needs": "chatgpt",
        "setting": "claude.fallback",
        "tips": ["ChatGPT has no file tools or Gmail; those wait for Claude."],
    },
    {
        "id": "files",
        "section": "claude",
        "title": "Your files, Gmail and Calendar",
        "icon": "folder",
        "line": "Claude sorts files and reads your mail and calendar, asking before changes.",
        "what": "With Claude Code, Claude works with the files in your folders (and runs "
        "PowerShell), and uses the services connected to your Claude account, like Gmail and "
        "Google Calendar. It asks before deleting, overwriting or sending anything.",
        "say": [
            "How many files are in my Downloads?",
            "What's on my calendar tomorrow?",
            "Move the PDFs from Downloads into a folder called Taxes",
        ],
        "steps": ["Permissions → Work with your files.", "Permissions → Connected services."],
        "where": {"page": "permissions", "label": "Permissions"},
        "needs": "claude_code",
        "setting": "claude.allow_files",
        "tips": ["Limit it to some folders under “Folders Claude may use”."],
    },
    # ----- screen -----
    {
        "id": "look",
        "section": "screen",
        "title": "Look at my screen",
        "icon": "eye",
        "line": "“What does this error mean?”: Claude looks at the screen you're using.",
        "what": "When what you say is about your screen, Claude asks to see it and Abdoh sends a "
        "picture of the screen with the window in front. It also translates and summarizes "
        "what's on screen.",
        "say": [
            "What does this error mean?",
            "Read this to me",
            "Translate my screen to Arabic",
            "Summarize my screen",
        ],
        "steps": ["Ask about what you see."],
        "where": {"page": "permissions", "label": "Permissions → Look at your screen when you ask"},
        "needs": "claude",
        "setting": "claude.allow_screen",
        "tips": ["Abdoh always says when it looks."],
    },
    {
        "id": "watch",
        "section": "screen",
        "title": "Watch me while I work",
        "icon": "eye",
        "line": "Abdoh watches your screen as you work: it tells you about mistakes, and gives tips if you want.",
        "what": "Ask Abdoh to watch you do something. It says it's watching, looks whenever your "
        "screen changes, stays quiet while you do fine and tells you when you make a mistake, are "
        "about to, or get stuck. Ask for suggestions too (“watch while I shop and give me "
        "suggestions”) and it also speaks up when it sees a better choice or a useful tip; when you "
        "don't say, it picks what suits the task. Meanwhile just talk, no wake word: ask about "
        "what's on screen, or say “stop suggesting for now”. “Stop looking at the screen” ends it "
        "all.",
        "say": [
            "Watch me fill in this form and tell me if I get anything wrong",
            "Watch while I shop and give me suggestions",
            "Is this one better than the last one?",
            "Stop suggesting for now",
            "Okay, you can stop looking at the screen",
        ],
        "steps": [
            "Ask Abdoh to watch you (“watch me do this and tell me if I'm wrong”, or “… and give "
            "me suggestions”).",
            "Work as usual; talk to it any time, about anything on screen.",
            "Say “stop watching” (or press ✕ on the red chip) to end it.",
        ],
        "where": {"page": "settings", "label": "Settings → Conversation → Watching your screen"},
        "needs": "claude",
        "setting": "claude.allow_screen",
        "tips": [
            "“You can suggest things too” or “just tell me about mistakes” changes it mid-watch.",
            "Each look uses a little of your plan; a still screen costs nothing.",
            "It ends by itself after 20 quiet minutes.",
        ],
    },
    # ----- roles -----
    {
        "id": "roles",
        "section": "roles",
        "title": "Act as",
        "icon": "role",
        "line": "A German teacher, a math tutor, a chef: Abdoh plays the role.",
        "what": "Give Abdoh a role with its own instructions, speed and answer length. It stays "
        "in the role until you say to stop, in any words. Lamps can set the mood.",
        "say": ["Act as my German teacher", "Act as a friendly chef", "You can stop acting now"],
        "steps": ["Act as → Suggestions or New role.", "Say “act as my …”."],
        "where": {"page": "roles", "label": "Act as"},
        "needs": "claude",
        "tips": ["You can also just say “act as a pirate”, no role needed."],
    },
    {
        "id": "board",
        "section": "roles",
        "title": "Lessons on the board",
        "icon": "board",
        "line": "A role explains with code, math, diagrams and pictures, and listens without the wake word.",
        "what": "With the window open, a teaching role writes on the board: steps, equations, "
        "code, state machines and charts, photos and drawings. During the lesson just talk, no "
        "“Hey Abdoh”. “Save the board” keeps it as a PDF.",
        "say": ["Show me on the board how binary search works", "Save the board"],
        "steps": [
            "Start a role with the board on.",
            "Keep the window open.",
            "Ask; just talk to go on.",
        ],
        "where": {"page": "roles", "label": "Act as → the board"},
        "needs": "claude",
        "setting": "lesson_listen_seconds",
        "tips": ["AI pictures on the board need an OpenRouter key."],
    },
    # ----- modes and lamps -----
    {
        "id": "modes",
        "section": "home",
        "title": "Modes",
        "icon": "layers",
        "line": "“Movie mode”: screens, volume, theme, apps and lamps at once. “Back to normal” undoes it.",
        "what": "A mode switches several things together and puts them back afterwards: which "
        "screens are on, brightness, volume, the speakers, dark mode, night light, apps to open, "
        "a role and the lamps. Start one by its phrase, at a time of day, or from the window.",
        "say": ["Movie mode", "Work mode", "Back to normal", "Which mode is on?"],
        "steps": ["Modes → Templates or New mode.", "Say its phrase."],
        "where": {"page": "modes", "label": "Modes"},
        "tips": [],
        "try": "Which mode is on?",
    },
    {
        "id": "lamps",
        "section": "home",
        "title": "Smart lamps",
        "icon": "lamp",
        "line": "WiZ lamps on your Wi-Fi: on, off, dim, colours, whites and scenes.",
        "what": "Abdoh switches WiZ lamps directly on your network, no cloud: brightness, warm or "
        "cool whites, any colour, and WiZ scenes like ocean, party or fireplace, fast or slow.",
        "say": [
            "Lights off",
            "Desk lamp blue",
            "Lights party fast",
            "Dim the lights to 30 percent",
        ],
        "steps": [
            "Set the lamps up in the WiZ app.",
            "Settings → Lamps → Find lamps, and name them.",
        ],
        "where": {"page": "lamps", "label": "Lamps"},
        "needs": "lamps",
        "tips": ["Newer lamps: allow all controls in the WiZ app (Settings → Security)."],
    },
    # ----- memory -----
    {
        "id": "memory",
        "section": "memory",
        "title": "Memory",
        "icon": "memory",
        "line": "Tell Abdoh things about you; it remembers them across conversations.",
        "what": "“My sister is called Lina”, “remember that I start work at 9”. Abdoh keeps short "
        "facts about you, and lessons about what works on this computer. See, change or forget "
        "them on the Memory page.",
        "say": [
            "Remember that I like jazz",
            "What do you know about me?",
            "Forget that I like jazz",
        ],
        "steps": ["Tell it, or add it on the Memory page."],
        "where": {"page": "memory", "label": "Memory"},
        "setting": "memory",
        "tips": ["It stays on this computer and goes to Claude with your requests."],
    },
    {
        "id": "recall",
        "section": "memory",
        "title": "A week of conversations",
        "icon": "calendar",
        "line": "“What did we talk about yesterday?”: Abdoh finds it.",
        "what": "What you said and what Abdoh answered is kept for a week, as text on this "
        "computer. Ask about an earlier conversation and Claude reads it back; older days are "
        "deleted.",
        "say": [
            "What was that recipe you told me on Monday?",
            "Yesterday we talked about my lamps, what did we decide?",
        ],
        "steps": ["Just ask about it."],
        "where": {"page": "memory", "label": "Memory → Conversations"},
        "needs": "claude",
        "setting": "keep_conversations",
        "tips": ["Delete a day, or everything, on the Memory page."],
    },
    {
        "id": "self-edit",
        "section": "memory",
        "title": "Abdoh changes its own commands",
        "icon": "pencil",
        "line": "“Make a command called good evening that locks the screen”: done.",
        "what": "Ask Abdoh to make or change your commands, modes and roles. It asks for what's "
        "missing, says what it changed, and “undo that” puts it back.",
        "say": ["Add Spotify to work mode", "Make the German teacher speak slower", "Undo that"],
        "steps": ["Just ask."],
        "where": {
            "page": "permissions",
            "label": "Permissions → Change its own commands, modes and roles",
        },
        "needs": "claude",
        "setting": "claude.allow_self_edit",
        "tips": [],
    },
    # ----- Codoh -----
    {
        "id": "codoh",
        "section": "codoh",
        "title": "Codoh, your coding assistant",
        "icon": "code",
        "line": "Open a folder and let Claude or ChatGPT read, change and run your code.",
        "what": "A coding chat for one folder, on your own plans: the model reads and searches "
        "the code, changes files and runs commands there. Every step shows as a card, changes with "
        "their diff, and it asks before anything risky. Switch models mid-chat; the Changes "
        "panel shows what changed in git.",
        "say": [
            "Abdoh, open Codoh",
            "Make a new chat in my portfolio folder and tell Codoh to add a dark mode",
            "Tell Codoh to run the tests too",
            "Yes, allow it",
            "What is Codoh doing?",
        ],
        "steps": [
            "Open Codoh (the </> page).",
            "Open a folder.",
            "Ask: “find and fix the bug in …”, “write tests for …”.",
            "Allow or deny changes as they come.",
        ],
        "where": {"page": "codoh", "label": "Codoh"},
        "needs": "claude_code",
        "tips": [
            "“Ask first” asks before every change; “Auto-edit” only before commands; “Plan only” changes nothing.",
            "Codoh's chats are separate from Abdoh's: none of Abdoh's instructions go to them.",
            "While Codoh's page is open, ask Abdoh “what is Codoh doing?”: it knows, without "
            "looking at the screen.",
            "Chats you start by voice: Abdoh says when Codoh needs you and when it's done.",
        ],
    },
    # ----- Abdoh itself -----
    {
        "id": "logs",
        "section": "abdoh",
        "title": "Abdoh reads its own log",
        "icon": "log",
        "line": "“Why did you stop talking?”: Abdoh checks its log and explains.",
        "what": "Abdoh keeps a log of what it heard, did and why (today and yesterday). Ask what "
        "happened and Claude reads the log of that time, knowing how Abdoh should work, and "
        "explains. You can read it too, under Settings → Advanced → Log.",
        "say": [
            "Why did you stop talking just now?",
            "Did you hear me a minute ago?",
            "Check your logs, did anything go wrong today?",
        ],
        "steps": [
            "Ask about what happened.",
            "Or Settings → Advanced → Log → Ask Abdoh what happened.",
        ],
        "where": {
            "page": "settings",
            "label": "Settings → Advanced → Log",
            "anchor": "#advanced-card",
        },
        "needs": "claude",
        "setting": "claude.allow_logs",
        "tips": ["Keys and tokens are never in what it reads."],
    },
    {
        "id": "about",
        "section": "abdoh",
        "title": "It knows about itself",
        "icon": "info",
        "line": "“Which speech model do you use?”, “what commands do I have?”",
        "what": "Claude knows Abdoh's version, models, voices, settings, your modes, commands and "
        "lamps. It can't change settings itself, but says where they are, and this Catalog has "
        "the rest.",
        "say": ["Which speech model do you use?", "What commands do I have?", "What can you do?"],
        "steps": ["Just ask."],
        "where": {"page": "catalog", "label": "Catalog"},
        "needs": "claude",
        "tips": [],
        "try": "What can you do?",
    },
    {
        "id": "models",
        "section": "abdoh",
        "title": "Choose the models",
        "icon": "chip",
        "line": "Other speech recognition models and voices, under Settings → Advanced.",
        "what": "Abdoh comes with the recommended models (Parakeet, natural voices). Under "
        "Advanced you can pick Whisper or Canary models for more languages or accuracy, and other "
        "voices; each says what it's good at and downloads with a progress bar.",
        "say": [],
        "steps": ["Settings → Advanced.", "Pick a model: it downloads, then switches."],
        "where": {"page": "settings", "label": "Settings → Advanced", "anchor": "#advanced-card"},
        "tips": ["“Back to recommended” undoes it and deletes downloads you don't use."],
    },
    {
        "id": "privacy",
        "section": "abdoh",
        "title": "What stays on this computer",
        "icon": "shield",
        "line": "Hearing, the wake word and voices run offline; only Claude's requests leave.",
        "what": "The wake word, speech recognition and the voices run on this computer. What you "
        "ask Claude goes to Claude (with your own plan). Memory, conversations and the log stay "
        "here; the log keeps two days. Permissions decide what Claude may do and see.",
        "say": [],
        "steps": ["Permissions: what Claude may do and see.", "Memory: what's remembered."],
        "where": {"page": "permissions", "label": "Permissions"},
        "tips": [],
    },
    {
        "id": "updates",
        "section": "abdoh",
        "title": "Updates and starting with Windows",
        "icon": "refresh",
        "line": "Abdoh checks for a new version once a day and can start when you sign in.",
        "what": "When a new version is out, Home shows a banner to install it. Abdoh can start in "
        "the tray when you sign in to Windows.",
        "say": [],
        "steps": ["Settings → General."],
        "where": {"page": "settings", "label": "Settings → General"},
        "setting": "check_updates",
        "tips": ["Run the first-start setup again from Settings → General."],
    },
]

# Settings a feature can depend on: off when False, or a number that is off at 0.
NEEDS_TEXT = {
    "claude": "Connect Claude",
    "claude_code": "Needs Claude Code",
    "chatgpt": "Connect ChatGPT",
    "openrouter": "Needs an OpenRouter key",
    "lamps": "Find your lamps",
}


def setting_value(cfg: Config, name: str):
    """A setting by its dotted name ("memory", "claude.allow_screen")."""
    target = cfg
    for part in name.split("."):
        target = getattr(target, part)
    return target


def _ready(cfg: Config) -> dict[str, bool]:
    """What's connected right now (cheap: files and settings only)."""
    from abdoh.claude.code import find_claude_code

    exe = None
    try:
        exe = find_claude_code(cfg.claude.code_path)
    except Exception:
        exe = None
    try:
        from abdoh.claude.chatgpt import Account

        chatgpt = Account.of(cfg).plan_usage
    except Exception:
        chatgpt = False
    lamps = Path(cfg.app_dir / "lamps.json")
    return {
        "claude_code": bool(exe),
        "chatgpt": chatgpt,
        "openrouter": cfg.has_openrouter_key,
        "claude": cfg.claude.backend != "off"
        and bool(exe or cfg.has_api_key or cfg.has_openrouter_key or chatgpt),
        "lamps": lamps.exists() and lamps.stat().st_size > 4,
    }


def status(feature: dict, cfg: Config, ready: dict[str, bool]) -> dict:
    """{"state": "on" | "off" | "needs", "text": ...} for a feature right now."""
    need = feature.get("needs")
    if need and not ready.get(need, False):
        return {"state": "needs", "text": NEEDS_TEXT.get(need, "Needs setting up")}
    name = feature.get("setting")
    if name:
        value = setting_value(cfg, name)
        if not value:
            return {"state": "off", "text": "Off"}
    return {"state": "on", "text": "On"}


def catalog(cfg: Config) -> dict:
    """The Catalog for the page: sections, the start steps, and every feature with whether it
    is on right now."""
    ready = _ready(cfg)
    features = [{**f, "status": status(f, cfg, ready)} for f in FEATURES]
    return {"sections": SECTIONS, "start": START, "features": features}


def for_log(words: list[str], limit: int = 4) -> str:
    """How the features a log question is about are meant to work, for Claude ("" when none
    matches): the best `limit` of them by the words they share."""
    scored = []
    wanted = {w.lower() for w in words if len(w) > 3}
    for f in FEATURES:
        text = " ".join([f["title"], f["line"], f["what"], *f.get("say", [])]).lower()
        score = sum(1 for w in wanted if w in text)
        if score:
            scored.append((score, f))
    scored.sort(key=lambda pair: -pair[0])
    return "\n".join(f"- {f['title']}: {f['what']}" for _, f in scored[:limit])
