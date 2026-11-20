/* The Commands page: your own voice shortcuts, edited with forms and saved to commands.yaml.
   Checking and saving happen in Python (AppApi.save_command); this only draws the forms. */
"use strict";

(() => {
  const state = { commands: [], templates: [], error: null };

  /* ---------- the list ---------- */

  async function load() {
    const result = await call("commands");
    if (!result) return;
    state.commands = result.commands || [];
    state.templates = result.templates || [];
    state.error = result.ok ? null : result.error;
    render();
  }

  function describe(action) {
    const spec = ACTIONS[action.type] || {};
    if (spec.options) {
      const option = (spec.options.find(([v]) => v === action.value) || [null, action.value])[1];
      return action.type === "media" ? `Press ${option.toLowerCase()}` : `${spec.label}: ${option.toLowerCase()}`;
    }
    const verbs = { say: "Say", open_url: "Open", open_app: "Open", play_youtube: "Play", timer: "Timer:", run: "Run", volume: "Volume to", brightness: "Brightness to", app_volume: "App volume:", type: "Type",
      displays: "Screens:", audio_output: "Sound to", keys: "Press", wait: "Wait", close_app: "Close",
      focus_app: "Switch to", window: "Window:", mode: "Mode:" };
    return `${verbs[action.type] || action.type} ${action.value}`;
  }

  function card(command) {
    const node = el("div", { class: "cmd", tabindex: "0", role: "button", title: "Edit" },
      el("div", { class: "cmd-head" },
        el("span", { class: "cmd-icon", html: svg(command.actions[0] ? command.actions[0].type : "bolt") }),
        el("span", { class: "cmd-name" }, command.name),
        el("button", { class: "btn small", title: "Run it now", onclick: (e) => { e.stopPropagation(); tryCommand(command); } },
          el("span", { html: svg("play") }), "Try it")),
      el("div", { class: "cmd-says" }, command.triggers.map((t) => el("span", { class: "say-chip" }, "“", phrase(t), "”"))),
      el("div", { class: "cmd-actions" }, command.actions.slice(0, 3).map((a) =>
        el("div", { class: "action-line" }, el("span", { html: svg(a.type), style: "display:contents" }), el("span", {}, describe(a)))),
      command.actions.length > 3 ? el("div", { class: "faint" }, `and ${command.actions.length - 3} more`) : null));
    node.addEventListener("click", () => openEditor(command));
    node.addEventListener("keydown", (e) => { if (e.key === "Enter") openEditor(command); });
    return node;
  }

  function render() {
    $("#cmd-error").hidden = !state.error;
    $("#cmd-error-text").textContent = state.error ? `Your commands file has an error: ${state.error}` : "";
    const query = $("#cmd-search").value.trim().toLowerCase();
    const shown = state.commands.filter((c) => !query
      || c.name.toLowerCase().includes(query)
      || c.triggers.some((t) => t.toLowerCase().includes(query)));
    $("#cmd-list").replaceChildren(...shown.map(card));
    $("#cmd-empty").hidden = !!state.error || state.commands.length > 0;
  }

  /* ---------- trying a command ---------- */

  function tryCommand(command) {
    const trigger = command.triggers[0];
    const slots = [...trigger.matchAll(/\{(\w+)\}/g)].map((m) => m[1]);
    const run = (text) => {
      call("send", text);
      showPage("home");
    };
    if (!slots.length) return run(trigger);
    const inputs = slots.map((name) => el("input", { class: "input", placeholder: `What should {${name}} be?`, "data-slot": name }));
    const go = () => {
      let text = trigger;
      for (const input of inputs) text = text.replace(`{${input.dataset.slot}}`, input.value.trim() || input.dataset.slot);
      dialog.close();
      run(text);
    };
    inputs.forEach((i) => i.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); }));
    const dialog = openModal({
      title: `Try “${trigger}”`,
      body: el("div", {}, inputs.map((input) => el("div", { class: "field" }, el("label", {}, `{${input.dataset.slot}}`), input))),
      actions: [el("div", { class: "spacer" }), el("button", { class: "btn primary", onclick: go }, "Run it")],
    });
  }

  /* ---------- the editor ---------- */

  function openEditor(command, fromTemplate = false) {
    const editing = command && !fromTemplate ? command.name : null;
    const start = command || { name: "", triggers: [], actions: [] };
    const name = el("input", { class: "input", value: start.name, placeholder: "e.g. Good morning", "aria-label": "Name" });
    const triggers = chipsInput(start.triggers, "Type a phrase, then press Enter");
    const actions = actionRows(start.actions);
    const error = el("p", { class: "error-text", hidden: true });
    const save = el("button", { class: "btn primary" }, "Save");
    const body = el("div", {},
      el("div", { class: "field" }, el("label", {}, "Name"), name),
      el("div", { class: "field" }, el("label", {}, "When I say"), triggers.box,
        el("small", {}, "Add a few ways you'd say it. Use {name} for a blank, e.g. “search youtube for {query}”. Don't include “Hey Xanthos”.")),
      el("div", { class: "field" }, el("label", {}, "Xanthos will"), actions.box,
        el("small", {}, "In texts and links you can use {time}, {date} and your {blanks}.")),
      error);
    const foot = [];
    if (editing) {
      foot.push(el("button", { class: "btn danger", onclick: async () => {
        if (!(await confirmBox(`Delete the command “${editing}”?`, "Delete", true))) return;
        const result = await call("delete_command", editing);
        if (result && result.ok) { dialog.close(); toast("Deleted."); load(); }
        else if (result) toast(result.error, true);
      } }, el("span", { html: svg("trash") }), "Delete"));
    }
    foot.push(el("div", { class: "spacer" }), el("button", { class: "btn", onclick: () => dialog.close() }, "Cancel"), save);
    save.addEventListener("click", async () => {
      save.disabled = true;
      const data = { name: name.value, triggers: triggers.values(), actions: actions.values() };
      const result = await call("save_command", data, editing);
      save.disabled = false;
      if (!result) return;
      if (!result.ok) {
        error.textContent = result.error;
        error.hidden = false;
        return;
      }
      dialog.close();
      toast(`Saved. Now say: “${result.command.triggers[0]}”`);
      load();
    });
    const dialog = openModal({ title: editing ? "Edit command" : "New command", body, actions: foot, wide: true });
  }

  function openTemplates() {
    const taken = new Set(state.commands.map((c) => c.name.toLowerCase()));
    const cards = state.templates.map((t) => el("div", { class: "template" },
      el("div", { class: "cmd-head" }, el("span", { class: "cmd-icon", html: svg(t.actions[0].type) }), el("b", {}, t.name)),
      el("span", { class: "say-chip" }, "“", phrase(t.triggers[0]), "”"),
      el("p", {}, t.description),
      el("button", { class: "btn small", disabled: taken.has(t.name.toLowerCase()), onclick: () => {
        dialog.close();
        openEditor({ name: t.name, triggers: t.triggers, actions: t.actions }, true);
      } }, taken.has(t.name.toLowerCase()) ? "Added" : "Use this")));
    const dialog = openModal({
      title: "Templates",
      body: el("div", {}, el("p", { class: "muted", style: "margin:0 0 14px" }, "Pick one to start from. You can change everything before saving."), el("div", { class: "templates" }, cards)),
      wide: true,
    });
  }

  /* ---------- wiring ---------- */

  function bind() {
    $("#cmd-search").addEventListener("input", render);
    $("#cmd-new").addEventListener("click", () => openEditor(null));
    $("#cmd-templates").addEventListener("click", openTemplates);
    $("#cmd-empty-templates").addEventListener("click", openTemplates);
    $("#cmd-open-file").addEventListener("click", () => call("open_commands_file"));
  }

  registerPage("commands", {
    boot() { bind(); },
    async show() {
      await load();
      const open = App.demo && new URLSearchParams(location.search).get("open");  // for screenshots
      if (open === "editor") openEditor(state.commands[state.commands.length - 1]);
      if (open === "templates") openTemplates();
    },
  });
})();
