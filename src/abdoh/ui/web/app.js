/* Abdoh's window: shows what Abdoh says and does, and forwards what you do. The logic lives in
   Python (AppApi and the daemon); this file only draws and forwards. */
"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const App = { api: null, settings: {}, status: "Starting...", version: "", pages: {} };

/* ---------- small helpers ---------- */

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === false || value == null) continue;
    if (key === "class") node.className = value;
    else if (key === "html") node.innerHTML = value; // only ever used with our own markup
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

const ICON = {
  logo: '<svg viewBox="0 0 24 24" fill="#fff"><rect x="2.6" y="9" width="2.6" height="6" rx="1.3"/><rect x="6.8" y="6" width="2.6" height="12" rx="1.3"/><rect x="11" y="2.5" width="2.6" height="19" rx="1.3"/><rect x="15.2" y="6" width="2.6" height="12" rx="1.3"/><rect x="19.4" y="9" width="2.6" height="6" rx="1.3"/></svg>',
};

/* Line icons (24x24, drawn with the current text color). */
const PATHS = {
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  pencil: '<path d="M4 20h4L19 9l-4-4L4 16v4z"/><path d="m13.5 6.5 4 4"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
  play: '<path d="M7 5v14l11-7z"/>',
  up: '<path d="m6 15 6-6 6 6"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7l1-8z"/>',
  sparkles: '<path d="M12 3l1.8 4.6L18 9l-4.2 1.4L12 15l-1.8-4.6L6 9l4.2-1.4z"/><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
  say: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>',
  open_url: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z"/>',
  open_app: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M7 6.5h.01M10 6.5h.01"/>',
  play_youtube: '<rect x="2.5" y="5" width="19" height="14" rx="4"/><path d="m10 9 5 3-5 3z"/>',
  media: '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
  timer: '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2M9 2h6"/>',
  volume: '<path d="M4 9v6h4l5 4V5L8 9H4z"/><path d="M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12"/>',
  brightness: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  type: '<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
  run: '<path d="m5 7 5 5-5 5M12 19h7"/>',
  file: '<path d="M14 3H6v18h12V7l-4-4z"/><path d="M14 3v4h4"/>',
  check: '<path d="m5 12 5 5L20 7"/>',
  // modes
  layers: '<path d="m12 3 9 5-9 5-9-5 9-5z"/><path d="m3 13 9 5 9-5"/>',
  film: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
  briefcase: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V4h6v3M3 12h18"/>',
  moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
  presentation: '<path d="M3 4h18M5 4v11h14V4M12 15v5M8 20h8"/>',
  music: '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
  game: '<rect x="2.5" y="7" width="19" height="11" rx="5"/><path d="M7 11v3M5.5 12.5h3M15.5 12h.01M18 13.5h.01"/>',
  coffee: '<path d="M4 8h13v6a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5V8z"/><path d="M17 10h1.5a2.5 2.5 0 0 1 0 5H17M8 2v3M12 2v3"/>',
  book: '<path d="M4 4h6a2 2 0 0 1 2 2v14a2 2 0 0 0-2-2H4zM20 4h-6a2 2 0 0 0-2 2v14a2 2 0 0 1 2-2h6z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V20h14V9.5"/>',
  monitor: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  // the newer actions
  displays: '<rect x="2" y="5" width="11" height="8" rx="1.5"/><rect x="11" y="10" width="11" height="8" rx="1.5"/>',
  app_volume: '<path d="M4 9v6h4l5 4V5L8 9H4z"/><path d="M17 9v6M20 7v10"/>',
  audio_output: '<rect x="6" y="3" width="12" height="18" rx="2"/><circle cx="12" cy="14" r="3"/><path d="M12 7h.01"/>',
  dark_mode: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  night_light: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/><path d="M17 3v3M15.5 4.5h3"/>',
  power_mode: '<path d="M13 2 4 14h7l-1 8 9-12h-7l1-8z"/>',
  power: '<path d="M12 3v8M6.3 6.3a8 8 0 1 0 11.4 0"/>',
  keys: '<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
  wait: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  close_app: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m9 10 6 6M15 10l-6 6"/>',
  focus_app: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M8 12h8M13 9l3 3-3 3"/>',
  window: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M12 9v11"/>',
  mode: '<path d="m12 3 9 5-9 5-9-5 9-5z"/><path d="m3 13 9 5 9-5"/>',
  role: '<circle cx="12" cy="7.5" r="3.5"/><path d="M5 20.5a7 7 0 0 1 14 0"/><path d="M17.5 3.5l1.2 1.2M20 7h-1.5"/>',
};

function svg(name) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${PATHS[name] || ""}</svg>`;
}

/* A dialog over the page. Returns {close}. Escape or a click outside closes it. */
function openModal({ title, body, actions = [], wide = false, onClose }) {
  const back = el("div", { class: "modal-back" });
  const onKey = (e) => { if (e.key === "Escape") close(); };
  function close() {
    back.remove();
    document.removeEventListener("keydown", onKey);
    if (onClose) onClose();
  }
  const modal = el("div", { class: wide ? "modal wide" : "modal", role: "dialog", "aria-modal": "true" },
    el("div", { class: "modal-head" }, el("h2", {}, title),
      el("button", { class: "icon-btn", title: "Close", html: svg("x"), onclick: close })),
    el("div", { class: "modal-body" }, body),
    actions.length ? el("div", { class: "modal-foot" }, actions) : null);
  back.append(modal);
  back.addEventListener("mousedown", (e) => { if (e.target === back) close(); });
  document.addEventListener("keydown", onKey);
  document.body.append(back);
  const first = modal.querySelector("input, select, textarea");
  if (first) setTimeout(() => first.focus(), 30);
  return { close, modal };
}

/* Ask yes or no. Resolves to true for yes. */
function confirmBox(text, okLabel = "OK", danger = false) {
  return new Promise((resolve) => {
    let answered = false;
    const answer = (value) => {
      if (!answered) { answered = true; resolve(value); }
      dialog.close();
    };
    const dialog = openModal({
      title: "Are you sure?",
      body: el("p", { style: "margin:0" }, text),
      actions: [el("div", { class: "spacer" }),
        el("button", { class: "btn", onclick: () => answer(false) }, "Cancel"),
        el("button", { class: danger ? "btn danger-fill" : "btn primary", onclick: () => answer(true) }, okLabel)],
      onClose: () => { if (!answered) { answered = true; resolve(false); } },
    });
  });
}

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch (e) { /* storage can be unavailable; it only remembers small things */ }
  return null;
}

function hotkeyKeys(hotkey) {
  return String(hotkey || "").split("+").map((k) => k.trim()).filter(Boolean)
    .map((k) => (k.length <= 1 ? k.toUpperCase() : k[0].toUpperCase() + k.slice(1)));
}

function hotkeyText(hotkey) { return hotkeyKeys(hotkey).join("+") || "the hotkey"; }

function kbds(hotkey) {
  const keys = hotkeyKeys(hotkey);
  if (!keys.length) return [document.createTextNode("the hotkey")];
  return keys.map((k) => el("kbd", {}, k)).flatMap((k, i) => (i ? [" ", k] : [k]));
}

function toast(text, bad = false) {
  const node = el("div", { class: bad ? "toast bad" : "toast" }, text);
  $("#toasts").append(node);
  setTimeout(() => node.remove(), 3200);
}

async function call(name, ...args) {
  /* Call AppApi; on failure show a toast and return null. */
  try {
    return await App.api[name](...args);
  } catch (e) {
    console.error(name, e);
    toast(`Something went wrong (${name}).`, true);
    return null;
  }
}

/* ---------- shared form pieces ---------- */

function phrase(text) {
  /* A phrase with its {slots} highlighted. */
  return String(text).split(/(\{[^{}]*\})/).filter(Boolean)
    .map((part) => (/^\{.*\}$/.test(part) ? el("span", { class: "slot" }, part) : part));
}

/* A box of removable chips with an input to add more. onChange(values) runs after each change. */
function chipsInput(values, placeholder, onChange) {
  const list = [...values];
  const input = el("input", { placeholder, "aria-label": placeholder });
  const box = el("div", { class: "chips-input" });
  const changed = () => { if (onChange) onChange([...list]); };
  const draw = () => {
    box.replaceChildren(...list.map((value, i) => el("span", { class: "chip-x" }, phrase(value),
      el("button", { title: "Remove", html: svg("x"), onclick: () => { list.splice(i, 1); draw(); changed(); input.focus(); } }))), input);
  };
  const add = () => {
    const value = input.value.trim().replace(/,$/, "").trim();
    input.value = "";
    if (value && !list.includes(value)) {
      list.push(value);
      changed();
    }
    draw();
    input.focus();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); }
    else if (e.key === "Backspace" && !input.value && list.length) { list.pop(); draw(); changed(); input.focus(); }
  });
  box.addEventListener("click", (e) => { if (e.target === box) input.focus(); });
  draw();
  return { box, values: () => { if (input.value.trim()) add(); return [...list]; } };
}


/* What Abdoh can do: commands and modes use the same actions. */
const ACTIONS = {
  say: { label: "Say something", placeholder: "Good morning! It's {time} on {date}." },
  open_url: { label: "Open a website", placeholder: "https://www.youtube.com" },
  open_app: { label: "Open an app", placeholder: "Spotify" },
  play_youtube: { label: "Play on YouTube", placeholder: "lofi hip hop radio" },
  media: {
    label: "Press a media key",
    options: [["play_pause", "Play / pause"], ["next", "Next track"], ["previous", "Previous track"],
      ["volume_up", "Volume up"], ["volume_down", "Volume down"], ["mute", "Mute"]],
  },
  timer: { label: "Start a timer", placeholder: "25 minutes" },
  volume: { label: "Set the volume", placeholder: "30" },
  app_volume: { label: "Set an app's volume", placeholder: "browser 30" },
  brightness: { label: "Set the brightness", placeholder: "70" },
  displays: { label: "Turn screens on or off", placeholder: "only 2   (or: all, 1 off, 3 on)" },
  audio_output: { label: "Switch the speakers", placeholder: "headphones" },
  dark_mode: { label: "Dark mode", options: [["on", "On"], ["off", "Off"], ["toggle", "Switch it"]] },
  night_light: { label: "Night light", options: [["on", "On"], ["off", "Off"]] },
  lamp: { label: "Set a lamp", placeholder: "all | warm white 60%   (or: desk lamp | off)" },
  power_mode: { label: "Power mode", options: [["best_performance", "Best performance"], ["balanced", "Balanced"], ["efficiency", "Best power efficiency"]] },
  power: { label: "Sleep or lock", options: [["screens_off", "Screens off"], ["lock", "Lock the computer"], ["sleep", "Sleep"]] },
  keys: { label: "Press keys", placeholder: "win+d" },
  wait: { label: "Wait", placeholder: "2 seconds" },
  close_app: { label: "Close a program", placeholder: "Spotify" },
  focus_app: { label: "Switch to a program", placeholder: "Chrome" },
  window: { label: "Move a window", placeholder: "Chrome to 2 maximized" },
  mode: { label: "Switch mode", placeholder: "Movie   (or: normal)" },
  role: { label: "Act as", placeholder: "German teacher   (or: off)" },
  type: { label: "Type some text", placeholder: "Best regards, Sam" },
  run: { label: "Run a program", placeholder: "notepad.exe" },
};

/* Rows of actions ("what Abdoh does"), for commands and modes. A mode may have none. */
function actionRows(actions, canBeEmpty = false) {
  const rows = actions.length ? actions.map((a) => ({ ...a }))
    : canBeEmpty ? [] : [{ type: "say", value: "" }];
  const box = el("div", { class: "action-rows" });
  const draw = () => {
    box.replaceChildren(...rows.map((row, i) => {
      const type = el("select", { class: "input", "aria-label": "What Abdoh does" },
        Object.entries(ACTIONS).map(([value, spec]) => el("option", { value, selected: value === row.type }, spec.label)));
      type.addEventListener("change", () => {
        row.type = type.value;
        const options = (ACTIONS[row.type] || {}).options;
        row.value = options ? options[0][0] : "";
        draw();
      });
      const spec = ACTIONS[row.type] || ACTIONS.say;
      let value;
      if (spec.options) {
        value = el("select", { class: "input", "aria-label": "Which key" },
          spec.options.map(([v, label]) => el("option", { value: v, selected: v === row.value }, label)));
        value.addEventListener("change", () => { row.value = value.value; });
      } else {
        value = el("input", { class: "input", value: row.value || "", placeholder: spec.placeholder, "aria-label": spec.label });
        value.addEventListener("input", () => { row.value = value.value; });
      }
      const move = (by) => {
        const j = i + by;
        if (j < 0 || j >= rows.length) return;
        [rows[i], rows[j]] = [rows[j], rows[i]];
        draw();
      };
      const note = row.type === "run" && !App.settings.allow_run
        ? el("div", { class: "note" }, "Running programs is off. Turn on “Your commands may run programs” in Permissions.")
        : null;
      return el("div", {},
        el("div", { class: "action-row" }, type, value,
          el("div", { class: "moves" },
            el("button", { class: "icon-btn", title: "Move up", html: svg("up"), disabled: i === 0, onclick: () => move(-1) }),
            el("button", { class: "icon-btn", title: "Move down", html: svg("down"), disabled: i === rows.length - 1, onclick: () => move(1) }),
            el("button", { class: "icon-btn", title: "Remove", html: svg("x"), disabled: rows.length === 1 && !canBeEmpty, onclick: () => { rows.splice(i, 1); draw(); } }))),
        note);
    }));
  };
  draw();
  const addButton = el("button", { class: "btn small", onclick: () => { rows.push({ type: "say", value: "" }); draw(); } },
    el("span", { html: svg("plus") }), canBeEmpty ? "Add an action" : "Add another action");
  return { box: el("div", {}, box, el("div", { style: "margin-top:10px" }, addButton)), values: () => rows.map((r) => ({ ...r })) };
}

/* A settings row: title, help text, and a control on the right. */
function row(title, help, control) {
  return el("div", { class: "row" }, el("div", { class: "label" }, el("b", {}, title), help ? el("small", {}, help) : null), control);
}

function toggle(checked, onChange, label) {
  const input = el("input", { type: "checkbox", class: "switch", checked: !!checked, "aria-label": label || "On or off" });
  input.addEventListener("change", () => onChange(input.checked, input));
  return input;
}

/* Save some settings (shaped like config.yaml). Updates App.settings; returns true if saved. */
async function saveSettings(changes, quiet = false) {
  const result = await call("save_settings", changes);
  if (!result) return false;
  if (!result.ok) {
    toast(result.error, true);
    return false;
  }
  App.settings = result.settings;
  App.restart = result.restart || [];
  for (const page of Object.values(App.pages)) if (page.settingsChanged) page.settingsChanged();
  if (!quiet) toast("Saved");
  return true;
}

/* ---------- pages ---------- */

function registerPage(name, page) {
  App.pages[name] = page;
  const button = $(`.nav button[data-page="${name}"]`);
  if (button) button.hidden = false;
}

function showPage(name) {
  if (!$(`#page-${name}`)) name = "home";
  const previous = App.pages[App.current];
  if (App.current !== name && previous && previous.hide) previous.hide();
  App.current = name;
  $$(".page").forEach((p) => p.classList.toggle("active", p.id === `page-${name}`));
  $$(".nav button").forEach((b) => b.classList.toggle("active", b.dataset.page === name));
  store("abdoh.page", name);
  const page = App.pages[name];
  if (page && page.show) page.show();
}

/* ---------- theme ---------- */

function applyTheme(theme) {
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}

/* ---------- banner ---------- */

let bannerSource = null;

function showBanner(kind, text, source, action) {
  bannerSource = source;
  const banner = $("#banner");
  banner.dataset.kind = kind;
  $("#banner-text").textContent = text;
  const button = $("#banner-action");
  button.hidden = !action;
  if (action) {
    button.textContent = action.label;
    button.onclick = action.run;
  }
  banner.hidden = false;
}

function hideBanner(source) {
  if (source && source !== bannerSource) return;
  $("#banner").hidden = true;
  bannerSource = null;
}

/* ---------- status ---------- */

const STATUS = {
  "Listening": ["listening", "Listening", () => `Say “Hey Abdoh” or press ${hotkeyText(App.settings.hotkey)}`],
  "Paused": ["idle", "Paused", () => "Not listening for the wake word. The hotkey still works."],
  "Hotkey only": ["listening", "Hotkey only", () => `The wake word couldn't start. Press ${hotkeyText(App.settings.hotkey)} to talk.`],
  "Listening to you...": ["hearing", "Listening to you", () => "Go ahead, I'm listening"],
  "Thinking...": ["busy", "Thinking", () => "Working on it"],
  "Speaking": ["busy", "Speaking", () => "Press the stop button to interrupt"],
  "Starting...": ["idle", "Starting", () => "Loading the speech models, this takes a few seconds"],
};

function explainError(detail) {
  if (/microphone/i.test(detail)) {
    return "Abdoh can't use your microphone. Check that it's connected and not muted. Abdoh keeps trying.";
  }
  return `Voice input isn't working: ${detail}. You can still type requests.`;
}

function setStatus(status) {
  App.status = status;
  const error = status.startsWith("Error");
  const detail = error ? status.replace(/^Error:\s*/, "") : "";
  const [kind, label, hint] = error ? ["error", "Problem", () => detail] : STATUS[status] || ["idle", status, () => ""];
  $("#status").dataset.kind = kind;
  $("#status-text").textContent = label;
  $("#status-hint").textContent = hint();
  const busy = status === "Thinking..." || status === "Speaking";
  const talk = $("#talk");
  talk.dataset.state = status === "Listening to you..." ? "hearing" : busy ? "busy" : "idle";
  talk.title = busy ? "Stop" : `Talk to Abdoh (${hotkeyText(App.settings.hotkey)})`;
  $("#talk-mic").hidden = busy;
  $("#talk-stop").hidden = !busy;
  if (status === "Listening" || status === "Paused") $("#listen-toggle").checked = status === "Listening";
  showTyping(status === "Thinking...");
  if (error) showBanner("error", explainError(detail), "status");
  else hideBanner("status");
}

/* ---------- conversation ---------- */

const MAX_MESSAGES = 200;

function avatar() {
  return el("span", { class: "logo avatar", html: ICON.logo, "aria-hidden": "true" });
}

function addHistory(line) {
  const match = /^(You|Abdoh): ([\s\S]*)$/.exec(line);
  const who = match ? (match[1] === "You" ? "you" : "abdoh") : "note";
  const text = match ? match[2] : line;
  if (!text.trim()) return;
  $("#chat-empty").hidden = true;
  const message = el("div", { class: `msg ${who}` }, who === "abdoh" ? avatar() : null, el("div", { class: "bubble" }, text));
  const inner = $("#chat-inner");
  const typing = $("#typing");
  inner.insertBefore(message, typing || null);
  const messages = $$(".msg:not(#typing)", inner);
  if (messages.length > MAX_MESSAGES) messages[0].remove();
  scrollChat();
}

/* A new day: the conversation starts empty (only today's is kept). */
function clearHistory() {
  $$(".msg:not(#typing)", $("#chat-inner")).forEach((message) => message.remove());
  if (!$("#typing")) $("#chat-empty").hidden = false;
}

function showTyping(on) {
  const existing = $("#typing");
  if (on && !existing) {
    $("#chat-empty").hidden = true;
    const typing = el("div", { class: "msg abdoh typing", id: "typing" }, avatar(), el("div", { class: "bubble" }, el("i"), el("i"), el("i")));
    $("#chat-inner").append(typing);
    scrollChat();
  } else if (!on && existing) {
    existing.remove();
    if (!$$(".msg", $("#chat-inner")).length) $("#chat-empty").hidden = false;
  }
}

function scrollChat() {
  const chat = $("#chat");
  requestAnimationFrame(() => { chat.scrollTop = chat.scrollHeight; });
}

function renderHowToTalk() {
  const words = (App.settings.wake_words || []).filter((w) => w.split(" ").length > 1);
  const wake = words.length ? words.map((w) => `“${w.replace(/\b\w/g, (c) => c.toUpperCase())}”`) : ["“Hey Abdoh”"];
  const p = $("#how-to-talk");
  p.replaceChildren("Say ", el("b", {}, wake.slice(0, 2).join(" or ")), ", press ", ...kbds(App.settings.hotkey), ", or type below.");
  $("#composer-hint").textContent = App.settings.hotkey
    ? `Press ${hotkeyText(App.settings.hotkey)} anywhere to talk to Abdoh, or to stop a reply.`
    : "";
}

/* ---------- side bar ---------- */

function setClaude(text) { $("#side-claude").textContent = `Claude: ${text}`; }
function setWake(text) { $("#side-wake").textContent = `Wake word: ${text}`; }
function setVoice(on) { $("#voice-toggle").checked = !!on; }
// Why Abdoh can't hear you over its own voice ("" when it can).
function setHearing(why) { App.hearing = why || ""; }
// The mode that is on ("" for none): a chip on Home, and the Modes page marks it.
function setMode(name) {
  App.mode = name || "";
  const chip = $("#mode-chip");
  if (!chip) return;
  chip.hidden = !App.mode;
  $("#mode-chip-name").textContent = App.mode ? `${App.mode} mode` : "";
}

/* The board (Act as): a role's code, equations and steps as cards {id, text}, one per answer;
   the newest grows while Claude writes it (same id: replaced). null clears it. */
function addToBoard(card) {
  const board = App.board || [];
  if (card == null) App.board = [];
  else if (board.length && board[board.length - 1].id === card.id) App.board = [...board.slice(0, -1), card];
  else App.board = [...board, card].slice(-30);
  if (window.Roles) window.Roles.board(card);
}

function setRole(name) {
  App.role = name || "";
  const chip = $("#role-chip");
  if (!chip) return;
  chip.hidden = !App.role;
  $("#role-chip-name").textContent = App.role;
  $("#role-chip-name").title = App.role ? `Acting as ${App.role} (Act as)` : "";
}

/* ---------- events from Abdoh ---------- */

function setActivity(text) {
  if (App.status === "Thinking..." || App.status === "Speaking") $("#status-hint").textContent = `${text}…`;
}

const HANDLERS = {
  status: setStatus,
  activity: setActivity,
  history: addHistory,
  clear: clearHistory,
  claude: setClaude,
  wake: setWake,
  hearing: setHearing,
  mode: setMode,
  role: setRole,
  board: addToBoard,
  voice: setVoice,
  page: showPage,
};

function handleEvent([kind, value]) {
  const handler = HANDLERS[kind];
  if (handler) handler(value);
  for (const page of Object.values(App.pages)) if (page.event) page.event(kind, value);
}

async function poll() {
  try {
    const events = await App.api.events();
    (events || []).forEach(handleEvent);
  } catch (e) {
    console.error("events", e);
  }
  setTimeout(poll, 150);
}

/* ---------- what you do ---------- */

async function sendText(text) {
  text = text.trim();
  if (!text) return;
  await call("send", text);
}

function bindHome() {
  const prompt = $("#prompt");
  const send = $("#send");
  prompt.addEventListener("input", () => { send.disabled = !prompt.value.trim(); });
  prompt.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send.click();
    }
  });
  send.addEventListener("click", () => {
    const text = prompt.value;
    prompt.value = "";
    send.disabled = true;
    sendText(text);
    prompt.focus();
  });
  $$("#suggestions .chip").forEach((chip) => chip.addEventListener("click", () => sendText(chip.textContent)));
  $("#talk").addEventListener("click", () => {
    const busy = App.status === "Thinking..." || App.status === "Speaking";
    call(busy ? "stop_speaking" : "talk");
  });
  $("#listen-toggle").addEventListener("change", (e) => call("set_paused", !e.target.checked));
  $("#voice-toggle").addEventListener("change", (e) => call("set_voice", e.target.checked));
  $("#banner-close").addEventListener("click", () => hideBanner());
  $$(".nav button").forEach((b) => b.addEventListener("click", () => showPage(b.dataset.page)));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && (App.status === "Thinking..." || App.status === "Speaking")) call("stop_speaking");
  });
}

/* ---------- updates ---------- */

function showUpdate(update) {
  showBanner("info", `Abdoh ${update.version} is out (you have ${update.current}).`, "update",
    { label: "Download", run: () => call("open_link", update.download || update.url) });
}

async function checkUpdate(force = false) {
  const update = await call("check_update", force);
  if (update && update.available) showUpdate(update);
  return update;
}

/* ---------- a microphone that's turned down ---------- */

async function checkMicVolume() {
  /* A muted or quiet microphone is the usual reason Abdoh mishears: offer to fix it. */
  const mic = await call("mic_volume");
  if (!mic || !mic.ok || !(mic.muted || mic.volume < 50)) return hideBanner("mic");
  const text = mic.muted ? "Your microphone is muted in Windows, so Abdoh can't hear you."
    : `Your microphone is turned down in Windows (${mic.volume}%), so Abdoh may mishear you.`;
  showBanner("warn", text, "mic", { label: "Turn it up", run: async () => {
    const fixed = await call("fix_mic_volume");
    if (fixed && fixed.ok) { hideBanner("mic"); toast("Microphone turned up."); }
    else if (fixed) toast(fixed.error, true);
  } });
}

/* ---------- start ---------- */

async function start() {
  App.api = await Bridge.ready;
  const boot = (await call("boot")) || {};
  App.settings = boot.settings || {};
  App.restart = boot.restart || [];
  App.version = boot.version || "";
  App.demo = !!boot.demo;
  $("#version").textContent = App.version ? `Abdoh ${App.version}` : "";
  const params = new URLSearchParams(location.search);
  applyTheme(params.get("theme") || store("abdoh.theme"));
  const state = boot.state || {};
  (state.history || []).forEach(addHistory);
  if (state.claude) setClaude(state.claude);
  if (state.wake) setWake(state.wake);
  setHearing(state.hearing);
  setMode(state.mode);
  setRole(state.role);
  App.board = state.board || [];
  setVoice(state.voice !== false);
  setStatus(state.status || "Starting...");
  renderHowToTalk();
  bindHome();
  for (const page of Object.values(App.pages)) if (page.boot) page.boot(boot);
  showPage(params.get("page") || store("abdoh.page") || "home");
  poll();
  setTimeout(() => checkUpdate(false), 5000);
  setTimeout(() => { if ($("#banner").hidden) checkMicVolume(); }, 2500);
}

window.addEventListener("DOMContentLoaded", start);
