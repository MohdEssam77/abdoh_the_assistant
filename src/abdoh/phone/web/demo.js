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
    if (/^open/.test(lower)) { // opened on the computer: the screen comes a moment later
      later(300, { type: "step", text: "Opened Music", for: "demo-phone" });
      later(700, { type: "history", line: "Abdoh: Done: open app Music." });
      later(760, { type: "status", text: "Listening" });
      later(800, { type: "done", for: "demo-phone" });
      later(1900, { type: "image", id: "demo-shot", src: picture(), caption: "Opened Music", for: "demo-phone" });
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
      if (path === "/api/text") { answer(body.text); return { ok: true, text: body.text }; }
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
