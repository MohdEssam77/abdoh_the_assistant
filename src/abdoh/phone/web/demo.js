/* The phone page with made-up data, for checking it in a browser: phone.js loads this file only
   with ?demo. ?demo=pair, ?demo=install, ?demo=offline and ?demo=empty show those states. */
"use strict";

(() => {
  const kind = new URLSearchParams(location.search).get("demo") || "";
  const events = [];
  let seq = 0;
  let waiting = null;
  const history = kind === "empty" ? [] : [
    "You: turn on the desk lamp",
    "Abdoh: The desk lamp is on.",
    "You (phone): what's the weather tomorrow in Berlin?",
    "Abdoh: Tomorrow in Berlin it's cloudy, 4 to 9 degrees, with rain likely in the afternoon. Take an umbrella.",
    "You (phone): play some jazz on the computer",
    "Abdoh: Playing jazz on YouTube.",
  ];

  function push(event) {
    events.push({ seq: ++seq, ...event });
    if (waiting) { const wake = waiting; waiting = null; wake(); }
  }

  const later = (ms, event) => setTimeout(() => push(event), ms);

  function answer(text) {
    const lower = text.toLowerCase();
    push({ type: "history", line: `You (phone): ${text}` });
    push({ type: "status", text: "Thinking..." });
    if (/shut ?down/.test(lower)) {
      later(500, { type: "history", line: "Abdoh: Shut down the computer now?" });
      later(520, { type: "say", text: "Shut down the computer now?", audio: null, for: "demo-phone" });
      later(540, { type: "question", text: "Shut down the computer now?" });
      later(560, { type: "status", text: "Listening" });
      later(580, { type: "done", for: "demo-phone" });
      return;
    }
    if (/board|explain/.test(lower)) { // shown on the board, written out while it's said
      BOARD.forEach((_, i) => later(600 + i * 1500, { type: "board", card: { id: 7, text: BOARD.slice(0, i + 1).join("\n\n") } }));
      ["Merge sort splits the list in half until each piece has one number.", "Then it merges the pieces back, in order.",
        "Each level of merging touches every number once, so it's n log n."]
        .forEach((t, i) => later(900 + i * 1600, { type: "say", text: t, audio: null, for: "demo-phone" }));
      later(5600, { type: "history", line: "Abdoh: Merge sort splits the list in half until each piece has one number. Then it merges the pieces back, in order. Each level of merging touches every number once, so it's n log n." });
      later(5700, { type: "status", text: "Listening" });
      later(5750, { type: "done", for: "demo-phone" });
      return;
    }
    if (/^open/.test(lower)) { // opened on the computer: the screen comes a moment later
      later(300, { type: "step", text: "Opened Music", for: "demo-phone" });
      later(700, { type: "history", line: "Abdoh: Done: open app Music." });
      later(760, { type: "status", text: "Listening" });
      later(800, { type: "done", for: "demo-phone" });
      later(1900, { type: "image", id: "demo-shot", src: picture(), caption: "Opened Music · Screen 2 · HP 32f", for: "demo-phone" });
      later(1950, { type: "live", screen: "2", for: "demo-phone" });
      return;
    }
    const sentences = /lamp|light/.test(lower) ? ["The desk lamp is off now."]
      : /vegetarian/.test(lower) ? ["Good news, it already is.", "Add a handful of spinach at the end if you like."]
      : /dinner|cook/.test(lower) ? ["How about pasta tonight?", "You have spaghetti and garlic, so aglio e olio works.", "Want the steps?"]
        : /steps|quick|yes/.test(lower) ? ["Sure.", "Boil salted water and cook the spaghetti for nine minutes.",
          "Meanwhile, fry sliced garlic in olive oil until it's golden.", "Then toss it all together with a splash of the pasta water."]
          : ["Here's a quick plan for tonight.", "Start the pasta water now, it takes about ten minutes.", "Then chop the garlic while you wait."];
    const steps = /lamp|light/.test(lower) ? ["Lamp: desk | off"]
      : ["Searching the web: quick pasta recipes with garlic", "Reading bbcgoodfood.com", "Looking for *recipes*.pdf"];
    later(400, { type: "aside", text: /lamp|light/.test(lower) ? "" : "Searching the web" });
    steps.forEach((s, i) => later(350 + i * 300, { type: "step", text: s, for: "demo-phone" }));
    sentences.forEach((s, i) => later(1300 + i * 900, { type: "say", text: s, audio: null, for: "demo-phone" }));
    later(1300 + sentences.length * 900, { type: "history", line: `Abdoh: ${sentences.join(" ")}` });
    later(1400 + sentences.length * 900, { type: "status", text: "Listening" });
    later(1450 + sentences.length * 900, { type: "done", for: "demo-phone" });
  }

  // Codoh in the demo: three chats, one working and waiting for an OK.
  const now = Date.now() / 1000;
  const codoh = {
    rev: 6,
    running: true,
    status: "Waiting for you",
    started: Date.now() - 41000,
    items: [
      { id: "i1", rev: 1, kind: "user", text: "Add a dark mode that follows the system setting, with a toggle in the header." },
      { id: "i2", rev: 2, kind: "assistant", text: "I'll look at how the styles are set up first." },
      { id: "i3", rev: 3, kind: "tool", kind_of: "read", title: "src/styles/theme.css", status: "done", ok: true },
      { id: "i4", rev: 4, kind: "tool", kind_of: "edit", title: "src/styles/theme.css", status: "done", ok: true,
        diff: "@@ -8,6 +8,14 @@\n :root {\n   --bg: #ffffff;\n   --text: #111827;\n }\n+@media (prefers-color-scheme: dark) {\n+  :root {\n+    --bg: #0f1115;\n+    --text: #eceef3;\n+  }\n+}" },
      { id: "i5", rev: 5, kind: "assistant", text: "The colours switch with the system now. I'll run the tests before adding the toggle." },
      { id: "i6", rev: 6, kind: "approval", tool: "Bash", kind_of: "command", title: "npm test", description: "Run the test suite", state: "waiting", suggestions: true },
    ],
  };
  const CHATS = [
    { id: "c1", title: "Add a dark mode", folder: "C:/code/portfolio", where: "portfolio", engine: "claude", model: "opus", updated: now - 60, running: true },
    { id: "c2", title: "Fix the contact form", folder: "C:/code/portfolio", where: "portfolio", engine: "claude", model: "sonnet", updated: now - 7200, running: false },
    { id: "c3", title: "Write tests for the parser", folder: "C:/code/notes-app", where: "notes-app", engine: "chatgpt", model: "", updated: now - 90000, running: false },
  ];

  function codohChange(item) {
    codoh.rev += 1;
    const at = codoh.items.findIndex((i) => i.id === item.id);
    const next = { ...item, rev: codoh.rev };
    if (at >= 0) codoh.items[at] = next;
    else codoh.items.push(next);
  }

  function codohAllowed(decision) {
    codohChange({ ...codoh.items.find((i) => i.id === "i6"), state: decision === "deny" ? "denied" : decision === "always" ? "always" : "allowed" });
    if (decision === "deny") { codoh.running = false; return; }
    codoh.status = "Running npm test";
    codohChange({ id: "i7", kind: "tool", kind_of: "command", title: "npm test" });
    setTimeout(() => {
      codohChange({ id: "i7", kind: "tool", kind_of: "command", title: "npm test", status: "done", ok: true,
        output: "PASS  src/theme.test.js\nPASS  src/header.test.js\n\nTests: 48 passed, 48 total\nTime:  3.2 s" });
      codohChange({ id: "i8", kind: "assistant", text: "All 48 tests pass. Next I'll add the toggle to the header." });
      codoh.status = "Writing";
    }, 1500);
  }

  // What the demo puts on the board, a part at a time.
  const BOARD = [
    "## Merge sort",
    "Split the list in half, sort each half, then **merge** the two sorted halves.",
    ["```mermaid", "graph TD", "  A[8 3 5 1] --> B[8 3]", "  A --> C[5 1]", "  B --> D[3 8]", "  C --> E[1 5]",
      "  D --> F[1 3 5 8]", "  E --> F", "```"].join("\n"),
    "Time: $O(n \\log n)$, because there are $\\log_2 n$ levels and each one does $n$ work.",
  ];

  // A made-up picture of the computer's screen: a desktop with a music app open.
  function picture() {
    const rows = ["Morning jazz", "Focus beats", "Late night piano", "Coffee house", "Sunday soul", "Rainy day"]
      .map((name, i) => `<rect x='470' y='${330 + i * 74}' width='960' height='62' rx='8' fill='${i === 0 ? "#1f3a2e" : "#181818"}'/>`
        + `<text x='500' y='${369 + i * 74}' fill='${i === 0 ? "#4ade80" : "#e5e5e5"}' font-size='24'>${i + 1}.  ${name}</text>`).join("");
    const svg = `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1600 1000' font-family='Segoe UI, Arial, sans-serif'>`
      + "<rect width='1600' height='1000' fill='#22384d'/><rect x='120' y='60' width='1360' height='850' rx='14' fill='#121212'/>"
      + "<rect x='120' y='60' width='1360' height='46' rx='14' fill='#1f1f1f'/><text x='150' y='91' fill='#ccc' font-size='19'>Music</text>"
      + "<rect x='120' y='106' width='310' height='804' fill='#0a0a0a'/><text x='160' y='170' fill='#fff' font-size='26' font-weight='700'>Home</text>"
      + "<text x='160' y='220' fill='#9ca3af' font-size='22'>Search</text><text x='160' y='265' fill='#9ca3af' font-size='22'>Your library</text>"
      + "<rect x='470' y='140' width='150' height='150' rx='10' fill='#0d9668'/><text x='650' y='200' fill='#fff' font-size='44' font-weight='800'>Jazz for the evening</text>"
      + `<text x='650' y='250' fill='#9ca3af' font-size='22'>Playlist · 6 songs</text>${rows}`
      + "<rect x='0' y='952' width='1600' height='48' fill='#0b1220'/><circle cx='800' cy='976' r='12' fill='#60a5fa'/></svg>";
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  }

  // Abdoh's own settings, as the computer would send them.
  const n = (key, label, value, low, high, step, unit, help = "") => ({ key, label, value, low, high, step, unit, help, kind: "number", choices: [] });
  const b = (key, label, value, help = "") => ({ key, label, value, help, kind: "bool", choices: [] });
  const c = (key, label, value, choices, help = "") => ({ key, label, value, help, kind: "choice", choices });
  const SETTINGS = [
    { title: "Voice", settings: [n("tts_rate", "Speed", 175, 120, 260, 5, "words a minute", "How fast Abdoh talks."),
      c("piper_voice_en", "English voice", "en_US-lessac-medium", [["en_US-lessac-medium", "Lessac (American)"], ["en_GB-jenny_dioco-medium", "Jenny Dioco (British)"]], "Abdoh's voice in English.")] },
    { title: "Conversation", settings: [c("confirm_actions", "When it does something for you", "sound", [["sound", "A short sound"], ["words", "Say what it did"]], "After “open Spotify”: a short sound, or it says what it did."),
      n("claude.voice_reply_max_sentences", "Longest spoken answer", 4, 1, 20, 1, "sentences", "How many sentences an answer may have, at most."),
      b("voice_interrupts", "Stop when I start talking", true, "Abdoh goes quiet as soon as it hears you."),
      c("voice_interrupt_sensitivity", "How easily your voice stops Abdoh", "medium", [["low", "Low"], ["medium", "Medium"], ["high", "High"]], "Higher reacts sooner; lower is for loud rooms."),
      b("duck_others", "Lower other sounds while I talk to Abdoh", true, "Music and videos go quieter while Abdoh listens and answers.")] },
    { title: "Memory", settings: [b("memory", "Remember things about me", true, "Abdoh remembers what you tell it."), n("conversation_days", "How long conversations are kept", 7, 1, 30, 1, "days")] },
  ];

  // What "you" say into the demo's microphone, in turn (a call goes on with the next).
  const SAID = ["help me plan dinner tonight", "yes, the quick steps please", "turn off the desk lamp"];
  let said = 0;

  window.AbdohDemo = {
    key: () => (kind === "pair" || kind === "install" ? null : "demo-key"),
    picture,
    async api(method, path, body) {
      await new Promise((r) => setTimeout(r, 60));
      if (path === "/api/pair") return { key: "demo-key" };
      if (path === "/api/state") {
        return { boot: "demo", seq, history, status: "Listening", phone: "iPhone", phone_id: "demo-phone",
          ai: { name: "Claude", label: "Claude", status: "Pro subscription" }, mode: kind === "empty" ? "" : "Work" };
      }
      if (path.startsWith("/api/events")) {
        if (kind === "offline") throw new TypeError("Failed to fetch");
        const after = Number(new URL(path, location.href).searchParams.get("after") || 0);
        if (!events.some((e) => e.seq > after)) await new Promise((r) => { waiting = r; setTimeout(r, 25000); });
        return { boot: "demo", seq, events: events.filter((e) => e.seq > after) };
      }
      if (path === "/api/text") {
        const text = (body.files || []).length ? `${body.text} [sent homework.jpg]`.trim() : body.text;
        answer(text);
        return { ok: true, text };
      }
      if (path === "/api/clipboard") return { ok: true, text: method === "GET" ? "Meeting moved to 3 pm, room 2.14" : "" };
      if (path.includes("over=1")) { // talked over the answer on a call: something new
        const heard = "actually, make it vegetarian";
        setTimeout(() => answer(heard), 700);
        return { ok: true, text: heard, kind: "request", heard: "request" };
      }
      if (path.startsWith("/api/voice")) {
        const heard = SAID[said++ % SAID.length];
        setTimeout(() => answer(heard), 700);
        return { ok: true, text: heard };
      }
      if (path === "/api/screen") return { ok: true, id: "demo" };
      if (path === "/api/settings" && method === "GET") return { ok: true, sections: SETTINGS };
      if (path === "/api/settings") return { ok: true, text: `${body.key}: ${body.value}`, restart: false };
      if (path === "/api/live/screens") {
        return { ok: true, screens: [{ id: "1", label: "Screen 1 · Laptop screen", primary: true },
          { id: "2", label: "Screen 2 · HP 32f", primary: false }, { id: "3", label: "Screen 3 · LG Ultrawide", primary: false }] };
      }
      if (path === "/api/board_pdf") {
        later(1600, { type: "file", id: "demo-pdf", src: "#", name: "Board 2026-11-28 21.40.pdf", size: 184320, kind: "pdf", for: "demo-phone" });
        return { ok: true };
      }
      if (path === "/api/codoh") {
        return { ok: true, chats: CHATS, folders: [{ path: "C:/code/portfolio", name: "portfolio" }, { path: "C:/code/notes-app", name: "notes-app" }], limited: "" };
      }
      if (path.startsWith("/api/codoh/chat")) {
        const url = new URL(path, location.href);
        const since = Number(url.searchParams.get("since") || 0);
        if (url.searchParams.get("id") !== "c1") {
          return { ok: true, chat: CHATS.find((c) => c.id === url.searchParams.get("id")), rev: 1, running: false, status: "", seconds: 0, queued: [],
            items: since ? [] : [{ id: "x1", rev: 1, kind: "user", text: "Fix the contact form: it sends twice." }, { id: "x2", rev: 1, kind: "assistant", text: "Fixed: the button now turns off while it sends." }, { id: "x3", rev: 1, kind: "done", seconds: 64 }] };
        }
        return { ok: true, chat: CHATS[0], rev: codoh.rev, running: codoh.running, status: codoh.status,
          seconds: (Date.now() - codoh.started) / 1000, queued: [], items: codoh.items.filter((i) => i.rev > since) };
      }
      if (path === "/api/codoh/answer") { codohAllowed(body.decision); return { ok: true }; }
      if (path === "/api/codoh/send") { codohChange({ id: `u${codoh.rev}`, kind: "user", text: body.text }); return { ok: true, queued: codoh.running }; }
      if (path === "/api/codoh/stop") { codoh.running = false; codohChange({ id: "stop", kind: "note", text: "Stopped." }); return { ok: true }; }
      if (path === "/api/stop") { push({ type: "status", text: "Listening" }); return { ok: true }; }
      if (path === "/api/controls") return { modes: ["Work", "Movie night", "Focus", "Gaming"], mode: kind === "empty" ? "" : "Work" };
      if (path === "/api/control" && body.kind === "mode") {
        push({ type: "mode", name: body.value });
        push({ type: "history", line: `Abdoh: ${body.value ? `${body.value} mode is on.` : "Back to normal."}` });
      }
      return { ok: true };
    },
  };
})();
