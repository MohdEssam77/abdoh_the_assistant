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
  speak: localStorage.getItem(SPEAK) !== "0",
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
  $("#messages").replaceChildren();
  for (const line of state.history || []) addLine(line);
  setAi(state.ai || {});
  setMode(state.mode || "");
  S.status = state.status || "";
  online(true);
  scrollDown(true);
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
    case "clear": $("#messages").replaceChildren(); S.live = null; updateEmpty(); break;
    case "status": S.status = event.text || ""; S.activity = ""; render(); break;
    case "activity":
    case "aside": S.activity = event.text || ""; render(); break;
    case "ai": setAi(event); break;
    case "mode": setMode(event.name || ""); break;
    case "say": addSaid(event); break;
    case "question": askQuestion(event.text || ""); break;
    default: break;
  }
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
    S.final = true;
    S.activity = "";
  } else {
    const fromPhone = who === "You (phone)";
    const sent = fresh && fromPhone ? takePending(text) : null;
    if (!sent) bubble("you", text, fromPhone ? null : "On the computer");
    S.live = null;
    S.final = false;
    hideQuestion();
  }
  render();
  scrollDown();
}

/* A sentence of the reply to this phone: shown, and said if this phone asked and speaks. */
function addSaid(event) {
  if (S.speak && event.for === S.me) play(event);
  if (S.final) return; // already shown whole (a short reply comes whole, then is said)
  if (!S.live) S.live = bubble("abdoh", "");
  const text = S.live.querySelector(".text");
  text.textContent = text.textContent ? `${text.textContent} ${event.text}` : event.text;
  S.activity = "";
  render();
  scrollDown();
}

function bubble(who, text, label = null) {
  const node = el("div", { class: `msg ${who}` },
    el("div", { class: "bubble" }, label ? el("span", { class: "from" }, label) : null, el("span", { class: "text" }, text)));
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
  found.node.querySelector(".text").textContent = text;
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
  const empty = !$("#text").value.trim();
  const talking = S.busy || player.playing;
  $("#form").hidden = rec.on;
  $("#recording").hidden = !rec.on;
  $("#stop").hidden = !(talking && empty);
  $("#mic").hidden = !(empty && !talking);
  $("#send").hidden = empty;
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

async function send(text) {
  text = text.trim();
  if (!text) return;
  silence(); // a new question: the last answer stops
  const node = bubble("you", text);
  node.classList.add("pending");
  S.pending.push({ node, text: same(text) });
  S.final = false;
  S.live = null;
  hideQuestion();
  render();
  scrollDown(true);
  try {
    await api("POST", "/api/text", { text, speak: S.speak });
  } catch (error) {
    S.pending = S.pending.filter((p) => p.node !== node);
    node.classList.remove("pending");
    S.final = true;
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
  render();
  try { await api("POST", "/api/stop"); } catch (error) { failed(error); }
}

/* ---------- hearing Abdoh's replies ----------
   Its own voice (a WAV from your computer) when it has a natural voice, else the phone's.
   A phone only plays sound after a tap: the first tap (send, talk) unlocks it. */

const player = { ctx: null, queue: [], playing: false, source: null, turn: 0, unlocked: false };

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
    return;
  }
  player.playing = true;
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
    source.connect(ctx.destination);
    source.onended = resolve;
    player.source = source;
    source.start();
  });
}

function speakHere(text) {
  return new Promise((resolve) => {
    if (DEMO || !("speechSynthesis" in window)) return resolve(); // the demo stays quiet
    const line = new SpeechSynthesisUtterance(text);
    line.onend = resolve;
    line.onerror = resolve;
    speechSynthesis.speak(line);
  });
}

function silence() {
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

async function startRecording() {
  unlockAudio();
  silence();
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    return failed({ shown: true, message: "The microphone can't be used here. Open Abdoh from your Home Screen (or over https)." });
  }
  try {
    rec.stream = DEMO ? null : await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  } catch (error) {
    return failed({ shown: true, message: error && error.name === "NotAllowedError"
      ? "Abdoh may not use the microphone. Allow it for Abdoh (Settings → Safari → Microphone on an iPhone), then try again."
      : "The microphone isn't available right now." });
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
  const seconds = Math.floor(ms / 1000);
  $("#rec-time").textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
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

async function sendVoice(pcm) {
  const node = bubble("you", "…");
  node.classList.add("pending");
  const pending = { node, text: "", voice: true };
  S.pending.push(pending);
  S.final = false;
  S.live = null;
  hideQuestion();
  render();
  scrollDown(true);
  try {
    const data = await api("POST", `/api/voice${S.speak ? "?speak=1" : ""}`, pcm, { timeout: 60000 });
    if (!data.text && S.pending.includes(pending)) {
      S.pending = S.pending.filter((p) => p !== pending);
      node.remove();
      S.final = true;
      note("Abdoh didn't catch that. Try again, a little closer to the phone.");
      render();
    }
  } catch (error) {
    S.pending = S.pending.filter((p) => p !== pending);
    node.remove();
    S.final = true;
    failed(error);
  }
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
  for (const button of document.querySelectorAll("[data-answer]")) {
    button.addEventListener("click", () => send(button.dataset.answer === "yes" ? "Yes" : "No"));
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
  if (!document.hidden && S.wake) S.wake(); // back in the app: try again now
});

setupComposer();
setupControls();
setupMenu();
start();
