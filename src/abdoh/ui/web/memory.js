/* The Memory page: what Abdoh remembers about you (facts) and what it learned works on this
   computer (lessons). Add, change and delete entries, or switch memory off (then nothing is kept
   or sent to Claude). Claude adds and forgets entries too; the page refreshes when it does.
   Below them, the week's conversations (conversations.py): each day kept, to open or delete. */
"use strict";

(() => {
  const KINDS = [["fact", "About you"], ["lesson", "Lesson (what works on this computer)"]];
  const state = { entries: [], error: null, chars: 0, max_entries: 60, max_chars: 4000 };
  const talks = { days: [], keep_days: 7, since: "" }; // the conversations kept

  async function load() {
    const [result, kept] = await Promise.all([call("memory"), call("conversations")]);
    if (kept) Object.assign(talks, kept);
    if (!result) return;
    Object.assign(state, { entries: result.entries || [], error: result.ok ? null : result.error,
      chars: result.chars || 0, max_entries: result.max_entries, max_chars: result.max_chars });
    render();
  }

  async function loadConversations() {
    const kept = await call("conversations");
    if (!kept) return;
    Object.assign(talks, kept);
    renderConversations();
  }

  const days = (n) => (n === 1 ? "1 day" : `${n} days`);

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
      toggle(on, (value, input) => saveSettings({ memory: value }).then((ok) => { if (!ok) input.checked = !value; render(); }), "Remember things about me")),
      keepRow(on));
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
    renderConversations();
  }

  /* "Keep conversations for 7 days": under the memory switch, and off with it. */
  function keepRow(memoryOn) {
    const keep = memoryOn && App.settings.keep_conversations !== false;
    const n = App.settings.conversation_days || talks.keep_days || 7;
    const input = toggle(keep, (value) => saveSettings({ keep_conversations: value }).then((ok) => {
      if (!ok) input.checked = !value;
      render();
    }), "Keep conversations");
    input.disabled = !memoryOn;
    const help = !memoryOn ? "Off while memory is off."
      : keep ? `What you say and what Abdoh answers stay on this computer for ${days(n)}, so you can ask about them later (“what did we talk about yesterday?”).`
        : "Off: nothing new is kept. The days below are deleted when they're a week old, or delete them now.";
    return row(`Keep conversations for ${days(n)}`, help, input);
  }

  function renderConversations() {
    const list = talks.days || [];
    const keep = App.settings.memory !== false && App.settings.keep_conversations !== false;
    $("#conv-title").textContent = list.length ? `Conversations since ${talks.since}` : "Conversations";
    $("#conv-lead").textContent = list.length || keep
      ? `Kept on this computer for ${days(talks.keep_days)}, then deleted. Claude sees a part only when you ask about an earlier conversation.`
      : "Not kept: switch on “Keep conversations” above.";
    $("#conv-forget").hidden = !list.length;
    $("#conv-list").replaceChildren(...list.map(dayItem));
    $("#conv-empty").hidden = !!list.length || !keep;
  }

  function dayItem(day) {
    return el("div", { class: "memory-item" },
      el("span", { class: "cmd-icon", html: svg("say") }),
      el("div", { class: "memory-text" }, el("b", {}, day.label),
        el("small", {}, day.count === 1 ? "1 exchange" : `${day.count} exchanges`)),
      el("button", { class: "btn small", onclick: () => openDay(day) }, "Open"),
      el("button", { class: "icon-btn", title: "Delete this day", "aria-label": `Delete ${day.label}`, html: svg("trash"), onclick: () => deleteDay(day) }));
  }

  /* One day, as it was said: the time, what you said, what Abdoh answered, and the board. */
  async function openDay(day) {
    const result = await call("conversation_day", day.date);
    if (!result) return;
    if (!result.ok) { toast(result.error, true); loadConversations(); return; }
    const body = el("div", { class: "conv-day" }, result.exchanges.map(exchange));
    openModal({ title: result.label === "Today" || result.label === "Yesterday" ? `${result.label}'s conversation` : `Conversation, ${result.label}`, body, wide: true });
  }

  function exchange(x) {
    const about = [x.at, x.typed ? "typed" : "", x.role ? `as ${x.role}` : "", x.mode ? `${x.mode} mode` : ""].filter(Boolean).join(" · ");
    return el("div", { class: "conv-exchange" },
      el("div", { class: "conv-time" }, about),
      el("div", { class: "msg you" }, el("div", { class: "bubble" }, x.you)),
      x.abdoh ? el("div", { class: "msg abdoh" }, el("div", { class: "bubble" }, x.abdoh)) : null,
      x.board ? board(x.board) : null);
  }

  /* What the answer put on the board, drawn again when opened (pictures aren't kept). */
  function board(text) {
    const box = el("details", { class: "conv-board" }, el("summary", {}, "On the board"));
    box.addEventListener("toggle", () => {
      if (!box.open || box.querySelector(".board-item")) return;
      const card = Board.render(text);
      card.querySelectorAll(".board-picture").forEach((figure) => {
        if (!figure.querySelector("img") && figure.fill) figure.fill({ ok: false, error: `A picture: ${figure.dataset.what}` });
      });
      box.append(card);
    });
    return box;
  }

  async function deleteDay(day) {
    if (!(await confirmBox(`Delete the conversations of ${day.label === "Today" || day.label === "Yesterday" ? day.label.toLowerCase() : day.label}?`, "Delete", true))) return;
    const result = await call("delete_conversation_day", day.date);
    if (result && result.ok) { toast("Deleted."); loadConversations(); }
  }

  async function forgetAll() {
    if (!(await confirmBox("Delete every conversation kept? What's in your memory above stays.", "Delete all", true))) return;
    const result = await call("forget_conversations");
    if (result && result.ok) { toast("All conversations deleted."); loadConversations(); }
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
    boot() {
      $("#memory-add").addEventListener("click", () => openEditor(null));
      $("#conv-forget").addEventListener("click", forgetAll);
    },
    show: load,
    event(kind) {
      if (kind === "memory" && active()) load();
      if (kind === "conversations" && active()) loadConversations();
    },
    settingsChanged() { if (active()) render(); },
  });
})();
