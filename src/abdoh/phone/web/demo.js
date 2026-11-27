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
      return;
    }
    const sentences = /lamp|light/.test(lower) ? ["The desk lamp is off now."]
      : ["Here's a quick plan for tonight.", "Start the pasta water now, it takes about ten minutes.", "Then chop the garlic while you wait."];
    later(400, { type: "aside", text: "Searching the web" });
    sentences.forEach((s, i) => later(1300 + i * 900, { type: "say", text: s, audio: null, for: "demo-phone" }));
    later(1300 + sentences.length * 900, { type: "history", line: `Abdoh: ${sentences.join(" ")}` });
    later(1400 + sentences.length * 900, { type: "status", text: "Listening" });
  }

  window.AbdohDemo = {
    key: () => (kind === "pair" || kind === "install" ? null : "demo-key"),
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
      if (path === "/api/text") { answer(body.text); return { ok: true, text: body.text }; }
      if (path.startsWith("/api/voice")) {
        const heard = "turn off the desk lamp";
        setTimeout(() => answer(heard), 700);
        return { ok: true, text: heard };
      }
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
