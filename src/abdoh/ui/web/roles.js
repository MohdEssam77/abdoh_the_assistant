/* The Act as page: your roles (ways for Abdoh to talk: a German teacher, a math teacher), the
   role that's on with a way to stop it, an editor, and suggestions to start from. */
"use strict";

(() => {
  const state = { roles: [], suggestions: [], current: null, error: null };
  const SPEEDS = [["slow", "Slower"], ["normal", "Normal"], ["fast", "Faster"]];
  // Writes the newest board card out like a teacher at a whiteboard (board.js).
  const typist = new Board.Typist((text) => {
    const board = $("#board");
    if (!board || !board.lastElementChild || !$("#page-roles").classList.contains("active")) return;
    board.lastElementChild.replaceWith(Board.render(text));
    board.scrollTop = board.scrollHeight;
  });
  const ANSWERS = [["short", "Short, as usual"], ["normal", "Longer (up to 5 sentences)"], ["long", "Long (up to 10 sentences)"]];

  async function load() {
    const result = await call("roles");
    if (!result) return;
    Object.assign(state, {
      roles: result.roles || [], suggestions: result.suggestions || [],
      current: result.current || null, error: result.ok ? null : result.error,
    });
    render();
  }

  /* ---------- the cards ---------- */

  const says = (role) => [`act as my ${role.name.toLowerCase()}`, ...(role.phrases || []).slice(0, 2)];

  function chips(role) {
    const out = [];
    if (role.speed === "slow") out.push("Speaks slower");
    if (role.speed === "fast") out.push("Speaks faster");
    if (role.answers === "normal") out.push("Longer answers");
    if (role.answers === "long") out.push("Long answers");
    if (role.board) out.push("Uses the board");
    return out;
  }

  const isOn = (role) => !!App.role && App.role.toLowerCase() === role.name.toLowerCase();

  function card(role) {
    const on = isOn(role);
    const node = el("div", { class: on ? "cmd on" : "cmd", tabindex: "0", role: "button", title: "Edit" },
      el("div", { class: "cmd-head" },
        el("span", { class: "cmd-icon", html: svg("role") }),
        el("span", { class: "cmd-name" }, role.name),
        on ? el("span", { class: "tag good" }, "On") : null,
        el("button", { class: on ? "btn small" : "btn small primary", onclick: (e) => { e.stopPropagation(); on ? stop() : start(role.name); } },
          on ? "Stop" : "Start")),
      el("div", { class: "cmd-says" }, says(role).map((p) => el("span", { class: "say-chip" }, `“${p}”`))),
      el("p", { class: "role-text" }, role.instructions),
      el("div", { class: "mode-sets" }, chips(role).map((text) => el("span", { class: "tag" }, text))));
    node.addEventListener("click", () => openEditor(role));
    node.addEventListener("keydown", (e) => { if (e.key === "Enter") openEditor(role); });
    return node;
  }

  /* The role that's on: its name, a way to stop it, (made up on the spot) to keep it, and the
     board: what it shows instead of only saying it. */
  function renderNow() {
    const box = $("#role-now");
    const current = App.role ? (state.current && state.current.name === App.role ? state.current : { name: App.role, saved: true }) : null;
    const items = App.board || [];
    const listening = App.listening || {};
    box.hidden = !current && !items.length;
    if (box.hidden) return box.replaceChildren();
    const usesBoard = items.length > 0 || !current || current.board !== false;
    box.replaceChildren(
      current ? el("div", { class: "role-now-head" },
        el("span", { class: "cmd-icon", html: svg("role") }),
        el("div", { class: "role-now-name" }, el("b", {}, `Acting as ${current.name}`),
          el("small", {}, "Stop it in any words, like “you can stop acting”."),
          el("small", {}, !listening.on ? "Listening only after “Hey Abdoh”."
            : listening.now ? "Listening now: just talk, no “Hey Abdoh” needed."
            : "In a lesson it listens without “Hey Abdoh”: with this window open, something on the board, and you talking with it.")),
        el("div", { class: "spacer" }),
        el("button", { class: "btn small", onclick: () => call("keep_listening", !listening.on) },
          listening.on ? "Stop listening" : "Keep listening"),
        current.saved === false
          ? el("button", { class: "btn small", onclick: () => openEditor({ ...current, phrases: [], board: true }, true) }, "Save this role")
          : null,
        el("button", { class: "btn small", onclick: stop }, "Stop")) : null,
      usesBoard ? el("div", { class: "board-wrap" },
        el("div", { class: "board-head" }, el("b", {}, "Board"), el("div", { class: "spacer" }),
          items.length ? el("button", { class: "btn small", onclick: () => call("clear_board") }, "Clear") : null),
        el("div", { class: "board", id: "board" }, items.length
          ? items.map((card) => Board.render(typist.shown(card)))
          : el("p", { class: "board-empty" }, "Code, equations and steps the role shows appear here."))) : null);
    const board = $("#board");
    if (board) board.scrollTop = board.scrollHeight; // the newest (maybe still growing) at the bottom
  }

  function render() {
    $("#role-error").hidden = !state.error;
    $("#role-error-text").textContent = state.error ? `Your roles file has an error: ${state.error}` : "";
    $("#role-list").replaceChildren(...state.roles.map(card));
    $("#role-empty").hidden = !!state.error || state.roles.length > 0;
    renderNow();
  }

  /* ---------- starting and stopping ---------- */

  async function start(name) {
    await call("start_role", name);
    toast(`Acting as ${name}.`);
  }

  async function stop() {
    await call("stop_role");
  }

  /* ---------- the editor ---------- */

  function choice(options, value, label) {
    return el("select", { class: "input compact", "aria-label": label },
      options.map(([v, text]) => el("option", { value: v, selected: v === value }, text)));
  }

  function openEditor(role, isNew = false) {
    const editing = role && !isNew ? role.name : null;
    const start_ = role || { name: "", phrases: [], instructions: "", speed: "normal", answers: "normal", board: false };
    const name = el("input", { class: "input", value: start_.name, placeholder: "e.g. German teacher", "aria-label": "Name" });
    const phrases = chipsInput(start_.phrases || [], "Another way to start it, then Enter");
    const text = el("textarea", { class: "input", rows: 5, maxlength: 1500, placeholder: "How Abdoh should act, e.g. You are my patient math teacher. Explain step by step…", "aria-label": "Instructions" });
    text.value = start_.instructions || "";
    const speed = choice(SPEEDS, start_.speed || "normal", "Speaking speed");
    const answers = choice(ANSWERS, start_.answers || "normal", "Answers");
    const board = el("input", { type: "checkbox", class: "switch", checked: !!start_.board, "aria-label": "Use the board" });
    const error = el("p", { class: "error-text", hidden: true });
    const setRow = (label, control, help) => el("div", { class: "set-row" }, el("b", {}, label),
      el("div", { class: "set-control" }, control, help ? el("small", { class: "muted" }, help) : null));

    const body = el("div", {},
      el("div", { class: "field" }, el("label", {}, "Name"), name),
      el("div", { class: "field" }, el("label", {}, "Say"), phrases.box,
        el("small", {}, "“Act as my <name>” always works. Stop it in any words.")),
      el("div", { class: "field" }, el("label", {}, "How Abdoh acts"), text,
        el("small", {}, "Claude follows this while the role is on. It can still look at your screen when you ask.")),
      el("div", { class: "field" }, el("label", {}, "While it's on"),
        el("div", {},
          setRow("Voice", speed),
          setRow("Answers", answers),
          setRow("Board", board, "Shows code, equations and steps here, instead of only saying them."))),
      error);

    const save = async (andStart) => {
      const data = { name: name.value, phrases: phrases.values(), instructions: text.value,
        speed: speed.value, answers: answers.value, board: board.checked };
      const result = await call("save_role", data, editing);
      if (!result) return;
      if (!result.ok) { error.textContent = result.error; error.hidden = false; return; }
      dialog.close();
      await load();
      if (andStart) start(result.role.name);
      else toast(`Saved. Now say: “act as my ${result.role.name.toLowerCase()}”`);
    };

    const foot = [];
    if (editing) {
      foot.push(el("button", { class: "btn danger", onclick: async () => {
        if (!(await confirmBox(`Delete the role “${editing}”?`, "Delete", true))) return;
        const result = await call("delete_role", editing);
        if (result && result.ok) { dialog.close(); toast("Deleted."); load(); }
        else if (result) toast(result.error, true);
      } }, el("span", { html: svg("trash") }), "Delete"));
    }
    foot.push(el("div", { class: "spacer" }),
      el("button", { class: "btn", onclick: () => dialog.close() }, "Cancel"),
      el("button", { class: "btn", onclick: () => save(true) }, "Save and start"),
      el("button", { class: "btn primary", onclick: () => save(false) }, "Save"));
    const dialog = openModal({ title: editing ? "Edit role" : "New role", body, actions: foot, wide: true });
  }

  function openSuggestions() {
    const taken = new Set(state.roles.map((r) => r.name.toLowerCase()));
    const cards = state.suggestions.map((s) => el("div", { class: "template" },
      el("div", { class: "cmd-head" }, el("span", { class: "cmd-icon", html: svg("role") }), el("b", {}, s.name)),
      el("p", {}, s.description),
      el("button", { class: "btn small", disabled: taken.has(s.name.toLowerCase()), onclick: () => { dialog.close(); openEditor(s, true); } },
        taken.has(s.name.toLowerCase()) ? "Added" : "Use this")));
    const dialog = openModal({
      title: "Roles to start from",
      body: el("div", {}, el("p", { class: "muted", style: "margin:0 0 14px" }, "Pick one, then change anything before saving."), el("div", { class: "templates" }, cards)),
      wide: true,
    });
  }

  /* ---------- wiring ---------- */

  function bind() {
    $("#role-new").addEventListener("click", () => openEditor(null));
    $("#role-suggestions").addEventListener("click", openSuggestions);
    $("#role-empty-suggestions").addEventListener("click", openSuggestions);
    $("#role-chip-name").addEventListener("click", () => showPage("roles"));
    $("#role-chip-end").addEventListener("click", stop);
  }

  /* The board changed: card is the newest (live: written out), or null when it's cleared. */
  function board(card) {
    typist.set(card);
    if ($("#page-roles").classList.contains("active")) renderNow();
  }

  window.Roles = { load, board };

  registerPage("roles", {
    boot() { bind(); },
    async show() {
      await load();
      const open = App.demo && new URLSearchParams(location.search).get("open");  // for screenshots
      if (open === "role-editor" && state.roles.length) openEditor(state.roles[0]);
      if (open === "suggestions") openSuggestions();
    },
    event(kind) {
      if (!$("#page-roles").classList.contains("active")) return;
      if (kind === "role") load();
      else if (kind === "listening") renderNow();
    },
  });
})();
