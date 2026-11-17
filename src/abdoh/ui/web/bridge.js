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
      wake_words: ["abdoh", "hey abdoh", "ya abdoh"], wake_word_aliases: ["abdo", "ab doe"],
      wake_word_model: "models/hey_abdoh.onnx", wake_word_threshold: 0.5, hotkey: "ctrl+alt+space",
      vosk_model: "", whisper_model: "small", languages: ["en"], speech_engine: "auto", match_threshold: 85,
      silence_seconds: 0.6, max_record_seconds: 10, follow_up_seconds: 6, wake_word_interrupts: true, voice_interrupts: true, voice_interrupt_sensitivity: "medium", duck_others: true, duck_percent: 30, tts_rate: 175, tts_voice: "", mic_device: "",
      allow_run: false, check_updates: true, setup_done: true, log_file: "~/.abdoh/abdoh.log",
      has_api_key: false,
      claude: {
        backend: "auto", code_path: "", code_model: "", model: "claude-opus-5-5", max_tokens: 4000,
        effort: "low", allow_web: true, allow_files: true, allow_screen: true,
        actions: ["open_url", "open_app", "play_youtube", "media", "timer", "volume", "brightness", "remind", "note"], folders: [],
        instructions: "", timeout_seconds: 120, followup_seconds: 60, listen_after_question: true,
        translate_target: "English", voice_reply_max_sentences: 4,
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
    const replies = {
      time: () => `It is ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}.`,
      timer: () => "Timer set for 10 minutes.",
    };
    return {
      demo: true,
      boot: async () => ({
        version: "0.4.0", platform: "win32", demo: true, settings,
        state: { status: "Starting...", claude: "", wake: "", hearing: "", voice: true, history },
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
