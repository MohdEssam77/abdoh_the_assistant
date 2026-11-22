/* The board (Act as page): what a role shows instead of only saying it (code, equations,
   worked steps, tables, word lists). Claude writes a little Markdown; `parse` turns it into
   plain data and `render` into page elements with text only (never innerHTML), so nothing
   Claude writes can run as HTML. */
"use strict";

const Board = (() => {
  const FENCE = /^\s*```\s*([\w+#.-]*)\s*$/;
  const FENCE_END = /^\s*```\s*$/;
  const HEADING = /^\s*(#{1,4})\s+(.*)$/;
  const ITEM = /^\s*(?:([-*•])|(\d+)[.)])\s+(.*)$/;
  const TABLE = /^\s*\|/;
  const RULE = /^:?-{2,}:?$/;

  /* `code`, **bold** and *italic* inside a line -> [{t: "text"|"code"|"b"|"i", text}] */
  function inline(text) {
    const spans = [];
    const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g;
    let last = 0;
    for (const found of text.matchAll(pattern)) {
      if (found.index > last) spans.push({ t: "text", text: text.slice(last, found.index) });
      const token = found[0];
      if (token.startsWith("`")) spans.push({ t: "code", text: token.slice(1, -1) });
      else if (token.startsWith("**")) spans.push({ t: "b", text: token.slice(2, -2) });
      else spans.push({ t: "i", text: token.slice(1, -1) });
      last = found.index + token.length;
    }
    if (last < text.length) spans.push({ t: "text", text: text.slice(last) });
    return spans;
  }

  const special = (line) => FENCE.test(line) || HEADING.test(line) || ITEM.test(line) || TABLE.test(line);

  /* The board's text -> blocks: code, heading, list, table, or a paragraph (its line breaks
     kept: worked steps are often one per line). */
  function parse(text) {
    const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
    const blocks = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      const fence = FENCE.exec(line);
      if (fence) {
        const body = [];
        for (i += 1; i < lines.length && !FENCE_END.test(lines[i]); i += 1) body.push(lines[i]);
        i += 1; // past the closing fence
        blocks.push({ type: "code", lang: fence[1] || "", text: body.join("\n") });
      } else if (!line.trim()) {
        i += 1;
      } else if (HEADING.test(line)) {
        const [, marks, words] = HEADING.exec(line);
        blocks.push({ type: "heading", level: marks.length, spans: inline(words.trim()) });
        i += 1;
      } else if (TABLE.test(line)) {
        const rows = [];
        for (; i < lines.length && TABLE.test(lines[i]); i += 1) {
          const cells = lines[i].trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
          if (!cells.every((c) => RULE.test(c))) rows.push(cells.map(inline));
        }
        blocks.push({ type: "table", rows });
      } else if (ITEM.test(line)) {
        const ordered = !ITEM.exec(line)[1];
        const items = [];
        for (; i < lines.length; i += 1) {
          const item = ITEM.exec(lines[i]);
          if (!item || !item[1] !== ordered) break;
          items.push(inline(item[3]));
        }
        blocks.push({ type: "list", ordered, items });
      } else {
        const para = [];
        for (; i < lines.length && lines[i].trim() && !special(lines[i]); i += 1) para.push(lines[i].trimEnd());
        blocks.push({ type: "para", spans: inline(para.join("\n")) });
      }
    }
    return blocks;
  }

  /* ---------- on the page (text only) ---------- */

  function spans(tag, list) {
    const node = document.createElement(tag);
    for (const s of list) {
      if (s.t === "text") node.append(document.createTextNode(s.text));
      else {
        const part = document.createElement({ code: "code", b: "strong", i: "em" }[s.t]);
        part.textContent = s.text;
        node.append(part);
      }
    }
    return node;
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
    } catch (e) { // older webviews: the textarea way
      const area = el("textarea", { style: "position:fixed;opacity:0" }, text);
      document.body.append(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    toast("Copied.");
  }

  function block(b) {
    if (b.type === "code") {
      const code = document.createElement("code");
      code.textContent = b.text;
      return el("div", { class: "board-code" },
        el("div", { class: "board-code-head" }, el("span", {}, b.lang || "code"),
          el("button", { class: "btn small", onclick: () => copyText(b.text) }, "Copy")),
        el("pre", {}, code));
    }
    if (b.type === "heading") return spans(b.level <= 2 ? "h3" : "h4", b.spans);
    if (b.type === "list") return el(b.ordered ? "ol" : "ul", {}, b.items.map((item) => spans("li", item)));
    if (b.type === "table") {
      const [head, ...rows] = b.rows;
      return el("div", { class: "board-table" }, el("table", {},
        head ? el("thead", {}, el("tr", {}, head.map((cell) => spans("th", cell)))) : null,
        el("tbody", {}, rows.map((row) => el("tr", {}, row.map((cell) => spans("td", cell)))))));
    }
    return spans("p", b.spans);
  }

  function render(text) {
    return el("div", { class: "board-item" }, parse(text).map(block));
  }

  return { parse, render };
})();

if (typeof module !== "undefined") module.exports = Board; // tests run parse() in Node
