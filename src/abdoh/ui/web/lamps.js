/* The Lamps page: your lamps right now, like the WiZ app. Switch each on and off, set its
   brightness, and its colour, white or scene (the lamp dialog, live): changes happen at once.
   It reads the lamps again every few seconds while you're on it, so changes made in the WiZ
   app or by voice show too. */
"use strict";

(() => {
  const REFRESH_MS = 5000;
  const TOUCHED_MS = 3000; // a lamp you just changed isn't redrawn from an older reading
  const state = { lamps: [], loaded: false, touched: {}, refresh: null, looking: false };
  const later = {};

  const active = () => $("#page-lamps").classList.contains("active");

  async function load() {
    const result = await call("lamp_states");
    if (!result) return;
    Lamps.options = result.options || Lamps.options;
    Lamps.list = result.lamps.map(({ name, mac, ip, kind }) => ({ name, mac, ip, kind }));
    const now = Date.now();
    state.lamps = result.lamps.map((lamp) => {
      const old = state.lamps.find((l) => l.mac === lamp.mac);
      return old && now - (state.touched[lamp.mac] || 0) < TOUCHED_MS ? { ...lamp, how: old.how } : lamp;
    });
    state.loaded = true;
    render();
  }

  /* Change lamps now; `key` holds back a slider's many changes to the last one. */
  function set(which, how, key = which) {
    clearTimeout(later[key]);
    later[key] = setTimeout(async () => {
      const result = await call("set_lamp", which, how);
      if (result && !result.ok) toast(result.error, true);
    }, 120);
  }

  /* What you just did, shown at once (the lamp is told a moment later). */
  function showNow(lamps, how) {
    for (const lamp of lamps) {
      lamp.how = how(lamp.how);
      state.touched[lamp.mac] = Date.now();
    }
    render();
  }

  const lookOf = (how) => (Lamps.options && how ? lampLookFrom(how, Lamps.options) : null);
  const isOn = (how) => !!how && how !== "off";

  /* "warm white 60%" with the brightness at 40 -> "warm white 40%" */
  function withLevel(how, level) {
    const look = lookOf(how);
    if (!look || look.what === "off") return `on ${level}%`;
    look.level = level;
    return lampLookText(look);
  }

  function bulb(how) {
    const paint = lampPaint(how || "off");
    const node = el("div", { class: `lamp-bulb${paint.moving ? " moving" : ""}`,
      style: `background:${paint.background};--glow:${paint.glow};opacity:${0.35 + 0.65 * paint.level};--spin:${(1200 / (paint.speed || NORMAL_SPEED)).toFixed(1)}s` });
    return node;
  }

  function levelSlider(level, disabled, onChange, label) {
    const range = el("input", { type: "range", min: "10", max: "100", step: "5", value: String(level || 100), disabled, "aria-label": label });
    const shown = el("span", { class: "value" }, disabled ? "" : `${level || 100}%`);
    range.addEventListener("input", () => { shown.textContent = `${range.value}%`; onChange(Number(range.value)); });
    return el("div", { class: "set-control lamp-level" }, el("span", { class: "muted" }, "Brightness"), range, shown);
  }

  function openLive(which, title, how) {
    openLampDialog({ title, which, how: isOn(how) ? how : "on", fixed: true, live: (text) => {
      const lamps = which === "all" ? state.lamps : state.lamps.filter((l) => l.name === which);
      lamps.forEach((l) => { l.how = text; state.touched[l.mac] = Date.now(); });
      set(which, text, `${which}:look`);
    } }).then(() => load());
  }

  function card(lamp) {
    const kinds = (Lamps.options && Lamps.options.kinds) || {};
    const kind = kinds[lamp.kind] ? capital(kinds[lamp.kind]) : "WiZ lamp";
    if (!lamp.answers) {
      return el("div", { class: "lamp-card off-line" },
        el("div", { class: "lamp-card-head" }, bulb("off"),
          el("div", { class: "lamp-card-name" }, el("b", {}, lamp.name), el("small", { class: "muted" }, kind))),
        el("p", { class: "muted" }, "Not answering. Is it switched on at the wall?"),
        el("button", { class: "btn small", type: "button", onclick: lookAgain }, "Look again"));
    }
    const on = isOn(lamp.how);
    const look = lookOf(lamp.how);
    const power = toggle(on, (value) => {
      showNow([lamp], () => (value ? "on" : "off"));
      set(lamp.name, value ? "on" : "off");
      setTimeout(load, 900); // "on" brings back what it was: read it
    }, `${lamp.name} on or off`);
    return el("div", { class: `lamp-card${on ? "" : " is-off"}` },
      el("div", { class: "lamp-card-head" }, bulb(lamp.how),
        el("div", { class: "lamp-card-name" }, el("b", {}, lamp.name), el("small", { class: "muted" }, kind)),
        power),
      el("div", { class: "lamp-card-now" }, on ? lampSummary(lamp.how) : "Off"),
      lamp.kind === "plug" ? null : levelSlider(look && look.level, !on, (level) => {
        lamp.how = withLevel(lamp.how, level);
        state.touched[lamp.mac] = Date.now();
        set(lamp.name, `${level}%`, `${lamp.name}:level`);
      }, `${lamp.name} brightness`),
      lamp.kind === "plug" ? null : el("button", { class: "btn small", type: "button", onclick: () => openLive(lamp.name, lamp.name, lamp.how) },
        "Colour, white and scenes"));
  }

  function allCard() {
    const answering = state.lamps.filter((l) => l.answers);
    const anyOn = answering.some((l) => isOn(l.how));
    const power = toggle(anyOn, (value) => {
      showNow(answering, () => (value ? "on" : "off"));
      set("all", value ? "on" : "off");
      setTimeout(load, 900);
    }, "All lamps on or off");
    const levels = answering.filter((l) => isOn(l.how)).map((l) => (lookOf(l.how) || {}).level || 100);
    const level = levels.length ? Math.round(levels.reduce((a, b) => a + b, 0) / levels.length) : 100;
    return el("div", { class: "lamp-card all" },
      el("div", { class: "lamp-card-head" },
        el("div", { class: "lamp-bulbs" }, answering.slice(0, 3).map((l) => bulb(l.how))),
        el("div", { class: "lamp-card-name" }, el("b", {}, "All lamps"), el("small", { class: "muted" }, `${answering.length} of ${state.lamps.length} answering`)),
        power),
      levelSlider(level, !anyOn, (value) => {
        answering.filter((l) => isOn(l.how)).forEach((l) => { l.how = withLevel(l.how, value); state.touched[l.mac] = Date.now(); });
        set("all", `${value}%`, "all:level");
      }, "All lamps' brightness"),
      el("button", { class: "btn small", type: "button", onclick: () => openLive("all", "All lamps", (answering.find((l) => isOn(l.how)) || {}).how || "on") },
        "Colour, white and scenes"));
  }

  async function lookAgain() {
    if (state.looking) return;
    state.looking = true;
    render();
    const result = await call("find_lamps");
    state.looking = false;
    if (result && !result.ok) toast(result.error, true);
    await loadLamps(true);
    await load();
  }

  function render() {
    const list = $("#lamp-cards");
    $("#lamp-find").disabled = state.looking;
    $("#lamp-find").textContent = state.looking ? "Looking…" : "Find lamps";
    $("#lamp-empty").hidden = !state.loaded || state.lamps.length > 0;
    if (!state.loaded) {
      list.replaceChildren(el("p", { class: "muted" }, "Asking your lamps…"));
      return;
    }
    const cards = state.lamps.map(card);
    if (state.lamps.filter((l) => l.answers).length > 1) cards.unshift(allCard());
    list.replaceChildren(...cards);
  }

  function stopRefresh() {
    clearInterval(state.refresh);
    state.refresh = null;
  }

  registerPage("lamps", {
    boot() {
      $("#lamp-find").addEventListener("click", lookAgain);
    },
    show() {
      render();
      load();
      stopRefresh();
      state.refresh = setInterval(() => {
        if (!active()) return stopRefresh();
        if (!document.querySelector(".modal-back")) load(); // not while you're in the dialog
      }, REFRESH_MS);
    },
    hide: stopRefresh,
  });
})();
