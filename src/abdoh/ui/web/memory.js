/* The Memory page: what Abdoh remembers about you (facts) and what it learned works on this
   computer (lessons). Add, change and delete entries, or switch memory off (then nothing is kept
   or sent to Claude). Claude adds and forgets entries too; the page refreshes when it does. */
"use strict";

(() => {
  const KINDS = [["fact", "About you"], ["lesson", "Lesson (what works on this computer)"]];
  const state = { entries: [], error: null, chars: 0, max_entries: 60, max_chars: 4000 };

  async function load() {
    const result = await call("memory");
    if (!result) return;
    Object.assign(state, { entries: result.entries || [], error: result.ok ? null : result.error,
      chars: result.chars || 0, max_entries: result.max_entries, max_chars: result.max_chars });
    render();
  }

  const active = () => $("#page-memory").classList.contains("active");

  function item(entry) {
    const lesson = entry.kind === "lesson";
    return el("div", { class: "memory-item" },
      el("span", { class: "cmd-icon", html: svg(lesson ? "lesson" : "memory") }),
      el("div", { class: "memory-text" }, el("b", {}, entry.text),
        entry.added ? el("small", {}, `${lesson ? "Learned" : "Added"} ${entry.added}`) : null),
      el("button", { class: "icon-btn", title: "Edit", "aria-label": "Edit", html: svg("pencil"), onclick: () => openEditor(entry) }),
      el("button", { class: "icon-btn", title: "Delete", "aria-label": "Delete", html: svg("trash"), onclick: () => forget(entry) }));
  }

  function render() {
    const on = App.settings.memory !== false;
    $("#memory-switch").replaceChildren(row("Remember things about me",
      on ? "Abdoh keeps what you tell it about yourself and what it learns, and Claude gets it with your requests."
        : "Off: nothing new is kept, and nothing here is sent to Claude. What's below stays until you delete it.",
      toggle(on, (value, input) => saveSettings({ memory: value }).then((ok) => { if (!ok) input.checked = !value; render(); }), "Remember things about me")));
    $("#memory-error").hidden = !state.error;
    $("#memory-error-text").textContent = state.error ? `${state.error} Fix it in memory.yaml (Settings → Your files), then come back.` : "";
    const facts = state.entries.filter((e) => e.kind !== "lesson");
    const lessons = state.entries.filter((e) => e.kind === "lesson");
    $("#memory-list").replaceChildren(
      facts.length ? el("div", { class: "memory-group" }, "About you") : null, ...facts.map(item),
      lessons.length ? el("div", { class: "memory-group" }, "Lessons") : null, ...lessons.map(item));
    $("#memory-empty").hidden = !!state.entries.length || !!state.error;
    $("#memory-usage").textContent = state.entries.length
      ? `${state.entries.length} of ${state.max_entries} entries, ${Math.round((100 * state.chars) / state.max_chars)}% full`
      : "";
    $("#memory-add").disabled = !!state.error;
  }

  function openEditor(entry) {
    const text = el("textarea", { class: "input", rows: 3, maxlength: 300, placeholder: "e.g. My sister is called Lina.", "aria-label": "What to remember" });
    text.value = entry ? entry.text : "";
    const kind = select(KINDS, entry ? entry.kind : "fact");
    const error = el("p", { class: "error-text", hidden: true });
    const save = async () => {
      const result = entry ? await call("change_memory", entry.text, text.value, kind.value) : await call("add_memory", text.value, kind.value);
      if (!result) return;
      if (!result.ok) { error.textContent = result.error; error.hidden = false; return; }
      dialog.close();
      toast(entry ? "Saved." : "Abdoh will remember that.");
      load();
    };
    const body = el("div", {},
      el("div", { class: "field" }, el("label", {}, "What to remember"), text,
        el("small", {}, "One short sentence. Never passwords, keys or card numbers.")),
      el("div", { class: "field" }, el("label", {}, "Kind"), kind), error);
    const dialog = openModal({ title: entry ? "Edit memory" : "Remember something", body, actions: [
      el("div", { class: "spacer" }),
      el("button", { class: "btn", onclick: () => dialog.close() }, "Cancel"),
      el("button", { class: "btn primary", onclick: save }, "Save")] });
    text.focus();
  }

  function select(options, value) {
    return el("select", { class: "input", "aria-label": "Kind" },
      options.map(([v, label]) => el("option", { value: v, selected: v === value }, label)));
  }

  async function forget(entry) {
    if (!(await confirmBox(`Forget “${entry.text}”?`, "Forget", true))) return;
    const result = await call("forget_memory", entry.text);
    if (result && result.ok) { toast("Forgotten."); load(); }
    else if (result) toast(result.error, true);
  }

  registerPage("memory", {
    boot() { $("#memory-add").addEventListener("click", () => openEditor(null)); },
    show: load,
    event(kind) { if (kind === "memory" && active()) load(); },
    settingsChanged() { if (active()) render(); },
  });
})();
