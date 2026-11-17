/* The Modes page: your modes as cards, an editor (screens, sound, theme, power, Abdoh's own
   switches, actions), templates, "Try it" with a way back, and how your screens are numbered. */
"use strict";

(() => {
  const state = { modes: [], templates: [], displays: [], outputs: [], icons: [], error: null };
  const KEEP_SECONDS = 15;
  const POWER = [["best_performance", "Best performance"], ["balanced", "Balanced"], ["efficiency", "Best power efficiency"]];

  async function load() {
    const result = await call("modes");
    if (!result) return;
    Object.assign(state, {
      modes: result.modes || [], templates: result.templates || [], displays: result.displays || [],
      outputs: result.outputs || [], icons: result.icons || [], error: result.ok ? null : result.error,
    });
    if (result.current !== undefined) setMode(result.current);
    render();
  }

  /* ---------- the cards ---------- */

  function screenText(value) {
    if (value === "all") return "All screens";
    const names = value.map((s) => (/^\d+$/.test(s) ? s : `“${s}”`));
    return names.length === 1 ? `Only screen ${names[0]}` : `Screens ${names.join(" and ")}`;
  }

  function summary(mode) {
    const s = mode.settings || {};
    const chips = [];
    if (s.displays) chips.push(screenText(s.displays));
    if (s.volume !== undefined) chips.push(`Volume ${s.volume}%`);
    if (s.brightness !== undefined) chips.push(`Brightness ${s.brightness}%`);
    if (s.audio_output) chips.push(`Sound: ${s.audio_output}`);
    if (s.dark_mode !== undefined) chips.push(s.dark_mode ? "Dark" : "Light");
    if (s.power_mode) chips.push((POWER.find(([v]) => v === s.power_mode) || [, s.power_mode])[1]);
    if (s.wake_word === false) chips.push("Wake word off");
    if (s.voice_replies === false) chips.push("Quiet replies");
    if (s.follow_up !== undefined) chips.push(s.follow_up ? "Keeps listening" : "No follow-up");
    if ((mode.schedule || []).length) chips.push(`At ${mode.schedule[0]}`);
    const n = (mode.actions || []).length;
    if (n) chips.push(`${n} action${n > 1 ? "s" : ""}`);
    return chips;
  }

  function card(mode) {
    const on = App.mode && App.mode.toLowerCase() === mode.name.toLowerCase();
    const node = el("div", { class: on ? "cmd on" : "cmd", tabindex: "0", role: "button", title: "Edit" },
      el("div", { class: "cmd-head" },
        el("span", { class: "cmd-icon", html: svg(mode.icon || "sparkles") }),
        el("span", { class: "cmd-name" }, mode.name),
        on ? el("span", { class: "tag good" }, "On") : null,
        el("button", { class: on ? "btn small" : "btn small primary", onclick: (e) => { e.stopPropagation(); on ? endMode() : tryMode(mode); } },
          on ? "Turn off" : "Turn on")),
      el("div", { class: "cmd-says" }, el("span", { class: "say-chip" }, `“${mode.name.toLowerCase()} mode”`),
        (mode.phrases || []).slice(0, 2).map((p) => el("span", { class: "say-chip" }, `“${p}”`))),
      el("div", { class: "mode-sets" }, summary(mode).map((text) => el("span", { class: "tag" }, text))));
    node.addEventListener("click", () => openEditor(mode));
    node.addEventListener("keydown", (e) => { if (e.key === "Enter") openEditor(mode); });
    return node;
  }

  function render() {
    $("#mode-error").hidden = !state.error;
    $("#mode-error-text").textContent = state.error ? `Your modes file has an error: ${state.error}` : "";
    $("#mode-list").replaceChildren(...state.modes.map(card));
    $("#mode-empty").hidden = !!state.error || state.modes.length > 0;
    $("#mode-normal").disabled = !App.mode;
    renderScreens();
  }

  /* ---------- switching ---------- */

  async function tryMode(mode) {
    await call("activate_mode", mode.name);
    toast(`${mode.name} mode.`);
    if (mode.settings && mode.settings.displays) keepOrGoBack(mode);
  }

  async function endMode() {
    await call("end_mode");
    toast("Back to normal.");
  }

  /* After screens change: a way back if a screen you need went dark. */
  function keepOrGoBack(mode) {
    let left = KEEP_SECONDS;
    const count = el("div", { class: "countdown" }, String(left));
    const timer = setInterval(() => {
      left -= 1;
      count.textContent = String(left);
      if (left <= 0) { clearInterval(timer); dialog.close(); endMode(); }
    }, 1000);
    const dialog = openModal({
      title: "Keep these screens?",
      body: el("div", {}, el("p", { class: "muted", style: "margin:0" }, `${mode.name} mode changed which screens are on. If you don't answer, everything goes back in:`), count),
      actions: [
        el("button", { class: "btn", onclick: () => { clearInterval(timer); dialog.close(); endMode(); } }, "Go back"),
        el("div", { class: "spacer" }),
        el("button", { class: "btn primary", onclick: () => { clearInterval(timer); dialog.close(); } }, "Keep"),
      ],
      onClose: () => clearInterval(timer),
    });
  }

  /* ---------- the editor ---------- */

  function choice(options, value, label) {
    const node = el("select", { class: "input compact", "aria-label": label },
      options.map(([v, text]) => el("option", { value: v, selected: String(v) === String(value) }, text)));
    return node;
  }

  const UNSET = "__unset__";
  const KEEP = [UNSET, "Don't change"];

  function onOff(value, onText = "On", offText = "Off") {
    return choice([KEEP, ["true", onText], ["false", offText]], value === undefined ? UNSET : String(value), onText);
  }

  function slider(value, label) {
    const change = el("input", { type: "checkbox", class: "switch", checked: value !== undefined, "aria-label": `Change the ${label}` });
    const range = el("input", { type: "range", min: "0", max: "100", step: "5", value: value === undefined ? 50 : value, disabled: value === undefined, "aria-label": label });
    const shown = el("span", { class: "value" }, value === undefined ? "" : `${value}%`);
    const sync = () => {
      range.disabled = !change.checked;
      shown.textContent = change.checked ? `${range.value}%` : "";
    };
    change.addEventListener("change", sync);
    range.addEventListener("input", sync);
    return {
      node: el("div", { class: "set-control" }, change, range, shown),
      value: () => (change.checked ? Number(range.value) : undefined),
    };
  }

  /* The screens as you see them on your desk: click one to keep it on in this mode. */
  function screenPicker(value) {
    const displays = state.displays;
    let chosen = new Set(value === "all" ? displays.map((d) => String(d.number)) : (value || []).map(String));
    const change = el("input", { type: "checkbox", class: "switch", checked: value !== undefined, "aria-label": "Change which screens are on" });
    const draw = el("div", { class: "screens-draw" });
    const placed = displays.filter((d) => d.rect);
    const minX = Math.min(...placed.map((d) => d.rect[0]), 0);
    const minY = Math.min(...placed.map((d) => d.rect[1]), 0);
    const maxX = Math.max(...placed.map((d) => d.rect[0] + d.rect[2]), 1);
    const maxY = Math.max(...placed.map((d) => d.rect[1] + d.rect[3]), 1);
    const offRow = displays.filter((d) => !d.rect);
    const paint = () => {
      draw.replaceChildren(...displays.map((d, i) => {
        const on = change.checked && chosen.has(String(d.number));
        let style;
        if (d.rect) {
          const scale = Math.min(460 / (maxX - minX), (offRow.length ? 70 : 100) / (maxY - minY));
          style = `left:${(d.rect[0] - minX) * scale}px;top:${(d.rect[1] - minY) * scale}px;width:${d.rect[2] * scale - 6}px;height:${d.rect[3] * scale - 6}px`;
        } else {
          style = `left:${offRow.indexOf(d) * 90}px;top:80px;width:84px;height:28px`;
        }
        const box = el("div", { class: `screen-box${on ? " on" : ""}${d.rect ? "" : " offline"}`, style, title: d.label, role: "button", tabindex: "0" },
          el("b", {}, String(d.number)), el("span", {}, d.nickname || d.label));
        box.addEventListener("click", () => {
          if (!change.checked) { change.checked = true; chosen = new Set(); }
          const key = String(d.number);
          chosen.has(key) ? chosen.delete(key) : chosen.add(key);
          paint();
        });
        return box;
      }));
    };
    change.addEventListener("change", () => { if (change.checked && !chosen.size) displays.forEach((d) => chosen.add(String(d.number))); paint(); });
    paint();
    const note = el("small", { class: "muted" }, displays.length
      ? "Click the screens to keep on. At least one stays on."
      : "Abdoh couldn't see your screens.");
    return {
      node: el("div", { style: "display:flex;flex-direction:column;gap:8px;width:100%" },
        el("div", { class: "set-control" }, change, el("span", {}, "Change which screens are on"),
          el("button", { class: "btn small", onclick: () => call("identify_displays") }, "Identify")),
        draw, note),
      value: () => {
        if (!change.checked) return undefined;
        if (!chosen.size) return [];
        if (chosen.size === displays.length) return "all";
        return [...chosen].sort();
      },
    };
  }

  /* "Switch it on at 23:00 every day": the first time in the mode's schedule (more can be
     written in modes.yaml; they're kept). */
  const DAY_CHOICES = [["daily", "Every day"], ["weekdays", "Weekdays"], ["weekends", "Weekends"]];

  function schedulePicker(schedule) {
    const [first, ...rest] = schedule || [];
    const found = /^(\S.*?)\s+(\d{1,2}):(\d{2})$/.exec(first || "");
    const on = el("input", { type: "checkbox", class: "switch", checked: !!found, "aria-label": "Switch on by itself" });
    const time = el("input", { type: "time", class: "input compact", value: found ? `${found[2].padStart(2, "0")}:${found[3]}` : "21:00", "aria-label": "At" });
    const days = choice(DAY_CHOICES, found ? found[1] : "daily", "On");
    if (found && !DAY_CHOICES.some(([v]) => v === found[1])) days.append(el("option", { value: found[1], selected: true }, found[1]));
    const sync = () => { time.disabled = days.disabled = !on.checked; };
    on.addEventListener("change", sync);
    sync();
    return {
      node: el("div", { class: "set-control" }, on, el("span", {}, "At"), time, days),
      value: () => (on.checked && time.value ? [`${days.value} ${time.value}`, ...rest] : rest),
    };
  }

  function openEditor(mode, fromTemplate = false) {
    const editing = mode && !fromTemplate ? mode.name : null;
    const start = mode || { name: "", icon: "sparkles", phrases: [], settings: {}, actions: [], exit_actions: [] };
    const s = start.settings || {};
    let icon = start.icon || "sparkles";
    const name = el("input", { class: "input", value: start.name, placeholder: "e.g. Movie", "aria-label": "Name" });
    const icons = el("div", { class: "icon-pick" }, (state.icons.length ? state.icons : ["sparkles"]).map((i) => {
      const b = el("button", { type: "button", title: i, "aria-pressed": i === icon ? "true" : "false", html: svg(i) });
      b.addEventListener("click", () => { icon = i; $$(".icon-pick button", icons).forEach((x) => x.setAttribute("aria-pressed", x === b ? "true" : "false")); });
      return b;
    }));
    const phrases = chipsInput(start.phrases || [], "Another way to say it, then Enter");
    const screens = screenPicker(s.displays);
    const volume = slider(s.volume, "volume");
    const brightness = slider(s.brightness, "brightness");
    const output = choice([KEEP, ...state.outputs.map((o) => [o, o])], s.audio_output || UNSET, "Speakers");
    const theme = choice([KEEP, ["true", "Dark"], ["false", "Light"]], s.dark_mode === undefined ? UNSET : String(s.dark_mode), "Theme");
    const power = choice([KEEP, ...POWER], s.power_mode || UNSET, "Power mode");
    const wake = onOff(s.wake_word, "Listens for its name", "Doesn't listen");
    const voice = onOff(s.voice_replies, "Speaks replies", "Quiet (shows them)");
    const follow = onOff(s.follow_up, "Keeps listening after a reply", "Doesn't");
    const when = schedulePicker(start.schedule);
    const actions = actionRows(start.actions || [], true);
    const exits = actionRows(start.exit_actions || [], true);
    const error = el("p", { class: "error-text", hidden: true });
    const setRow = (label, control) => el("div", { class: "set-row" }, el("b", {}, label), el("div", { class: "set-control" }, control));

    const body = el("div", {},
      el("div", { class: "field" }, el("label", {}, "Name"), name),
      el("div", { class: "field" }, el("label", {}, "Icon"), icons),
      el("div", { class: "field" }, el("label", {}, "Say"), phrases.box,
        el("small", {}, "“<name> mode” always works. Add other ways to say it, like “movie night”.")),
      el("div", { class: "field" }, el("label", {}, "In this mode"),
        el("div", {},
          el("div", { class: "set-row" }, el("b", {}, "Screens"), screens.node),
          setRow("Volume", volume.node),
          setRow("Brightness", brightness.node),
          setRow("Speakers", output),
          setRow("Theme", theme),
          setRow("Power", power),
          setRow("Wake word", wake),
          setRow("Voice replies", voice),
          setRow("Follow-up", follow)),
        el("small", {}, "All of these go back to how they were when you say “back to normal”.")),
      el("div", { class: "field" }, el("label", {}, "Then Abdoh will"), actions.box),
      el("div", { class: "field" }, el("label", {}, "Switch it on by itself"), when.node,
        el("small", {}, "Abdoh switches this mode on at that time (while it's running).")),
      el("div", { class: "field" }, el("label", {}, "When the mode ends"), exits.box),
      error);

    const read = () => {
      const pick = (node) => (node.value === UNSET ? undefined : node.value);
      const bool = (node) => (node.value === UNSET ? undefined : node.value === "true");
      const settings = {
        displays: screens.value(), volume: volume.value(), brightness: brightness.value(),
        audio_output: pick(output), dark_mode: bool(theme), power_mode: pick(power),
        wake_word: bool(wake), voice_replies: bool(voice), follow_up: bool(follow),
      };
      Object.keys(settings).forEach((k) => settings[k] === undefined && delete settings[k]);
      return { name: name.value, icon, phrases: phrases.values(), settings,
        actions: actions.values(), exit_actions: exits.values(), schedule: when.value() };
    };

    const save = async (andTry) => {
      const data = read();
      if (Array.isArray(data.settings.displays) && !data.settings.displays.length) {
        error.textContent = "Keep at least one screen on.";
        error.hidden = false;
        return;
      }
      const result = await call("save_mode", data, editing);
      if (!result) return;
      if (!result.ok) { error.textContent = result.error; error.hidden = false; return; }
      dialog.close();
      await load();
      if (andTry) tryMode(result.mode);
      else toast(`Saved. Now say: “${result.mode.name.toLowerCase()} mode”`);
    };

    const foot = [];
    if (editing) {
      foot.push(el("button", { class: "btn danger", onclick: async () => {
        if (!(await confirmBox(`Delete the mode “${editing}”?`, "Delete", true))) return;
        const result = await call("delete_mode", editing);
        if (result && result.ok) { dialog.close(); toast("Deleted."); load(); }
        else if (result) toast(result.error, true);
      } }, el("span", { html: svg("trash") }), "Delete"));
    }
    foot.push(el("div", { class: "spacer" }),
      el("button", { class: "btn", onclick: () => dialog.close() }, "Cancel"),
      el("button", { class: "btn", onclick: () => save(true) }, "Save and try it"),
      el("button", { class: "btn primary", onclick: () => save(false) }, "Save"));
    const dialog = openModal({ title: editing ? "Edit mode" : "New mode", body, actions: foot, wide: true });
  }

  function openTemplates() {
    const taken = new Set(state.modes.map((m) => m.name.toLowerCase()));
    const cards = state.templates.map((t) => el("div", { class: "template" },
      el("div", { class: "cmd-head" }, el("span", { class: "cmd-icon", html: svg(t.icon || "sparkles") }), el("b", {}, t.name)),
      el("p", {}, t.description),
      el("button", { class: "btn small", disabled: taken.has(t.name.toLowerCase()), onclick: () => {
        dialog.close();
        openEditor({ ...t, phrases: [], exit_actions: [] }, true);
      } }, taken.has(t.name.toLowerCase()) ? "Added" : "Use this")));
    const dialog = openModal({
      title: "Mode templates",
      body: el("div", {}, el("p", { class: "muted", style: "margin:0 0 14px" }, "Pick one to start from, then choose your screens and change anything before saving."), el("div", { class: "templates" }, cards)),
      wide: true,
    });
  }

  /* ---------- your screens ---------- */

  function renderScreens() {
    const displays = state.displays;
    $("#screens-card").hidden = !displays.length;
    $("#screen-rows").replaceChildren(...displays.map((d, i) => {
      const nick = el("input", { class: "input compact", value: d.nickname || "", placeholder: "A name, like TV", "aria-label": `Name for screen ${d.number}` });
      nick.addEventListener("change", async () => {
        const result = await call("rename_display", d.id, nick.value);
        if (result) { state.displays = result.displays; toast("Saved."); }
      });
      const move = async (by) => {
        const ids = displays.map((x) => x.id);
        const j = i + by;
        [ids[i], ids[j]] = [ids[j], ids[i]];
        const result = await call("reorder_displays", ids);
        if (result) { state.displays = result.displays; renderScreens(); }
      };
      return el("div", { class: "screen-row" },
        el("span", { class: "num" }, String(d.number)),
        el("div", {}, el("div", {}, d.name || d.label), el("small", {}, d.active ? (d.primary ? "On, main screen" : "On") : "Off")),
        nick,
        el("div", { class: "moves" },
          el("button", { class: "icon-btn", title: "Lower number", html: svg("up"), disabled: i === 0, onclick: () => move(-1) }),
          el("button", { class: "icon-btn", title: "Higher number", html: svg("down"), disabled: i === displays.length - 1, onclick: () => move(1) })));
    }));
  }

  /* ---------- wiring ---------- */

  function bind() {
    $("#mode-new").addEventListener("click", () => openEditor(null));
    $("#mode-templates").addEventListener("click", openTemplates);
    $("#mode-empty-templates").addEventListener("click", openTemplates);
    $("#mode-normal").addEventListener("click", endMode);
    $("#screens-identify").addEventListener("click", () => call("identify_displays"));
    $("#mode-chip-name").addEventListener("click", () => showPage("modes"));
    $("#mode-chip-end").addEventListener("click", endMode);
  }

  registerPage("modes", {
    boot() { bind(); },
    async show() {
      await load();
      const open = App.demo && new URLSearchParams(location.search).get("open");  // for screenshots
      if (open === "editor" && state.modes.length) openEditor(state.modes[0]);
      if (open === "templates") openTemplates();
      if (open === "keep" && state.modes.length) keepOrGoBack(state.modes[0]);
    },
    event(kind) { if (kind === "mode" && $("#page-modes").classList.contains("active")) render(); },
  });
})();
