/* The Catalog: everything Abdoh can do and how to use it (the content is abdoh/catalog.py). */
"use strict";

(() => {
  const COLORS = {
    talk: "#22c55e", do: "#f59e0b", claude: "#a78bfa", screen: "#3b82f6", roles: "#ec4899",
    home: "#eab308", memory: "#14b8a6", codoh: "#6366f1", abdoh: "#64748b",
  };
  const PATHS = {
    mic: '<rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7l1-8z"/>',
    sparkles: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
    eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    role: '<circle cx="12" cy="7.5" r="3.5"/><path d="M5 20.5a7 7 0 0 1 14 0"/><path d="M17.5 3.5l1.2 1.2M20 7h-1.5"/>',
    lamp: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z"/>',
    memory: '<path d="M12 5a3 3 0 0 0-5.9-.8A3 3 0 0 0 4 9.5a3 3 0 0 0 .8 5.3A3.5 3.5 0 0 0 9 20a3 3 0 0 0 3-2.5V5z"/><path d="M12 5a3 3 0 0 1 5.9-.8A3 3 0 0 1 20 9.5a3 3 0 0 1-.8 5.3A3.5 3.5 0 0 1 15 20a3 3 0 0 1-3-2.5"/>',
    code: '<path d="m8 7-5 5 5 5M16 7l5 5-5 5M13.5 4l-3 16"/>',
    settings: '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
    shield: '<path d="M12 3 4.5 6v6c0 4.5 3.2 7.7 7.5 9 4.3-1.3 7.5-4.5 7.5-9V6L12 3z"/><path d="m9 12 2 2 4-4"/>',
    chat: '<path d="M4 5h16v11H9l-5 4V5z"/>',
    wave: '<path d="M3 12h2l2-6 4 12 3-9 2 3h5"/>',
    pause: '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>',
    speaker: '<path d="M4 9v6h4l5 4V5L8 9H4z"/><path d="M16 9a4 4 0 0 1 0 6M19 6a8 8 0 0 1 0 12"/>',
    monitor: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    power: '<path d="M12 3v8M6.3 6.3a8 8 0 1 0 11.4 0"/>',
    key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M17 6l3 3M14 9l2 2"/>',
    swap: '<path d="M4 8h13l-3-3M20 16H7l3 3"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    board: '<rect x="3" y="4" width="18" height="12" rx="1.5"/><path d="M7 20l2-4M17 20l-2-4M7 9h6M7 12h9"/>',
    layers: '<path d="m12 3 9 5-9 5-9-5 9-5z"/><path d="m3 13 9 5 9-5"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    pencil: '<path d="M4 20h4L19 9l-4-4L4 16v4z"/><path d="m14 6 4 4"/>',
    log: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5h.01"/>',
    chip: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
    refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    play: '<path d="M7 4v16l13-8z"/>',
    bulb: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z"/>',
    book: '<path d="M4 4h6a2 2 0 0 1 2 2v14a2 2 0 0 0-2-2H4zM20 4h-6a2 2 0 0 0-2 2v14a2 2 0 0 1 2-2h6z"/>',
  };
  const ico = (name) => el("span", { class: "ct-ico", html: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${PATHS[name] || PATHS.info}</svg>` });

  const S = { data: null, section: "all", query: "" };

  function matches(f, words) {
    const text = [f.title, f.line, f.what, ...(f.say || []), ...(f.steps || []), ...(f.tips || []), f.where && f.where.label].join(" ").toLowerCase();
    return words.every((w) => text.includes(w));
  }

  function chip(status) {
    return el("span", { class: `ct-status ${status.state}` }, status.state === "on" ? "On" : status.text);
  }

  function card(f) {
    const color = COLORS[f.section] || "#64748b";
    return el("button", { class: `ct-card ${f.status.state}`, type: "button", style: `--c:${color}`, onclick: () => detail(f) },
      el("div", { class: "ct-card-top" }, el("span", { class: "ct-bubble" }, ico(f.icon)), chip(f.status)),
      el("b", { class: "ct-card-title" }, f.title),
      el("p", { class: "ct-card-line" }, f.line),
      (f.say || []).length ? el("div", { class: "ct-card-say" }, f.say.slice(0, 2).map((s) => el("span", {}, `“${s}”`))) : null);
  }

  function goTo(where) {
    if (!where) return;
    showPage(where.page);
    if (where.anchor) {
      setTimeout(() => {
        const target = $(where.anchor);
        if (!target) return;
        if (target.tagName === "DETAILS") target.open = true;
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 350);
    }
  }

  async function tryIt(text, dialog) {
    const sent = await call("send", text);
    if (sent === false) { toast("Abdoh is busy. Try again in a moment.", true); return; }
    if (dialog) dialog.close();
    showPage("home");
  }

  function detail(f) {
    const color = COLORS[f.section] || "#64748b";
    const section = (S.data.sections || []).find((s) => s.id === f.section) || {};
    const body = el("div", { class: "ct-detail", style: `--c:${color}` },
      el("div", { class: "ct-detail-head" },
        el("span", { class: "ct-bubble big" }, ico(f.icon)),
        el("div", {}, el("h2", {}, f.title)),
        chip(f.status)),
      el("p", { class: "ct-detail-what" }, f.what),
      f.status.state !== "on" ? el("p", { class: `ct-detail-note ${f.status.state}` },
        f.status.state === "off" ? `It's switched off right now: ${f.where ? f.where.label : "Settings"}.` : `${f.status.text} first: ${f.where ? f.where.label : "Settings"}.`) : null,
      (f.say || []).length ? el("div", { class: "ct-block" }, el("h3", {}, "Try saying"),
        el("div", { class: "ct-says" }, f.say.map((s) => el("button", {
          class: "ct-say", type: "button", title: "Copy",
          onclick: async () => { try { await navigator.clipboard.writeText(s); toast("Copied."); } catch (e) { toast(s); } },
        }, ico("chat"), `“${s}”`)))) : null,
      (f.steps || []).length ? el("div", { class: "ct-block" }, el("h3", {}, "How"),
        el("ol", { class: "ct-steps" }, f.steps.map((s) => el("li", {}, s)))) : null,
      (f.tips || []).length ? el("div", { class: "ct-block" }, el("h3", {}, "Good to know"),
        el("ul", { class: "ct-tips" }, f.tips.map((t) => el("li", {}, ico("bulb"), el("span", {}, t))))) : null);
    const actions = [
      f.where ? el("button", { class: "btn", type: "button", onclick: () => { dialog.close(); goTo(f.where); } }, ico("arrow"), f.where.label) : null,
      el("div", { class: "spacer" }),
      f.try ? el("button", { class: "btn primary", type: "button", onclick: () => tryIt(f.try, dialog) }, ico("play"), `Try “${f.try}”`) : null,
    ].filter(Boolean);
    const dialog = openModal({ title: section.title || "Catalog", body, actions, wide: true });
  }

  function hero(data) {
    const on = data.features.filter((f) => f.status.state === "on").length;
    const search = el("input", { id: "ct-search", placeholder: "What do you want to do? Try “timer”, “screen”, “code”…", value: S.query, "aria-label": "Search the Catalog", autocomplete: "off" });
    search.addEventListener("input", () => { S.query = search.value; drawList(); });
    search.addEventListener("keydown", (e) => { if (e.key === "Escape") { search.value = ""; S.query = ""; drawList(); } });
    return el("header", { class: "ct-hero" },
      el("div", { class: "ct-hero-glow" }),
      el("div", { class: "ct-hero-inner" },
        el("span", { class: "ct-hero-badge" }, ico("book"), "Catalog"),
        el("h1", {}, "Everything Abdoh can do"),
        el("p", {}, `${data.features.length} features, ${on} on right now. Find one, see what to say, and try it.`),
        el("label", { class: "ct-search" }, ico("search"), search, el("kbd", {}, "Esc"))));
  }

  function start(data) {
    return el("section", { class: "ct-start" },
      el("h2", { class: "ct-h2" }, "Start here"),
      el("div", { class: "ct-start-grid" }, data.start.map((s, i) => el("button", { class: "ct-step", type: "button", onclick: () => showPage(s.page) },
        el("span", { class: "ct-step-n" }, String(i + 1)),
        el("div", {}, el("b", {}, s.title), el("p", {}, s.line)),
        ico("arrow")))));
  }

  function pills(data) {
    const all = [{ id: "all", title: "Everything", icon: "sparkles" }, ...data.sections];
    return el("nav", { class: "ct-pills", "aria-label": "Sections" }, all.map((s) => el("button", {
      class: S.section === s.id ? "ct-pill on" : "ct-pill", type: "button", style: `--c:${COLORS[s.id] || "var(--accent)"}`,
      onclick: (e) => { S.section = s.id; const on = e.currentTarget; $$(".ct-pill").forEach((p) => p.classList.toggle("on", p === on)); drawList(); },
    }, ico(s.icon), s.title)));
  }

  function drawList() {
    const box = $("#ct-list");
    if (!box || !S.data) return;
    const start = $(".ct-start");
    if (start) start.hidden = !!S.query.trim();
    const words = S.query.toLowerCase().split(/\s+/).filter(Boolean);
    const sections = S.data.sections.filter((s) => S.section === "all" || S.section === s.id);
    const groups = sections.map((s) => [s, S.data.features.filter((f) => f.section === s.id && matches(f, words))]).filter(([, list]) => list.length);
    if (!groups.length) {
      box.replaceChildren(el("div", { class: "ct-none" },
        el("b", {}, "Nothing about that here yet"),
        el("p", {}, "Abdoh may still know: ask it."),
        S.query ? el("button", { class: "btn primary", type: "button", onclick: () => tryIt(`Can you help me ${S.query.trim()}?`) }, ico("chat"), `Ask Abdoh “can you help me ${S.query.trim()}?”`) : null));
      return;
    }
    box.replaceChildren(...groups.map(([s, list]) => el("section", { class: "ct-section", style: `--c:${COLORS[s.id]}` },
      el("div", { class: "ct-section-head" }, el("span", { class: "ct-bubble" }, ico(s.icon)), el("div", {}, el("h2", { class: "ct-h2" }, s.title), el("small", {}, s.line))),
      el("div", { class: "ct-grid" }, list.map(card)))));
  }

  async function render() {
    const root = $("#catalog");
    const data = await call("catalog");
    if (!data || !root) return;
    S.data = data;
    root.replaceChildren(hero(data), el("div", { class: "ct-body" }, start(data), pills(data), el("div", { id: "ct-list" })));
    drawList();
  }

  registerPage("catalog", { show: render });
  window.Catalog = { open: () => showPage("catalog") };
})();
