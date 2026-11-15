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
      vosk_model: "", whisper_model: "base", language: "en", match_threshold: 85,
      silence_seconds: 0.6, max_record_seconds: 10, tts_rate: 175, tts_voice: "", mic_device: "",
      allow_run: false, check_updates: true, setup_done: true, log_file: "~/.abdoh/abdoh.log",
      has_api_key: false,
      claude: {
        backend: "auto", code_path: "", code_model: "", model: "claude-opus-5-5", max_tokens: 4000,
        effort: "low", allow_web: true, allow_files: true, allow_screen: true,
        actions: ["open_url", "open_app", "play_youtube", "media", "timer"], folders: [],
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
    const replies = {
      time: () => `It is ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}.`,
      timer: () => "Timer set for 10 minutes.",
    };
    return {
      demo: true,
      boot: async () => ({
        version: "0.3.0", platform: "win32", demo: true, settings,
        state: { status: "Starting...", claude: "", wake: "", voice: true, history },
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
