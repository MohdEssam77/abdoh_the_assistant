/* The Settings page: voice, microphone (with a live level meter), wake word and hotkey, speech
   recognition, and general things. Changes save right away; a few need a restart. */
"use strict";

(() => {
  const MODELS = [
    ["tiny", "Fastest", "Least accurate. For slower computers."],
    ["base", "Balanced (recommended)", "Fast, and good with clear speech."],
    ["small", "Most accurate", "Slower, and uses more memory."],
  ];
  const RESTART_LABELS = {
    hotkey: "hotkey", wake_words: "wake words", wake_word_aliases: "wake word spellings",
    wake_word_model: "wake word model", vosk_model: "fallback wake word model",
    whisper_model: "speech model", language: "language", log_file: "log file",
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
      el("div", { class: "text" }, `Restart Abdoh to use your new ${pending.join(", ")}.`),
      el("button", { class: "btn small", onclick: () => call("restart") }, "Restart now"));
  }

  /* ---------- voice ---------- */

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
    return card("Voice", null,
      row("Voice replies", "Speak answers out loud. Turn off to only see them here.",
        toggle($("#voice-toggle").checked, (on) => call("set_voice", on), "Voice replies")),
      row("Voice", list.length ? "More voices: Windows Settings → Time & language → Speech." : "No voices found.",
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
    return card("Microphone", "Abdoh listens with this microphone. Talk to see the level move.",
      row("Microphone", null, select(options, current, (value) => saveSettings({ mic_device: value }), "Microphone")),
      el("div", { class: "row stack" },
        el("div", { class: "meter", "aria-label": "Microphone level" }, el("i", { id: "mic-level" })),
        el("div", { class: "mic-status" }, el("span", { id: "mic-status" }, "Checking…"), el("div", { class: "spacer" }),
          el("button", { class: "btn small", onclick: () => call("open_sound_settings") }, "Windows sound settings"))));
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
      status.textContent = "The microphone isn't open yet (Abdoh is starting, or it can't use it).";
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
        el("small", {}, "What you say to wake Abdoh. Your trained wake word model listens for the sound; these words are checked in what Abdoh heard.")), words.box),
      row("Sensitivity", "Left: wakes more easily. Right: fewer false wake-ups.",
        el("div", { class: "range-wrap" }, sensitivity, el("div", { class: "range-ends" }, el("span", {}, "More easily"), el("span", {}, "Fewer mistakes")))),
      row("Hotkey", "Press it anywhere to talk without the wake word, or to stop a reply. Empty turns it off.",
        el("div", { class: "btn-row" }, hotkey, saveHotkey)),
      row("Listening with", null, el("span", { class: "tag", id: "wake-engine" }, $("#side-wake").textContent.replace(/^Wake word: /, ""))));
  }

  /* ---------- speech recognition ---------- */

  function speechCard() {
    const settings = App.settings;
    const model = MODELS.find(([v]) => v === settings.whisper_model) || [settings.whisper_model, settings.whisper_model, ""];
    return card("Speech recognition", "How Abdoh turns what you say into text. Everything runs on this computer.",
      row("Model", model[2], select(MODELS.map(([v, label]) => [v, label]).concat(MODELS.some(([v]) => v === settings.whisper_model) ? [] : [[settings.whisper_model, settings.whisper_model]]),
        settings.whisper_model, (value) => saveSettings({ whisper_model: value }), "Speech model")),
      row("Language", "Abdoh's voice speaks English; requests in other languages work best with Claude.",
        select([["en", "English"], ["auto", "Detect automatically"]], settings.language || "auto",
          (value) => saveSettings({ language: value === "auto" ? null : value }), "Language")));
  }

  /* ---------- general ---------- */

  function generalCard(login) {
    const settings = App.settings;
    const theme = store("abdoh.theme") || "system";
    return card("General", null,
      row("Start Abdoh when I sign in", "Abdoh starts in the tray when you sign in to Windows.",
        toggle(login && login.on, async (on, input) => {
          input.disabled = true;
          const result = await call("set_login_item", on);
          input.disabled = false;
          if (!result || !result.ok) {
            input.checked = !on;
            if (result) toast(result.error, true);
          } else toast(on ? "Abdoh will start when you sign in." : "Abdoh won't start by itself.");
        }, "Start at sign-in")),
      row("Check for updates", `Look for a new version of Abdoh once a day. You have ${App.version}.`,
        el("div", { class: "btn-row" },
          el("button", { class: "btn small", onclick: async (e) => {
            e.currentTarget.disabled = true;
            const update = await checkUpdate(true);
            e.currentTarget.disabled = false;
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
      voiceCard(voices), micCard(mics), wakeCard(), speechCard(), generalCard(login),
      el("p", { class: "faint", style: "text-align:center;margin:8px 0 0" }, `Abdoh ${App.version}`),
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
