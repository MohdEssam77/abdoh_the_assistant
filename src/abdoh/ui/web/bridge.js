/* The bridge to Abdoh: pywebview's js_api inside the app, or (with ?demo in the address) a demo
   with made-up data, so the page can be designed and screenshotted in a normal browser. */
"use strict";

const Bridge = (() => {
  const params = new URLSearchParams(location.search);

  function demoApi() {
    const queue = [];
    const push = (kind, value) => queue.push([kind, value]);
    let paused = false;
    const settings = {
      wake_words: ["abdoh", "hey abdoh", "ya abdoh"], wake_word_aliases: ["abdo", "abdul"],
      wake_word_model: "models/hey_abdoh.onnx", wake_word_threshold: 0.5, wake_word_voice_threshold: 0.5, hotkey: "ctrl+alt+space",
      whisper_model: "small", languages: ["en"], speech_engine: "auto", match_threshold: 85,
      silence_seconds: 0.6, max_record_seconds: 10, follow_up_seconds: 6, lesson_listen_seconds: 120, speech_model: "", memory: true, keep_conversations: true, conversation_days: 7, use_gpu: true, confirm_actions: "sound", wake_word_interrupts: true, keep_unclear_clips: false, voice_interrupts: true, voice_interrupt_sensitivity: "medium", duck_others: true, duck_percent: 30, tts_engine: "piper", piper_voice_en: "en_US-lessac-medium", piper_voice_de: "de_DE-thorsten-medium", tts_rate: 175, tts_voice: "", mic_device: "",
      allow_run: false, allow_power: true, check_updates: true, setup_done: true, log_file: "~/.abdoh/abdoh.log",
      has_api_key: false,
      claude: {
        backend: "auto", code_path: "", code_model: "", model: "claude-opus-5-5", max_tokens: 4000,
        effort: "low", allow_web: true, allow_files: true, allow_screen: true, allow_self_edit: true, allow_logs: true,
        actions: ["open_url", "open_app", "play_youtube", "media", "timer", "volume", "brightness", "app_volume", "remind", "note", "mode", "displays", "audio_output", "dark_mode", "lamp", "window"], folders: [], connectors: ["Gmail", "Google Calendar"],
        instructions: "", timeout_seconds: 120, followup_seconds: 60, listen_after_question: true,
        translate_target: "English", voice_reply_max_sentences: 4, chatgpt_model: "", fallback: true,
      },
    };
    const history = params.get("demo") === "empty" ? [] : [
      "You: What time is it?",
      "Abdoh: It is 9:41 AM.",
      "You: Set a timer for 25 minutes and play some lofi",
      "Abdoh: Timer set for 25 minutes. Playing lofi hip hop radio on YouTube.",
      "You: What's a good name for a grey cat?",
      "Abdoh: How about Smokey, Ash, or Pebble? Pebble is short, sweet and easy to call out.",
    ];
    setTimeout(() => {
      push("claude", "Pro subscription (Claude Code)");
      push("wake", "openWakeWord (hey_abdoh)");
      push("status", "Listening");
    }, 250);
    let commands = [
      { name: "Good morning", triggers: ["good morning"], actions: [
        { type: "say", value: "Good morning! Here's your playlist." },
        { type: "open_url", value: "https://www.youtube.com/watch?v=jfKfPfyJRdk" }] },
      { name: "Open my mail", triggers: ["open my mail", "open email"], actions: [{ type: "open_url", value: "https://mail.google.com" }] },
      { name: "YouTube search", triggers: ["search youtube for {query}"], actions: [{ type: "open_url", value: "https://www.youtube.com/results?search_query={query}" }] },
      { name: "Play on YouTube", triggers: ["play {query} on youtube"], actions: [{ type: "play_youtube", value: "{query}" }] },
      { name: "Open VS Code", triggers: ["open code", "open vs code"], actions: [{ type: "open_app", value: "Visual Studio Code" }] },
      { name: "Focus time", triggers: ["focus time"], actions: [{ type: "timer", value: "25 minutes" }, { type: "play_youtube", value: "lofi hip hop radio" }, { type: "media", value: "volume_down" }] },
    ];
    const templates = [
      { name: "Take a break", description: "A 5-minute break timer.", triggers: ["take a break"], actions: [{ type: "timer", value: "5 minutes" }] },
      { name: "Google search", description: "Searches Google for whatever you say.", triggers: ["google {query}"], actions: [{ type: "open_url", value: "https://www.google.com/search?q={query}" }] },
      { name: "Weather", description: "Shows the weather forecast.", triggers: ["what's the weather"], actions: [{ type: "open_url", value: "https://www.google.com/search?q=weather" }] },
      { name: "Focus time", description: "A 25-minute focus timer with calm music.", triggers: ["focus time"], actions: [{ type: "timer", value: "25 minutes" }] },
    ];
    const MODE_ICONS = ["sparkles", "film", "briefcase", "moon", "target", "presentation", "music", "game", "coffee", "book", "sun", "home"];
    let currentMode = params.get("mode") || "";
    let currentRole = params.get("role") || "";
    let roles = [
      { name: "German teacher", phrases: ["german lesson"], instructions: "You are my German teacher, and I'm a beginner. Speak German slowly and simply, explain new words in English, correct my mistakes kindly, and ask me to repeat new phrases.", speed: "slow", answers: "long", board: true, saved: true },
      { name: "Math teacher", phrases: ["math lesson"], instructions: "You are my patient math teacher. Explain step by step and check that I follow before going on. Put the worked steps on the board.", speed: "normal", answers: "long", board: true, saved: true },
    ];
    const demoBoard = [
      { id: 1, text: "### Solving $x^2 - x - 13 = 0$\n$$x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}$$\nHere $a = 1$, $b = -1$ and $c = -13$, so $x = \\frac{1 \\pm \\sqrt{53}}{2}$." },
      { id: 2, text: "Binary search keeps halving the list:\n\n```python\ndef binary_search(items, target):\n    low, high = 0, len(items) - 1\n    while low <= high:\n        mid = (low + high) // 2\n```" },
    ];
    let memory = [
      { text: "Their name is Mo; they study at Saarland University.", kind: "fact", added: "2026-11-20" },
      { text: "Their sister is called Lina.", kind: "fact", added: "2026-11-21" },
      { text: "They like to study with lo-fi music on Spotify.", kind: "fact", added: "2026-11-22" },
      { text: "WhatsApp: maximize its main window; the first window found is a hidden helper.", kind: "lesson", added: "2026-11-22" },
    ];
    let demoTalks = {
      "2026-11-25": { label: "Today", exchanges: [
        { at: "09:12", you: "Hey Abdoh, what's the weather like in Saarbrücken?", abdoh: "It's 4 degrees and cloudy, with rain after 3 pm." },
        { at: "14:03", you: "What does a proper carbonara look like?", abdoh: "Here's the classic from Rome: no cream, only eggs, pecorino and guanciale.", role: "Chef",
          board: "## Carbonara\nThe classic, from Rome:\n| Ingredient | Why |\n|---|---|\n| Guanciale | The soul of the dish |\n| Pecorino | Salty, sharp |\n[picture: spaghetti carbonara]" },
        { at: "14:05", you: "save the board", abdoh: "The board is saved as a PDF in your Documents, Abdoh, Boards.", role: "Chef", typed: true },
      ] },
      "2026-11-24": { label: "Yesterday", exchanges: [
        { at: "20:41", you: "Show me a DFA for binary numbers divisible by 3", abdoh: "The state is the remainder so far: reading a bit doubles it and adds the bit.", role: "Theoretical CS professor",
          board: "## Divisible by 3\n```dot\ndigraph { rankdir=LR; q0 [shape=doublecircle]; q0 -> q0 [label=0]; q0 -> q1 [label=1]; q1 -> q2 [label=0]; q1 -> q0 [label=1]; q2 -> q1 [label=0]; q2 -> q2 [label=1]; }\n```" },
        { at: "21:10", you: "movie mode", abdoh: "Done.", mode: "Movie" },
      ] },
      "2026-11-21": { label: "Saturday 21 November", exchanges: [
        { at: "11:00", you: "Remind me in 20 minutes to take the pizza out", abdoh: "I'll remind you at 11:20." },
      ] },
    };
    /* Settings → Advanced: the speech models (abdoh/models.py) and a pretend download. */
    const demoModels = [
      { id: "parakeet-v3", name: "Parakeet v3", line: "English, German and 23 more European languages, and the most accurate for its speed. Inside the app. On a graphics card with 4 GB or more it runs there (downloads 2.4 GB once), otherwise on the processor.", size_mb: 0, gpu: true, ready: true },
      { id: "parakeet-v2", name: "Parakeet v2", line: "English only. As accurate as v3 in English, a little better on clear speech, and as fast. Processor only. Downloads 630 MB.", size_mb: 630, gpu: false, ready: false },
      { id: "canary-180m-flash", name: "Canary 180M Flash", line: "English, German, Spanish or French, one language at a time (it must be told which). Small and quick, but makes more mistakes than Parakeet. Processor only. Downloads 215 MB.", size_mb: 215, gpu: false, ready: false },
      { id: "canary-1b-v2", name: "Canary 1B v2", line: "One of Parakeet's 25 languages at a time (it must be told which). About as accurate as Parakeet, but half as fast, and it needs about 1.2 GB of memory. Processor only. Downloads 1 GB.", size_mb: 1030, gpu: false, ready: false },
      { id: "whisper-base", name: "Whisper base", line: "Any language. Small and quick, but makes clearly more mistakes than Parakeet. Processor only. Downloads 150 MB.", size_mb: 150, gpu: false, ready: false },
      { id: "whisper-small", name: "Whisper small", line: "Any language. Good accuracy, slower than Parakeet and less accurate in English and German. Processor only. Downloads 490 MB.", size_mb: 490, gpu: false, ready: false },
      { id: "whisper-medium", name: "Whisper medium", line: "Any language, more accurate than small, but slow without a strong processor (a second or more for each request). Processor only. Downloads 1.5 GB.", size_mb: 1530, gpu: false, ready: false },
      { id: "whisper-large-v3-turbo", name: "Whisper large-v3 turbo", line: "Any language, very accurate. Needs a strong computer: on a laptop processor each request takes 5 seconds or more. Processor only. Downloads 1.6 GB.", size_mb: 1620, gpu: false, ready: false },
      { id: "whisper-large-v3", name: "Whisper large-v3", line: "Any language, the most accurate Whisper and the slowest: 6 seconds or more for each request on a laptop processor, and about 1.7 GB of memory. Processor only. Downloads 3.1 GB.", size_mb: 3090, gpu: false, ready: false },
    ];
    let demoUsing = "parakeet-v3";
    let demoStatus = {};
    let demoTimer = null;
    const demoSwitch = (id) => {
      clearInterval(demoTimer);
      const target = id || "parakeet-v3";
      const model = demoModels.find((m) => m.id === target);
      if (target === demoUsing) { demoStatus = { state: "ready", id: target }; push("speech_model", demoStatus); return; }
      let percent = model.ready ? 100 : 0;
      demoTimer = setInterval(() => {
        percent = Math.min(100, percent + 4);
        if (percent < 100) demoStatus = { state: "downloading", id: target, percent };
        else if (demoStatus.state !== "switching") demoStatus = { state: "switching", id: target };
        else { clearInterval(demoTimer); model.ready = true; demoUsing = target; demoStatus = { state: "ready", id: target }; }
        push("speech_model", demoStatus);
      }, window.DEMO_MODEL_TICK || 400);
    };
    const talkList = () => Object.entries(demoTalks).map(([date, d]) => ({ date, label: d.label, count: d.exchanges.length }));
    const memoryChanged = (result) => {
      if (result.ok) push("memory", null);
      return result;
    };
    const roleSuggestions = [
      { name: "German teacher", description: "Teaches you German slowly, in German, and corrects you kindly.", phrases: ["german lesson"], instructions: "You are my German teacher.", speed: "slow", answers: "long", board: true },
      { name: "Programming teacher", description: "Explains ideas simply, and shows the code on the board.", phrases: ["coding lesson"], instructions: "You are my programming teacher.", speed: "normal", answers: "long", board: true },
    ];
    let voiceActive = false;
    let demoOpenRouter = false;
    let demoChatGPT = params.has("chatgpt"); // ?chatgpt: already connected
    // Settings → Advanced → Log, newest first.
    const demoLog = () => [
      { time: "09:41:12", day: "today", level: "INFO", part: "Abdoh", text: "Abdoh: It is 9:41 AM.", details: "" },
      { time: "09:41:10", day: "today", level: "INFO", part: "Requests", text: "Local skill: time", details: "" },
      { time: "09:41:09", day: "today", level: "INFO", part: "Abdoh", text: "You: What time is it?", details: "" },
      { time: "09:41:08", day: "today", level: "INFO", part: "Wake word", text: "Wake word (0.93, voice 0.99)", details: "" },
      { time: "09:40:51", day: "today", level: "WARNING", part: "Speech", text: "Slow transcription: 1.84s for 3.2s of speech", details: "" },
      { time: "09:38:02", day: "today", level: "INFO", part: "Hearing", text: "You started talking (medium sensitivity, on the Microphone Array mic; Abdoh's voice reaches the mic at -31 dB, -58 dB of it left once cleaned)", details: "" },
      { time: "09:37:58", day: "today", level: "INFO", part: "Claude", text: "Claude is using WebSearch", details: "" },
      { time: "09:37:55", day: "today", level: "INFO", part: "Abdoh", text: "You: What's the weather like tomorrow?", details: "" },
      { time: "09:12:40", day: "today", level: "ERROR", part: "Abdoh", text: "Error handling 'turn on the desk lamp'", details: "Traceback (most recent call last):\n  File \"lights.py\", line 212, in send\nTimeoutError: the lamp didn't answer" },
      { time: "09:02:11", day: "today", level: "INFO", part: "Abdoh", text: "Abdoh 0.12.0 started", details: "" },
      { time: "20:27:04", day: "yesterday", level: "WARNING", part: "Claude", text: "Claude Code reported an error: You've hit your usage limit. It resets at 8:50 PM.", details: "" },
      { time: "20:27:03", day: "yesterday", level: "INFO", part: "Abdoh", text: "You: Uh okay you can stop now", details: "" },
    ];
    let demoChatGPTAt = 0;
    let demoLamps = [{ name: "Desk lamp", mac: "a8bb5006f1e2", ip: "192.168.1.41", kind: "colour" }];
    const demoLampHow = { "Desk lamp": "scene party speed 160 80%", "Lamp 2": "warm white 60%" };
    // abdoh.lights.options(), as the app gets it
    const demoLampOptions = {"colours":[["red","#ff0000"],["crimson","#dc143c"],["rose","#ff3c6e"],["coral","#ff5f46"],["salmon","#ff826e"],["peach","#ffa06e"],["orange","#ff6e00"],["amber","#ff9600"],["gold","#ffbe00"],["yellow","#ffdc00"],["lime","#aaff00"],["green","#00ff00"],["mint","#50ffaa"],["teal","#00c8a0"],["turquoise","#00e6d2"],["cyan","#00ffff"],["sky blue","#5abeff"],["blue","#0000ff"],["royal blue","#3250ff"],["indigo","#5000ff"],["purple","#8c00ff"],["violet","#aa3cff"],["lavender","#be96ff"],["magenta","#ff00ff"],["pink","#ff3ca0"],["hot pink","#ff148c"]],"whites":[["candle",2200],["warm",2700],["neutral",4000],["cool",6500]],"scenes":[{"id":1,"name":"Ocean","kinds":["colour"]},{"id":2,"name":"Romance","kinds":["colour"]},{"id":3,"name":"Sunset","kinds":["colour"]},{"id":4,"name":"Party","kinds":["colour"]},{"id":5,"name":"Fireplace","kinds":["colour"]},{"id":6,"name":"Cozy","kinds":["colour","white"]},{"id":7,"name":"Forest","kinds":["colour"]},{"id":8,"name":"Pastel colors","kinds":["colour"]},{"id":9,"name":"Wake up","kinds":["colour","white","dimmable"]},{"id":10,"name":"Bedtime","kinds":["colour","white","dimmable"]},{"id":11,"name":"Warm white","kinds":["colour","white"]},{"id":12,"name":"Daylight","kinds":["colour","white"]},{"id":13,"name":"Cool white","kinds":["colour","white"]},{"id":14,"name":"Night light","kinds":["colour","white","dimmable"]},{"id":15,"name":"Focus","kinds":["colour","white"]},{"id":16,"name":"Relax","kinds":["colour","white"]},{"id":17,"name":"True colors","kinds":["colour"]},{"id":18,"name":"TV time","kinds":["colour","white"]},{"id":19,"name":"Plant growth","kinds":["colour"]},{"id":20,"name":"Spring","kinds":["colour"]},{"id":21,"name":"Summer","kinds":["colour"]},{"id":22,"name":"Fall","kinds":["colour"]},{"id":23,"name":"Deep dive","kinds":["colour"]},{"id":24,"name":"Jungle","kinds":["colour"]},{"id":25,"name":"Mojito","kinds":["colour"]},{"id":26,"name":"Club","kinds":["colour"]},{"id":27,"name":"Christmas","kinds":["colour"]},{"id":28,"name":"Halloween","kinds":["colour"]},{"id":29,"name":"Candlelight","kinds":["colour","white","dimmable"]},{"id":30,"name":"Golden white","kinds":["colour","white"]},{"id":31,"name":"Pulse","kinds":["colour","white","dimmable"]},{"id":32,"name":"Steampunk","kinds":["colour","white","dimmable"]},{"id":33,"name":"Diwali","kinds":["colour","white"]},{"id":34,"name":"White","kinds":["colour","dimmable"]},{"id":36,"name":"Snowy sky","kinds":["colour"]},{"id":40,"name":"Dim to warm","kinds":["colour","white"]}],"kinds":{"colour":"colours and whites","white":"whites only","dimmable":"brightness only","plug":"on and off only"},"scene_words":{"ocean":"ocean","romance":"romance","sunset":"sunset","party":"party","fireplace":"fireplace","cozy":"cozy","forest":"forest","pastel colors":"pastel colors","wake up":"wake up","bedtime":"bedtime","warm white":"warm white","daylight":"daylight","cool white":"cool white","night light":"night light","focus":"focus","relax":"relax","true colors":"true colors","tv time":"tv time","plant growth":"plant growth","spring":"spring","summer":"summer","fall":"fall","deep dive":"deep dive","jungle":"jungle","mojito":"mojito","club":"club","christmas":"christmas","halloween":"halloween","candlelight":"candlelight","golden white":"golden white","pulse":"pulse","steampunk":"steampunk","diwali":"diwali","white":"white","snowy sky":"snowy sky","dim to warm":"dim to warm","disco":"party","cosy":"cozy","pastel colours":"pastel colors","autumn":"fall","true colours":"true colors","candle light":"candlelight","plantgrowth":"plant growth","wake-up":"wake up","dim-to-warm":"dim to warm","deepdive":"deep dive"},"white_first":["cool white","daylight","warm white","white"],"white_names":{"warm white":2700,"warm":2700,"soft white":2700,"candle white":2200,"white":4000,"neutral white":4000,"natural white":4000,"cool white":6500,"cool":6500,"cold white":6500,"daylight":6500,"bright white":6500},"speeds":{"very slow":20,"slowly":50,"slow":50,"fast":160,"quick":160,"very fast":200},"filler":["a","and","at","brightness","change","color","colour","in","it","lamp","lamps","light","lights","make","mode","now","of","on","please","put","scene","set","speed","switch","the","to","turn","with"]};
    let displays = [
      { id: "laptop", number: 1, label: "Laptop screen", name: "", nickname: "", active: true, internal: true, primary: false, rect: [-3840, 0, 1920, 1080] },
      { id: "hp", number: 2, label: "TV", name: "HP 32f", nickname: "TV", active: true, internal: false, primary: false, rect: [-1920, 0, 1920, 1080] },
      { id: "wide", number: 3, label: "C34H89x", name: "C34H89x", nickname: "", active: true, internal: false, primary: true, rect: [0, 0, 3440, 1440] },
    ];
    let modes = [
      { name: "Movie", icon: "film", phrases: ["movie night"], settings: { displays: ["2"], volume: 60, dark_mode: true },
        actions: [{ type: "say", value: "Enjoy the movie." }], exit_actions: [], schedule: [] },
      { name: "Work", icon: "briefcase", phrases: [], settings: { displays: "all", brightness: 100, power_mode: "best_performance" },
        actions: [{ type: "play_youtube", value: "jazz music" }, { type: "open_app", value: "Visual Studio Code" }], exit_actions: [], schedule: [] },
      { name: "Night", icon: "moon", phrases: [], settings: { brightness: 30, volume: 30, dark_mode: true }, actions: [], exit_actions: [], schedule: [] },
    ];
    const modeTemplates = [
      { name: "Focus", icon: "target", description: "A 25-minute timer, and Abdoh stops listening for more after replies.", settings: { follow_up: false }, actions: [{ type: "timer", value: "25 minutes" }] },
      { name: "Presentation", icon: "presentation", description: "Light theme, full brightness, and Abdoh stays quiet.", settings: { dark_mode: false, brightness: 100, voice_replies: false }, actions: [] },
    ];
    const replies = {
      time: () => `It is ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}.`,
      timer: () => "Timer set for 10 minutes.",
    };
    return {
      demo: true,
      boot: async () => ({
        version: "0.12.0", platform: "win32", demo: true, settings,
        state: { status: "Starting...", claude: "", wake: "", hearing: "", mode: currentMode, role: currentRole, listening: { on: !!currentRole, now: !!currentRole }, voice: true, history, board: currentRole ? demoBoard : [], gpu: "Speech recognition runs on your NVIDIA GeForce RTX 3050 6GB Laptop GPU (6 GB): about twice as fast, with less memory." },
      }),
      events: async () => queue.splice(0),
      send: async (text) => {
        push("history", `You: ${text}`);
        push("status", "Thinking...");
        const key = /time/i.test(text) ? "time" : /timer/i.test(text) ? "timer" : null;
        setTimeout(() => {
          push("history", `Abdoh: ${key ? replies[key]() : "This is the demo, so I can't really do that."}`);
          push("status", paused ? "Paused" : "Listening");
        }, 1100);
        return true;
      },
      talk: async () => {
        push("status", "Listening to you...");
        setTimeout(() => push("status", paused ? "Paused" : "Listening"), 2500);
      },
      stop_speaking: async () => push("status", paused ? "Paused" : "Listening"),
      set_paused: async (value) => { paused = value; push("status", value ? "Paused" : "Listening"); },
      set_voice: async (on) => push("voice", on),
      hide: async () => {},
      quit: async () => {},
      open_link: async () => true,
      commands: async () => ({ ok: true, commands, templates }),
      save_command: async (command, oldName) => {
        if (!command.name.trim()) return { ok: false, error: "Give the command a name." };
        if (!command.triggers.length) return { ok: false, error: "Add at least one phrase that triggers the command." };
        commands = commands.filter((c) => c.name !== oldName).concat([command]);
        return { ok: true, command };
      },
      delete_command: async (name) => {
        commands = commands.filter((c) => c.name !== name);
        return { ok: true };
      },
      open_commands_file: async () => {},
      modes: async () => ({ ok: true, modes, templates: modeTemplates, current: currentMode, displays, outputs: ["Speakers", "C34H89x"], icons: MODE_ICONS, roles: roles.map((r) => r.name) }),
      roles: async () => ({ ok: true, roles, suggestions: roleSuggestions, current: roles.find((r) => r.name === currentRole) || null }),
      save_role: async (role, oldName) => {
        if (!role.name.trim()) return { ok: false, error: "Give the role a name." };
        if (!role.instructions.trim()) return { ok: false, error: "Say how Abdoh should act (instructions)." };
        roles = roles.filter((r) => r.name !== oldName && r.name !== role.name).concat([{ ...role, saved: true }]);
        return { ok: true, role };
      },
      delete_role: async (name) => { roles = roles.filter((r) => r.name !== name); return { ok: true }; },
      start_role: async (name) => { currentRole = name; push("role", name); push("listening", { on: true, now: true }); push("history", `Abdoh: Acting as ${name}.`); },
      stop_role: async () => { currentRole = ""; push("board", null); push("role", ""); push("listening", { on: false, now: false }); push("history", "Abdoh: Stopped acting."); },
      memory: async () => ({ ok: true, entries: memory, max_entries: 60, max_chars: 4000, chars: memory.reduce((n, e) => n + e.text.length, 0) }),
      add_memory: async (text, kind) => {
        if (!text.trim()) return { ok: false, error: "There's nothing to remember." };
        const entry = { text: text.trim(), kind, added: "2026-11-23" };
        memory = [...memory, entry];
        return memoryChanged({ ok: true, entry });
      },
      change_memory: async (old, text, kind) => {
        memory = memory.map((e) => (e.text === old ? { ...e, text: text.trim(), kind } : e));
        return memoryChanged({ ok: true });
      },
      models: async () => {
        const chosen = settings.speech_model || "";
        return {
          speech: demoModels.map((m) => ({ ...m, recommended: m.id === "parakeet-v3", chosen: m.id === chosen, using: m.id === demoUsing })),
          speech_model: chosen, chosen_fits: true, using: demoUsing, status: demoStatus,
        };
      },
      conversations: async () => {
        const days = talkList();
        return { days, keep_days: settings.conversation_days || 7, since: days.length ? days[days.length - 1].label : "", since_date: days.length ? days[days.length - 1].date : "" };
      },
      conversation_day: async (date) => (demoTalks[date] ? { ok: true, label: demoTalks[date].label, exchanges: demoTalks[date].exchanges } : { ok: false, error: "That day isn't kept anymore." }),
      delete_conversation_day: async (date) => { delete demoTalks[date]; return { ok: true }; },
      forget_conversations: async () => { const n = Object.keys(demoTalks).length; demoTalks = {}; return { ok: true, days: n }; },
      forget_memory: async (text) => {
        memory = memory.filter((e) => e.text !== text);
        return memoryChanged({ ok: true });
      },
      keep_listening: async (on) => push("listening", { on: !!on, now: !!on }),
      clear_board: async () => push("board", null),
      save_mode: async (mode, oldName) => {
        if (!mode.name.trim()) return { ok: false, error: "Give the mode a name." };
        modes = modes.filter((m) => m.name !== oldName && m.name !== mode.name).concat([mode]);
        return { ok: true, mode };
      },
      delete_mode: async (name) => { modes = modes.filter((m) => m.name !== name); return { ok: true }; },
      activate_mode: async (name) => { currentMode = name; push("mode", name); push("history", `Abdoh: ${name} mode.`); },
      end_mode: async () => { currentMode = ""; push("mode", ""); push("history", "Abdoh: Back to normal."); },
      displays: async () => ({ displays }),
      rename_display: async (id, nickname) => { displays.find((d) => d.id === id).nickname = nickname; return { displays }; },
      reorder_displays: async (ids) => {
        displays = ids.map((id, i) => ({ ...displays.find((d) => d.id === id), number: i + 1 }));
        return { displays };
      },
      identify_displays: async () => {},
      settings: async () => ({ settings, restart: [] }),
      save_settings: async (changes) => {
        for (const [key, value] of Object.entries(changes)) {
          if (key === "claude") Object.assign(settings.claude, value);
          else settings[key] = value;
        }
        const restart = ["hotkey", "wake_words", "whisper_model", "languages", "speech_engine", "tts_engine"].filter((k) => k in changes);
        if ("speech_model" in changes) demoSwitch(changes.speech_model);
        return { ok: true, settings, restart };
      },
      microphones: async () => ({
        devices: [
          { name: "Microphone (Lenovo FHD Webcam Audio)", default: true },
          { name: "Microphone Array (Realtek(R) Audio)", default: false },
        ],
        current: settings.mic_device,
      }),
      mic_volume: async () => ({ ok: true, name: "Microphone Array", volume: 28, muted: false }),
      fix_mic_volume: async () => ({ ok: true, name: "Microphone Array", volume: 90, muted: false }),
      mic_level: async () => Math.round(400 + Math.random() * 9000),
      voices: async () => ({
        voices: ["Microsoft David Desktop - English (United States)", "Microsoft Zira Desktop - English (United States)"],
        current: settings.tts_voice,
      }),
      test_voice: async () => {},
      lamps: async () => ({ lamps: demoLamps, options: demoLampOptions }),
      board_pdf: async () => ({ ok: true, path: "C:\\Users\\you\\Documents\\Abdoh\\Boards\\Board.pdf" }),
      try_lamp: async () => ({ ok: true, lamps: demoLamps, options: demoLampOptions }),
      lamp_states: async () => ({ options: demoLampOptions,
        lamps: demoLamps.map((l) => ({ ...l, how: demoLampHow[l.name] || "warm white 80%", answers: true })) }),
      set_lamp: async (which, how) => {
        for (const l of demoLamps) {
          if (which !== "all" && l.name !== which) continue;
          const now = demoLampHow[l.name] || "warm white 80%";
          const level = /^(\d+)%$/.exec(how);
          demoLampHow[l.name] = how === "on" ? (now === "off" ? "warm white 80%" : now)
            : level ? (now === "off" ? `on ${level[1]}%` : `${now.replace(/\s*\d+%$/, "")} ${level[1]}%`) : how;
        }
        return { ok: true };
      },
      find_lamps: async () => { await new Promise((r) => setTimeout(r, 1200)); demoLamps = [{ name: "Desk lamp", mac: "a8bb5006f1e2", ip: "192.168.1.41", kind: "colour" }, { name: "Lamp 2", mac: "a8bb5006f1e3", ip: "192.168.1.42", kind: "white" }]; return { ok: true, lamps: demoLamps, options: demoLampOptions }; },
      rename_lamp: async (mac, name) => { demoLamps = demoLamps.map((l) => (l.mac === mac ? { ...l, name } : l)); return { ok: true, lamps: demoLamps }; },
      blink_lamp: async () => ({ ok: true, lamps: demoLamps }),
      forget_lamp: async (mac) => { demoLamps = demoLamps.filter((l) => l.mac !== mac); return { ok: true, lamps: demoLamps }; },
      connectors: async () => ({
        available: true, url: "https://claude.ai/settings/connectors",
        connectors: [
          { name: "Gmail", status: "connected", on: (settings.claude.connectors || []).includes("Gmail") },
          { name: "Google Calendar", status: "connected", on: (settings.claude.connectors || []).includes("Google Calendar") },
          { name: "Google Drive", status: "connected", on: (settings.claude.connectors || []).includes("Google Drive") },
        ],
      }),
      voice_check: async () => ({ possible: true, active: voiceActive, stale: false, recorded: voiceActive ? 10 : 0 }),
      record_voice: async (kind) => { await new Promise((r) => setTimeout(r, kind === "talk" ? 2500 : 900)); return { ok: true, heard: true }; },
      train_voice: async () => { voiceActive = true; push("wake", "openWakeWord (hey_abdoh), your voice"); return { ok: true, passed: 10, total: 10, woke: 10, recorded: 10 }; },
      forget_voice: async () => { voiceActive = false; push("wake", "openWakeWord (hey_abdoh)"); return { possible: true, active: false, stale: false, recorded: 0 }; },
      login_item: async () => ({ ok: true, on: true }),
      set_login_item: async (on) => ({ ok: true, on }),
      pick_folder: async () => "C:\\Users\\you\\Documents\\Projects",
      open_folder: async () => true,
      open_sound_settings: async () => {},
      open_mic_privacy: async () => {},
      restart: async () => {},
      claude_status: async () => ({
        installed: true, signed_in: true, plan: "pro", method: "claude.ai", has_api_key: false,
        has_openrouter_key: demoOpenRouter, openrouter_model: settings.claude.openrouter_model || "openrouter/auto",
        backend: settings.claude.backend, using: settings.claude.backend === "chatgpt" && demoChatGPT ? "chatgpt" : "code", connected: true,
        chatgpt: { connected: demoChatGPT, email: demoChatGPT ? "you@example.com" : "", plan_usage: demoChatGPT, model: settings.claude.chatgpt_model || "" },
        summary: settings.claude.backend === "chatgpt" && demoChatGPT ? "Using your ChatGPT plan." : "Connected with your Pro plan.",
      }),
      chatgpt_connect: async () => { demoChatGPTAt = Date.now(); return { ok: true, url: "https://auth.openai.com/api/accounts/authorize?client_id=dynamic_agent_client" }; },
      chatgpt_progress: async () => {
        if (!demoChatGPTAt) return { state: "none" };
        if (Date.now() - demoChatGPTAt < 3000) return { state: "waiting", error: "" };
        const first = !demoChatGPT;
        demoChatGPT = true;
        return { state: "done", error: "", plan_usage: true, first };
      },
      chatgpt_models: async () => ({ ok: true, chosen: settings.claude.chatgpt_model || "", models: [
        { id: "gpt-6.2-sol", name: "GPT-6.2 Sol" },
        { id: "gpt-6.1-sol", name: "GPT-6.1 Sol" },
        { id: "gpt-6-mini", name: "GPT-6 mini" },
      ] }),
      chatgpt_disconnect: async () => { demoChatGPT = false; demoChatGPTAt = 0; return { ok: true, revoked: true }; },
      install_claude: async () => ({ ok: true }),
      claude_sign_in: async () => ({ ok: true }),
      claude_sign_out: async () => ({ ok: true }),
      set_api_key: async () => ({ ok: true }),
      set_openrouter_key: async (key) => { demoOpenRouter = !!key; return { ok: true }; },
      openrouter_pictures: async () => ({ ok: true, chosen: "black-forest-labs/flux-3-image-klein", price: 0.008, credit: 4.37, models: [
        { id: "black-forest-labs/flux-3-image-klein", name: "Black Forest Labs: FLUX 3 Image Klein", free: false },
        { id: "google/gemini-3.1-flash-lite-image", name: "Google: Nano Banana 2 Lite", free: false },
        { id: "recraft/recraft-v4.1-flash-v2:free", name: "Recraft: Recraft V4.1 Flash V2 (free)", free: true },
      ] }),
      picture_price: async (model) => ({ price: model.endsWith(":free") ? 0 : 0.039 }),
      openrouter_models: async () => ({ ok: true, models: [
        { id: "openrouter/auto", name: "Auto Router", images: true, price: "" },
        { id: "anthropic/claude-sonnet-5.5", name: "Anthropic: Claude Sonnet 5.5", images: true, price: "$3 / $15 per million tokens" },
        { id: "google/gemini-3-pro", name: "Google: Gemini 3 Pro", images: true, price: "$2 / $12 per million tokens" },
        { id: "meta-llama/llama-4:free", name: "Meta: Llama 4 (free)", images: false, price: "free" },
      ] }),
      logs: async (problems, search) => {
        const all = demoLog().filter((e) => (!problems || e.level !== "INFO") && (!search || `${e.text} ${e.part}`.toLowerCase().includes(String(search).toLowerCase())));
        return { ok: true, entries: all, total: demoLog().length, problems: demoLog().filter((e) => e.level !== "INFO").length, path: "C:\\Users\\you\\.abdoh\\abdoh.log" };
      },
      open_log: async () => true,
      claude_test: async () => ({ ok: true, reply: "OK", via: settings.claude.backend === "chatgpt" ? "ChatGPT" : "Claude Code" }),
      refresh_claude: async () => {},
      check_update: async () => (params.get("update")
        ? { available: true, current: "0.3.0", version: "0.3.1", url: "https://github.com", download: "https://github.com" }
        : { available: false, current: "0.3.0" }),
    };
  }

  const ready = new Promise((resolve) => {
    if (params.has("demo")) return resolve(demoApi());
    const api = () => window.pywebview && window.pywebview.api;
    if (api() && api().boot) return resolve(api());
    window.addEventListener("pywebviewready", () => resolve(api()));
  });

  return { ready };
})();
