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

/* ---------- pages ---------- */

function registerPage(name, page) {
  App.pages[name] = page;
  const button = $(`.nav button[data-page="${name}"]`);
  if (button) button.hidden = false;
}

function showPage(name) {
  if (!$(`#page-${name}`)) name = "home";
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

/* ---------- events from Abdoh ---------- */

const HANDLERS = {
  status: setStatus,
  history: addHistory,
  claude: setClaude,
  wake: setWake,
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

/* ---------- start ---------- */

async function start() {
  App.api = await Bridge.ready;
  const boot = (await call("boot")) || {};
  App.settings = boot.settings || {};
  App.version = boot.version || "";
  App.demo = !!boot.demo;
  $("#version").textContent = App.version ? `Abdoh ${App.version}` : "";
  const params = new URLSearchParams(location.search);
  applyTheme(params.get("theme") || store("abdoh.theme"));
  const state = boot.state || {};
  (state.history || []).forEach(addHistory);
  if (state.claude) setClaude(state.claude);
  if (state.wake) setWake(state.wake);
  setVoice(state.voice !== false);
  setStatus(state.status || "Starting...");
  renderHowToTalk();
  bindHome();
  for (const page of Object.values(App.pages)) if (page.boot) page.boot(boot);
  showPage(params.get("page") || store("abdoh.page") || "home");
  poll();
}

window.addEventListener("DOMContentLoaded", start);
