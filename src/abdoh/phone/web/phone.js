/* Abdoh on your phone (ABDOH_EPIC_10.md, 3.5): pair once, then the conversation with Abdoh on
   your computer. It asks for new events and waits for them (long polling, /api/events), so it
   copes with a flaky mobile network and never misses one. ?demo shows it with made-up data. */
"use strict";

const KEY = "abdoh.key";
const SPEAK = "abdoh.speak";
const params = new URLSearchParams(location.search);
const DEMO = params.has("demo");
const WAIT_MS = 35000; // the computer answers within 25 s, even with nothing new
const RETRY_MS = [1000, 2000, 4000, 8000];
const MAX_MESSAGES = 300;
const LINE = /^(You|You \(phone\)|Abdoh): ([\s\S]*)$/;
const SHARE_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V3M7 8l5-5 5 5"/><path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/></svg>';

const S = {
  key: null, me: "", boot: "", seq: 0, online: null, polling: false, retry: 0, wake: null,
  status: "", activity: "", busy: false, ai: "Claude",
  live: null, // the bubble a reply to this phone is growing in, sentence by sentence
  final: true, // the reply to the last request is shown in full
  pending: [], // what this phone sent, until the computer shows it: [{node, text}]
  attached: null, // a file for the next message: {name, size, id (once on the computer), progress, failed, xhr}
  speak: localStorage.getItem(SPEAK) !== "0",
  steps: null, // the steps of the request being answered: {node, box, title, list, count, done}
  asked: 0, answered: 0, // this phone's requests that reached the computer, and those answered
  cut: 0, // replies to the requests up to this one aren't said (stopped, or the call ended)
};

const $ = (selector) => document.querySelector(selector);

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (name === "html") node.innerHTML = value; // only the page's own icons
    else if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else node.setAttribute(name, value === true ? "" : value);
  }
  node.append(...children.flat().filter((c) => c !== null && c !== undefined && c !== false));
  return node;
}

/* ---------- talking to Abdoh on your computer ---------- */

class Unpaired extends Error {}

async function api(method, path, body, { timeout = 20000 } = {}) {
  if (DEMO) return window.AbdohDemo.api(method, path, body);
  const headers = {};
  if (S.key) headers.Authorization = `Bearer ${S.key}`;
  let payload;
  if (body instanceof Blob || body instanceof ArrayBuffer) payload = body;
  else if (body !== undefined) {
    payload = JSON.stringify(body);
    headers["Content-Type"] = "application/json";
  }
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), timeout);
  let response;
  try {
    response = await fetch(path, { method, headers, body: payload, cache: "no-store", signal: abort.signal });
  } finally {
    clearTimeout(timer);
  }
  if (response.status === 401 && path !== "/api/pair") throw new Unpaired();
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || `Your computer answered ${response.status}.`);
    error.shown = true; // a message for people
    error.status = response.status;
    throw error;
  }
  return data;
}

/* ---------- starting: pairing, or the conversation ---------- */

function pairCode() { return new URLSearchParams(location.hash.slice(1)).get("pair") || ""; }
function forgetCode() { history.replaceState(null, "", location.pathname + location.search); }
function standalone() { return navigator.standalone === true || matchMedia("(display-mode: standalone)").matches; }
function iPhone() { return /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1); }

/* In Safari on an iPhone, the key must be made inside the Home Screen app (it keeps its own
   storage): first say how to add it there. The link keeps its code for the app. */
function needsInstall() {
  if (DEMO) return params.get("demo") === "install";
  return iPhone() && !standalone() && !params.has("browser");
}

function deviceName() {
  const agent = navigator.userAgent;
  if (/iPad/.test(agent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)) return "iPad";
  if (/iPhone/.test(agent)) return "iPhone";
  if (/Android/.test(agent)) return "Android phone";
  return "Phone";
}

async function start() {
  if (DEMO) {
    await loadScript("demo.js");
    if (params.get("theme")) document.documentElement.dataset.theme = params.get("theme");
  }
  fitToScreen();
  S.key = DEMO ? window.AbdohDemo.key() : localStorage.getItem(KEY);
  const code = pairCode() || (DEMO && params.get("demo") === "install" ? "K7MX-2Q9P" : "");
  if (S.key) {
    if (code) forgetCode();
    return openApp();
  }
  if (code && needsInstall()) return installScreen(code);
  if (code) return pair(code);
  pairScreen();
}

function loadScript(src) {
  return new Promise((resolve) => document.head.append(el("script", { src, onload: resolve, onerror: resolve })));
}

async function pair(code) {
  try {
    const data = await api("POST", "/api/pair", { code, name: deviceName() });
    S.key = data.key;
    if (!DEMO) localStorage.setItem(KEY, data.key);
    forgetCode();
    openApp();
  } catch (error) {
    pairScreen(error.shown ? error.message : "Can't reach your computer. Is Tailscale on, here and on the computer?");
  }
}

function screen(title, ...body) {
  $("#app").hidden = true;
  $("#screen").hidden = false;
  $("#screen-title").textContent = title;
  $("#screen-body").replaceChildren(...body.flat().filter(Boolean));
}

function pairScreen(error = "") {
  const input = el("input", { class: "code-input", placeholder: "K7MX-2Q9P", autocapitalize: "characters", autocomplete: "off",
    autocorrect: "off", spellcheck: "false", maxlength: 12, "aria-label": "Pairing code" });
  const button = el("button", { class: "wide" }, "Pair");
  const go = () => {
    const code = input.value.trim();
    if (!code) return input.focus();
    button.disabled = true;
    button.textContent = "Pairing…";
    pair(code);
  };
  button.addEventListener("click", go);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  screen("Pair this phone",
    el("p", {}, "On your computer, open Abdoh, then Settings → Phone → Pair a phone. Scan the code with this phone's camera, or type the code shown there:"),
    input, error ? el("p", { class: "error", role: "alert" }, error) : null, button);
}

function installScreen(code) {
  screen("Add Abdoh to your Home Screen",
    el("p", {}, "Then it opens like an app, and stays paired with your computer."),
    el("ol", { class: "steps" },
      el("li", {}, el("span", { class: "n" }, "1"), el("span", { html: `Tap ${SHARE_ICON} <b>Share</b> in Safari.` })),
      el("li", {}, el("span", { class: "n" }, "2"), el("span", { html: "Tap <b>Add to Home Screen</b>, then <b>Add</b>." })),
      el("li", {}, el("span", { class: "n" }, "3"), el("span", { html: "Open <b>Abdoh</b> from your Home Screen." }))),
    el("button", { class: "link", onclick: () => pair(code) }, "Use it in Safari instead"));
}

function unpaired(message = "This phone isn't paired any more. Pair it again to use Abdoh.") {
  S.key = null;
  if (!DEMO) localStorage.removeItem(KEY);
  pairScreen(message);
}

/* ---------- the conversation ---------- */

async function openApp() {
  $("#screen").hidden = true;
  $("#app").hidden = false;
  $("#where").textContent = DEMO ? "laptop.tail1234.ts.net" : location.host;
  try {
    await load();
  } catch (error) {
    if (error instanceof Unpaired) return unpaired();
    online(false);
  }
  poll();
  if ("serviceWorker" in navigator && !DEMO && location.protocol === "https:") {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
}

/* Everything as it is now: today's conversation, the status, the AI, the mode. */
async function load() {
  const state = await api("GET", "/api/state");
  S.boot = state.boot;
  S.seq = state.seq;
  S.me = state.phone_id || "";
  S.live = null;
  S.final = true;
  S.pending = [];
  S.steps = null;
  S.answered = S.asked; // what was being answered is over (or Abdoh restarted)
  $("#messages").replaceChildren();
  // Pictures and files sent to this phone, each where it fell in the conversation ("line":
  // how many lines came before it today; the first line shown is number first_line).
  const media = (state.media || []).filter((m) => m.for === S.me || m.type === "board");
  board.cards = state.board || [];
  board.seen = new Set(board.cards.map((c) => c.id));
  App.boardPictures = state.pictures || {};
  if (board.typist && board.cards.length) board.typist.set(board.cards[board.cards.length - 1], false);
  const first = state.first_line || 0;
  let next = 0;
  (state.history || []).forEach((line, i) => {
    for (; next < media.length && media[next].line <= first + i; next += 1) {
      if (media[next].line >= first) addMedia(media[next]);
    }
    addLine(line);
  });
  media.slice(next).forEach((m) => addMedia(m));
  setAi(state.ai || {});
  setMode(state.mode || "");
  S.status = state.status || "";
  online(true);
  scrollDown(true);
  turnOver();
}

async function poll() {
  if (S.polling) return;
  S.polling = true;
  while (S.key) {
    try {
      if (!S.boot) await load();
      const data = await api("GET", `/api/events?after=${S.seq}`, undefined, { timeout: WAIT_MS });
      online(true);
      S.retry = 0;
      if (data.reset || data.boot !== S.boot) {  // missed some, or Abdoh restarted
        await load();
        continue;
      }
      for (const event of data.events || []) {
        S.seq = Math.max(S.seq, event.seq);
        take(event);
      }
    } catch (error) {
      if (error instanceof Unpaired) { unpaired(); break; }
      online(false);
      await rest(RETRY_MS[Math.min(S.retry++, RETRY_MS.length - 1)]);
    }
  }
  S.polling = false;
}

/* Wait a little before trying again; coming back to the app tries at once. */
function rest(ms) {
  return new Promise((resolve) => {
    S.wake = resolve;
    setTimeout(resolve, ms);
  });
}

function take(event) {
  switch (event.type) {
    case "history": addLine(event.line, true); break;
    case "clear": $("#messages").replaceChildren(); S.live = null; S.steps = null; updateEmpty(); break;
    case "status": S.status = event.text || ""; S.activity = ""; render(); break;
    case "activity":
    case "aside": S.activity = event.text || ""; render(); break;
    case "ai": setAi(event); break;
    case "mode": setMode(event.name || ""); break;
    case "say": addSaid(event); break;
    case "question": askQuestion(event.text || ""); break;
    case "done": if (event.for === S.me) { S.answered += 1; stepsDone(); turnOver(); } break;
    case "step": if (event.for === S.me) addStep(event.text || ""); break;
    case "note": if (event.for === S.me) { note(event.text || ""); scrollDown(); if (board.pdf && /PDF/.test(event.text || "")) board.pdf = false; } break;
    case "image":
    case "file": if (event.for === S.me) { addMedia(event); scrollDown(true); boardPdfCame(event); } break;
    case "board": takeBoard(event.card || null); break;
    case "codoh": takeCodoh(event); break;
    case "setting": if (prefs.open) showSettings(); break;
    case "live": if (event.for === S.me) openLive(event.screen || "follow"); break;
    case "board_picture": takePicture(event.picture || {}); break;
    default: break;
  }
}

/* ---------- the computer's screen, live (story 155) ----------
   Frames come when something changes on that screen (about 5 a second at most), asked for one
   after the other like the conversation's events. "Follow" is the screen of the window you're
   working in; a chip picks one screen. On a call, the call becomes a bar on top: it goes on
   (listening, answering), and the bar brings the call back, mutes or ends it. */

const live = { open: false, which: "follow", id: 0, url: "", turn: 0, frames: [], quiet: 0, label: "" };

async function openLive(which = "follow") {
  $("#controls").hidden = true;
  $("#viewer").hidden = true;
  live.open = true;
  live.which = String(which || "follow");
  live.id = 0;
  live.frames = [];
  $("#live").hidden = false;
  $("#live-wait").hidden = false;
  $("#live-wait").textContent = "Connecting to your screen…";
  $("#live").classList.remove("bare");
  dockCall();
  showScreens();
  liveLoop(++live.turn);
}

function closeLive() {
  live.open = false;
  live.turn += 1;
  $("#live").hidden = true;
  if (live.url) URL.revokeObjectURL(live.url);
  live.url = "";
  $("#live-img").removeAttribute("src");
  dockCall();
}

async function showScreens() {
  const box = $("#live-screens");
  let screens = [];
  try {
    screens = (await api("GET", "/api/live/screens")).screens || [];
  } catch (error) {
    if (error instanceof Unpaired) return unpaired();
  }
  const chip = (id, label) => el("button", { class: `chip${live.which === id ? " on" : ""}`, type: "button",
    onclick: () => { if (live.which !== id) { live.which = id; live.id = 0; showScreens(); liveLoop(++live.turn); } } }, label);
  box.replaceChildren(chip("follow", "Follow"), ...screens.map((s) => chip(s.id, s.label.replace(/^Screen (\d+) · /, "$1 · "))));
}

async function liveLoop(turn) {
  if (DEMO) return demoLive(turn);
  while (live.open && turn === live.turn) {
    let response;
    try {
      const abort = new AbortController();
      const timer = setTimeout(() => abort.abort(), 12000);
      response = await fetch(`/api/live?screen=${encodeURIComponent(live.which)}&after=${live.id}`, {
        headers: { Authorization: `Bearer ${S.key}` }, cache: "no-store", signal: abort.signal });
      clearTimeout(timer);
    } catch (error) {
      if (turn !== live.turn) return;
      $("#live-state").textContent = "Can't reach your computer · trying again…";
      await new Promise((r) => setTimeout(r, 1500));
      continue;
    }
    if (turn !== live.turn) return;
    if (response.status === 401) return unpaired();
    if (response.status === 204) { // nothing changed on the screen
      live.quiet += 1;
      showLiveState();
      continue;
    }
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      $("#live-wait").hidden = false;
      $("#live-wait").textContent = data.error || "The screen can't be shown right now.";
      await new Promise((r) => setTimeout(r, 3000));
      continue;
    }
    const blob = await response.blob();
    if (turn !== live.turn) return;
    const url = URL.createObjectURL(blob);
    $("#live-img").src = url;
    if (live.url) URL.revokeObjectURL(live.url);
    live.url = url;
    live.id = Number(response.headers.get("X-Frame")) || live.id + 1;
    live.label = decodeURIComponent(response.headers.get("X-Screen") || "");
    live.frames.push(Date.now());
    live.quiet = 0;
    $("#live-wait").hidden = true;
    showLiveState();
  }
}

function showLiveState() {
  const now = Date.now();
  live.frames = live.frames.filter((t) => now - t < 3000);
  $("#live-title").textContent = live.label || "Your screen";
  const fps = Math.round(live.frames.length / 3);
  $("#live-state").textContent = !live.frames.length ? "Up to date: nothing is moving on this screen"
    : fps < 1 ? "Up to date" : `${fps} frame${fps === 1 ? "" : "s"} a second`;
}

/* Picture: this screen now, into the conversation (to keep). */
async function livePicture() {
  try {
    await api("POST", "/api/screen", { screen: live.which });
    toast("The picture is in the conversation");
  } catch (error) {
    toast(error.shown ? error.message : "Can't reach your computer right now.");
  }
}

/* The demo: a made-up screen, still. */
function demoLive(turn) {
  $("#live-img").src = window.AbdohDemo.picture();
  live.label = live.which === "follow" ? "Screen 1 · Laptop screen" : `Screen ${live.which} · HP 32f`;
  $("#live-wait").hidden = true;
  live.frames = [Date.now(), Date.now(), Date.now(), Date.now(), Date.now(), Date.now(), Date.now(), Date.now(), Date.now(), Date.now(), Date.now(), Date.now()];
  showLiveState();
}

/* A call while the screen is live, the board is up or Codoh is open: the call is a bar on top
   (it goes on), and comes back when they close (or with a tap on the bar). */
function dockCall() {
  const docked = call.on && (live.open || board.open || codoh.open || prefs.open);
  $("#call").classList.toggle("docked", docked);
  $("#call-bar").hidden = !docked;
  document.body.classList.toggle("call-docked", docked);
}

/* The bar's tap: back to the call (what's up over it closes). */
function backToCall() {
  if (live.open) closeLive();
  if (board.open) closeBoard();
  if (codoh.open) closeCodoh();
  if (prefs.open) closeSettings();
}

/* ---------- pictures and files from the computer (stories 148, 149) ----------
   Behind secret links (/media/<id>, an hour): an <img> and the phone's own viewer can't send
   the phone's key. */

function mediaSrc(event) {
  return event.src || `/media/${event.id}`; // the demo draws its own
}

function addMedia(event) {
  if (event.type === "file") return place(fileCard(event), "msg abdoh media");
  if (event.type === "board") return boardChip(event.id);
  const src = mediaSrc(event);
  const figure = el("figure", { class: "shot", onclick: () => openViewer(src, event.caption || "") });
  const img = el("img", { src, alt: event.caption || "The computer's screen", loading: "lazy" });
  img.addEventListener("error", () => figure.replaceChildren(el("span", { class: "gone" }, "This picture has expired.")));
  img.addEventListener("load", () => scrollDown()); // its height is known now
  figure.append(img);
  if (event.caption) figure.append(el("figcaption", {}, event.caption));
  return place(figure, "msg abdoh media");
}

/* A file card: its name, size and kind; Open (the phone's own viewer) and Download. */
function fileCard(event) {
  const src = mediaSrc(event);
  return el("div", { class: "file" },
    el("span", { class: `file-icon ${event.kind || "file"}`, "aria-hidden": "true" }, fileLabel(event)),
    el("div", { class: "file-main" },
      el("span", { class: "file-about" }, el("b", {}, event.name || "A file"), el("small", {}, size(event.size))),
      el("div", { class: "file-buttons" },
        el("a", { class: "file-button", href: src, target: "_blank", rel: "noopener" }, "Open"),
        el("button", { class: "file-button primary", type: "button", onclick: (e) => saveToPhone(event, e.currentTarget) }, "Save to phone"))));
}

/* Save to phone: the file comes to the phone first, then the phone's share sheet opens with it
   (Save to Files, Photos, or an app). The share sheet needs a fresh tap: when getting a big
   file took too long, the button says to tap again. Without a share sheet: a download. */
async function saveToPhone(event, button) {
  const src = mediaSrc(event);
  const link = `${src}${src.includes("?") ? "&" : "?"}download=1`;
  const download = (href) => {
    const a = el("a", { href, download: event.name || "file" });
    document.body.append(a);
    a.click();
    a.remove();
  };
  if (DEMO) return toast("The phone's share sheet opens here: Save to Files");
  if (!navigator.canShare || !window.File) return download(link);
  if (!button.file) {
    button.disabled = true;
    button.textContent = "Getting it…";
    try {
      const response = await fetch(link, { cache: "no-store" });
      if (!response.ok) throw new Error("gone");
      const blob = await response.blob();
      button.file = new File([blob], event.name || "file", { type: blob.type || "application/octet-stream" });
    } catch (error) {
      toast("The file couldn't come: its link may have expired (an hour).");
      button.disabled = false;
      button.textContent = "Save to phone";
      return;
    }
    button.disabled = false;
  }
  if (!navigator.canShare({ files: [button.file] })) return download(URL.createObjectURL(button.file));
  try {
    await navigator.share({ files: [button.file] });
    button.textContent = "Save to phone";
  } catch (error) {
    if (error && error.name === "NotAllowedError") { // getting it took the tap's moment
      button.textContent = "Tap to save";
      toast("It's here: tap Tap to save");
    } else button.textContent = "Save to phone";
  }
}

function fileLabel(event) {
  const dot = String(event.name || "").lastIndexOf(".");
  return dot > 0 ? String(event.name).slice(dot + 1, dot + 5).toUpperCase() : "FILE";
}

function size(bytes) {
  const n = Number(bytes) || 0;
  if (n < 1024) return `${n} bytes`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 / 1024).toFixed(n < 10 * 1024 * 1024 ? 1 : 0)} MB`;
  return `${(n / 1024 ** 3).toFixed(1)} GB`;
}

function openViewer(src, caption) {
  $("#viewer-img").src = src;
  $("#viewer-caption").textContent = caption;
  $("#viewer-open").href = src;
  $("#viewer-open").hidden = src.startsWith("data:");
  $("#viewer").hidden = false;
}

function closeViewer() {
  $("#viewer").hidden = true;
  $("#viewer-img").removeAttribute("src");
}

/* ---------- Codoh, the coding page, from the phone (story 151) ----------
   The same chats as the window's Codoh page: a chat's messages, tool cards and questions live
   (asked again every 0.8 s while it works), instructions for it (queued while it works),
   Stop, Allow / Always / Deny, answers to its questions, and a new chat in one of its folders. */

const codoh = { open: false, chatId: "", rev: 0, nodes: new Map(), timer: null, running: false, folders: [], asking: 0 };
const CODOH_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 7l-5 5 5 5M16 7l5 5-5 5M13.5 4l-3 16"/></svg>';
const DID = { read: "Read", search: "Searched", list: "Looked in", edit: "Edited", write: "Wrote", command: "Ran",
  web: "Looked up", task: "Worked on", todo: "Planned", other: "Used" };
const DOING_NOW = { read: "Reading", search: "Searching", list: "Looking in", edit: "Editing", write: "Writing",
  command: "Running", web: "Looking up", task: "Working on", todo: "Planning", other: "Using" };
const ASKS = { edit: "change", write: "write", command: "run", web: "look up", read: "read", other: "use" };

function openCodoh(chat = "") {
  $("#menu").hidden = true;
  codoh.open = true;
  $("#codoh-view").hidden = false;
  dockCall();
  if (chat) showChat(chat);
  else showChats();
}

function closeCodoh() {
  codoh.open = false;
  clearTimeout(codoh.timer);
  $("#codoh-view").hidden = true;
  dockCall();
}

function codohSay(text) {
  $("#codoh-body").replaceChildren(el("p", { class: "board-empty" }, text));
}

async function showChats() {
  clearTimeout(codoh.timer);
  codoh.chatId = "";
  const asking = ++codoh.asking;
  $("#codoh-title").textContent = "Codoh";
  $("#codoh-status").textContent = "Your coding chats on the computer";
  $("#codoh-back").hidden = true;
  $("#codoh-composer").hidden = true;
  if (!$("#codoh-body").children.length) codohSay("…");
  let data;
  try {
    data = await api("GET", "/api/codoh");
  } catch (error) {
    if (error instanceof Unpaired) return unpaired();
    return codohSay(error.shown ? error.message : "Can't reach your computer right now.");
  }
  if (!codoh.open || codoh.chatId || asking !== codoh.asking) return;
  codoh.folders = data.folders || [];
  $("#codoh-body").replaceChildren(...[
    data.limited ? el("p", { class: "cx-note" }, `Claude's limit is used up ${data.limited}.`) : null,
    el("button", { class: "codoh-new", type: "button", onclick: newChat }, "+ New chat"),
    ...((data.chats || []).length ? data.chats.map(chatRow) : [el("p", { class: "board-empty" }, "No chats yet: start one in a folder Codoh knows.")]),
  ].filter(Boolean));
  if ((data.chats || []).some((c) => c.running)) codoh.timer = setTimeout(() => { if (codoh.open && !codoh.chatId) showChats(); }, 4000);
}

function chatRow(chat) {
  const engine = chat.engine === "chatgpt" ? "ChatGPT" : "Claude";
  return el("button", { class: "codoh-chat", type: "button", onclick: () => showChat(chat.id) },
    el("i", { class: `codoh-dot${chat.running ? " on" : ""}` }),
    el("span", {}, el("b", {}, chat.title || "New chat"),
      el("small", {}, [chat.where, chat.model ? `${engine} ${chat.model}` : engine, ago(chat.updated)].filter(Boolean).join(" · "))));
}

function ago(seconds) {
  const s = Math.max(0, Date.now() / 1000 - (Number(seconds) || 0));
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

/* A new chat: one of Codoh's folders, and what it should do. */
function newChat() {
  clearTimeout(codoh.timer);
  codoh.asking += 1; // a list refresh on its way doesn't replace the form
  $("#codoh-title").textContent = "New chat";
  $("#codoh-status").textContent = "In which folder?";
  $("#codoh-back").hidden = false;
  if (!codoh.folders.length) return codohSay("Codoh doesn't know any folders yet: open one on its page on the computer, or ask Abdoh (“open my portfolio folder in Codoh”).");
  let picked = codoh.folders[0].path;
  const chips = codoh.folders.map((f) => el("button", { class: `chip${f.path === picked ? " on" : ""}`, type: "button", title: f.path,
    onclick: (e) => { picked = f.path; chips.forEach((c) => c.classList.remove("on")); e.currentTarget.classList.add("on"); } }, f.name || f.path));
  const words = el("textarea", { class: "clip-text", rows: 4, placeholder: "What should Codoh do?", "aria-label": "What should Codoh do?" });
  const start = el("button", { class: "sheet-button primary", type: "button" }, "Start");
  start.addEventListener("click", async () => {
    start.disabled = true;
    try {
      const data = await api("POST", "/api/codoh/new", { folder: picked, text: words.value });
      if (data.ok) return showChat(data.chat);
      toast(data.error || "Codoh couldn't start that chat.");
    } catch (error) {
      failed(error);
    }
    start.disabled = false;
  });
  $("#codoh-body").replaceChildren(el("div", { class: "codoh-form" }, el("div", { class: "chips" }, chips), words, start));
}

async function showChat(id) {
  clearTimeout(codoh.timer);
  Object.assign(codoh, { chatId: id, rev: 0, nodes: new Map(), running: false });
  $("#codoh-back").hidden = false;
  $("#codoh-composer").hidden = false;
  $("#codoh-status").textContent = "";
  codohSay("…");
  await pollChat();
}

async function pollChat() {
  clearTimeout(codoh.timer);
  const id = codoh.chatId;
  if (!codoh.open || !id) return;
  const asking = ++codoh.asking; // only the newest ask goes on (one loop, never two)
  let data;
  try {
    data = await api("GET", `/api/codoh/chat?id=${encodeURIComponent(id)}&since=${codoh.rev}`);
  } catch (error) {
    if (error instanceof Unpaired) return unpaired();
    if (asking === codoh.asking) codoh.timer = setTimeout(pollChat, 4000);
    return;
  }
  if (asking !== codoh.asking || id !== codoh.chatId || !codoh.open) return;
  if (!data.ok) return codohSay(data.error || "That chat is gone.");
  const body = $("#codoh-body");
  const near = body.scrollHeight - body.scrollTop - body.clientHeight < 200 || codoh.rev === 0;
  if (codoh.rev === 0) body.replaceChildren();
  for (const item of data.items || []) putItem(item);
  codoh.rev = data.rev;
  codoh.running = !!data.running;
  $("#codoh-title").textContent = (data.chat || {}).title || "New chat";
  $("#codoh-status").textContent = data.running ? `${data.status || "Working"} · ${Math.round(data.seconds || 0)} s` : "Ready";
  $("#codoh-stop").hidden = !data.running;
  const queued = data.queued || [];
  $("#codoh-queued").hidden = !queued.length;
  $("#codoh-queued").textContent = queued.length ? `Next: ${queued.join(" · ")}` : "";
  if (near && (data.items || []).length) requestAnimationFrame(() => { body.scrollTop = body.scrollHeight; });
  codoh.timer = setTimeout(pollChat, data.running ? 800 : 3000);
}

function putItem(item) {
  const node = codohItem(item);
  const old = codoh.nodes.get(item.id);
  if (old) {
    if (old.open) node.open = true; // a card you opened stays open
    old.replaceWith(node);
  } else $("#codoh-body").append(node);
  codoh.nodes.set(item.id, node);
}

function codohItem(item) {
  switch (item.kind) {
    case "user": return el("div", { class: "msg you" }, el("div", { class: "bubble" }, el("span", { class: "text" }, item.text || "")));
    case "assistant": return el("div", { class: "cx-answer" }, codeText(item.text || ""));
    case "tool": return toolCard(item);
    case "approval": return askCard(item);
    case "error": return el("p", { class: "cx-error" }, item.text || "Something went wrong.");
    case "done": return el("p", { class: "cx-note" }, `Done in ${Math.round(item.seconds || 0)} s`);
    default: return el("p", { class: "cx-note" }, item.text || "");
  }
}

/* An answer: its words, and its code blocks as code. */
function codeText(text) {
  return text.split(/(```[^\n]*\n[\s\S]*?(?:```|$))/).filter(Boolean).map((part) => {
    const code = /^```[^\n]*\n([\s\S]*?)(?:```)?$/.exec(part);
    return code ? el("pre", { class: "cx-code" }, code[1]) : el("p", {}, part.trim());
  });
}

function diffView(diff) {
  return el("pre", { class: "cx-diff" }, diff.split("\n").map((line) => el("span", {
    class: line.startsWith("+") && !line.startsWith("+++") ? "add" : line.startsWith("-") && !line.startsWith("---") ? "del" : line.startsWith("@@") ? "hunk" : "",
  }, `${line}\n`)));
}

function toolCard(item) {
  const kind = item.kind_of || "other";
  const busy = !item.status || item.status === "waiting";
  const badge = item.status === "failed" ? "Failed" : item.status === "stopped" ? "Stopped" : busy ? "…" : "";
  const card = el("details", { class: `cx-tool ${item.status || "running"}` },
    el("summary", {}, el("span", { class: "cx-verb" }, busy ? DOING_NOW[kind] || "Using" : DID[kind] || "Used"),
      el("code", {}, item.title || ""), item.detail ? el("small", {}, item.detail) : null,
      badge ? el("em", {}, badge) : null));
  if (item.diff) card.append(diffView(item.diff));
  if (item.output) card.append(el("pre", { class: "cx-code" }, item.output));
  if (!item.diff && !item.output) card.append(el("p", { class: "cx-note" }, busy ? "Working on it…" : "Nothing more to show."));
  return card;
}

/* Codoh asks first (to run, change or write something), or asks the user a question. */
function askCard(item) {
  const waiting = item.state === "waiting";
  const box = el("div", { class: `cx-ask${waiting ? " waiting" : ""}` });
  if ((item.questions || []).length) return questionCard(item, box, waiting);
  box.append(el("b", {}, `Codoh asks to ${ASKS[item.kind_of] || "use"}:`), el("code", { class: "cx-ask-what" }, item.title || item.tool || ""));
  if (item.description) box.append(el("p", {}, item.description));
  if (item.diff) box.append(diffView(item.diff));
  else if (item.detail) box.append(el("p", { class: "cx-note" }, item.detail));
  if (!waiting) {
    box.append(el("p", { class: "cx-state" }, { allowed: "Allowed", always: "Allowed for this chat", denied: "Said no", expired: "Not needed any more" }[item.state] || item.state));
    return box;
  }
  const answer = (decision) => async (e) => {
    box.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    try {
      const data = await api("POST", "/api/codoh/answer", { id: codoh.chatId, item: item.id, decision });
      if (!data.ok) toast(data.error || "That was already answered.");
    } catch (error) { failed(error); }
    pollChat();
  };
  box.append(el("div", { class: "cx-ask-buttons" },
    el("button", { class: "pill primary", type: "button", onclick: answer("allow") }, "Allow"),
    item.suggestions ? el("button", { class: "pill", type: "button", onclick: answer("always") }, "Always") : null,
    el("button", { class: "pill", type: "button", onclick: answer("deny") }, "Deny")));
  return box;
}

function questionCard(item, box, waiting) {
  const picked = new Map(item.questions.map((q) => [q.question, new Set()]));
  const own = new Map();
  box.append(el("b", {}, "Codoh asks you:"));
  for (const q of item.questions) {
    const block = el("div", { class: "cx-q" }, el("p", {}, q.question));
    if (!waiting) {
      block.append(el("p", { class: "cx-state" }, (item.answers || {})[q.question] || "No answer"));
      box.append(block);
      continue;
    }
    const options = q.options.map((o) => el("button", { class: "chip", type: "button", title: o.about || "",
      onclick: (e) => {
        const set = picked.get(q.question);
        if (!q.multi) { set.clear(); options.forEach((b) => b.classList.remove("on")); }
        if (set.has(o.label)) { set.delete(o.label); e.currentTarget.classList.remove("on"); }
        else { set.add(o.label); e.currentTarget.classList.add("on"); }
      } }, o.label));
    const words = el("input", { class: "code-input cx-own", placeholder: "Or your own answer…", "aria-label": `Your own answer to: ${q.question}` });
    words.addEventListener("input", () => own.set(q.question, words.value));
    block.append(el("div", { class: "chips" }, options), words);
    box.append(block);
  }
  if (!waiting) return box;
  const reply = (decision) => async () => {
    const answers = {};
    for (const q of item.questions) {
      const words = (own.get(q.question) || "").trim();
      answers[q.question] = [...picked.get(q.question), ...(words ? [words] : [])].join(", ");
    }
    if (decision === "allow" && !Object.values(answers).some(Boolean)) return toast("Pick an answer first.");
    try {
      const data = await api("POST", "/api/codoh/answer", { id: codoh.chatId, item: item.id, decision, answers: decision === "deny" ? {} : answers });
      if (!data.ok) toast(data.error || "That was already answered.");
    } catch (error) { failed(error); }
    pollChat();
  };
  box.append(el("div", { class: "cx-ask-buttons" },
    el("button", { class: "pill primary", type: "button", onclick: reply("allow") }, "Send answer"),
    el("button", { class: "pill", type: "button", onclick: reply("deny") }, "Skip")));
  return box;
}

async function sendCodoh(e) {
  e.preventDefault();
  const box = $("#codoh-text");
  const text = box.value.trim();
  if (!text || !codoh.chatId) return;
  box.value = "";
  try {
    const data = await api("POST", "/api/codoh/send", { id: codoh.chatId, text });
    if (!data.ok) toast(data.error || "Codoh couldn't take that.");
    else if (data.queued) toast("Codoh gets that when it's done");
  } catch (error) { failed(error); }
  pollChat();
}

async function stopCodoh() {
  try { await api("POST", "/api/codoh/stop", { id: codoh.chatId }); } catch (error) { failed(error); }
  pollChat();
}

/* Codoh, for this phone: a chat Abdoh started for it ("open"), or what one needs ("text"). */
function takeCodoh(event) {
  if (event.for !== S.me) return;
  const chip = el("button", { class: "board-chip", type: "button", onclick: () => openCodoh(event.chat) },
    el("span", { class: "board-chip-icon", html: CODOH_ICON }),
    el("span", { class: "board-chip-about" }, el("b", {}, "Codoh"), el("small", {}, event.text || "Working on it on the computer")),
    el("span", { class: "board-chip-open" }, "Open"));
  place(chip, "msg abdoh media");
  scrollDown();
  if (event.text) toast(`Codoh: ${event.text}`);
  if (codoh.open && codoh.chatId === event.chat) pollChat();
  else if (event.open && S.answered < S.asked) openCodoh(event.chat);
}

/* ---------- Abdoh's own settings (story 157) ----------
   The everyday ones (voice, how it listens and talks, memory), the same as on the computer:
   a change counts at once there. Never permissions or keys (they stay on the computer). */

const prefs = { open: false };

async function openSettings() {
  $("#menu").hidden = true;
  prefs.open = true;
  $("#settings-view").hidden = false;
  dockCall();
  await showSettings();
}

function closeSettings() {
  prefs.open = false;
  $("#settings-view").hidden = true;
  dockCall();
}

async function showSettings() {
  const body = $("#settings-body");
  if (!body.children.length) body.replaceChildren(el("p", { class: "board-empty" }, "…"));
  let data;
  try {
    data = await api("GET", "/api/settings");
  } catch (error) {
    if (error instanceof Unpaired) return unpaired();
    return body.replaceChildren(el("p", { class: "board-empty" }, error.shown ? error.message : "Can't reach your computer right now."));
  }
  const scroll = body.scrollTop;
  body.replaceChildren(...(data.sections || []).map((section) => el("div", { class: "prefs-group" },
    el("h3", {}, section.title), ...section.settings.map(settingRow))));
  body.scrollTop = scroll;
}

function settingRow(s) {
  const save = async (value, undo) => {
    try {
      const result = await api("POST", "/api/settings", { key: s.key, value });
      if (!result.ok) { toast(result.error || "That can't be changed."); undo(); return; }
      toast(result.restart ? `${result.text} · after a restart` : result.text);
    } catch (error) {
      toast(error.shown ? error.message : "Can't reach your computer right now.");
      undo();
    }
  };
  let control;
  if (s.kind === "bool") {
    control = el("input", { type: "checkbox", class: "switch", checked: !!s.value, "aria-label": s.label });
    control.addEventListener("change", () => save(control.checked, () => { control.checked = !control.checked; }));
  } else if (s.kind === "choice") {
    control = el("select", { class: "prefs-select", "aria-label": s.label },
      s.choices.map(([value, name]) => el("option", { value, selected: value === s.value }, name)));
    const was = s.value;
    control.addEventListener("change", () => save(control.value, () => { control.value = was; }));
  } else {
    const shown = el("span", { class: "prefs-value" });
    const show = (v) => { shown.textContent = s.unit === "%" ? `${v}%` : `${v}${s.unit ? ` ${s.unit}` : ""}`; };
    const slider = el("input", { type: "range", class: "prefs-range", min: s.low, max: s.high, step: s.step, value: s.value, "aria-label": s.label });
    show(s.value);
    const was = s.value;
    slider.addEventListener("input", () => show(slider.value));
    slider.addEventListener("change", () => save(Number(slider.value), () => { slider.value = was; show(was); }));
    control = el("div", { class: "prefs-number" }, slider, shown);
  }
  const wide = s.kind === "number";
  return el("div", { class: `prefs-row${wide ? " stacked" : ""}` },
    el("span", { class: "prefs-label" }, el("b", {}, s.label), s.help ? el("small", {}, s.help) : null), control);
}

/* ---------- the board (story 150) ----------
   The window's own board.js draws it (code, math, tables, drawings, pictures), loaded with
   KaTeX the first time it's needed; the newest card is written out the way a teacher writes. */

window.App = { boardPictures: {} }; // board.js finds the board's pictures here
const board = { cards: [], seen: new Set(), typist: null, ready: null, open: false, pdf: false };
const BOARD_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="13" rx="2"/><path d="M7 21l3-4M17 21l-3-4M7 9h6M7 12h9"/></svg>';

function loadBoard() {
  board.ready = board.ready || (async () => {
    document.head.append(el("link", { rel: "stylesheet", href: "vendor/katex/katex.min.css" }));
    await loadScript("vendor/katex/katex.min.js");
    await loadScript("vendor/katex/contrib/mhchem.min.js");
    await loadScript("board.js");
    if (typeof Board === "undefined") throw new Error("The board couldn't load."); // a const, not on window
    board.typist = new Board.Typist((text) => {
      const list = $("#board");
      if (!board.open || !list.lastElementChild || !list.lastElementChild.classList.contains("board-item")) return;
      list.lastElementChild.replaceWith(Board.render(text));
      follow();
    });
    const last = board.cards[board.cards.length - 1];
    if (last) board.typist.set(last, false); // what was there before: whole
  })();
  return board.ready;
}

/* A card grew (or the board was cleared: null). */
function takeBoard(card) {
  if (!card) {
    board.cards = [];
    App.boardPictures = {};
    if (board.typist) board.typist.set(null);
    return renderBoard();
  }
  const last = board.cards[board.cards.length - 1];
  if (last && last.id === card.id) board.cards[board.cards.length - 1] = card;
  else board.cards = [...board.cards, card].slice(-30);
  const fresh = !board.seen.has(card.id);
  board.seen.add(card.id);
  if (fresh) {
    boardChip(card.id);
    scrollDown();
    if (call.on || S.answered < S.asked) openBoard(); // the answer to this phone is on it
  }
  loadBoard().then(() => {
    board.typist.set(card);
    renderBoard();
  }).catch(() => renderBoard());
}

/* The board's PDF came (a file card in the conversation): the board closes to show it. */
function boardPdfCame(event) {
  if (!board.pdf || !/\.pdf$/i.test(event.name || "")) return;
  board.pdf = false;
  if (board.open) closeBoard();
  toast("The board as a PDF: open it, or save it to your phone");
}

function takePicture(picture) {
  if (!picture.what) return;
  App.boardPictures = { ...App.boardPictures, [picture.what]: picture };
  for (const figure of document.querySelectorAll(".board-picture")) {
    if (figure.dataset.what === picture.what && figure.fill) figure.fill(picture);
  }
}

/* In the conversation: "On the board", with its first line, opens it. */
function boardChip(id) {
  const card = board.cards.find((c) => c.id === id);
  if (!card) return null;
  const title = el("small", {}, boardTitle(card.text));
  const chip = el("button", { class: "board-chip", type: "button", onclick: openBoard },
    el("span", { class: "board-chip-icon", html: BOARD_ICON }), el("span", { class: "board-chip-about" }, el("b", {}, "On the board"), title),
    el("span", { class: "board-chip-open" }, "Open"));
  chip.dataset.card = id;
  return place(chip, "msg abdoh media");
}

function boardTitle(text) {
  const line = String(text || "").split("\n").map((l) => l.trim()).find((l) => l && !l.startsWith("```")) || "";
  const plain = line.replace(/^#+\s*|^[-*•]\s+|^\d+[.)]\s+|[*`$|]/g, "").trim();
  return plain.length > 60 ? `${plain.slice(0, 59)}…` : plain || "A drawing";
}

async function openBoard() {
  board.open = true;
  $("#board-view").hidden = false;
  dockCall(); // on a call: the call goes on as a bar on top, and you watch the board
  renderBoard();
  try {
    await loadBoard();
  } catch (error) { /* said on the board */ }
  renderBoard();
}

function closeBoard() {
  board.open = false;
  $("#board-view").hidden = true;
  dockCall();
}

/* Save as PDF: the computer makes it the way its window does, and it comes as a file card. */
async function boardPdf() {
  const button = $("#board-pdf");
  button.disabled = true;
  button.textContent = "Making the PDF…";
  try {
    await api("POST", "/api/board_pdf");
    board.pdf = true; // the next PDF that comes is this one: the board makes way for it
  } catch (error) {
    failed(error);
    toast(error.shown ? error.message : "Can't reach your computer right now.");
  }
  setTimeout(() => { button.disabled = false; button.textContent = "Save as PDF"; }, board.pdf ? 2500 : 0);
}

function renderBoard() {
  if (!board.open) return;
  const list = $("#board");
  const ready = typeof Board !== "undefined" && board.typist;
  $("#board-note").textContent = board.cards.length ? `${board.cards.length} card${board.cards.length === 1 ? "" : "s"}` : "";
  $("#board-pdf").hidden = !board.cards.length;
  if (!ready) {
    list.replaceChildren(el("p", { class: "board-empty" }, board.ready ? "Getting the board ready…" : "The board couldn't load."));
    return;
  }
  list.replaceChildren(...(board.cards.length ? board.cards.map((card) => Board.render(board.typist.shown(card)))
    : [el("p", { class: "board-empty" }, "Nothing on the board yet. Ask Abdoh to explain something on the board.")]));
  follow();
}

function follow() {
  const list = $("#board");
  requestAnimationFrame(() => { list.scrollTop = list.scrollHeight; });
}

/* ---------- a photo or a file for the computer (story 149) ----------
   Sent as soon as it's picked (with progress), then goes with the next message. */

function pickFile() {
  const input = $("#attach-input");
  input.value = "";
  input.click();
}

function attach(file) {
  if (!file) return;
  if (S.attached && S.attached.xhr) S.attached.xhr.abort();
  const item = { name: file.name || "file", size: file.size, id: null, progress: 0, failed: "", xhr: null };
  S.attached = item;
  if (file.size > 100 * 1024 * 1024) item.failed = "That file is too big for the computer (100 MB at most).";
  if (!file.size) item.failed = "That file is empty.";
  showAttached();
  if (item.failed) return;
  if (DEMO) {
    setTimeout(() => { item.progress = 1; item.id = "demo-file"; showAttached(); }, 900);
    return;
  }
  const xhr = new XMLHttpRequest();
  item.xhr = xhr;
  xhr.open("POST", `/api/upload?name=${encodeURIComponent(item.name)}`);
  xhr.setRequestHeader("Authorization", `Bearer ${S.key}`);
  xhr.upload.onprogress = (e) => { if (e.lengthComputable) { item.progress = e.loaded / e.total; showAttached(); } };
  xhr.onload = () => {
    let data = {};
    try { data = JSON.parse(xhr.responseText || "{}"); } catch (error) { /* not JSON */ }
    if (xhr.status === 401) return unpaired();
    if (xhr.status === 200 && data.id) Object.assign(item, { id: data.id, name: data.name || item.name, progress: 1 });
    else item.failed = data.error || "Your computer couldn't take that file.";
    item.xhr = null;
    showAttached();
  };
  xhr.onerror = () => { item.failed = "Your computer can't be reached right now."; item.xhr = null; showAttached(); };
  xhr.send(file);
}

function showAttached() {
  const item = S.attached;
  $("#attached").hidden = !item;
  if (item) {
    $("#attached-name").textContent = item.name;
    $("#attached-icon").textContent = fileLabel(item);
    $("#attached-state").textContent = item.failed || (item.id ? `${size(item.size)} · ready to send`
      : `Sending to the computer… ${Math.round(item.progress * 100)}%`);
    $("#attached").classList.toggle("failed", !!item.failed);
  }
  render();
}

function dropAttached() {
  if (S.attached && S.attached.xhr) S.attached.xhr.abort();
  S.attached = null;
  showAttached();
}

/* ---------- the computer's clipboard (story 149) ---------- */

async function openClipboard() {
  $("#controls").hidden = true;
  const box = $("#clip-text");
  box.value = "";
  box.placeholder = "Getting the computer's clipboard…";
  $("#clip").hidden = false;
  try {
    const data = await api("GET", "/api/clipboard");
    box.value = data.text || "";
  } catch (error) {
    if (error instanceof Unpaired) return unpaired();
  }
  box.placeholder = "Nothing copied on the computer. Paste here to send it there.";
}

async function copyHere() {
  const text = $("#clip-text").value;
  try {
    await navigator.clipboard.writeText(text);
  } catch (error) { // older phones: the selection
    $("#clip-text").select();
    document.execCommand("copy");
  }
  toast("Copied to this phone");
}

async function sendClipboard() {
  try {
    await api("POST", "/api/clipboard", { text: $("#clip-text").value });
    $("#clip").hidden = true;
    toast("On the computer's clipboard");
  } catch (error) {
    $("#clip").hidden = true;
    failed(error);
  }
}


/* What Abdoh is doing for this phone's request, step by step (story 147): live above its
   answer while it works, then folded into "3 steps". */
function addStep(text) {
  if (!text) return;
  if (!S.steps) {
    const title = el("span", { class: "work-title" });
    const list = el("ol", { class: "work-list" });
    const box = el("details", { class: "work", open: true }, el("summary", {}, el("i", { class: "spin" }), title), list);
    const node = el("div", { class: "msg abdoh work-msg" }, box);
    $("#messages").insertBefore(node, S.live || $("#typing"));
    S.steps = { node, box, title, list, count: 0, done: false };
  }
  S.steps.count += 1;
  S.steps.list.append(el("li", {}, text));
  showSteps();
  scrollDown();
}

function showSteps() {
  const steps = S.steps;
  if (!steps) return;
  const count = `${steps.count} step${steps.count === 1 ? "" : "s"}`;
  steps.title.textContent = steps.done ? count : `Working on it · ${count}`;
  steps.box.classList.toggle("done", steps.done);
}

function stepsDone() {
  if (!S.steps || S.steps.done) return;
  S.steps.done = true;
  S.steps.box.open = false;
  showSteps();
}

function addLine(line, fresh = false) {
  const match = LINE.exec(line || "");
  if (!match) return note(line);
  const [, who, text] = match;
  if (who === "Abdoh") {
    if (S.live) {  // the reply grew sentence by sentence: now it's whole
      S.live.querySelector(".text").textContent = text;
      S.live = null;
    } else bubble("abdoh", text);
    if (call.on && call.state === "thinking") call.abdoh = text; // done without words: shown
    S.final = true;
    S.activity = "";
  } else {
    const fromPhone = who === "You (phone)";
    const sent = fresh && fromPhone ? takePending(text) : null;
    if (!sent) bubble("you", text, fromPhone ? null : "On the computer");
    S.live = null;
    S.final = false;
    if (S.steps) stepsDone();
    S.steps = null; // a new request: its own steps
    hideQuestion();
  }
  render();
  scrollDown();
}

/* A sentence of the reply to this phone: shown, and said if this phone asked and speaks (on a
   call, always). Not the rest of a reply that was stopped. */
function addSaid(event) {
  const wanted = call.on ? ANSWERING.includes(call.state) : S.speak;
  if (wanted && event.for === S.me && S.answered >= S.cut) play(event);
  if (S.final) return; // already shown whole (a short reply comes whole, then is said)
  if (!S.live) S.live = bubble("abdoh", "");
  const text = S.live.querySelector(".text");
  text.textContent = text.textContent ? `${text.textContent} ${event.text}` : event.text;
  S.activity = "";
  render();
  scrollDown();
}

function bubble(who, text, label = null) {
  const [words, file] = who === "you" ? withFile(text) : [text, ""];
  return place(el("div", { class: "bubble" }, label ? el("span", { class: "from" }, label) : null,
    file ? el("span", { class: "sent-file" }, `📎 ${file}`) : null,
    el("span", { class: "text" }, words)), `msg ${who}`);
}

/* "explain this [sent photo.jpg]" -> ["explain this", "photo.jpg"]: what the phone sent with
   a message, shown as a file line above it. */
function withFile(text) {
  const sent = /^([\s\S]*?)\s*\[sent (.+)\]$/.exec(text || "");
  return sent ? [sent[1], sent[2]] : [text, ""];
}

/* A new message at the end of the conversation (above the typing dots). */
function place(content, classes) {
  const node = el("div", { class: classes }, content);
  const list = $("#messages");
  list.insertBefore(node, $("#typing"));
  while (list.children.length > MAX_MESSAGES) list.firstElementChild.remove();
  updateEmpty();
  return node;
}

function note(text) {
  if (!text || !text.trim()) return null;
  return bubble("note", text);
}

const same = (text) => text.replace(/\s+/g, " ").trim().slice(0, 2000);

function takePending(text) {
  const at = S.pending.findIndex((p) => p.text === same(text) || p.voice);
  if (at < 0) return null;
  const [found] = S.pending.splice(at, 1);
  found.node.classList.remove("pending");
  const [words, file] = withFile(text);
  found.node.querySelector(".text").textContent = words;
  if (file && !found.node.querySelector(".sent-file")) found.node.querySelector(".bubble").prepend(el("span", { class: "sent-file" }, `📎 ${file}`));
  return found.node;
}

/* The header, the typing dots, and the buttons, from the state. */
function render() {
  const offline = S.online === false;
  S.busy = /^(Thinking|Speaking)/.test(S.status);
  $("#dot").className = `dot ${offline ? "off" : S.busy ? "busy" : S.online ? "on" : ""}`;
  $("#status").textContent = offline ? "Can't reach your computer" : S.activity ? `${S.activity}…`.replace(/\.+…$/, "…")
    : S.status.startsWith("Thinking") ? "Thinking…" : S.status.startsWith("Speaking") ? "Answering…"
      : /paus/i.test(S.status) ? "Paused on the computer" : S.online ? `Online · ${S.ai}` : "Connecting…";
  const waiting = !S.final && !S.live && (S.busy || S.pending.length > 0);
  const typing = $("#typing");
  if (waiting && !typing) {
    $("#messages").append(el("div", { class: "msg abdoh typing", id: "typing" }, el("div", { class: "bubble" }, el("i"), el("i"), el("i"))));
    scrollDown();
  } else if (!waiting && typing) typing.remove();
  const typed = !!$("#text").value.trim();
  const talking = S.busy || player.playing;
  $("#form").hidden = rec.on;
  $("#recording").hidden = !rec.on;
  $("#stop").hidden = !(talking && !typed && !S.attached);
  $("#mic").hidden = typed || talking; // with a photo waiting: say what to do with it, or type
  $("#send").hidden = !typed && !S.attached;
  updateEmpty();
}

function updateEmpty() {
  $("#empty").hidden = $("#messages").children.length > 0;
}

function online(on) {
  if (S.online === on) return;
  S.online = on;
  $("#offline").hidden = on;
  render();
}

function setAi(info) {
  S.ai = info.label || info.name || "Claude";
  render();
}

function setMode(name) {
  $("#mode").hidden = !name;
  $("#mode").textContent = name ? `${name} mode` : "";
}

function scrollDown(now = false) {
  const chat = $("#chat");
  const near = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 160;
  if (now || near) requestAnimationFrame(() => { chat.scrollTop = chat.scrollHeight; });
}

/* ---------- asking ---------- */

async function send(text, { withFile = true } = {}) {
  text = text.trim().replace(/\s+/g, " ");
  const file = withFile ? S.attached : null;
  if (file && !file.id) return toast(file.failed ? "That file didn't go: remove it or pick it again." : "The file is still on its way…");
  if (!text && !file) return;
  S.attached = null;
  showAttached();
  const shown = file ? `${text} [sent ${file.name}]`.trim() : text; // as the computer shows it
  silence(); // a new question: the last answer stops
  const node = bubble("you", shown);
  node.classList.add("pending");
  S.pending.push({ node, text: same(shown) });
  S.final = false;
  S.live = null;
  hideQuestion();
  render();
  scrollDown(true);
  try {
    const data = await api("POST", "/api/text", { text, speak: S.speak, files: file ? [file.id] : [] });
    if (data.quiet) S.final = true; // only a file: kept on the computer, nothing to answer
    else S.asked += 1;
    render();
  } catch (error) {
    S.pending = S.pending.filter((p) => p.node !== node);
    node.classList.remove("pending");
    S.final = true;
    if (file && !S.attached) { // it didn't go: the file waits for the next message again
      S.attached = file;
      if (error.status === 410) file.failed = error.message; // gone: pick it again
      showAttached();
    }
    failed(error);
  }
}

function failed(error) {
  if (error instanceof Unpaired) return unpaired();
  note(error.shown ? error.message : "Couldn't send that: your computer can't be reached right now.");
  render();
  scrollDown(true);
}

function askQuestion(text) {
  $("#question-text").textContent = text;
  $("#question").hidden = false;
  scrollDown(true);
}

function hideQuestion() { $("#question").hidden = true; }

async function stop() {
  silence();
  S.cut = S.asked;
  render();
  try { await api("POST", "/api/stop"); } catch (error) { failed(error); }
}

/* ---------- hearing Abdoh's replies ----------
   Its own voice (a WAV from your computer) when it has a natural voice, else the phone's.
   A phone only plays sound after a tap: the first tap (send, talk) unlocks it. */

const player = { ctx: null, queue: [], playing: false, source: null, turn: 0, unlocked: false, gain: null, ducked: false };

function audioContext() {
  if (!player.ctx) {
    const Context = window.AudioContext || window.webkitAudioContext;
    if (Context) player.ctx = new Context();
  }
  return player.ctx;
}

function unlockAudio() {
  const ctx = audioContext();
  if (ctx && ctx.state === "suspended") ctx.resume();
  if (!player.unlocked && "speechSynthesis" in window && !DEMO) speechSynthesis.speak(new SpeechSynthesisUtterance(""));
  player.unlocked = true;
}

function play(event) {
  player.queue.push({ text: event.text, sound: event.audio ? fetchSound(event.audio) : null });
  if (!player.playing) next(player.turn);
  render();
}

async function fetchSound(id) {
  if (DEMO) throw new Error("no sound in the demo");
  const response = await fetch(`/api/audio/${id}`, { headers: { Authorization: `Bearer ${S.key}` }, cache: "no-store" });
  if (!response.ok) throw new Error("the sound is gone");
  const data = await response.arrayBuffer();
  return new Promise((resolve, reject) => audioContext().decodeAudioData(data, resolve, reject));
}

async function next(turn) {
  const item = player.queue.shift();
  if (!item || turn !== player.turn) {
    player.playing = false;
    render();
    turnOver();
    return;
  }
  player.playing = true;
  if (call.on) callSays(item.text);
  try {
    if (item.sound) await playSound(await item.sound);
    else await speakHere(item.text);
  } catch (error) {
    if (turn === player.turn) await speakHere(item.text); // the sound didn't come: the phone's voice
  }
  next(turn);
}

function playSound(buffer) {
  return new Promise((resolve) => {
    const ctx = audioContext();
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(output());
    source.onended = resolve;
    player.source = source;
    source.start();
  });
}

function speakHere(text) {
  return new Promise((resolve) => {
    if (DEMO) return setTimeout(resolve, 500 + text.length * 40); // the demo stays quiet
    if (!("speechSynthesis" in window)) return resolve();
    const line = new SpeechSynthesisUtterance(text);
    line.onend = resolve;
    line.onerror = resolve;
    speechSynthesis.speak(line);
  });
}

/* Abdoh's voice goes through this, so it can be turned down while you talk over it. */
function output() {
  if (!player.gain) {
    player.gain = audioContext().createGain();
    player.gain.connect(audioContext().destination);
  }
  return player.gain;
}

function duck(on) {
  if (player.ducked === on) return;
  player.ducked = on;
  if (player.gain) player.gain.gain.setTargetAtTime(on ? CALL.duck : 1, player.gain.context.currentTime, 0.05);
}

function silence() {
  duck(false);
  player.turn += 1;
  player.queue = [];
  player.playing = false;
  if (player.source) {
    try { player.source.stop(); } catch (error) { /* already over */ }
    player.source = null;
  }
  if ("speechSynthesis" in window) speechSynthesis.cancel();
}

/* ---------- talking: tap the microphone, talk, tap send ----------
   The phone records, turns it into what your computer's speech recognition reads (16 kHz,
   mono, 16-bit) and sends it. A minute at most. */

const rec = { on: false, stream: null, source: null, node: null, chunks: [], rate: 48000, started: 0, timer: null, level: 0 };
const MAX_RECORD_MS = 60000;
const NO_MIC = { shown: true, message: "The microphone can't be used here. Open Abdoh from your Home Screen (or over https)." };

/* The microphone (null in the demo). Throws a message for people. */
async function openMic() {
  if (DEMO) return null;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw NO_MIC;
  try {
    return await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  } catch (error) {
    throw { shown: true, message: error && error.name === "NotAllowedError"
      ? "Abdoh may not use the microphone. Allow it for Abdoh (Settings → Safari → Microphone on an iPhone), then try again."
      : "The microphone isn't available right now." };
  }
}

const clock = (seconds) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

async function startRecording() {
  unlockAudio();
  silence();
  try {
    rec.stream = await openMic();
  } catch (error) {
    return failed(error);
  }
  rec.chunks = [];
  if (rec.stream) {
    const ctx = audioContext();
    rec.rate = ctx.sampleRate;
    rec.source = ctx.createMediaStreamSource(rec.stream);
    rec.node = ctx.createScriptProcessor(4096, 1, 1);
    rec.node.onaudioprocess = (e) => {
      const data = e.inputBuffer.getChannelData(0);
      rec.chunks.push(new Float32Array(data));
      let sum = 0;
      for (let i = 0; i < data.length; i += 16) sum += data[i] * data[i];
      rec.level = Math.min(1, Math.sqrt(sum / (data.length / 16)) * 6);
    };
    rec.source.connect(rec.node);
    rec.node.connect(ctx.destination); // silent: it only runs while connected
  }
  rec.on = true;
  rec.started = Date.now();
  rec.timer = setInterval(showRecording, 100);
  showRecording();
  render();
}

function showRecording() {
  const ms = Date.now() - rec.started;
  $("#rec-time").textContent = clock(Math.floor(ms / 1000));
  const level = DEMO ? 0.35 + 0.3 * Math.sin(ms / 180) : rec.level;
  [...document.querySelectorAll(".meter i")].forEach((bar, i) => {
    const wave = 0.55 + 0.45 * Math.sin(ms / 120 + i * 1.3);
    bar.style.height = `${4 + Math.round(18 * level * wave)}px`;
  });
  if (ms >= MAX_RECORD_MS) stopRecording(true);
}

function stopRecording(sendIt) {
  if (!rec.on) return;
  rec.on = false;
  clearInterval(rec.timer);
  if (rec.node) { rec.node.disconnect(); rec.node.onaudioprocess = null; }
  if (rec.source) rec.source.disconnect();
  if (rec.stream) rec.stream.getTracks().forEach((track) => track.stop()); // the microphone is free again
  rec.node = rec.source = rec.stream = null;
  render();
  if (!sendIt) return;
  const pcm = DEMO ? new ArrayBuffer(32000) : toPcm16k(rec.chunks, rec.rate);
  rec.chunks = [];
  if (pcm.byteLength < 16000 * 2 * 0.4) return note("That was very short. Tap the microphone, talk, then tap send.");
  sendVoice(pcm);
}

/* Float samples at the phone's rate -> 16 kHz 16-bit (averaging each step: no aliasing hiss). */
function toPcm16k(chunks, rate) {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const all = new Float32Array(total);
  let at = 0;
  for (const chunk of chunks) { all.set(chunk, at); at += chunk.length; }
  const step = rate / 16000;
  const out = new Int16Array(Math.floor(total / step));
  for (let i = 0; i < out.length; i++) {
    const from = Math.floor(i * step);
    const to = Math.max(from + 1, Math.min(total, Math.floor((i + 1) * step)));
    let sum = 0;
    for (let j = from; j < to; j++) sum += all[j];
    out[i] = Math.round(Math.max(-1, Math.min(1, sum / (to - from))) * 32767);
  }
  return out.buffer;
}

/* What you said, sent: returns what Abdoh heard ("" if nothing). On a call (`inCall`), the
   call says what went wrong: errors are thrown. */
async function sendVoice(pcm, { speak = S.speak, inCall = false } = {}) {
  const file = !inCall && S.attached && S.attached.id ? S.attached : null;
  if (file) {
    S.attached = null;
    showAttached();
  }
  const node = bubble("you", file ? `… [sent ${file.name}]` : "…");
  node.classList.add("pending");
  const pending = { node, text: "", voice: true };
  S.pending.push(pending);
  S.final = false;
  S.live = null;
  hideQuestion();
  render();
  scrollDown(true);
  const drop = () => {
    S.pending = S.pending.filter((p) => p !== pending);
    node.remove();
    S.final = true;
    if (file && !S.attached) { // it didn't go: the file waits for the next message again
      S.attached = file;
      showAttached();
    }
    render();
  };
  let data;
  try {
    const query = [speak ? "speak=1" : "", file ? `files=${encodeURIComponent(file.id)}` : ""].filter(Boolean).join("&");
    data = await api("POST", `/api/voice${query ? `?${query}` : ""}`, pcm, { timeout: 60000 });
  } catch (error) {
    drop();
    if (inCall) throw error;
    failed(error);
    return "";
  }
  if (data.text) S.asked += 1;
  else if (S.pending.includes(pending)) {
    drop();
    if (!inCall) note("Abdoh didn't catch that. Try again, a little closer to the phone.");
  }
  return data.text || "";
}

/* ---------- a call: back and forth by voice, hands-free (stories 145, 146) ----------
   The phone button in the header starts it. Abdoh listens; when you pause, what you said is
   sent, the reply is said here, and it listens again, until you hang up.

   You can talk over Abdoh, as on a phone call (the phone's echo canceller keeps its own voice
   out of the microphone): at the first sign of you its voice drops, and when you pause, your
   computer decides (hub.hear_over): "okay", a noise or its own voice coming back, and it goes
   on; "wait", and it stops; anything else, and it stops and answers that. Fooled three times
   in a call (a noisy street), it stops listening over itself: tap the circle instead. */

const CALL = {
  frame: 2048,
  preRollMs: 350, // kept from just before you started: the first word isn't cut off
  startMs: 120, // this much sound above the room's hum: you're talking
  endMs: 1200, // then this long quiet: your turn is over
  minSpeechMs: 300, // less: a knock or a cough, not words
  maxTurnMs: 45000,
  graceMs: 450, // after Abdoh's voice (or the microphone opening): its echo dies away
  quietEndMs: 5 * 60000, // nobody talked this long: the call ends
  overLevel: 0.03, // over Abdoh's answer: louder than this (and 4 times the room)...
  overMs: 300, // ... for this long (short gaps between words allowed): you're talking over it
  duck: 0.15, // Abdoh's voice while you talk over it
  fooledMax: 3, // talking over Abdoh turned out to be nothing this often: tap the circle instead
};
const OVER = ["thinking", "speaking"]; // Abdoh's turn: you may talk over it
const ANSWERING = ["sending", "thinking", "speaking", "over", "checking"]; // its answer is said
const call = {
  on: false, state: "", muted: false, stream: null, source: null, node: null, rate: 48000,
  ear: newEar(), pre: [], chunks: [], level: 0, fooled: 0, overOff: false,
  armed: 0, idle: 0, started: 0, timer: null, demo: null, lock: null, you: "", abdoh: "", hint: "",
};

/* The call's ear: how loud the room is (`floor`), and your turn so far. */
function newEar(floor = 0.004) {
  return { floor, talking: false, loudMs: 0, speechMs: 0, quietMs: 0, totalMs: 0 };
}

/* One block from the microphone (its loudness and length): "start" when you started talking,
   "end" when you've stopped, "drop" when it was only a knock or a cough, else null. `over`:
   while Abdoh answers, it takes more (louder, longer) to count as you. */
function earStep(ear, rms, ms, over = false) {
  const loud = over ? Math.max(CALL.overLevel, ear.floor * 4) : Math.max(0.015, ear.floor * 3);
  if (!ear.talking) {
    ear.floor += (rms - ear.floor) * (rms < ear.floor ? 0.1 : 0.004); // follows the room's hum
    ear.loudMs = rms > loud ? ear.loudMs + ms : over ? Math.max(0, ear.loudMs - ms / 2) : 0;
    if (ear.loudMs < (over ? CALL.overMs : CALL.startMs)) return null;
    Object.assign(ear, { talking: true, speechMs: ear.loudMs, quietMs: 0, totalMs: ear.loudMs });
    return "start";
  }
  ear.totalMs += ms;
  if (rms > loud * 0.55) {
    ear.quietMs = 0;
    ear.speechMs += ms;
  } else ear.quietMs += ms;
  if (ear.quietMs < CALL.endMs && ear.totalMs < CALL.maxTurnMs) return null;
  ear.talking = false;
  ear.loudMs = 0;
  return ear.speechMs < CALL.minSpeechMs ? "drop" : "end";
}

async function startCall() {
  if (call.on) return;
  unlockAudio(); // a tap: replies may be heard
  silence();
  if (rec.on) stopRecording(false);
  $("#controls").hidden = true;
  $("#menu").hidden = true;
  let stream;
  try {
    stream = await openMic();
  } catch (error) {
    return failed(error);
  }
  Object.assign(call, { on: true, muted: false, stream, started: Date.now(), ear: newEar(), fooled: 0, overOff: false,
    you: "", abdoh: "", hint: "" });
  S.cut = S.asked; // a reply still coming from before the call isn't said in it
  if (stream) {
    const ctx = audioContext();
    call.rate = ctx.sampleRate;
    call.source = ctx.createMediaStreamSource(stream);
    call.node = ctx.createScriptProcessor(CALL.frame, 1, 1);
    call.node.onaudioprocess = (e) => hearFrame(e.inputBuffer.getChannelData(0));
    call.source.connect(call.node);
    call.node.connect(ctx.destination); // silent: it only runs while connected
    for (const track of stream.getTracks()) {
      track.addEventListener("ended", () => endCall("The call ended: the microphone stopped."));
    }
  }
  $("#call").hidden = false;
  dockCall(); // the screen, the board or Codoh is up: the call joins it as a bar
  call.timer = setInterval(showCall, 100);
  keepAwake(true);
  listen();
}

/* Your turn: wait for you to talk (once Abdoh's echo has died away). */
function listen(grace = CALL.graceMs) {
  if (!call.on) return;
  clearTimeout(call.demo);
  Object.assign(call, { state: "listening", ear: newEar(call.ear.floor), pre: [], chunks: [] });
  call.armed = Date.now() + grace;
  call.idle = Date.now();
  if (DEMO && !call.muted) demoTalk();
  showCall();
}

/* Every block from the microphone: did you start talking (also over Abdoh), and have you
   stopped? */
function hearFrame(data) {
  if (!call.on) return;
  let sum = 0;
  for (let i = 0; i < data.length; i += 4) sum += data[i] * data[i];
  const rms = Math.sqrt(sum / Math.ceil(data.length / 4));
  call.level = call.muted ? 0 : Math.min(1, rms * 6);
  const over = OVER.includes(call.state) && !call.overOff;
  if (call.muted || !(over || ["listening", "hearing", "over"].includes(call.state))) return;
  const ear = call.ear;
  if (Date.now() < call.armed) { // not yet: learn how loud the room is meanwhile
    if (call.state === "listening") ear.floor += (rms - ear.floor) * 0.2;
    return;
  }
  const ms = (data.length / call.rate) * 1000;
  const heard = earStep(ear, rms, ms, over || call.state === "over");
  if (call.state === "listening" || over) {
    call.pre.push(new Float32Array(data));
    while (call.pre.length * ms > CALL.preRollMs) call.pre.shift();
    if (over) duck(ear.loudMs >= CALL.startMs); // the first sign of you: Abdoh's voice drops
    if (heard === "start") Object.assign(call, { state: over ? "over" : "hearing", chunks: call.pre, pre: [], hint: "" });
    if (heard === "start") showCall();
    return;
  }
  call.chunks.push(new Float32Array(data));
  if (heard === "drop") return call.state === "over" ? backToAnswer() : listen(0);
  if (heard !== "end") return;
  const extra = Math.floor(Math.max(0, ear.quietMs - 300) / ms); // most of the quiet at the end
  const chunks = call.chunks.slice(0, call.chunks.length - extra);
  if (call.state === "over") sendOver(chunks);
  else sendTurn(chunks);
}

/* What you said over Abdoh's answer: your computer decides what it was (hub.hear_over), while
   Abdoh goes on quietly. */
async function sendOver(chunks) {
  Object.assign(call, { state: "checking", chunks: [] });
  showCall();
  const cut = S.asked; // the requests being answered now
  const pcm = DEMO ? new ArrayBuffer(32000) : toPcm16k(chunks, call.rate);
  let got;
  try {
    got = await api("POST", "/api/voice?speak=1&over=1", pcm, { timeout: 60000 });
  } catch (error) {
    if (error instanceof Unpaired) {
      endCall();
      return unpaired();
    }
    return backToAnswer();
  }
  if (!call.on || call.state !== "checking") return;
  if (got.kind === "end") return endCall("You said to stop listening, so the call ended.");
  if (got.kind !== "stop" && got.kind !== "request") {
    if (got.heard === "nothing" || got.heard === "echo") fooled();
    return backToAnswer();
  }
  S.cut = cut; // your computer stopped the answer: the rest of it isn't said
  silence();
  call.abdoh = "";
  if (got.kind === "stop") return listen(250);
  S.asked += 1; // ... and asked what you said instead
  call.you = got.text;
  call.state = "thinking";
  showCall();
  turnOver();
}

/* It wasn't you (a noise, or Abdoh's own voice): the answer goes on, at full volume. */
function backToAnswer() {
  if (!call.on) return;
  duck(false);
  Object.assign(call, { ear: newEar(call.ear.floor), pre: [], chunks: [] });
  call.state = player.playing || player.queue.length ? "speaking" : "thinking";
  showCall();
  turnOver();
}

function fooled() {
  call.fooled += 1;
  if (call.fooled >= CALL.fooledMax) call.overOff = true; // a noisy place: tap the circle instead
}

/* What you said goes to your computer; the reply comes as events ("say", then "done"). */
async function sendTurn(chunks) {
  clearTimeout(call.demo);
  Object.assign(call, { state: "sending", chunks: [], hint: "" });
  showCall();
  const pcm = DEMO ? new ArrayBuffer(32000) : toPcm16k(chunks, call.rate);
  let heard;
  try {
    heard = await sendVoice(pcm, { speak: true, inCall: true });
  } catch (error) {
    if (error instanceof Unpaired) {
      endCall();
      return unpaired();
    }
    call.hint = error.shown ? error.message : "Couldn't send that: your computer can't be reached. Say it again?";
    return listen();
  }
  if (!call.on) { // hung up meanwhile: its reply isn't said
    S.cut = S.asked;
    if (heard) api("POST", "/api/stop").catch(() => {});
    return;
  }
  if (!heard) {
    call.hint = "Abdoh didn't catch that. Say it again?";
    return listen(0);
  }
  call.you = heard;
  if (call.state === "sending") {
    call.state = "thinking";
    call.abdoh = "";
  }
  showCall();
  turnOver();
}

/* A sentence of the reply starts (quietly, while you talk over it). */
function callSays(text) {
  if (!ANSWERING.includes(call.state)) return;
  if (!["over", "checking"].includes(call.state)) call.state = "speaking";
  call.abdoh = text;
  showCall();
}

/* Abdoh answered everything it was asked, and said it all: your turn again. */
function turnOver() {
  if (!call.on || !["thinking", "speaking"].includes(call.state)) return;
  if (S.answered >= S.asked && !player.playing && !player.queue.length) listen();
}

/* The circle: stop Abdoh and talk (what you already said over it is kept), or unmute. */
function tapOrb() {
  if (!call.on) return;
  if (call.muted) return toggleMute();
  if (![...OVER, "over"].includes(call.state)) return;
  S.cut = S.asked;
  silence();
  api("POST", "/api/stop").catch(() => {});
  call.abdoh = "";
  if (call.state !== "over") return listen(250);
  call.state = "hearing";
  showCall();
}

function toggleMute() {
  if (!call.on) return;
  call.muted = !call.muted;
  if (call.stream) call.stream.getAudioTracks().forEach((track) => { track.enabled = !call.muted; });
  if (["listening", "hearing"].includes(call.state)) listen(0); // what you were saying is dropped
  else if (call.state === "over") backToAnswer();
  showCall();
}

function endCall(why = "") {
  if (!call.on) return;
  const busy = S.answered < S.asked || player.playing || ["sending", "checking"].includes(call.state);
  const seconds = Math.floor((Date.now() - call.started) / 1000);
  call.on = false;
  clearInterval(call.timer);
  clearTimeout(call.demo);
  if (call.node) { call.node.disconnect(); call.node.onaudioprocess = null; }
  if (call.source) call.source.disconnect();
  if (call.stream) call.stream.getTracks().forEach((track) => track.stop()); // the microphone is free
  call.node = call.source = call.stream = null;
  call.state = "";
  keepAwake(false);
  silence();
  S.cut = S.asked;
  if (busy) api("POST", "/api/stop").catch(() => {});
  $("#call").hidden = true;
  dockCall();
  note(why || `Call with Abdoh · ${clock(seconds)}`);
  render();
  scrollDown(true);
}

/* The screen stays on during a call where the phone allows it (a locked phone ends the call). */
async function keepAwake(on) {
  try {
    if (!on) {
      if (call.lock) call.lock.release();
      call.lock = null;
    } else if (!call.lock && "wakeLock" in navigator) call.lock = await navigator.wakeLock.request("screen");
  } catch (error) {
    call.lock = null; // not on this phone: it may dim
  }
}

const CALL_STATE = { listening: "Listening…", hearing: "Listening…", sending: "Thinking…", speaking: "Answering",
  over: "Listening…", checking: "One moment…", muted: "Muted" };
const CALL_HINT = { listening: "Talk whenever you like", hearing: "Pause when you're done", over: "Pause when you're done",
  thinking: "Talk or tap the circle to cut in", speaking: "Talk or tap the circle to cut in", muted: "Abdoh can't hear you" };
const NOISY_HINT = "It's noisy here: tap the circle to cut in";

function showCall() {
  if (!call.on) return;
  const now = Date.now();
  if (call.state === "listening" && now - call.idle > CALL.quietEndMs) return endCall("The call ended after five quiet minutes.");
  const state = call.muted && ["listening", "hearing"].includes(call.state) ? "muted" : call.state;
  $("#call").dataset.state = state;
  $("#call-time").textContent = clock(Math.floor((now - call.started) / 1000));
  let level = 0;
  if (state === "hearing" || state === "over") level = DEMO ? 0.45 + 0.35 * Math.sin(now / 140) : call.level;
  else if (state === "listening") level = DEMO ? 0.04 : call.level;
  $("#orb").style.setProperty("--level", level.toFixed(3));
  const offline = S.online === false;
  const thinking = S.activity ? `${S.activity}…`.replace(/\.+…$/, "…") : "Thinking…";
  $("#call-state").textContent = offline ? "Can't reach your computer" : state === "thinking" ? thinking : CALL_STATE[state] || "";
  const hint = call.overOff && OVER.includes(state) ? NOISY_HINT : CALL_HINT[state];
  $("#call-hint").textContent = offline ? "Trying again…" : call.hint || hint || "";
  $("#call-you").textContent = call.you ? `“${call.you}”` : "";
  $("#call-abdoh").textContent = call.abdoh;
  $("#call-bar-state").textContent = $("#call-state").textContent;
  $("#call-bar-time").textContent = `On a call · ${$("#call-time").textContent}`;
  $("#call-bar-mute").setAttribute("aria-pressed", call.muted ? "true" : "false");
  $("#call-bar").dataset.state = state;
  $("#call-mute").setAttribute("aria-pressed", call.muted ? "true" : "false");
  $("#call-mute-label").textContent = call.muted ? "Unmute" : "Mute";
  $("#orb").setAttribute("aria-label", call.muted ? "Unmute" : ["thinking", "speaking"].includes(state) ? "Talk now" : "Abdoh is listening");
}

/* The demo has no microphone: "you" talk a moment after Abdoh starts listening. */
function demoTalk() {
  call.demo = setTimeout(() => {
    if (call.state !== "listening" || call.muted) return;
    call.state = "hearing";
    call.demo = setTimeout(() => { if (call.state === "hearing") sendTurn([]); }, 2200);
  }, 1800);
}

/* ---------- the page's controls ---------- */

function setupComposer() {
  const text = $("#text");
  const grow = () => {
    text.style.height = "auto";
    text.style.height = `${Math.min(text.scrollHeight, 140)}px`;
    text.style.overflowY = text.scrollHeight > 140 ? "auto" : "hidden";
    render();
  };
  text.addEventListener("input", grow);
  text.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      $("#form").requestSubmit();
    }
  });
  $("#form").addEventListener("submit", (e) => {
    e.preventDefault();
    unlockAudio(); // a tap: the reply may be heard
    const value = text.value;
    text.value = "";
    grow();
    send(value);
  });
  $("#stop").addEventListener("click", stop);
  $("#mic").addEventListener("click", startRecording);
  $("#rec-send").addEventListener("click", () => stopRecording(true));
  $("#cancel").addEventListener("click", () => stopRecording(false));
  $("#attach").addEventListener("click", pickFile);
  $("#attach-input").addEventListener("change", (e) => attach(e.target.files && e.target.files[0]));
  $("#attached-remove").addEventListener("click", dropAttached);
  $("#call-button").addEventListener("click", startCall);
  $("#orb").addEventListener("click", tapOrb);
  $("#call-mute").addEventListener("click", toggleMute);
  $("#hang-up").addEventListener("click", () => endCall());
  for (const button of document.querySelectorAll("[data-answer]")) {
    button.addEventListener("click", () => send(button.dataset.answer === "yes" ? "Yes" : "No", { withFile: false }));
  }
}

/* ---------- quick controls: music, volume, modes, locking ---------- */

const MEDIA_DONE = { play_pause: "Play or pause", next: "Next", previous: "Previous", volume_up: "Louder",
  volume_down: "Quieter", mute: "Mute" };

function toast(text) {
  const box = $("#toast");
  box.textContent = text;
  box.hidden = false;
  clearTimeout(box.timer);
  box.timer = setTimeout(() => { box.hidden = true; }, 1600);
}

async function control(kind, value = "") {
  try {
    await api("POST", "/api/control", { kind, value, speak: S.speak });
    return true;
  } catch (error) {
    $("#controls").hidden = true;
    failed(error);
    return false;
  }
}

async function openControls() {
  const sheet = $("#controls");
  sheet.hidden = false;
  const box = $("#modes");
  box.replaceChildren(el("span", { class: "muted" }, "…"));
  let data = { modes: [], mode: "" };
  try { data = await api("GET", "/api/controls"); } catch (error) { if (error instanceof Unpaired) return unpaired(); }
  $("#modes-group").hidden = !(data.modes || []).length;
  const pick = (name) => async () => {
    if (await control("mode", name)) {
      sheet.hidden = true;
      toast(name ? `${name} mode` : "Back to normal");
    }
  };
  box.replaceChildren(
    el("button", { class: `chip${data.mode ? "" : " on"}`, onclick: pick("") }, "Normal"),
    ...(data.modes || []).map((name) => el("button", { class: `chip${name === data.mode ? " on" : ""}`, onclick: pick(name) }, name)));
}

function setupControls() {
  const sheet = $("#controls");
  $("#controls-button").addEventListener("click", openControls);
  $("#controls-close").addEventListener("click", () => { sheet.hidden = true; });
  sheet.addEventListener("click", (e) => { if (e.target === sheet) sheet.hidden = true; });
  for (const key of document.querySelectorAll("[data-media]")) {
    key.addEventListener("click", async () => {
      if (await control("media", key.dataset.media)) toast(MEDIA_DONE[key.dataset.media]);
    });
  }
  $("#see-screen").addEventListener("click", () => openLive("follow"));
  $("#viewer-live").addEventListener("click", () => openLive("follow"));
  $("#live-close").addEventListener("click", closeLive);
  $("#live-shot").addEventListener("click", livePicture);
  $("#live-stage").addEventListener("click", () => $("#live").classList.toggle("bare"));
  $("#call-bar-back").addEventListener("click", backToCall);
  $("#call-bar-mute").addEventListener("click", () => toggleMute());
  $("#call-bar-end").addEventListener("click", () => endCall());
  $("#board-close").addEventListener("click", closeBoard);
  $("#board-pdf").addEventListener("click", boardPdf);
  $("#codoh-close").addEventListener("click", closeCodoh);
  $("#codoh-back").addEventListener("click", showChats);
  $("#codoh-form").addEventListener("submit", sendCodoh);
  $("#codoh-stop").addEventListener("click", stopCodoh);
  $("#codoh-text").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#codoh-form").requestSubmit(); }
  });
  $("#clipboard").addEventListener("click", openClipboard);
  $("#clip-copy").addEventListener("click", copyHere);
  $("#clip-send").addEventListener("click", sendClipboard);
  $("#clip-close").addEventListener("click", () => { $("#clip").hidden = true; });
  $("#clip").addEventListener("click", (e) => { if (e.target.id === "clip") $("#clip").hidden = true; });
  $("#viewer-close").addEventListener("click", closeViewer);
  $("#viewer").addEventListener("click", (e) => { if (e.target.id === "viewer") closeViewer(); });
  $("#lock").addEventListener("click", async () => {
    if (!confirm("Lock your computer now?")) return;
    if (await control("lock")) { sheet.hidden = true; toast("Locked"); }
  });
}

function setupMenu() {
  const menu = $("#menu");
  const speak = $("#speak");
  speak.checked = S.speak;
  speak.addEventListener("change", () => {
    S.speak = speak.checked;
    localStorage.setItem(SPEAK, S.speak ? "1" : "0");
  });
  $("#menu-button").addEventListener("click", () => { menu.hidden = false; });
  $("#open-codoh").addEventListener("click", () => openCodoh());
  $("#open-settings").addEventListener("click", openSettings);
  $("#settings-close").addEventListener("click", closeSettings);
  $("#menu-close").addEventListener("click", () => { menu.hidden = true; });
  menu.addEventListener("click", (e) => { if (e.target === menu) menu.hidden = true; });
  $("#unpair").addEventListener("click", async () => {
    if (!confirm("Unpair this phone? To use Abdoh here again, you'll pair it again from your computer.")) return;
    menu.hidden = true;
    try { await api("POST", "/api/forget"); } catch (error) { /* unpaired anyway */ }
    unpaired("This phone is unpaired.");
  });
}

/* The page fills what's visible, also with the keyboard open (iPhone). */
function fitToScreen() {
  const view = window.visualViewport;
  const fit = () => {
    const app = $("#app");
    app.style.setProperty("--app-height", `${view ? view.height : window.innerHeight}px`);
    app.style.top = view ? `${view.offsetTop}px` : "0px";
  };
  fit();
  if (view) {
    view.addEventListener("resize", fit);
    view.addEventListener("scroll", fit);
  } else window.addEventListener("resize", fit);
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden && call.on) endCall("The call ended when Abdoh went to the background.");
  if (!document.hidden && S.wake) S.wake(); // back in the app: try again now
});

setupComposer();
setupControls();
setupMenu();
start();
