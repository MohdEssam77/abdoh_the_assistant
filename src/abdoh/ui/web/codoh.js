/* Codoh: the coding assistant page. Open a folder, chat with Claude (Claude Code) or your
   ChatGPT plan about the code; Codoh reads, changes and runs things there, and asks first.
   The logic lives in Python (abdoh/codoh); this draws it and polls for what changed. */
"use strict";

(() => {
  const ENGINE = { claude: "Claude", chatgpt: "ChatGPT" };
  const MODES = [
    ["ask", "Ask first", "Reads freely; asks before every change and command.", "shield"],
    ["auto_edit", "Auto-edit", "Changes files without asking; still asks before commands.", "pencil"],
    ["plan", "Plan only", "Changes nothing: reads, then proposes a plan.", "map"],
    ["full", "Full access", "Changes files and runs commands without asking.", "bolt"],
  ];
  const EFFORTS = [["", "Auto"], ["low", "Low"], ["medium", "Medium"], ["high", "High"], ["max", "Max"]];
  const SUGGESTIONS = [
    "Explain how this project is organized",
    "Find and fix a bug in the main code",
    "Write tests for the most important module",
    "Review my uncommitted changes",
    "Add a README that explains how to run it",
  ];
  const DOING = { read: "Read", search: "Searched", list: "Listed", edit: "Edited", write: "Wrote", command: "Ran", web: "Looked up", task: "Delegated", todo: "Planned", other: "Used" };
  const RUNNING = { read: "Reading", search: "Searching", list: "Listing", edit: "Editing", write: "Writing", command: "Running", web: "Looking up", task: "Delegating", todo: "Planning", other: "Using" };
  const ICONS = {
    codoh: '<path d="m8 7-5 5 5 5M16 7l5 5-5 5M13.5 4l-3 16"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    branch: '<circle cx="6" cy="5" r="2.2"/><circle cx="6" cy="19" r="2.2"/><circle cx="18" cy="7" r="2.2"/><path d="M6 7.2v9.6M18 9.2c0 4-6 3-11 7"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    send: '<path d="M12 19V5M5 12l7-7 7 7"/>',
    stop: '<rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor"/>',
    shield: '<path d="M12 3 4.5 6v6c0 4.5 3.2 7.7 7.5 9 4.3-1.3 7.5-4.5 7.5-9V6L12 3z"/>',
    pencil: '<path d="M4 20h4L19 9l-4-4L4 16v4z"/><path d="m14 6 4 4"/>',
    map: '<path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2z"/><path d="M9 4v14M15 6v14"/>',
    bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7l1-8z"/>',
    gauge: '<path d="M4 15a8 8 0 1 1 16 0"/><path d="m12 15 4-5"/>',
    read: '<path d="M4 4h6a2 2 0 0 1 2 2v14a2 2 0 0 0-2-2H4zM20 4h-6a2 2 0 0 0-2 2v14a2 2 0 0 1 2-2h6z"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
    edit: '<path d="M4 20h4L19 9l-4-4L4 16v4z"/>',
    write: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M12 12v6M9 15h6"/>',
    command: '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="m7 9 3 3-3 3M12.5 15H17"/>',
    web: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    task: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/>',
    todo: '<path d="M9 6h11M9 12h11M9 18h11"/><path d="m3.5 6 1 1 2-2M3.5 12l1 1 2-2M3.5 18l1 1 2-2"/>',
    other: '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    x: '<path d="M6 6l12 12M18 6 6 18"/>',
    chev: '<path d="m9 6 6 6-6 6"/>',
    down: '<path d="m6 9 6 6 6-6"/>',
    copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    dots: '<circle cx="5" cy="12" r="1.4" fill="currentColor"/><circle cx="12" cy="12" r="1.4" fill="currentColor"/><circle cx="19" cy="12" r="1.4" fill="currentColor"/>',
    code: '<path d="m8 7-5 5 5 5M16 7l5 5-5 5"/>',
    note: '<path d="M12 3v3M12 18v3M3 12h3M18 12h3"/><circle cx="12" cy="12" r="3"/>',
    alert: '<path d="M12 3 2 20h20L12 3z"/><path d="M12 10v4M12 17h.01"/>',
    diff: '<path d="M6 3v12M3 9h6M15 15h6M18 3v18"/>',
    refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6"/>',
    side: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
    ask: '<path d="M21 12a8.5 8.5 0 0 1-12.6 7.4L3 21l1.6-5.4A8.5 8.5 0 1 1 21 12z"/><path d="M9.6 9.5a2.5 2.5 0 0 1 4.8 1c0 1.7-2.4 2-2.4 3.4M12 17h.01"/>',
  };
  const icon = (name, cls = "") => el("span", { class: `cx-ico ${cls}`.trim(), html: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ICONS.other}</svg>` });

  const C = {
    state: null, models: null, chatId: store("abdoh.codoh.chat") || "", chat: null,
    rev: 0, nodes: new Map(), items: new Map(), running: false, status: "", seconds: 0,
    timer: null, visible: false, git: {}, changesOpen: false, sideOpen: false, filter: "",
    renderAt: new Map(), menu: null,
  };

  /* ---------- small things ---------- */

  function ago(epoch) {
    const s = Math.max(0, Date.now() / 1000 - epoch);
    if (s < 60) return "now";
    if (s < 3600) return `${Math.floor(s / 60)}m`;
    if (s < 86400) return `${Math.floor(s / 3600)}h`;
    return `${Math.floor(s / 86400)}d`;
  }
  const short = (path) => String(path || "").replace(/^[A-Za-z]:\\Users\\[^\\]+/, "~");
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

  async function copy(text, what = "Copied.") {
    try { await navigator.clipboard.writeText(text); toast(what); } catch (e) { toast("Couldn't copy.", true); }
  }

  function modelName(chat) {
    const models = C.models || {};
    const list = chat.engine === "claude" ? models.claude || [] : models.chatgpt || [];
    const found = list.find((m) => m.id === chat.model);
    if (found) return found.name;
    if (!chat.model) return chat.engine === "claude" ? "Default" : (list[0] ? list[0].name : "Automatic");
    return chat.model;
  }

  /* ---------- Markdown, safely: text nodes only ---------- */

  const KEYWORDS = new Set(("and as async await break case catch class const continue def default del delete do elif else enum except export extends false finally fn for from func function go if impl import in interface is lambda let match mod mut new nil none not null or package pass private protected pub public raise return self static struct super switch this throw true try type typeof use var void while with yield None True False").split(" "));

  function highlight(code, lang) {
    const out = document.createDocumentFragment();
    const hashComments = /^(py|python|sh|bash|shell|ps1|powershell|ruby|rb|yaml|yml|toml|r|perl)$/i.test(lang || "");
    const re = hashComments
      ? /(#[^\n]*|"""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|\b\d+(?:\.\d+)?\b|\b[A-Za-z_]\w*\b)/g
      : /(\/\/[^\n]*|\/\*[\s\S]*?\*\/|<!--[\s\S]*?-->|`(?:\\.|[^`\\])*`|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|\b\d+(?:\.\d+)?\b|\b[A-Za-z_$][\w$]*\b)/g;
    let at = 0;
    for (const m of code.matchAll(re)) {
      if (m.index > at) out.append(code.slice(at, m.index));
      const t = m[0];
      let cls = "";
      if (/^(#|\/\/|\/\*|<!--)/.test(t)) cls = "tk-c";
      else if (/^["'`]/.test(t)) cls = "tk-s";
      else if (/^\d/.test(t)) cls = "tk-n";
      else if (KEYWORDS.has(t)) cls = "tk-k";
      out.append(cls ? el("span", { class: cls }, t) : t);
      at = m.index + t.length;
    }
    if (at < code.length) out.append(code.slice(at));
    return out;
  }

  function codeBlock(code, lang) {
    return el("div", { class: "cx-code" },
      el("div", { class: "cx-code-head" }, el("span", {}, lang || "code"),
        el("button", { class: "cx-icon-btn", title: "Copy", onclick: () => copy(code) }, icon("copy"))),
      el("pre", {}, el("code", {}, highlight(code, lang))));
  }

  function inline(text) {
    const out = document.createDocumentFragment();
    const re = /(`[^`\n]+`|\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\s][^*\n]*\*|\[[^\]\n]+\]\((https?:\/\/[^)\s]+)\))/g;
    let at = 0;
    for (const m of text.matchAll(re)) {
      if (m.index > at) out.append(text.slice(at, m.index));
      const t = m[0];
      if (t.startsWith("`")) out.append(el("code", { class: "cx-inline" }, t.slice(1, -1)));
      else if (t.startsWith("**") || t.startsWith("__")) out.append(el("strong", {}, inline(t.slice(2, -2))));
      else if (t.startsWith("*")) out.append(el("em", {}, t.slice(1, -1)));
      else {
        const label = t.slice(1, t.indexOf("]"));
        const url = m[2];
        out.append(el("a", { href: "#", title: url, onclick: (e) => { e.preventDefault(); call("open_link", url); } }, label));
      }
      at = m.index + t.length;
    }
    if (at < text.length) out.append(text.slice(at));
    return out;
  }

  function markdown(text) {
    const root = el("div", { class: "cx-md" });
    const lines = String(text || "").replace(/\r/g, "").split("\n");
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      const fence = line.match(/^\s*```\s*([\w+#.-]*)/);
      if (fence) {
        const body = [];
        i++;
        while (i < lines.length && !/^\s*```/.test(lines[i])) body.push(lines[i++]);
        i++;
        root.append(codeBlock(body.join("\n"), fence[1]));
        continue;
      }
      const head = line.match(/^(#{1,4})\s+(.*)/);
      if (head) { root.append(el(`h${Math.min(head[1].length + 2, 6)}`, {}, inline(head[2]))); i++; continue; }
      if (/^\s*([-*_])\s*\1\s*\1[\s\1]*$/.test(line)) { root.append(el("hr")); i++; continue; }
      if (/^\s*>/.test(line)) {
        const quote = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) quote.push(lines[i++].replace(/^\s*>\s?/, ""));
        root.append(el("blockquote", {}, inline(quote.join(" "))));
        continue;
      }
      if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
        const cells = (row) => row.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        const header = cells(line);
        i += 2;
        const rows = [];
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(cells(lines[i++]));
        root.append(el("div", { class: "cx-table" }, el("table", {},
          el("thead", {}, el("tr", {}, header.map((h) => el("th", {}, inline(h))))),
          el("tbody", {}, rows.map((r) => el("tr", {}, r.map((c) => el("td", {}, inline(c)))))))));
        continue;
      }
      const bullet = line.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)/);
      if (bullet) {
        const ordered = /\d/.test(bullet[2]);
        const list = el(ordered ? "ol" : "ul");
        while (i < lines.length) {
          const m = lines[i].match(/^(\s*)([-*+]|\d+[.)])\s+(.*)/);
          if (!m) {
            if (lines[i].trim() && /^\s{2,}/.test(lines[i]) && list.lastChild) { list.lastChild.append(" ", inline(lines[i].trim())); i++; continue; }
            break;
          }
          const task = m[3].match(/^\[([ xX])\]\s+(.*)/);
          const li = el("li", { class: m[1].length >= 2 ? "cx-sub" : null });
          if (task) li.append(el("span", { class: task[1] === " " ? "cx-check" : "cx-check on" }), inline(task[2]));
          else li.append(inline(m[3]));
          list.append(li);
          i++;
        }
        root.append(list);
        continue;
      }
      if (!line.trim()) { i++; continue; }
      const para = [];
      while (i < lines.length && lines[i].trim() && !/^\s*(```|#{1,4}\s|>|[-*+]\s|\d+[.)]\s|\|)/.test(lines[i])) para.push(lines[i++]);
      if (!para.length) para.push(lines[i++]);
      root.append(el("p", {}, inline(para.join(" "))));
    }
    return root;
  }

  /* ---------- diffs ---------- */

  function diffView(text, max = 400) {
    const box = el("div", { class: "cx-diff" });
    let oldNo = 0, newNo = 0, shown = 0;
    for (const line of String(text || "").split("\n")) {
      if (line.startsWith("---") || line.startsWith("+++") || line.startsWith("diff ") || line.startsWith("index ")) continue;
      if (shown++ > max) { box.append(el("div", { class: "cx-dl more" }, el("span"), el("span"), el("span", {}, "…"))); break; }
      const hunk = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)/);
      if (hunk) {
        oldNo = Number(hunk[1]); newNo = Number(hunk[2]);
        box.append(el("div", { class: "cx-dl hunk" }, el("span"), el("span"), el("span", {}, line)));
        continue;
      }
      if (line.startsWith("@@")) { box.append(el("div", { class: "cx-dl hunk" }, el("span"), el("span"), el("span", {}, line))); continue; }
      const kind = line[0] === "+" ? "add" : line[0] === "-" ? "del" : "ctx";
      const a = kind === "add" ? "" : oldNo ? oldNo++ : "";
      const b = kind === "del" ? "" : newNo ? newNo++ : "";
      box.append(el("div", { class: `cx-dl ${kind}` }, el("span", { class: "n" }, a), el("span", { class: "n" }, b),
        el("span", {}, line.slice(kind === "ctx" && line[0] !== " " ? 0 : 1) || " ")));
    }
    return box;
  }

  function counts(diff) {
    let added = 0, removed = 0;
    for (const line of String(diff || "").split("\n")) {
      if (line.startsWith("+") && !line.startsWith("+++")) added++;
      else if (line.startsWith("-") && !line.startsWith("---")) removed++;
    }
    return [added, removed];
  }

  const plusMinus = (added, removed) => el("span", { class: "cx-pm" },
    added ? el("b", { class: "plus" }, `+${added}`) : null, removed ? el("b", { class: "minus" }, `−${removed}`) : null);

  /* ---------- the chat's items ---------- */

  function toolNode(item) {
    const kind = item.kind_of || "other";
    const [added, removed] = item.diff ? counts(item.diff) : [0, 0];
    const state = item.status || "done";
    const mark = state === "running" ? el("span", { class: "cx-spin" })
      : state === "waiting" ? el("span", { class: "cx-wait-dot", title: "Waiting for you" })
        : state === "failed" ? icon("x", "bad") : state === "stopped" ? icon("stop", "faint") : icon("check", "good");
    const hasMore = !!(item.diff || item.output || (kind === "todo" && item.detail));
    const head = el("button", { class: "cx-tool-head", type: "button", "aria-expanded": "false" },
      icon(kind, "kind"),
      el("span", { class: "cx-tool-verb" }, (state === "running" || state === "waiting" ? RUNNING : DOING)[kind] || "Used"),
      el("span", { class: kind === "command" ? "cx-tool-title mono" : "cx-tool-title" }, item.title || item.tool),
      item.detail && kind !== "todo" ? el("span", { class: "cx-tool-detail" }, item.detail) : null,
      el("span", { class: "spacer" }),
      item.diff ? plusMinus(added, removed) : null,
      mark,
      hasMore ? icon("chev", "chev") : null);
    const node = el("div", { class: `cx-tool ${state}`, "data-kind": kind }, head);
    if (hasMore) {
      const body = el("div", { class: "cx-tool-body", hidden: true });
      head.addEventListener("click", () => {
        if (!body.childNodes.length) fillTool(body, item);
        body.hidden = !body.hidden;
        node.classList.toggle("open", !body.hidden);
        head.setAttribute("aria-expanded", String(!body.hidden));
      });
      node.append(body);
      if (C.items.get(item.id) && C.nodes.get(item.id) && C.nodes.get(item.id).classList.contains("open")) {
        fillTool(body, item); body.hidden = false; node.classList.add("open");
      }
    } else head.disabled = true;
    return node;
  }

  function fillTool(body, item) {
    body.replaceChildren();
    if (item.kind_of === "todo") {
      let todos = [];
      try { todos = JSON.parse(item.detail || "[]"); } catch (e) { todos = []; }
      body.append(el("ul", { class: "cx-todos" }, todos.map((t) => el("li", { class: t.status },
        el("span", { class: t.status === "completed" ? "cx-check on" : t.status === "in_progress" ? "cx-check half" : "cx-check" }), t.text))));
      return;
    }
    if (item.diff) body.append(diffView(item.diff));
    if (item.output && !(item.diff && item.kind_of !== "command")) {
      body.append(el("div", { class: "cx-output" },
        el("button", { class: "cx-icon-btn", title: "Copy", onclick: () => copy(item.output) }, icon("copy")),
        el("pre", {}, item.output)));
    }
  }

  /* Claude asks the user something (AskUserQuestion): pick an option per question, or write
     your own answer. Sent back as {question: answer}. */
  function questionNode(item) {
    const questions = ((item.input || {}).questions || []).filter((q) => q && q.question);
    const waiting = item.state === "waiting";
    const picked = new Map(questions.map((q) => [q.question, new Set()]));
    const own = new Map();
    const who = ENGINE[C.chat && C.chat.engine] || "Codoh";
    const node = el("div", { class: `cx-ask cx-q-card ${item.state}` },
      el("div", { class: "cx-ask-head" }, icon("ask", "kind"),
        el("b", {}, waiting ? `${who} has a question for you` : `${who} asked you`),
        el("span", { class: "spacer" }),
        waiting ? el("span", { class: "cx-tag warn" }, "Needs you")
          : el("span", { class: `cx-tag ${item.state === "denied" ? "" : "good"}` }, item.state === "denied" ? "Skipped" : item.state === "expired" ? "Not answered" : "Answered")));
    const send = el("button", { class: "btn primary small", type: "button", disabled: true }, "Send answer");
    const ready = () => {
      send.disabled = !questions.every((q) => picked.get(q.question).size || (own.get(q.question) || "").trim());
    };
    for (const q of questions) {
      const block = el("div", { class: "cx-q" },
        el("div", { class: "cx-q-title" }, q.header ? el("span", { class: "cx-q-chip" }, q.header) : null, el("span", {}, q.question)));
      if (!waiting) {
        const answer = (item.answers || {})[q.question];
        block.append(el("div", { class: "cx-q-answer" }, icon(answer ? "check" : "x"), answer || "No answer"));
        node.append(block);
        continue;
      }
      const opts = el("div", { class: "cx-q-opts", role: q.multiSelect ? "group" : "radiogroup" });
      for (const o of q.options || []) {
        const button = el("button", { class: "cx-q-opt", type: "button", "aria-pressed": "false" },
          el("span", { class: "cx-q-mark" }, q.multiSelect ? icon("check") : null),
          el("span", { class: "cx-q-text" }, el("b", {}, o.label), o.description ? el("small", {}, o.description) : null));
        button.addEventListener("click", () => {
          const set = picked.get(q.question);
          if (q.multiSelect) set.has(o.label) ? set.delete(o.label) : set.add(o.label);
          else { set.clear(); set.add(o.label); other.value = ""; own.delete(q.question); }
          opts.querySelectorAll(".cx-q-opt").forEach((b) => {
            const on = set.has(b.querySelector("b").textContent);
            b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on));
          });
          ready();
        });
        opts.append(button);
      }
      const other = el("input", { class: "cx-q-other", placeholder: "Or write your own answer…", "aria-label": `Your own answer to: ${q.question}` });
      other.addEventListener("input", () => {
        own.set(q.question, other.value);
        if (other.value.trim() && !q.multiSelect) {
          picked.get(q.question).clear();
          opts.querySelectorAll(".cx-q-opt").forEach((b) => { b.classList.remove("on"); b.setAttribute("aria-pressed", "false"); });
        }
        ready();
      });
      block.append(opts, other);
      node.append(block);
    }
    if (waiting) {
      const reply = async (decision, button) => {
        const answers = {};
        for (const q of questions) {
          const words = (own.get(q.question) || "").trim();
          answers[q.question] = [...picked.get(q.question), ...(words ? [words] : [])].join(", ");
        }
        node.querySelectorAll("button, input").forEach((b) => { b.disabled = true; });
        button.classList.add("busy");
        const result = await call("codoh_answer", C.chatId, item.id, decision, decision === "deny" ? {} : answers);
        if (result && !result.ok && result.error) { toast(result.error, true); node.querySelectorAll("button, input").forEach((b) => { b.disabled = false; }); ready(); }
        poll(true);
      };
      send.addEventListener("click", (e) => reply("allow", e.currentTarget));
      node.append(el("div", { class: "cx-ask-actions" }, send, el("span", { class: "spacer" }),
        el("button", { class: "btn small", type: "button", onclick: (e) => reply("deny", e.currentTarget) }, "Skip")));
    }
    return node;
  }

  function askNode(item) {
    if (item.tool === "AskUserQuestion") return questionNode(item);
    const kind = item.kind_of || "command";
    const what = kind === "command" ? "run a command" : kind === "write" ? `create ${item.title}` : kind === "edit" ? `change ${item.title}` : `use ${item.tool}`;
    const waiting = item.state === "waiting";
    const node = el("div", { class: `cx-ask ${item.state}` },
      el("div", { class: "cx-ask-head" }, icon(kind === "command" ? "command" : "edit", "kind"),
        el("b", {}, `${ENGINE[C.chat && C.chat.engine] || "Codoh"} wants to ${what}`),
        el("span", { class: "spacer" }),
        waiting ? el("span", { class: "cx-tag warn" }, "Needs you") : el("span", { class: `cx-tag ${item.state === "denied" ? "bad" : item.state === "expired" ? "" : "good"}` },
          { allowed: "Allowed", always: "Allowed for this chat", denied: "Denied", expired: "Not answered" }[item.state] || item.state)));
    if (item.description && item.description !== item.title) node.append(el("p", { class: "cx-ask-why" }, item.description));
    if (kind === "command") node.append(el("div", { class: "cx-ask-cmd mono" }, el("span", { class: "prompt" }, "›"), item.title));
    else if (item.diff) node.append(diffView(item.diff, waiting ? 160 : 24));
    if (waiting) {
      const label = (item.suggestions || []).map((s) => s.label).find(Boolean)
        || (kind === "command" ? "Allow commands like this" : "Allow changes in this chat");
      const answer = async (decision, button) => {
        node.querySelectorAll("button").forEach((b) => { b.disabled = true; });
        button.classList.add("busy");
        const result = await call("codoh_answer", C.chatId, item.id, decision);
        if (result && !result.ok && result.error) toast(result.error, true);
        poll(true);
      };
      node.append(el("div", { class: "cx-ask-actions" },
        el("button", { class: "btn primary small", type: "button", onclick: (e) => answer("allow", e.currentTarget) }, "Allow"),
        (item.suggestions || []).length ? el("button", { class: "btn small", type: "button", onclick: (e) => answer("always", e.currentTarget) }, label) : null,
        el("span", { class: "spacer" }),
        el("button", { class: "btn small danger", type: "button", onclick: (e) => answer("deny", e.currentTarget) }, "Deny")));
    }
    return node;
  }

  function avatar(engine) {
    return el("span", { class: `cx-avatar ${engine || "claude"}`, title: ENGINE[engine] || "" },
      el("span", { html: engine === "chatgpt"
        ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3.5 19.4 7.8v8.4L12 20.5 4.6 16.2V7.8z"/><path d="M12 8v8M8.5 10l7 4M15.5 10l-7 4"/></svg>'
        : '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2.5l1.6 6.3 6.2-2.2-4.4 5 4.4 5-6.2-2.2L12 21.5l-1.6-6.3-6.2 2.2 4.4-5-4.4-5 6.2 2.2z"/></svg>' }));
  }

  function itemNode(item) {
    switch (item.kind) {
      case "user":
        return el("div", { class: "cx-msg user" }, el("div", { class: "cx-bubble" }, item.text));
      case "assistant":
        return el("div", { class: "cx-msg ai" }, avatar(item.engine), el("div", { class: "cx-ai-body" }, markdown(item.text)));
      case "tool":
        return toolNode(item);
      case "approval":
        return askNode(item);
      case "note":
        return el("div", { class: "cx-note" }, el("span", {}, icon("note"), item.text));
      case "error":
        return el("div", { class: "cx-error" }, icon("alert"), el("div", {}, el("b", {}, "That didn't work"), el("p", {}, item.text)),
          el("button", { class: "btn small", type: "button", onclick: retry }, "Try again"));
      case "done":
        return el("div", { class: "cx-done" }, icon("check"), `Done in ${item.seconds >= 60 ? `${Math.floor(item.seconds / 60)}m ${Math.round(item.seconds % 60)}s` : `${Math.round(item.seconds || 0)}s`}`);
      default:
        return el("div");
    }
  }

  function retry() {
    const users = [...C.items.values()].filter((i) => i.kind === "user");
    if (users.length) send(users[users.length - 1].text);
  }

  /* ---------- the page ---------- */

  function root() { return $("#codoh"); }

  function render() {
    const page = root();
    if (!page) return;
    page.replaceChildren(side(), main(), changesPanel(),
      el("div", { class: "cx-scrim", onclick: () => { C.sideOpen = false; page.classList.remove("side-open"); } }));
    page.classList.toggle("side-open", C.sideOpen);
    page.classList.toggle("changes-open", C.changesOpen && !!C.chat);
  }

  function side() {
    const state = C.state || { folders: [], chats: [] };
    const filter = C.filter.toLowerCase();
    const byFolder = new Map();
    for (const f of state.folders) byFolder.set(f.path, { folder: f, chats: [] });
    for (const chat of state.chats) {
      if (filter && !String(chat.title).toLowerCase().includes(filter)) continue;
      if (!byFolder.has(chat.folder)) byFolder.set(chat.folder, { folder: { path: chat.folder, name: chat.folder.split(/[\\/]/).pop(), exists: true }, chats: [] });
      byFolder.get(chat.folder).chats.push(chat);
    }
    const groups = [...byFolder.values()].filter((g) => g.chats.length || !filter);
    const search = el("input", { placeholder: "Search chats", "aria-label": "Search chats", value: C.filter });
    search.addEventListener("input", () => { C.filter = search.value; const list = $(".cx-projects"); if (list) list.replaceWith(side().querySelector(".cx-projects")); });
    return el("aside", { class: "cx-side" },
      el("div", { class: "cx-brand" },
        el("span", { class: "cx-logo" }, icon("codoh")),
        el("div", {}, el("b", {}, "Codoh"), el("small", {}, "Your coding assistant"))),
      el("button", { class: "cx-new", type: "button", onclick: () => newChat() }, icon("plus"), "New chat"),
      el("label", { class: "cx-find" }, icon("search"), search),
      el("div", { class: "cx-projects" }, groups.length ? groups.map(projectGroup)
        : el("p", { class: "cx-side-empty" }, filter ? "No chats match." : "Open a folder to start your first chat.")),
      el("button", { class: "cx-open", type: "button", onclick: openFolder }, icon("folder"), "Open a folder…"));
  }

  function projectGroup({ folder, chats }) {
    const menu = (e) => {
      e.stopPropagation();
      popover(e.currentTarget, [{ title: short(folder.path), options: [
        { label: "New chat here", icon: "plus", run: () => newChat(folder.path) },
        { label: "Open in VS Code", icon: "code", run: () => openEditor(folder.path) },
        { label: "Show in Explorer", icon: "folder", run: () => call("codoh_reveal", folder.path) },
        { label: "Remove from the list", icon: "x", run: async () => { await call("codoh_forget_folder", folder.path); refreshState(); } },
      ] }], "down");
    };
    return el("div", { class: folder.exists === false ? "cx-project gone" : "cx-project" },
      el("div", { class: "cx-project-head" },
        icon("folder"), el("span", { class: "cx-project-name", title: folder.path }, folder.name),
        el("button", { class: "cx-icon-btn", title: "New chat in this folder", type: "button", onclick: () => newChat(folder.path) }, icon("plus")),
        el("button", { class: "cx-icon-btn", title: "More", type: "button", onclick: menu }, icon("dots"))),
      chats.length ? chats.map((chat) => el("button", {
        class: chat.id === C.chatId ? "cx-chat active" : "cx-chat", type: "button",
        onclick: () => openChat(chat.id),
      }, el("span", { class: `cx-dot ${chat.engine}${chat.running ? " running" : ""}` }),
      el("span", { class: "cx-chat-title" }, chat.title), el("small", {}, ago(chat.updated)))) : null);
  }

  function main() {
    return el("section", { class: "cx-main" }, C.chat ? chatView() : hero());
  }

  function hero() {
    const state = C.state || { folders: [], engines: {} };
    const engines = state.engines || {};
    const plan = (name, info, line) => el("div", { class: `cx-plan ${info && info.ready ? "ready" : ""}` },
      avatar(name),
      el("div", {}, el("b", {}, ENGINE[name]), el("small", {}, info && info.ready ? line : (info && info.why) || "Not connected")),
      el("span", { class: `cx-tag ${info && info.ready ? "good" : ""}` }, info && info.ready ? "Ready" : "Off"));
    return el("div", { class: "cx-hero" },
      el("div", { class: "cx-hero-mark" }, el("span", { class: "cx-logo big" }, icon("codoh"))),
      el("h1", {}, "What are we building?"),
      el("p", { class: "cx-hero-lead" }, "Open a folder and talk to Claude or ChatGPT about your code. Codoh reads it, changes it and runs things there, and asks before anything risky."),
      el("button", { class: "btn primary cx-hero-open", type: "button", onclick: openFolder }, icon("folder"), "Open a folder"),
      state.folders.length ? el("div", { class: "cx-recent" },
        el("h3", {}, "Recent folders"),
        el("div", { class: "cx-recent-grid" }, state.folders.slice(0, 6).map((f) => el("button", {
          class: "cx-recent-card", type: "button", disabled: f.exists === false, onclick: () => newChat(f.path),
        }, icon("folder"), el("b", {}, f.name), el("small", {}, short(f.path)),
        el("span", { class: "cx-recent-count" }, plural((state.chats || []).filter((c) => c.folder === f.path).length, "chat")))))) : null,
      el("div", { class: "cx-plans" },
        plan("claude", engines.claude, `Claude Code · ${engines.claude && engines.claude.plan ? engines.claude.plan : "your Claude plan"}`),
        plan("chatgpt", engines.chatgpt, "Your ChatGPT plan")),
      state.limited_until ? el("p", { class: "cx-hero-note" }, `Claude's limit is used up ${state.limited_text}: new chats use your ChatGPT plan until then.`) : null);
  }

  function chatView() {
    const chat = C.chat;
    const git = C.git[chat.folder];
    const title = el("button", { class: "cx-title", type: "button", title: "Rename", onclick: rename }, chat.title || "New chat");
    const head = el("header", { class: "cx-head" },
      el("button", { class: "cx-icon-btn cx-side-toggle", type: "button", title: "Chats", onclick: () => { C.sideOpen = !C.sideOpen; root().classList.toggle("side-open", C.sideOpen); } }, icon("side")),
      el("button", { class: "cx-chip", type: "button", title: `${chat.folder} (show in Explorer)`, onclick: () => call("codoh_reveal", chat.folder) },
        icon("folder"), chat.folder.split(/[\\/]/).pop()),
      git ? el("span", { class: "cx-chip quiet", title: "Git branch" }, icon("branch"), git.branch) : null,
      git ? el("button", { class: `cx-chip ${git.changed ? "warn" : "quiet"}${C.changesOpen ? " on" : ""}`, type: "button", title: "What changed", onclick: toggleChanges },
        icon("diff"), git.changed ? `${git.changed} changed` : "No changes") : null,
      el("span", { class: "spacer" }),
      title,
      el("button", { class: "cx-icon-btn", type: "button", title: "More", onclick: (e) => popover(e.currentTarget, [{ options: [
        { label: "Rename", icon: "pencil", run: rename },
        { label: "Open folder in VS Code", icon: "code", run: () => openEditor(chat.folder) },
        { label: "Show folder in Explorer", icon: "folder", run: () => call("codoh_reveal", chat.folder) },
        { label: "Delete this chat", icon: "x", danger: true, run: removeChat },
      ] }], "down") }, icon("dots")));
    const thread = el("div", { class: "cx-thread", id: "cx-thread" });
    const scroll = el("div", { class: "cx-scroll", id: "cx-scroll" }, thread);
    return [head, scroll, composer()];
  }

  function emptyThread() {
    const chat = C.chat;
    return el("div", { class: "cx-start", id: "cx-start" },
      el("span", { class: "cx-logo" }, icon("codoh")),
      el("h2", {}, `New chat in ${chat.folder.split(/[\\/]/).pop()}`),
      el("p", {}, `${ENGINE[chat.engine]} · ${modelName(chat)} · ${MODES.find((m) => m[0] === chat.mode)[1]}. Ask anything about this code, or let it make changes.`),
      el("div", { class: "cx-suggest" }, SUGGESTIONS.map((s) => el("button", { class: "cx-suggestion", type: "button", onclick: () => send(s) }, s))));
  }

  function composer() {
    const chat = C.chat;
    const box = el("textarea", { id: "cx-input", rows: 1, placeholder: `Ask ${ENGINE[chat.engine]} to build, fix or explain something…`, "aria-label": "Message Codoh" });
    const resize = () => { box.style.height = "auto"; box.style.height = `${Math.min(box.scrollHeight, 240)}px`; };
    box.addEventListener("input", () => { resize(); updateSend(); });
    box.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (!C.running) send(box.value); }
      if (e.key === "Escape" && C.running) { e.preventDefault(); stop(); }
    });
    const mode = MODES.find((m) => m[0] === chat.mode) || MODES[0];
    const effort = EFFORTS.find((e) => e[0] === (chat.effort || "")) || EFFORTS[0];
    return el("footer", { class: "cx-composer" },
      el("div", { class: "cx-box" },
        box,
        el("div", { class: "cx-bar" },
          el("button", { class: "cx-pill", type: "button", title: "Model", onclick: modelMenu },
            el("span", { class: `cx-dot ${chat.engine}` }), modelName(chat), icon("down", "small")),
          el("button", { class: `cx-pill mode-${chat.mode}`, type: "button", title: mode[2], onclick: modeMenu },
            icon(mode[3]), mode[1], icon("down", "small")),
          el("button", { class: "cx-pill", type: "button", title: "How hard it thinks", onclick: effortMenu },
            icon("gauge"), effort[0] ? effort[1] : "Effort", icon("down", "small")),
          el("span", { class: "spacer" }),
          el("span", { class: "cx-hint", id: "cx-hint" }, "Enter to send · Shift+Enter for a new line"),
          el("button", { class: "cx-send", id: "cx-send", type: "button", title: "Send", onclick: () => (C.running ? stop() : send(box.value)) }, icon("send")))));
  }

  function updateSend() {
    const button = $("#cx-send");
    const box = $("#cx-input");
    if (!button || !box) return;
    button.classList.toggle("stop", C.running);
    button.title = C.running ? "Stop (Esc)" : "Send (Enter)";
    button.replaceChildren(icon(C.running ? "stop" : "send"));
    button.disabled = !C.running && !box.value.trim();
    const hint = $("#cx-hint");
    if (hint) hint.textContent = C.running ? "Esc to stop" : "Enter to send · Shift+Enter for a new line";
  }

  /* ---------- menus ---------- */

  function popover(anchor, sections, where = "up") {
    closeMenu();
    const menu = el("div", { class: "cx-menu", role: "menu" });
    for (const section of sections) {
      if (section.title) menu.append(el("div", { class: "cx-menu-title" }, section.title));
      if (section.empty) menu.append(el("div", { class: "cx-menu-empty" }, section.empty));
      for (const o of section.options || []) {
        menu.append(el("button", {
          class: `cx-menu-item${o.selected ? " on" : ""}${o.danger ? " danger" : ""}`, type: "button", role: "menuitem", disabled: o.disabled,
          onclick: () => { closeMenu(); o.run(); },
        }, o.dot ? el("span", { class: `cx-dot ${o.dot}` }) : o.icon ? icon(o.icon) : el("span", { class: "cx-ico" }),
        el("span", { class: "cx-menu-text" }, el("b", {}, o.label), o.line ? el("small", {}, o.line) : null),
        o.selected ? icon("check", "good") : null));
      }
    }
    document.body.append(menu);
    const r = anchor.getBoundingClientRect();
    const m = menu.getBoundingClientRect();
    const left = Math.min(Math.max(8, r.left), window.innerWidth - m.width - 8);
    const top = where === "up" ? Math.max(8, r.top - m.height - 8) : Math.min(r.bottom + 6, window.innerHeight - m.height - 8);
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
    const away = (e) => { if (!menu.contains(e.target) && e.target !== anchor) closeMenu(); };
    const key = (e) => { if (e.key === "Escape") closeMenu(); };
    setTimeout(() => { document.addEventListener("mousedown", away); document.addEventListener("keydown", key); }, 0);
    C.menu = { menu, away, key };
    const first = menu.querySelector(".cx-menu-item.on") || menu.querySelector(".cx-menu-item");
    if (first) first.focus();
  }

  function closeMenu() {
    if (!C.menu) return;
    C.menu.menu.remove();
    document.removeEventListener("mousedown", C.menu.away);
    document.removeEventListener("keydown", C.menu.key);
    C.menu = null;
  }

  async function modelMenu(e) {
    const anchor = e.currentTarget;
    const chat = C.chat;
    const engines = (C.state && C.state.engines) || {};
    if (!C.models) C.models = await call("codoh_models");
    const models = C.models || {};
    const pick = (engine, id) => configure({ model: `${engine}:${id === "default" && engine === "claude" ? "" : id}` });
    const claudeOptions = (models.claude || []).map((m) => ({
      label: m.name, line: m.line, dot: "claude",
      selected: chat.engine === "claude" && (chat.model || "default") === m.id, run: () => pick("claude", m.id),
    }));
    const chatgptOptions = (models.chatgpt || []).map((m, i) => ({
      label: m.name, line: i === 0 ? "Your plan's first model" : "", dot: "chatgpt",
      selected: chat.engine === "chatgpt" && (chat.model || (models.chatgpt[0] || {}).id) === m.id, run: () => pick("chatgpt", m.id),
    }));
    popover(anchor, [
      { title: `Claude${models.claude_plan ? ` · ${models.claude_plan}` : ""}`, options: engines.claude && engines.claude.ready ? claudeOptions : [], empty: engines.claude && engines.claude.ready ? null : engines.claude ? engines.claude.why : "" },
      { title: "ChatGPT · your plan", options: chatgptOptions, empty: engines.chatgpt && engines.chatgpt.ready ? (models.chatgpt_error || (chatgptOptions.length ? null : "Loading…")) : "Connect your ChatGPT plan in Settings → Claude." },
    ]);
  }

  function modeMenu(e) {
    popover(e.currentTarget, [{ title: "How Codoh may act", options: MODES.map(([value, label, line, ic]) => ({
      label, line, icon: ic, selected: C.chat.mode === value, danger: value === "full", run: () => configure({ mode: value }),
    })) }]);
  }

  function effortMenu(e) {
    popover(e.currentTarget, [{ title: "How hard it thinks", options: EFFORTS.map(([value, label]) => ({
      label, line: value === "" ? "The model's own default" : value === "max" ? "Slowest, uses more of your plan" : value === "low" ? "Quickest" : "",
      selected: (C.chat.effort || "") === value, run: () => configure({ effort: value }),
    })) }]);
  }

  async function configure(changes) {
    const result = await call("codoh_configure", C.chatId, changes);
    if (!result) return;
    if (!result.ok) { toast(result.error, true); return; }
    C.chat = result.chat;
    const footer = $(".cx-composer");
    const text = $("#cx-input") ? $("#cx-input").value : "";
    if (footer) footer.replaceWith(composer());
    if ($("#cx-input")) $("#cx-input").value = text;
    updateSend();
    const start = $("#cx-start");
    if (start) start.replaceWith(emptyThread());
    poll(true);
    refreshState();
  }

  /* ---------- the changes panel (git) ---------- */

  function changesPanel() {
    return el("aside", { class: "cx-changes", id: "cx-changes" },
      el("div", { class: "cx-changes-head" }, el("b", {}, "Changes"), el("span", { class: "spacer" }),
        el("button", { class: "cx-icon-btn", type: "button", title: "Refresh", onclick: loadChanges }, icon("refresh")),
        el("button", { class: "cx-icon-btn", type: "button", title: "Close", onclick: toggleChanges }, icon("x"))),
      el("div", { class: "cx-changes-list", id: "cx-changes-list" }),
      el("div", { class: "cx-changes-diff", id: "cx-changes-diff" }));
  }

  function toggleChanges() {
    C.changesOpen = !C.changesOpen;
    root().classList.toggle("changes-open", C.changesOpen);
    const chip = $$(".cx-chip").find((c) => /changed|No changes/.test(c.textContent));
    if (chip) chip.classList.toggle("on", C.changesOpen);
    if (C.changesOpen) loadChanges();
  }

  async function loadChanges() {
    if (!C.chat) return;
    const list = $("#cx-changes-list");
    const result = await call("codoh_changes", C.chat.folder);
    if (!result || !list) return;
    if (!result.ok) { list.replaceChildren(el("p", { class: "cx-side-empty" }, result.error)); $("#cx-changes-diff").replaceChildren(); return; }
    C.git[C.chat.folder] = result.git;
    if (!result.files.length) { list.replaceChildren(el("p", { class: "cx-side-empty" }, "Nothing changed since the last commit.")); $("#cx-changes-diff").replaceChildren(); return; }
    list.replaceChildren(...result.files.map((f) => el("button", { class: "cx-file", type: "button", onclick: (e) => showDiff(f.path, e.currentTarget) },
      el("span", { class: `cx-state ${f.state}` }, f.state[0].toUpperCase()),
      el("span", { class: "cx-file-name", title: f.path }, f.path),
      plusMinus(f.added, f.removed))));
    showDiff(result.files[0].path, list.firstChild);
  }

  async function showDiff(path, button) {
    $$(".cx-file").forEach((b) => b.classList.toggle("on", b === button));
    const result = await call("codoh_diff", C.chat.folder, path);
    const box = $("#cx-changes-diff");
    if (!result || !box) return;
    box.replaceChildren(el("div", { class: "cx-diff-name mono" }, path), result.diff ? diffView(result.diff, 1200) : el("p", { class: "cx-side-empty" }, "No difference to show."));
  }

  /* ---------- talking to Python ---------- */

  async function refreshState() {
    const state = await call("codoh_state");
    if (!state) return;
    C.state = state;
    const sideNode = $(".cx-side");
    if (sideNode) sideNode.replaceWith(side());
    if (!C.chat && $(".cx-main")) $(".cx-main").replaceWith(main());
  }

  async function openFolder() {
    const result = await call("codoh_open_folder");
    if (!result || result.cancelled) return;
    if (!result.ok) { toast(result.error, true); return; }
    await newChat(result.folder.path);
  }

  async function openEditor(folder) {
    const result = await call("codoh_open_editor", folder);
    if (result && result.ok) toast(result.editor === "Explorer" ? "VS Code isn't installed: opened the folder." : `Opened in ${result.editor}.`);
  }

  async function newChat(folder) {
    if (!folder) {
      const chosen = C.chat ? C.chat.folder : ((C.state && C.state.folders[0]) || {}).path;
      if (!chosen) { openFolder(); return; }
      folder = chosen;
    }
    const engine = C.chat ? C.chat.engine : "";
    const model = C.chat && C.chat.engine === engine ? C.chat.model : "";
    const result = await call("codoh_new_chat", folder, engine, model, C.chat ? C.chat.mode : "");
    if (!result) return;
    if (!result.ok) { toast(result.error, true); return; }
    await refreshState();
    openChat(result.chat.id);
  }

  async function openChat(id) {
    C.chatId = id;
    store("abdoh.codoh.chat", id);
    C.rev = 0;
    C.items = new Map();
    C.nodes = new Map();
    C.sideOpen = false;
    const result = await call("codoh_chat", id, 0);
    if (!result || !result.ok) { C.chat = null; C.chatId = ""; render(); return; }
    C.chat = result.chat;
    render();
    apply(result, true);
    folderGit(C.chat.folder);
    const input = $("#cx-input");
    if (input) input.focus();
    schedule();
  }

  async function folderGit(folder) {
    const info = await call("codoh_folder", folder);
    if (!info || !C.chat || C.chat.folder !== folder) return;
    C.git[folder] = info.git;
    const head = $(".cx-head");
    if (head) {
      const fresh = chatView()[0];
      head.replaceWith(fresh);
    }
  }

  function nearBottom() {
    const s = $("#cx-scroll");
    return !s || s.scrollHeight - s.scrollTop - s.clientHeight < 160;
  }

  function apply(result, first = false) {
    const thread = $("#cx-thread");
    if (!thread) return;
    const stick = first || nearBottom();
    const wasRunning = C.running;
    C.running = result.running;
    C.status = result.status;
    C.seconds = result.seconds;
    C.rev = result.rev;
    if (result.chat) {
      const renamed = C.chat && result.chat.title !== C.chat.title;
      C.chat = { ...C.chat, ...result.chat };
      const title = $(".cx-title");
      if (renamed && title) title.textContent = C.chat.title;
    }
    for (const item of result.items) {
      const known = C.items.get(item.id);
      C.items.set(item.id, item);
      if (known && known.kind === "assistant" && item.kind === "assistant") {
        const node = C.nodes.get(item.id);
        const body = node && node.querySelector(".cx-ai-body");
        if (body) { body.replaceChildren(markdown(item.text)); continue; }
      }
      const node = itemNode(item);
      if (known && C.nodes.get(item.id)) {
        const old = C.nodes.get(item.id);
        if (old.classList.contains("open") && node.querySelector(".cx-tool-head")) {
          node.querySelector(".cx-tool-head").click();
        }
        old.replaceWith(node);
      } else thread.append(node);
      C.nodes.set(item.id, node);
    }
    const start = $("#cx-start");
    if (!C.items.size && !start) thread.append(emptyThread());
    if (C.items.size && start) start.remove();
    working(thread);
    if (wasRunning !== C.running) {
      updateSend();
      if (!C.running) { refreshState(); folderGit(C.chat.folder); if (C.changesOpen) loadChanges(); }
    }
    if (stick) { const s = $("#cx-scroll"); if (s) s.scrollTop = s.scrollHeight; }
  }

  function working(thread) {
    let node = $("#cx-working");
    if (!C.running) { if (node) node.remove(); return; }
    const seconds = Math.round(C.seconds || 0);
    const waiting = C.status === "Waiting for you";
    const text = waiting ? "Waiting for your answer above" : `${C.status || "Working"}…`;
    if (!node) node = el("div", { class: "cx-working", id: "cx-working" });
    node.classList.toggle("waiting", waiting);
    node.replaceChildren(el("span", { class: "cx-orb" }), el("span", { class: "cx-shimmer" }, text), el("small", {}, `${seconds}s · Esc to stop`));
    thread.append(node);
  }

  function schedule() {
    clearTimeout(C.timer);
    if (!C.visible || !C.chatId) return;
    C.timer = setTimeout(() => poll(), C.running ? 220 : 1500);
  }

  async function poll(now = false) {
    if (now) clearTimeout(C.timer);
    if (!C.chatId || !C.visible) return;
    const id = C.chatId;
    try {
      const result = await App.api.codoh_chat(id, C.rev);
      if (result && result.ok && id === C.chatId) apply(result);
    } catch (e) { /* the next poll tries again */ }
    schedule();
  }

  async function send(text) {
    text = String(text || "").trim();
    if (!text || !C.chatId) return;
    const input = $("#cx-input");
    const result = await call("codoh_send", C.chatId, text);
    if (!result) return;
    if (!result.ok) { toast(result.error, true); poll(true); return; }
    if (input) { input.value = ""; input.style.height = "auto"; }
    C.running = true;
    updateSend();
    poll(true);
    refreshState();
  }

  async function stop() {
    await call("codoh_stop", C.chatId);
    poll(true);
  }

  function rename() {
    const chat = C.chat;
    const input = el("input", { class: "input", value: chat.title, "aria-label": "Chat name", maxlength: 60 });
    const dialog = openModal({
      title: "Rename chat", body: input,
      actions: [el("div", { class: "spacer" }),
        el("button", { class: "btn", type: "button", onclick: () => dialog.close() }, "Cancel"),
        el("button", { class: "btn primary", type: "button", onclick: async () => {
          const result = await call("codoh_rename", C.chatId, input.value);
          if (result && result.ok) { dialog.close(); C.chat = { ...C.chat, title: input.value.trim() }; const t = $(".cx-title"); if (t) t.textContent = C.chat.title; refreshState(); }
        } }, "Rename")],
    });
    setTimeout(() => { input.focus(); input.select(); }, 30);
  }

  function removeChat() {
    const dialog = openModal({
      title: "Delete this chat?",
      body: el("p", {}, `“${C.chat.title}” goes from Codoh. Changes it made to your files stay.`),
      actions: [el("div", { class: "spacer" }),
        el("button", { class: "btn", type: "button", onclick: () => dialog.close() }, "Cancel"),
        el("button", { class: "btn danger-fill", type: "button", onclick: async () => {
          await call("codoh_delete", C.chatId);
          dialog.close();
          C.chat = null; C.chatId = ""; store("abdoh.codoh.chat", "");
          await refreshState();
          render();
        } }, "Delete")],
    });
  }

  async function show() {
    C.visible = true;
    const [state, models] = await Promise.all([call("codoh_state"), call("codoh_models")]);
    C.state = state || { folders: [], chats: [], engines: {} };
    C.models = models;
    const known = C.chatId && (C.state.chats || []).some((c) => c.id === C.chatId);
    if (known) await openChat(C.chatId);
    else { C.chat = null; render(); }
    setTimeout(async () => { const fresh = await call("codoh_models"); if (fresh) C.models = fresh; }, 4000);
  }

  function hide() {
    C.visible = false;
    clearTimeout(C.timer);
    closeMenu();
  }

  registerPage("codoh", { show, hide });
  // Abdoh by voice: the page, the chat (a new one is in the list now too)
  window.Codoh = { open: (id) => { showPage("codoh"); refreshState(); if (id) openChat(id); } };
})();
