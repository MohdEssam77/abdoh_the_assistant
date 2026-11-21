/* The bridge to Krekos: pywebview's js_api inside the app, or (with ?demo in the address) a demo
   with made-up data, so the page can be designed and screenshotted in a normal browser. */
"use strict";

const Bridge = (() => {
  const params = new URLSearchParams(location.search);

  function demoApi() {
    const queue = [];
    const push = (kind, value) => queue.push([kind, value]);
    let paused = false;
    const settings = {
      wake_words: ["krekos", "hey krekos", "ya krekos"], wake_word_aliases: ["krecos", "cricos"],
      wake_word_model: "models/hey_krekos.onnx", wake_word_threshold: 0.5, wake_word_voice_threshold: 0.5, hotkey: "ctrl+alt+space",
      whisper_model: "small", languages: ["en"], speech_engine: "auto", match_threshold: 85,
      silence_seconds: 0.6, max_record_seconds: 10, follow_up_seconds: 6, confirm_actions: "sound", wake_word_interrupts: true, voice_interrupts: true, voice_interrupt_sensitivity: "medium", duck_others: true, duck_percent: 30, tts_engine: "piper", piper_voice_en: "en_US-lessac-medium", piper_voice_de: "de_DE-thorsten-medium", tts_rate: 175, tts_voice: "", mic_device: "", mic_raw: true,
      allow_run: false, allow_power: true, check_updates: true, setup_done: true, log_file: "~/.krekos/krekos.log",
      has_api_key: false,
      claude: {
        backend: "auto", code_path: "", code_model: "", model: "claude-opus-5-5", max_tokens: 4000,
        effort: "low", allow_web: true, allow_files: true, allow_screen: true,
        actions: ["open_url", "open_app", "play_youtube", "media", "timer", "volume", "brightness", "app_volume", "remind", "note", "mode", "displays", "audio_output", "dark_mode", "lamp"], folders: [], connectors: ["Gmail", "Google Calendar"],
        instructions: "", timeout_seconds: 120, followup_seconds: 60, listen_after_question: true,
        translate_target: "English", voice_reply_max_sentences: 4,
      },
    };
    const history = params.get("demo") === "empty" ? [] : [
      "You: What time is it?",
      "Krekos: It is 9:41 AM.",
      "You: Set a timer for 25 minutes and play some lofi",
      "Krekos: Timer set for 25 minutes. Playing lofi hip hop radio on YouTube.",
      "You: What's a good name for a grey cat?",
      "Krekos: How about Smokey, Ash, or Pebble? Pebble is short, sweet and easy to call out.",
    ];
    setTimeout(() => {
      push("claude", "Pro subscription (Claude Code)");
      push("wake", "openWakeWord (hey_krekos)");
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
    let voiceActive = false;
    let demoLamps = [{ name: "Desk lamp", mac: "a8bb5006f1e2", ip: "192.168.1.41" }];
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
      { name: "Focus", icon: "target", description: "A 25-minute timer, and Krekos stops listening for more after replies.", settings: { follow_up: false }, actions: [{ type: "timer", value: "25 minutes" }] },
      { name: "Presentation", icon: "presentation", description: "Light theme, full brightness, and Krekos stays quiet.", settings: { dark_mode: false, brightness: 100, voice_replies: false }, actions: [] },
    ];
    const replies = {
      time: () => `It is ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}.`,
      timer: () => "Timer set for 10 minutes.",
    };
    return {
      demo: true,
      boot: async () => ({
        version: "0.7.3", platform: "win32", demo: true, settings,
        state: { status: "Starting...", claude: "", wake: "", hearing: "", mode: currentMode, voice: true, history },
      }),
      events: async () => queue.splice(0),
      send: async (text) => {
        push("history", `You: ${text}`);
        push("status", "Thinking...");
        const key = /time/i.test(text) ? "time" : /timer/i.test(text) ? "timer" : null;
        setTimeout(() => {
          push("history", `Krekos: ${key ? replies[key]() : "This is the demo, so I can't really do that."}`);
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
      modes: async () => ({ ok: true, modes, templates: modeTemplates, current: currentMode, displays, outputs: ["Speakers", "C34H89x"], icons: MODE_ICONS }),
      save_mode: async (mode, oldName) => {
        if (!mode.name.trim()) return { ok: false, error: "Give the mode a name." };
        modes = modes.filter((m) => m.name !== oldName && m.name !== mode.name).concat([mode]);
        return { ok: true, mode };
      },
      delete_mode: async (name) => { modes = modes.filter((m) => m.name !== name); return { ok: true }; },
      activate_mode: async (name) => { currentMode = name; push("mode", name); push("history", `Krekos: ${name} mode.`); },
      end_mode: async () => { currentMode = ""; push("mode", ""); push("history", "Krekos: Back to normal."); },
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
        const restart = ["hotkey", "wake_words", "whisper_model", "languages", "speech_engine"].filter((k) => k in changes);
        return { ok: true, settings, restart };
      },
      microphones: async () => ({
        devices: [
          { name: "Microphone (Lenovo FHD Webcam A", default: true },
          { name: "Microphone Array (Realtek(R) Au", default: false },
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
      lamps: async () => ({ lamps: demoLamps }),
      find_lamps: async () => { await new Promise((r) => setTimeout(r, 1200)); demoLamps = [{ name: "Desk lamp", mac: "a8bb5006f1e2", ip: "192.168.1.41" }, { name: "Lamp 2", mac: "a8bb5006f1e3", ip: "192.168.1.42" }]; return { ok: true, lamps: demoLamps }; },
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
      train_voice: async () => { voiceActive = true; push("wake", "openWakeWord (hey_krekos), your voice"); return { ok: true, passed: 10, total: 10, woke: 10, recorded: 10 }; },
      forget_voice: async () => { voiceActive = false; push("wake", "openWakeWord (hey_krekos)"); return { possible: true, active: false, stale: false, recorded: 0 }; },
      login_item: async () => ({ ok: true, on: true }),
      set_login_item: async (on) => ({ ok: true, on }),
      pick_folder: async () => "C:\\Users\\you\\Documents\\Projects",
      open_folder: async () => true,
      open_sound_settings: async () => {},
      restart: async () => {},
      claude_status: async () => ({
        installed: true, signed_in: true, plan: "pro", method: "claude.ai", has_api_key: false,
        backend: settings.claude.backend, using: "code", connected: true,
        summary: "Connected with your Pro plan.",
      }),
      install_claude: async () => ({ ok: true }),
      claude_sign_in: async () => ({ ok: true }),
      claude_sign_out: async () => ({ ok: true }),
      set_api_key: async () => ({ ok: true }),
      claude_test: async () => ({ ok: true, reply: "OK", via: "Claude Code" }),
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
