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
  S.answered = S.asked; // what was being answered is over (or Abdoh restarted)
  $("#messages").replaceChildren();
  for (const line of state.history || []) addLine(line);
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
    case "clear": $("#messages").replaceChildren(); S.live = null; updateEmpty(); break;
    case "status": S.status = event.text || ""; S.activity = ""; render(); break;
    case "activity":
    case "aside": S.activity = event.text || ""; render(); break;
    case "ai": setAi(event); break;
    case "mode": setMode(event.name || ""); break;
    case "say": addSaid(event); break;
    case "question": askQuestion(event.text || ""); break;
    case "done": if (event.for === S.me) { S.answered += 1; turnOver(); } break;
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
    if (call.on && call.state === "thinking") call.abdoh = text; // done without words: shown
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

/* A sentence of the reply to this phone: shown, and said if this phone asked and speaks (on a
   call, always). Not the rest of a reply that was stopped. */
function addSaid(event) {
  const wanted = call.on ? ["sending", "thinking", "speaking"].includes(call.state) : S.speak;
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
    S.asked += 1;
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
  S.cut = S.asked;
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
    source.connect(ctx.destination);
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
  const node = bubble("you", "…");
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
    render();
  };
  let data;
  try {
    data = await api("POST", `/api/voice${speak ? "?speak=1" : ""}`, pcm, { timeout: 60000 });
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

/* ---------- a call: back and forth by voice, hands-free (story 145) ----------
   The phone button in the header starts it. Abdoh listens; when you pause, what you said is
   sent, the reply is said here, and it listens again, until you hang up. The microphone stays
   open for the whole call (one permission), but what it hears while Abdoh answers is ignored,
   so its own voice is never taken for yours: tap the circle to talk over it. */

const CALL = {
  frame: 2048,
  preRollMs: 350, // kept from just before you started: the first word isn't cut off
  startMs: 120, // this much sound above the room's hum: you're talking
  endMs: 1200, // then this long quiet: your turn is over
  minSpeechMs: 300, // less: a knock or a cough, not words
  maxTurnMs: 45000,
  graceMs: 450, // after Abdoh's voice (or the microphone opening): its echo dies away
  quietEndMs: 5 * 60000, // nobody talked this long: the call ends
};
const call = {
  on: false, state: "", muted: false, stream: null, source: null, node: null, rate: 48000,
  ear: newEar(), pre: [], chunks: [], level: 0,
  armed: 0, idle: 0, started: 0, timer: null, demo: null, lock: null, you: "", abdoh: "", hint: "",
};

/* The call's ear: how loud the room is (`floor`), and your turn so far. */
function newEar(floor = 0.004) {
  return { floor, talking: false, loudMs: 0, speechMs: 0, quietMs: 0, totalMs: 0 };
}

/* One block from the microphone (its loudness and length): "start" when you started talking,
   "end" when you've stopped, "drop" when it was only a knock or a cough, else null. */
function earStep(ear, rms, ms) {
  const loud = Math.max(0.015, ear.floor * 3);
  if (!ear.talking) {
    ear.floor += (rms - ear.floor) * (rms < ear.floor ? 0.1 : 0.004); // follows the room's hum
    ear.loudMs = rms > loud ? ear.loudMs + ms : 0;
    if (ear.loudMs < CALL.startMs) return null;
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
  Object.assign(call, { on: true, muted: false, stream, started: Date.now(), ear: newEar(), you: "", abdoh: "", hint: "" });
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

/* Every block from the microphone: did you start talking, and have you stopped? */
function hearFrame(data) {
  if (!call.on) return;
  let sum = 0;
  for (let i = 0; i < data.length; i += 4) sum += data[i] * data[i];
  const rms = Math.sqrt(sum / Math.ceil(data.length / 4));
  call.level = call.muted ? 0 : Math.min(1, rms * 6);
  if (call.muted || !["listening", "hearing"].includes(call.state)) return;
  const ear = call.ear;
  if (Date.now() < call.armed) { // not yet: learn how loud the room is meanwhile
    if (call.state === "listening") ear.floor += (rms - ear.floor) * 0.2;
    return;
  }
  const ms = (data.length / call.rate) * 1000;
  const heard = earStep(ear, rms, ms);
  if (call.state === "listening") {
    call.pre.push(new Float32Array(data));
    while (call.pre.length * ms > CALL.preRollMs) call.pre.shift();
    if (heard === "start") Object.assign(call, { state: "hearing", chunks: call.pre, pre: [], hint: "" });
    return;
  }
  call.chunks.push(new Float32Array(data));
  if (heard === "drop") return listen(0);
  if (heard !== "end") return;
  const extra = Math.floor(Math.max(0, ear.quietMs - 300) / ms); // most of the quiet at the end
  sendTurn(call.chunks.slice(0, call.chunks.length - extra));
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

/* A sentence of the reply starts. */
function callSays(text) {
  if (!["sending", "thinking", "speaking"].includes(call.state)) return;
  call.state = "speaking";
  call.abdoh = text;
  showCall();
}

/* Abdoh answered everything it was asked, and said it all: your turn again. */
function turnOver() {
  if (!call.on || !["thinking", "speaking"].includes(call.state)) return;
  if (S.answered >= S.asked && !player.playing && !player.queue.length) listen();
}

/* The circle: talk over Abdoh (it stops), or unmute. */
function tapOrb() {
  if (!call.on) return;
  if (call.muted) return toggleMute();
  if (!["thinking", "speaking"].includes(call.state)) return;
  S.cut = S.asked;
  silence();
  api("POST", "/api/stop").catch(() => {});
  call.abdoh = "";
  listen(250);
}

function toggleMute() {
  if (!call.on) return;
  call.muted = !call.muted;
  if (call.stream) call.stream.getAudioTracks().forEach((track) => { track.enabled = !call.muted; });
  if (["listening", "hearing"].includes(call.state)) listen(0); // what you were saying is dropped
  showCall();
}

function endCall(why = "") {
  if (!call.on) return;
  const busy = S.answered < S.asked || player.playing || call.state === "sending";
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

const CALL_STATE = { listening: "Listening…", hearing: "Listening…", sending: "Thinking…", speaking: "Answering", muted: "Muted" };
const CALL_HINT = { listening: "Talk whenever you like", hearing: "Pause when you're done", thinking: "Tap the circle to stop it",
  speaking: "Tap the circle to talk", muted: "Abdoh can't hear you" };

function showCall() {
  if (!call.on) return;
  const now = Date.now();
  if (call.state === "listening" && now - call.idle > CALL.quietEndMs) return endCall("The call ended after five quiet minutes.");
  const state = call.muted && ["listening", "hearing"].includes(call.state) ? "muted" : call.state;
  $("#call").dataset.state = state;
  $("#call-time").textContent = clock(Math.floor((now - call.started) / 1000));
  let level = 0;
  if (state === "hearing") level = DEMO ? 0.45 + 0.35 * Math.sin(now / 140) : call.level;
  else if (state === "listening") level = DEMO ? 0.04 : call.level;
  $("#orb").style.setProperty("--level", level.toFixed(3));
  const offline = S.online === false;
  const thinking = S.activity ? `${S.activity}…`.replace(/\.+…$/, "…") : "Thinking…";
  $("#call-state").textContent = offline ? "Can't reach your computer" : state === "thinking" ? thinking : CALL_STATE[state] || "";
  $("#call-hint").textContent = offline ? "Trying again…" : call.hint || CALL_HINT[state] || "";
  $("#call-you").textContent = call.you ? `“${call.you}”` : "";
  $("#call-abdoh").textContent = call.abdoh;
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
  $("#call-button").addEventListener("click", startCall);
  $("#orb").addEventListener("click", tapOrb);
  $("#call-mute").addEventListener("click", toggleMute);
  $("#hang-up").addEventListener("click", () => endCall());
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
  if (document.hidden && call.on) endCall("The call ended when Abdoh went to the background.");
  if (!document.hidden && S.wake) S.wake(); // back in the app: try again now
});

setupComposer();
setupControls();
setupMenu();
start();
