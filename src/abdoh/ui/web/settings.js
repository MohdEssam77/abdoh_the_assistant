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
      el("div", { class: "text" }, `Restart Abdoh to use your new ${pending.join(", ")}.`),
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
        ? "Natural voices, made on this computer. The first time Abdoh speaks a new language, its voice downloads (about 60 MB)."
        : "The Windows voice. Natural voices sound much better, especially in German.",
        select([["piper", "Natural (recommended)"], ["windows", "Windows voice"]], natural ? "piper" : "windows",
          (value) => saveSettings({ tts_engine: value }).then(() => render()), "Kind of voice")),
      natural ? row("English voice", null, voicePick("piper_voice_en", ENGLISH_VOICES, "English voice")) : null,
      natural ? row("German voice", null, voicePick("piper_voice_de", GERMAN_VOICES, "German voice")) : null,
      natural ? downloadRow() : null,
      row(natural ? "Backup voice" : "Voice", natural
        ? "Speaks only until a natural voice is ready."
        : list.length ? "For English. Replies in other languages use a voice for that language, if Windows has one (add voices in Windows Settings → Time & language → Speech)." : "No voices found.",
        select(voiceOptions, settings.tts_voice || "", (value) => saveSettings({ tts_voice: value }), "Voice")),
      row("Speed", speedText, speed),
      row("Hear it", "Play a short sample with this voice and speed.",
        el("button", { class: "btn small", onclick: () => call("test_voice") }, el("span", { html: svg("play") }), "Test voice")));
  }

  /* A natural voice downloading: how far along it is (hidden when nothing downloads). */
  function downloadRow() {
    const bar = el("i", {});
    const text = el("small", {});
    const line = el("div", { class: "row", id: "voice-download" },
      el("div", { class: "label" }, el("b", {}, "Getting a voice ready"), text),
      el("div", { class: "meter download" }, bar));
    line.update = () => {
      const d = App.voiceDownload;
      line.hidden = !d;
      if (!d) return;
      text.textContent = `The natural ${d.language} voice is downloading: ${d.percent}%. The backup voice speaks meanwhile.`;
      bar.style.width = `${d.percent}%`;
    };
    line.update();
    return line;
  }

  /* ---------- microphone ---------- */

  function micCard(mics) {
    const devices = (mics && mics.devices) || [];
    const fallback = devices.find((d) => d.default);
    const options = [["", `Windows default${fallback ? ` (${fallback.name})` : ""}`], ...devices.map((d) => [d.name, d.name])];
    const current = (mics && mics.current) || "";
    if (current && !devices.some((d) => d.name === current)) options.push([current, `${current} (not connected)`]);
    const using = mics && mics.using;
    const windows = el("div", { class: "mic-windows" });
    const card = el("div", { class: "card", id: "mic-card" }, el("h2", {}, "Microphone"),
      el("p", { class: "lead" }, "Abdoh listens with this microphone. Talk to see the level move."),
      row("Microphone", using ? el("span", { class: "warn-text" }, `It isn't connected, so Abdoh listens with ${using} until it's back.`) : null,
        select(options, current, async (value) => {
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

  /* The microphone's own volume in Windows: a quiet one makes Abdoh mishear you. */
  async function showMicVolume(box, state) {
    state = state || await call("mic_volume");
    if (!state || !state.ok) return box.replaceChildren();
    const low = state.muted || state.volume < 60;
    const text = state.muted ? "It's muted in Windows, so Abdoh can't hear you."
      : low ? `Its volume in Windows is only ${state.volume}%. Abdoh hears you better when it's higher.`
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
        el("small", {}, "The wake word model listens for “Hey Abdoh” and “Ya Abdoh”. The words here are removed from what you say or type, so they never become part of a request.")), words.box),
      row("Sensitivity", "Left: wakes more easily. Right: fewer false wake-ups.",
        el("div", { class: "range-wrap" }, sensitivity, el("div", { class: "range-ends" }, el("span", {}, "More easily"), el("span", {}, "Fewer mistakes")))),
      row("Only my voice", "Say “Hey Abdoh” ten times (some close, some from across the room) and talk for 20 seconds, and only your voice wakes it. Then you can move Sensitivity to the left without false wake-ups. The recordings stay on this computer.", voiceCheck()),
      row("Keep unclear recordings", "When Abdoh hears you after its name but can't make out the words, keep that recording for a day, to find out why. Only those, only on this computer. Turning it off deletes them.",
        toggle(settings.keep_unclear_clips, (on, input) => saveSettings({ keep_unclear_clips: on }).then((ok) => { if (!ok) input.checked = !on; }), "Keep unclear recordings")),
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
      if (state.starting) {  // Abdoh is still loading its models
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
          toast("Your voice recordings are deleted. Any voice wakes Abdoh again.");
          show();
        } }, "Forget my voice") : null),
        ...(note ? [el("small", { class: "warn-text" }, note)] : []));
    };
    show();
    return box;
  }

  /* Why a recording wasn't taken, from how loud the microphone was meanwhile. */
  const MISSED = {
    silent: "Abdoh hears only silence. Is the microphone muted, or not allowed for apps in Windows? Fix it, then say it again.",
    low: "That was very quiet. Speak up or come closer, or turn the microphone up in Windows.",
    "": "I didn't hear that one. Once more, please.",
  };

  async function teachVoice(box, done) {
    let cancelled = false;
    const title = el("b", {});
    const hint = el("small", {});
    const bar = el("i", {});
    const fix = el("div", { class: "btn-row", hidden: true },
      el("button", { class: "btn small", onclick: () => call("open_mic_privacy") }, "Microphone privacy"),
      el("button", { class: "btn small", onclick: () => call("open_sound_settings") }, "Sound settings"));
    box.replaceChildren(el("div", { class: "voice-teach" }, title, hint, fix,
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
      let missed = null; // why the last one wasn't taken (MISSED), or null
      for (let n = from; n <= to && !cancelled;) {
        say(`Say “Hey Abdoh” (${n} of ${to})`, missed !== null ? MISSED[missed] || MISSED[""]
          : n <= 5 ? "Close to the laptop, the way you normally talk. Wait for the number to change after each one."
            : "Now from where you usually are: across the room, or a few steps away. Wait for the number to change.");
        fix.hidden = missed !== "silent" && missed !== "low";
        const result = await call("record_voice", "phrase", n);
        if (!result || !result.ok) { if (result) toast(result.error, true); return false; }
        missed = result.heard ? null : result.quiet || "";
        if (result.heard) n++;
      }
      fix.hidden = true;
      return !cancelled;
    };
    try {
      if (!(await record(1, 10))) return;
      say("Now read this aloud in your normal voice (20 seconds)", READ_ALOUD);
      const talk = await call("record_voice", "talk");
      if (cancelled || !talk) return;
      if (!talk.ok || !talk.heard) {
        return toast(talk.error || (talk.quiet === "silent" ? MISSED.silent : "I couldn't hear you talking. Try again."), true);
      }
      say("Learning your voice...", "This takes a few seconds.");
      let result = await call("train_voice");
      if (result && result.ok && result.total && result.passed < result.total - 2) {
        say(`It knew you in ${result.passed} of ${result.total}. Five more, please.`, "");
        if (!(await record(11, 15))) return;
        say("Learning your voice...", "This takes a few seconds.");
        result = await call("train_voice");
      }
      if (result && result.ok) toast("Done. Now only your voice wakes Abdoh.");
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
      loadLamps(true); // the pickers in commands and modes see the change
      const kinds = (Lamps.options && Lamps.options.kinds) || {};
      const rows = lamps.map((lamp) => {
        const name = el("input", { class: "input", value: lamp.name, "aria-label": "Lamp name", style: "width:160px" });
        name.addEventListener("change", async () => {
          const result = await call("rename_lamp", lamp.mac, name.value);
          if (result && !result.ok) toast(result.error, true);
          else if (result) toast(`Say “turn on the ${name.value.trim().toLowerCase()}”.`);
        });
        const does = kinds[lamp.kind] ? `${kinds[lamp.kind][0].toUpperCase()}${kinds[lamp.kind].slice(1)}. ` : "";
        return row(lamp.name, `${does}On your network at ${lamp.ip}.`, el("div", { class: "btn-row" }, name,
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
          if (!result.lamps.length) toast("No lamps answered. Is this computer on the same Wi-Fi as the lamps? In the WiZ app, under Settings → Security, allow all controls.", true);
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
    return card("Lamps", "WiZ smart lamps on your Wi-Fi. Say “turn on the lamp”, “desk lamp blue”, “lights party fast” or “dim the lights to 30 percent”, or use them in your modes and commands.", body);
  }

  /* ---------- conversation ---------- */

  const LESSON_TIMES = [[0, "Off"], [60, "1 minute"], [120, "2 minutes (recommended)"], [300, "5 minutes"], [600, "10 minutes"]];

  /* How long Abdoh keeps listening in a lesson after the last word: a choice, your own number of
     minutes (Custom), or off. */
  function lessonListening(settings) {
    const seconds = Number(settings.lesson_listen_seconds ?? 120);
    const preset = LESSON_TIMES.some(([value]) => value === seconds);
    const minutes = el("input", { type: "number", class: "input compact", min: 1, max: 60, step: 1,
      value: preset ? 3 : Math.round((seconds / 60) * 10) / 10, "aria-label": "Minutes", style: "width:5.5em" });
    const custom = el("span", { class: "lesson-custom", hidden: preset }, minutes, el("small", {}, "minutes"));
    const saveMinutes = () => {
      const value = Math.min(60, Math.max(1, Number(minutes.value) || 1));
      minutes.value = value;
      return saveSettings({ lesson_listen_seconds: Math.round(value * 60) });
    };
    minutes.addEventListener("change", saveMinutes);
    const pick = select([...LESSON_TIMES.map(([value, text]) => [String(value), text]), ["custom", "Custom…"]],
      preset ? String(seconds) : "custom", (value) => {
        custom.hidden = value !== "custom";
        if (value === "custom") {
          saveMinutes();
          minutes.focus();
        } else saveSettings({ lesson_listen_seconds: Number(value) });
      }, "Keep listening in a lesson");
    return el("div", { class: "lesson-listening" }, pick, custom);
  }

  function conversationCard() {
    const settings = App.settings;
    const claude = settings.claude || {};
    const save = (changes, input, on) => saveSettings(changes).then((ok) => { if (!ok) input.checked = !on; });
    return card("Conversation", "How talking with Abdoh flows.",
      row("When it does something for you", "“Open Spotify”, “volume 30”, “work mode”: it does it and plays a short sound, or says what it did. It speaks anyway if something goes wrong.",
        select([["sound", "A short sound"], ["words", "Say what it did"]], settings.confirm_actions || "sound",
          (value) => saveSettings({ confirm_actions: value }), "When it does something for you")),
      row("Keep listening after a reply", "After Claude answers a question, Abdoh listens for a few more seconds, so you can go on without the wake word. Not after it did something for you. Say “thanks” or just stay quiet to end.",
        toggle(settings.follow_up_seconds > 0, (on, input) => save({ follow_up_seconds: on ? 6 : 0 }, input, on), "Keep listening after a reply")),
      row("Keep listening in a lesson", "While a role (Act as) explains on the board with this window open, just talk: no “Hey Abdoh” needed. It goes back to the wake word after this long without a word from either of you, when you hide the window, or when you tell it to stop listening. Off: always the wake word.",
        lessonListening(settings)),
      row("Answer Claude's questions right away", "When Claude asks you something, just answer.",
        toggle(claude.listen_after_question, (on, input) => save({ claude: { listen_after_question: on } }, input, on), "Answer questions right away")),
      row("Stop when I start talking", App.hearing
        ? `Not available on this computer: ${App.hearing}.`
        : "Abdoh goes quiet as soon as it hears you, and listens. Say “okay” and it goes on; say “wait” and it stops. Works best with headphones or the volume not too loud.",
        App.hearing ? null : toggle(settings.voice_interrupts, (on, input) => save({ voice_interrupts: on }, input, on).then(() => render()), "Stop when I start talking")),
      settings.voice_interrupts && !App.hearing ? row("How easily your voice stops Abdoh", "Higher reacts sooner; lower is for loud rooms, or when Abdoh stops by itself.",
        select([["low", "Low"], ["medium", "Medium (recommended)"], ["high", "High"]], settings.voice_interrupt_sensitivity,
          (value) => saveSettings({ voice_interrupt_sensitivity: value }), "How easily your voice stops Abdoh")) : null,
      row("Lower other sounds while I talk to Abdoh", `Music and videos drop to ${settings.duck_percent}% of their volume while Abdoh listens and answers, then come back. Abdoh's own voice stays as it is.`,
        toggle(settings.duck_others, (on, input) => save({ duck_others: on }, input, on), "Lower other sounds while I talk to Abdoh")),
      row("Interrupt with the wake word", "Say “Hey Abdoh” while Abdoh is talking to stop it and say something new.",
        toggle(settings.wake_word_interrupts, (on, input) => save({ wake_word_interrupts: on }, input, on), "Interrupt with the wake word")));
  }

  /* ---------- speech recognition ---------- */

  /* On a suitable graphics card speech recognition runs there: the switch, and how it's going. */
  const GPU_HINT = "Faster speech recognition with less memory, on a graphics card with 4 GB or more of its own. Downloads 2.4 GB once.";

  function gpuRow(settings) {
    const line = row("Use the graphics card", App.gpu || GPU_HINT,
      toggle(settings.use_gpu, (on, input) => saveSettings({ use_gpu: on }).then((ok) => { if (!ok) input.checked = !on; }), "Use the graphics card"));
    line.querySelector("small").id = "gpu-status";
    return line;
  }

  function speechCard(models) {
    const settings = App.settings;
    const picked = models && models.speech_model && models.chosen_fits
      ? (models.speech || []).find((m) => m.id === models.speech_model) : null;
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
    const how = !fast ? "With these languages Abdoh uses the Whisper model below. It's slower, and it answers in the language you spoke."
      : lighter ? "The lighter Whisper model: less memory, more mistakes."
        : "English and German work without choosing: Abdoh hears which one you spoke, with the fastest and most accurate model. Add any other language you speak here.";
    return card("Speech recognition", "How Abdoh turns what you say into text. Everything runs on this computer.",
      el("div", { class: "row stack" }, el("div", { class: "label" }, el("b", {}, "Languages you speak to Abdoh"), el("small", {}, how)), picks),
      picked ? row("Model", `${picked.name}, chosen in Advanced below.`,
        el("button", { class: "btn small", onclick: openAdvanced }, "Change")) : null,
      fast && !picked ? row("Quality", "Best accuracy uses about 700 MB more memory (less on a graphics card).",
        select([["auto", "Best accuracy (recommended)"], ["whisper", "Lighter"]], lighter ? "whisper" : "auto",
          (value) => saveSettings({ speech_engine: value }).then((ok) => ok && render()), "Speech quality")) : null,
      fast && !lighter && (!picked || picked.gpu) ? gpuRow(settings) : null,
      picked ? null : !fast || lighter ? row("Whisper model", (MODELS.find(([v]) => v === settings.whisper_model) || ["", "", ""])[2],
        select(MODELS.map(([v, label]) => [v, label]).concat(MODELS.some(([v]) => v === settings.whisper_model) ? [] : [[settings.whisper_model, settings.whisper_model]]),
          settings.whisper_model, (value) => saveSettings({ whisper_model: value }), "Whisper model")) : null);
  }

  /* ---------- advanced: choosing the models (abdoh/models.py) ---------- */

  let advancedOpen = false; // stays open when the page draws itself again
  const mb = (n) => (n >= 1000 ? `${(n / 1000).toFixed(1)} GB` : `${n} MB`);

  function openAdvanced() {
    advancedOpen = true;
    const box = $("#advanced-card");
    if (box) { box.open = true; box.scrollIntoView({ behavior: "smooth", block: "start" }); }
  }

  function advancedCard(models) {
    if (!models) return null;
    const box = el("details", { class: "card advanced", id: "advanced-card" });
    box.open = advancedOpen;
    box.addEventListener("toggle", () => { advancedOpen = box.open; });
    const languages = (App.settings.languages || ["en"]).map((c) => (LANGUAGES.find(([code]) => code === c) || [c, c])[1]);
    const custom = !!App.settings.speech_model || (App.settings.tts_engine || "piper") !== "piper";
    const unfit = App.settings.speech_model && !models.chosen_fits;
    box.append(...[
      el("summary", {},
        el("div", { class: "label" }, el("h2", {}, "Advanced"),
          el("small", {}, "For people who like to choose their models. The recommended ones work well for most people.")),
        el("span", { class: "chev", html: svg("down") })),
      el("div", { class: "advanced-group" }, "Speech recognition"),
      el("p", { class: "advanced-lead" }, `The models that understand ${languages.join(" and ")}. Choosing one downloads it while Abdoh keeps listening, switches when it's ready, and deletes the one it replaced if that was downloaded.`),
      unfit ? el("p", { class: "error-text" }, "The model you chose doesn't understand your languages, so Abdoh uses the recommended one.") : null,
      el("div", { class: "model-list", id: "speech-models" }, (models.speech || []).map((m) => speechItem(m, models))),
      el("div", { class: "advanced-group" }, "Voice"),
      el("div", { class: "model-list" }, voiceItems()),
      custom ? el("div", { class: "advanced-back" },
        el("small", {}, "Parakeet and the natural voices, as Abdoh comes. Downloaded models you no longer use are deleted."),
        el("button", { class: "btn small", onclick: backToRecommended }, "Back to recommended")) : null,
    ].filter(Boolean)); // append() would write out a null
    return box;
  }

  function speechItem(m, models) {
    const status = models.status || {};
    const mine = status.id === m.id;
    const busy = mine && (status.state === "downloading" || status.state === "switching") && !m.using;
    const failed = mine && status.state === "failed" && !m.using;
    const current = (models.speech || []).find((x) => x.using);
    let action = null;
    if (busy) action = el("button", { class: "btn small", onclick: () => cancel(models) }, "Cancel");
    else if (!m.using) action = el("button", { class: "btn small", onclick: () => choose(m, current) }, m.ready ? "Use" : "Download and use");
    const item = el("div", { class: m.using ? "model-item using" : "model-item", "data-model": m.id },
      el("div", { class: "model-text" },
        el("div", { class: "model-name" }, el("b", {}, m.name),
          m.recommended ? el("span", { class: "tag good" }, "Recommended") : null,
          m.using ? el("span", { class: "tag on" }, "In use") : null),
        el("small", {}, m.line)),
      action);
    if (busy) item.append(progressLine(status, m, current));
    if (failed) item.append(el("p", { class: "error-text model-note" }, `${m.name} isn't ready: ${status.error} Abdoh keeps using ${current ? current.name : "the model it has"}. Try again later.`));
    return item;
  }

  function progressLine(status, m, current) {
    const downloading = status.state === "downloading";
    const percent = downloading ? status.percent || 0 : 100;
    const keeps = current ? ` Abdoh keeps using ${current.name} meanwhile.` : "";
    return el("div", { class: "model-progress", id: "model-progress" },
      el("div", { class: "meter download" }, el("i", { style: `width:${percent}%` })),
      el("small", {}, downloading ? `Downloading: ${percent}% of ${mb(m.size_mb)}.${keeps}` : `Loading ${m.name}…${keeps}`));
  }

  async function choose(m, current) {
    if (!m.ready && m.size_mb) {
      const now = current ? ` Abdoh keeps using ${current.name} until it's ready.` : "";
      if (!(await confirmBox(`${m.name} downloads ${mb(m.size_mb)}.${now}`, "Download"))) return;
    }
    if (await saveSettings({ speech_model: m.recommended ? "" : m.id }, true)) refreshModels();
  }

  async function cancel(models) {
    const current = (models.speech || []).find((x) => x.using);
    const back = !current || current.recommended ? "" : current.id;
    if (await saveSettings({ speech_model: back }, true)) { toast("Cancelled."); refreshModels(); }
  }

  async function backToRecommended() {
    if (await saveSettings({ speech_model: "", tts_engine: "piper" }, true)) { toast("Back to the recommended models."); render(); }
  }

  function voiceItems() {
    const engine = App.settings.tts_engine || "piper";
    const restart = (App.restart || []).includes("tts_engine");
    const VOICES = [
      ["piper", "Natural voices (Piper)", "English and German voices made on this computer. Another language's voice downloads once, about 60 MB.", true],
      ["windows", "Windows voice", "The voices that come with Windows: nothing to download, but they sound flat, especially in German.", false],
    ];
    return VOICES.map(([id, name, line, recommended]) => el("div", { class: engine === id ? "model-item using" : "model-item" },
      el("div", { class: "model-text" },
        el("div", { class: "model-name" }, el("b", {}, name),
          recommended ? el("span", { class: "tag good" }, "Recommended") : null,
          engine === id ? el("span", { class: "tag on" }, restart ? "After a restart" : "In use") : null),
        el("small", {}, line)),
      engine === id
        ? restart ? el("button", { class: "btn small", onclick: () => call("restart") }, "Restart now") : null
        : el("button", { class: "btn small", onclick: () => saveSettings({ tts_engine: id }, true).then((ok) => ok && render()) }, "Use")));
  }

  /* The Advanced card again (a switch moved on), keeping the page where it is. */
  async function refreshModels() {
    const models = await call("models");
    const old = $("#advanced-card");
    if (models && old) old.replaceWith(advancedCard(models));
    const speech = $("#speech-card");
    if (models && speech) { const card = speechCard(models); card.id = "speech-card"; speech.replaceWith(card); }
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
    const [voices, mics, login, models] = await Promise.all([call("voices"), call("microphones"), call("login_item"), call("models")]);
    const speech = speechCard(models);
    speech.id = "speech-card";
    const extra = (window.SettingsExtras || []).map((make) => make()).filter(Boolean);
    $("#settings-content").replaceChildren(...[
      el("div", { class: "page-head" }, el("h1", {}, "Settings")),
      restartBanner(),
      ...extra,
      voiceCard(voices), micCard(mics), wakeCard(), conversationCard(), speech, lampsCard(), generalCard(login),
      advancedCard(models),
      el("p", { class: "faint", style: "text-align:center;margin:8px 0 0" }, `Abdoh ${App.version}`),
    ].filter(Boolean));
    startMeter();
  }

  registerPage("settings", {
    show: render,
    hide: stopMeter,
    async event(kind, value) {
      const tag = $("#wake-engine");
      if (kind === "wake" && tag) tag.textContent = value;
      if (kind === "gpu" && $("#gpu-status")) $("#gpu-status").textContent = value || GPU_HINT;
      if (kind === "voice_download" && $("#voice-download")) $("#voice-download").update();
      if (kind === "speech_model" && $("#advanced-card")) {  // a model downloading, loading, ready
        const bar = $("#model-progress");
        const item = bar && bar.closest(".model-item");
        if (value && value.state === "downloading" && item && item.dataset.model === value.id) {
          bar.querySelector("i").style.width = `${value.percent || 0}%`;
          const text = bar.querySelector("small");
          text.textContent = text.textContent.replace(/\d+%/, `${value.percent || 0}%`);
        } else refreshModels();
      }
      if (kind === "devices" && $("#mic-card")) {  // a microphone was plugged in or out
        const mics = await call("microphones");
        const old = $("#mic-card");
        if (old) old.replaceWith(micCard(mics));
      }
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
