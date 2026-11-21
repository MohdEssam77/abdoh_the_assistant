/* The Settings page: voice, microphone (with a live level meter), wake word and hotkey, speech
   recognition, and general things. Changes save right away; a few need a restart. */
"use strict";

(() => {
  const MODELS = [
    ["base", "Fast", "Quick, but makes more mistakes."],
    ["small", "Balanced (recommended)", "Good accuracy. Downloads about 480 MB the first time."],
    ["medium", "Most accurate", "Slow without a fast computer. Downloads about 1.5 GB the first time."],
  ];
  const LANGUAGES = [["en", "English"], ["ar", "Arabic"], ["fr", "French"], ["de", "German"], ["es", "Spanish"],
    ["it", "Italian"], ["pt", "Portuguese"], ["tr", "Turkish"], ["ur", "Urdu"], ["hi", "Hindi"], ["id", "Indonesian"],
    ["nl", "Dutch"], ["ru", "Russian"], ["zh", "Chinese"], ["ja", "Japanese"], ["ko", "Korean"]];
  const RESTART_LABELS = {
    hotkey: "hotkey", wake_words: "wake words", wake_word_aliases: "wake word spellings",
    wake_word_model: "wake word model",
    whisper_model: "speech model", languages: "languages", speech_engine: "speech quality", log_file: "log file",
  };
  const QUIET = 100; // a mic this quiet for a few seconds is probably muted (of 32768)
  const HEARD = 1500;
  let meter = { timer: null, quietSince: null, heardAt: 0, root: document };

  /* Shared with other pages (e.g. the first-start setup). */
  window.Settings = { micCard, voiceCard, startMeter, stopMeter };

  function card(title, lead, ...rows) {
    return el("div", { class: "card" }, el("h2", {}, title), lead ? el("p", { class: "lead" }, lead) : null, rows);
  }

  function select(options, value, onChange, label) {
    const node = el("select", { class: "input compact", "aria-label": label },
      options.map(([v, text]) => el("option", { value: v, selected: v === value }, text)));
    node.addEventListener("change", () => onChange(node.value, node));
    return node;
  }

  function restartBanner() {
    const pending = (App.restart || []).map((k) => RESTART_LABELS[k] || k);
    if (!pending.length) return null;
    return el("div", { class: "banner", "data-kind": "warn" },
      el("span", { html: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></svg>', style: "display:contents" }),
      el("div", { class: "text" }, `Restart Krekos to use your new ${pending.join(", ")}.`),
      el("button", { class: "btn small", onclick: () => call("restart") }, "Restart now"));
  }

  /* ---------- voice ---------- */

  const ENGLISH_VOICES = ["en_US-lessac-medium", "en_US-amy-medium", "en_US-ryan-medium", "en_US-joe-medium",
    "en_US-kristin-medium", "en_GB-alan-medium", "en_GB-cori-medium", "en_GB-jenny_dioco-medium"];
  const GERMAN_VOICES = ["de_DE-thorsten-medium", "de_DE-kerstin-medium"];

  function voiceCard(voices) {
    const settings = App.settings;
    const list = (voices && voices.voices) || [];
    const speed = el("input", { type: "range", min: 120, max: 260, step: 5, value: settings.tts_rate, "aria-label": "Voice speed" });
    const speedText = el("small", {});
    const describeSpeed = () => {
      const v = Number(speed.value);
      speedText.textContent = `${v} words a minute${v < 160 ? " (slow)" : v > 205 ? " (fast)" : " (normal)"}`;
    };
    describeSpeed();
    speed.addEventListener("input", describeSpeed);
    speed.addEventListener("change", () => saveSettings({ tts_rate: Number(speed.value) }));
    const voiceOptions = [["", "Windows default voice"], ...list.map((v) => [v, v.replace(/ - .*$/, "")])];
    const natural = (settings.tts_engine || "piper") === "piper";
    const pretty = (name) => {  // "en_GB-jenny_dioco-medium" -> "Jenny Dioco (British)"
      const [code, who] = name.split("-");
      const accent = { en_US: "American", en_GB: "British", de_DE: "German" }[code] || code;
      return `${who.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())} (${accent})`;
    };
    const voicePick = (key, names, label) => select(names.map((n) => [n, pretty(n)]), settings[key], (value) => saveSettings({ [key]: value }), label);
    return card("Voice", null,
      row("Voice replies", "Speak answers out loud. Turn off to only see them here.",
        toggle($("#voice-toggle").checked, (on) => call("set_voice", on), "Voice replies")),
      row("Kind of voice", natural
        ? "Natural voices for English, German and other languages, made on this computer. A new language's voice downloads the first time (about 60 MB); the Windows voice speaks meanwhile."
        : "The Windows voice. Natural voices sound much better, especially in German.",
        select([["piper", "Natural (recommended)"], ["windows", "Windows voice"]], natural ? "piper" : "windows",
          (value) => saveSettings({ tts_engine: value }).then(() => render()), "Kind of voice")),
      natural ? row("English voice", null, voicePick("piper_voice_en", ENGLISH_VOICES, "English voice")) : null,
      natural ? row("German voice", null, voicePick("piper_voice_de", GERMAN_VOICES, "German voice")) : null,
      row(natural ? "Windows voice" : "Voice", natural
        ? "Speaks while a natural voice is still downloading."
        : list.length ? "For English. Replies in other languages use a voice for that language, if Windows has one (add voices in Windows Settings → Time & language → Speech)." : "No voices found.",
        select(voiceOptions, settings.tts_voice || "", (value) => saveSettings({ tts_voice: value }), "Voice")),
      row("Speed", speedText, speed),
      row("Hear it", "Play a short sample with this voice and speed.",
        el("button", { class: "btn small", onclick: () => call("test_voice") }, el("span", { html: svg("play") }), "Test voice")));
  }

  /* ---------- microphone ---------- */

  function micCard(mics) {
    const devices = (mics && mics.devices) || [];
    const fallback = devices.find((d) => d.default);
    const options = [["", `Windows default${fallback ? ` (${fallback.name})` : ""}`], ...devices.map((d) => [d.name, d.name])];
    const current = (mics && mics.current) || "";
    if (current && !devices.some((d) => d.name === current)) options.push([current, `${current} (not found)`]);
    const windows = el("div", { class: "mic-windows" });
    const card = el("div", { class: "card" }, el("h2", {}, "Microphone"),
      el("p", { class: "lead" }, "Krekos listens with this microphone. Talk to see the level move."),
      row("Microphone", null, select(options, current, async (value) => {
        if (await saveSettings({ mic_device: value })) showMicVolume(windows);
      }, "Microphone")),
      el("div", { class: "row stack" },
        el("div", { class: "meter", "aria-label": "Microphone level" }, el("i", { id: "mic-level" })),
        el("div", { class: "mic-status" }, el("span", { id: "mic-status" }, "Checking…"), el("div", { class: "spacer" }),
          el("button", { class: "btn small", onclick: () => call("open_sound_settings") }, "Windows sound settings"))),
      windows);
    showMicVolume(windows);
    return card;
  }

  /* The microphone's own volume in Windows: a quiet one makes Krekos mishear you. */
  async function showMicVolume(box, state) {
    state = state || await call("mic_volume");
    if (!state || !state.ok) return box.replaceChildren();
    const low = state.muted || state.volume < 60;
    const text = state.muted ? "It's muted in Windows, so Krekos can't hear you."
      : low ? `Its volume in Windows is only ${state.volume}%. Krekos hears you better when it's higher.`
        : `Its volume in Windows is ${state.volume}%.`;
    box.replaceChildren(row("Windows volume", el("span", { class: low ? "warn-text" : "" }, text),
      low ? el("button", { class: "btn small primary", onclick: async (e) => {
        e.currentTarget.disabled = true;
        const fixed = await call("fix_mic_volume");
        if (fixed && fixed.ok) { toast("Microphone turned up."); showMicVolume(box, fixed); }
        else if (fixed) toast(fixed.error, true);
      } }, state.muted ? "Unmute and turn up" : "Turn it up") : el("span", { class: "tag good" }, "Good")));
  }

  async function readMeter() {
    const bar = $("#mic-level", meter.root);
    const status = $("#mic-status", meter.root);
    if (!bar || !status) return stopMeter();
    let level = null;
    try { level = await App.api.mic_level(); } catch (e) { level = null; }
    const now = Date.now();
    if (level == null) {
      bar.style.width = "0%";
      status.textContent = "The microphone isn't open yet (Krekos is starting, or it can't use it).";
      return;
    }
    const db = 20 * Math.log10(Math.max(level, 1) / 32768);
    bar.style.width = `${Math.max(0, Math.min(100, ((db + 60) / 60) * 100))}%`;
    if (level >= HEARD) meter.heardAt = now;
    if (level < QUIET) meter.quietSince = meter.quietSince || now;
    else meter.quietSince = null;
    if (meter.quietSince && now - meter.quietSince > 3000) {
      status.textContent = "Very quiet. Is the microphone muted? Check it in Windows' sound settings.";
      status.className = "warn-text";
    } else if (now - meter.heardAt < 1500) {
      status.textContent = "Hearing you.";
      status.className = "good-text";
    } else {
      status.textContent = "Listening. Say something to test it.";
      status.className = "";
    }
  }

  function startMeter(root = $("#settings-content")) {
    stopMeter();
    meter = { timer: setInterval(readMeter, 120), quietSince: null, heardAt: 0, root };
  }

  function stopMeter() {
    if (meter.timer) clearInterval(meter.timer);
    meter.timer = null;
  }

  /* ---------- wake word and hotkey ---------- */

  function wakeCard() {
    const settings = App.settings;
    const words = chipsInput(settings.wake_words || [], "Add a wake word, then press Enter", (values) => {
      if (values.length) saveSettings({ wake_words: values });
      else toast("Keep at least one wake word.", true);
    });
    const sensitivity = el("input", { type: "range", min: 0.3, max: 0.8, step: 0.05, value: settings.wake_word_threshold, "aria-label": "Wake word sensitivity" });
    sensitivity.addEventListener("change", () => saveSettings({ wake_word_threshold: Number(sensitivity.value) }));
    const hotkey = el("input", { class: "input", value: settings.hotkey || "", placeholder: "ctrl+alt+space", style: "width:180px" });
    const saveHotkey = el("button", { class: "btn small", onclick: () => {
      const value = hotkey.value.trim().toLowerCase().replace(/\s*\+\s*/g, "+");
      if (value && !/^((ctrl|alt|shift|win)\+)+[a-z0-9]+$/.test(value)) return toast("Use keys like ctrl+alt+space or ctrl+shift+a.", true);
      saveSettings({ hotkey: value });
    } }, "Save");
    return card("Wake word and hotkey", null,
      el("div", { class: "row stack" }, el("div", { class: "label" }, el("b", {}, "Wake words"),
        el("small", {}, "The wake word model listens for “Hey Krekos” and “Ya Krekos”. The words here are removed from what you say or type, so they never become part of a request.")), words.box),
      row("Sensitivity", "Left: wakes more easily. Right: fewer false wake-ups.",
        el("div", { class: "range-wrap" }, sensitivity, el("div", { class: "range-ends" }, el("span", {}, "More easily"), el("span", {}, "Fewer mistakes")))),
      row("Only my voice", "Say “Hey Krekos” ten times (some close, some from across the room) and talk for 20 seconds, and only your voice wakes it. Then you can move Sensitivity to the left without false wake-ups. The recordings stay on this computer.", voiceCheck()),
      row("Hotkey", "Press it anywhere to talk without the wake word, or to stop a reply. Empty turns it off.",
        el("div", { class: "btn-row" }, hotkey, saveHotkey)),
      row("Listening with", null, el("span", { class: "tag", id: "wake-engine" }, $("#side-wake").textContent.replace(/^Wake word: /, ""))));
  }

  /* ---------- your voice check ---------- */

  const READ_ALOUD = "This morning was mild, so I walked to the bakery on the corner and bought fresh bread. " +
    "On the way back I called a friend, and we talked about the weekend, a film we both want to see, and where to have dinner. " +
    "Later I made coffee, read a few pages of my book, and answered some emails before lunch.";

  function voiceCheck() {
    const box = el("div", { class: "voice-check" });
    const show = async () => {
      const state = (await call("voice_check")) || {};
      if (state.starting) {  // Krekos is still loading its models
        box.replaceChildren(el("span", { class: "tag" }, "Starting…"));
        if (box.isConnected || !box.parentNode) setTimeout(show, 1500);
        return;
      }
      if (!state.possible) return box.replaceChildren(el("span", { class: "tag" }, "Needs the wake word model"));
      const note = state.stale ? "It was made for another wake word model: teach it again." : "";
      box.replaceChildren(el("div", { class: "btn-row" },
        el("span", { class: state.active ? "tag good" : "tag" }, state.active ? "On" : "Off"),
        el("button", { class: state.active ? "btn small" : "btn small primary", onclick: () => teachVoice(box, show) },
          state.active ? "Teach it again" : "Teach it your voice"),
        state.active || state.recorded ? el("button", { class: "btn small", onclick: async () => {
          await call("forget_voice");
          toast("Your voice recordings are deleted. Any voice wakes Krekos again.");
          show();
        } }, "Forget my voice") : null),
        ...(note ? [el("small", { class: "warn-text" }, note)] : []));
    };
    show();
    return box;
  }

  async function teachVoice(box, done) {
    let cancelled = false;
    const title = el("b", {});
    const hint = el("small", {});
    const bar = el("i", {});
    box.replaceChildren(el("div", { class: "voice-teach" }, title, hint,
      el("div", { class: "meter" }, bar),
      el("div", { class: "btn-row" }, el("button", { class: "btn small", onclick: () => { cancelled = true; title.textContent = "Stopping..."; } }, "Cancel"))));
    const say = (text, help) => { title.textContent = text; hint.textContent = help; };
    const timer = setInterval(async () => {
      let level = null;
      try { level = await App.api.mic_level(); } catch (e) { level = null; }
      const db = 20 * Math.log10(Math.max(level || 1, 1) / 32768);
      bar.style.width = `${Math.max(0, Math.min(100, ((db + 60) / 60) * 100))}%`;
    }, 120);
    const record = async (from, to) => {
      let missed = false;
      for (let n = from; n <= to && !cancelled;) {
        say(`Say “Hey Krekos” (${n} of ${to})`, missed ? "I didn't hear that one. Once more, please."
          : n <= 5 ? "Close to the laptop, the way you normally talk. Wait for the number to change after each one."
            : "Now from where you usually are: across the room, or a few steps away. Wait for the number to change.");
        const result = await call("record_voice", "phrase", n);
        if (!result || !result.ok) { if (result) toast(result.error, true); return false; }
        missed = !result.heard;
        if (result.heard) n++;
      }
      return !cancelled;
    };
    try {
      if (!(await record(1, 10))) return;
      say("Now read this aloud in your normal voice (20 seconds)", READ_ALOUD);
      const talk = await call("record_voice", "talk");
      if (cancelled || !talk) return;
      if (!talk.ok || !talk.heard) return toast(talk.error || "I couldn't hear you talking. Try again.", true);
      say("Learning your voice...", "This takes a few seconds.");
      let result = await call("train_voice");
      if (result && result.ok && result.total && result.passed < result.total - 2) {
        say(`It knew you in ${result.passed} of ${result.total}. Five more, please.`, "");
        if (!(await record(11, 15))) return;
        say("Learning your voice...", "This takes a few seconds.");
        result = await call("train_voice");
      }
      if (result && result.ok) toast("Done. Now only your voice wakes Krekos.");
      else if (result) toast(result.error, true);
    } finally {
      clearInterval(timer);
      done();
    }
  }

  /* ---------- smart lamps ---------- */

  function lampsCard() {
    const body = el("div", {});
    const draw = (lamps) => {
      const rows = lamps.map((lamp) => {
        const name = el("input", { class: "input", value: lamp.name, "aria-label": "Lamp name", style: "width:160px" });
        name.addEventListener("change", async () => {
          const result = await call("rename_lamp", lamp.mac, name.value);
          if (result && !result.ok) toast(result.error, true);
          else if (result) toast(`Say “turn on the ${name.value.trim().toLowerCase()}”.`);
        });
        return row(lamp.name, `On your network at ${lamp.ip}.`, el("div", { class: "btn-row" }, name,
          el("button", { class: "btn small", onclick: async () => {
            const result = await call("blink_lamp", lamp.mac);
            if (result && !result.ok) toast(result.error, true);
          } }, "Blink"),
          el("button", { class: "btn small", onclick: async () => {
            const result = await call("forget_lamp", lamp.mac);
            if (result && result.ok) draw(result.lamps);
          } }, "Forget")));
      });
      const find = el("button", { class: "btn small primary", onclick: async (e) => {
        const button = e.currentTarget;
        button.disabled = true;
        button.textContent = "Looking…";
        const result = await call("find_lamps");
        if (result && result.ok) {
          draw(result.lamps);
          if (!result.lamps.length) toast("No lamps answered. In the WiZ app, turn on “Allow local communication”.", true);
        } else {
          button.disabled = false;
          button.textContent = "Find lamps";
          if (result) toast(result.error, true);
        }
      } }, "Find lamps");
      body.replaceChildren(...(rows.length ? rows : [el("p", { class: "faint" }, "No lamps yet. Set them up in the WiZ app on your Wi-Fi, then press Find lamps.")]),
        el("div", { class: "btn-row", style: "margin-top:10px" }, find));
    };
    call("lamps").then((state) => draw((state && state.lamps) || []));
    return card("Lamps", "WiZ smart lamps on your Wi-Fi. Say “turn on the lamp”, “desk lamp blue” or “dim the lights to 30 percent”, or use them in your modes and commands.", body);
  }

  /* ---------- conversation ---------- */

  function conversationCard() {
    const settings = App.settings;
    const claude = settings.claude || {};
    const save = (changes, input, on) => saveSettings(changes).then((ok) => { if (!ok) input.checked = !on; });
    return card("Conversation", "How talking with Krekos flows.",
      row("When it does something for you", "“Open Spotify”, “volume 30”, “work mode”: it does it and plays a short sound, or says what it did. It speaks anyway if something goes wrong.",
        select([["sound", "A short sound"], ["words", "Say what it did"]], settings.confirm_actions || "sound",
          (value) => saveSettings({ confirm_actions: value }), "When it does something for you")),
      row("Keep listening after a reply", "After Claude answers a question, Krekos listens for a few more seconds, so you can go on without the wake word. Not after it did something for you. Say “thanks” or just stay quiet to end.",
        toggle(settings.follow_up_seconds > 0, (on, input) => save({ follow_up_seconds: on ? 6 : 0 }, input, on), "Keep listening after a reply")),
      row("Answer Claude's questions right away", "When Claude asks you something, just answer.",
        toggle(claude.listen_after_question, (on, input) => save({ claude: { listen_after_question: on } }, input, on), "Answer questions right away")),
      row("Stop when I start talking", App.hearing
        ? `Not available on this computer: ${App.hearing}.`
        : "Krekos goes quiet as soon as it hears you, and listens. Say “okay” and it goes on; say “wait” and it stops. Works best with headphones or the volume not too loud.",
        App.hearing ? null : toggle(settings.voice_interrupts, (on, input) => save({ voice_interrupts: on }, input, on).then(() => render()), "Stop when I start talking")),
      settings.voice_interrupts && !App.hearing ? row("How easily your voice stops Krekos", "Higher reacts sooner; lower is for loud rooms, or when Krekos stops by itself.",
        select([["low", "Low"], ["medium", "Medium (recommended)"], ["high", "High"]], settings.voice_interrupt_sensitivity,
          (value) => saveSettings({ voice_interrupt_sensitivity: value }), "How easily your voice stops Krekos")) : null,
      row("Lower other sounds while I talk to Krekos", `Music and videos drop to ${settings.duck_percent}% of their volume while Krekos listens and answers, then come back. Krekos's own voice stays as it is.`,
        toggle(settings.duck_others, (on, input) => save({ duck_others: on }, input, on), "Lower other sounds while I talk to Krekos")),
      row("Interrupt with the wake word", "Say “Hey Krekos” while Krekos is talking to stop it and say something new.",
        toggle(settings.wake_word_interrupts, (on, input) => save({ wake_word_interrupts: on }, input, on), "Interrupt with the wake word")));
  }

  /* ---------- speech recognition ---------- */

  function speechCard() {
    const settings = App.settings;
    const chosen = new Set(settings.languages || ["en"]);
    /* Parakeet (fast, accurate) understands these; anything else is Whisper. */
    const FAST = ["bg", "hr", "cs", "da", "nl", "en", "et", "fi", "fr", "de", "el", "hu", "it", "lv", "lt", "mt", "pl", "pt", "ro", "sk", "sl", "es", "sv", "ru", "uk"];
    const fast = [...chosen].every((c) => FAST.includes(c)) && (chosen.size === 1 || [...chosen].every((c) => c === "en" || c === "de"));
    const picks = el("div", { class: "picks" }, LANGUAGES.map(([code, name]) => {
      const button = el("button", { class: chosen.has(code) ? "pick on" : "pick", "aria-pressed": chosen.has(code) ? "true" : "false" }, name);
      button.addEventListener("click", async () => {
        const next = LANGUAGES.map(([c]) => c).filter((c) => (c === code ? !chosen.has(c) : chosen.has(c)));
        if (!next.length) return toast("Keep at least one language.", true);
        if (await saveSettings({ languages: next })) render();
      });
      return button;
    }));
    const lighter = settings.speech_engine === "whisper";
    const how = !fast ? "With these languages Krekos uses the Whisper model below. It's slower, and it answers in the language you spoke."
      : lighter ? "The lighter Whisper model: less memory, more mistakes."
        : "English and German work without choosing: Krekos hears which one you spoke, with the fastest and most accurate model. Add any other language you speak here.";
    return card("Speech recognition", "How Krekos turns what you say into text. Everything runs on this computer.",
      el("div", { class: "row stack" }, el("div", { class: "label" }, el("b", {}, "Languages you speak to Krekos"), el("small", {}, how)), picks),
      fast ? row("Quality", "Best accuracy uses about 700 MB more memory.",
        select([["auto", "Best accuracy (recommended)"], ["whisper", "Lighter"]], lighter ? "whisper" : "auto",
          (value) => saveSettings({ speech_engine: value }).then((ok) => ok && render()), "Speech quality")) : null,
      !fast || lighter ? row("Whisper model", (MODELS.find(([v]) => v === settings.whisper_model) || ["", "", ""])[2],
        select(MODELS.map(([v, label]) => [v, label]).concat(MODELS.some(([v]) => v === settings.whisper_model) ? [] : [[settings.whisper_model, settings.whisper_model]]),
          settings.whisper_model, (value) => saveSettings({ whisper_model: value }), "Whisper model")) : null);
  }

  /* ---------- general ---------- */

  function generalCard(login) {
    const settings = App.settings;
    const theme = store("abdoh.theme") || "system";
    return card("General", null,
      row("Start Krekos when I sign in", "Krekos starts in the tray when you sign in to Windows.",
        toggle(login && login.on, async (on, input) => {
          input.disabled = true;
          const result = await call("set_login_item", on);
          input.disabled = false;
          if (!result || !result.ok) {
            input.checked = !on;
            if (result) toast(result.error, true);
          } else toast(on ? "Krekos will start when you sign in." : "Krekos won't start by itself.");
        }, "Start at sign-in")),
      row("Check for updates", `Look for a new version of Krekos once a day. You have ${App.version}.`,
        el("div", { class: "btn-row" },
          el("button", { class: "btn small", onclick: async (e) => {
            const button = e.currentTarget; // gone from the event once we've awaited
            button.disabled = true;
            const update = await checkUpdate(true);
            button.disabled = false;
            if (update && !update.available) toast("You have the latest version.");
            if (update && update.available) showPage("home");
          } }, "Check now"),
          toggle(settings.check_updates, (on, input) => saveSettings({ check_updates: on }).then((ok) => { if (!ok) input.checked = !on; }), "Check for updates"))),
      row("Appearance", null, select([["system", "Same as Windows"], ["light", "Light"], ["dark", "Dark"]], theme, (value) => {
        store("abdoh.theme", value);
        applyTheme(value);
      }, "Appearance")),
      row("Your files", "Settings, commands and logs.",
        el("div", { class: "btn-row" },
          el("button", { class: "btn small", onclick: () => call("open_folder", "data") }, "Open data folder"),
          el("button", { class: "btn small", onclick: () => call("open_folder", "logs") }, "Open logs"))),
      row("First-start setup", "Check the microphone and the voice, and connect Claude, step by step.",
        el("button", { class: "btn small", onclick: () => window.Setup && window.Setup.open() }, "Run setup again")));
  }

  /* ---------- the page ---------- */

  async function render() {
    const [voices, mics, login] = await Promise.all([call("voices"), call("microphones"), call("login_item")]);
    const extra = (window.SettingsExtras || []).map((make) => make()).filter(Boolean);
    $("#settings-content").replaceChildren(...[
      el("div", { class: "page-head" }, el("h1", {}, "Settings")),
      restartBanner(),
      ...extra,
      voiceCard(voices), micCard(mics), wakeCard(), conversationCard(), speechCard(), lampsCard(), generalCard(login),
      el("p", { class: "faint", style: "text-align:center;margin:8px 0 0" }, `Krekos ${App.version}`),
    ].filter(Boolean));
    startMeter();
  }

  registerPage("settings", {
    show: render,
    hide: stopMeter,
    event(kind, value) {
      const tag = $("#wake-engine");
      if (kind === "wake" && tag) tag.textContent = value;
    },
    settingsChanged() {
      if (App.current !== "settings") return;
      const banner = restartBanner();
      const old = $("#settings-content > .banner");
      if (old) old.remove();
      if (banner) $("#settings-content .page-head").after(banner);
    },
  });
})();
