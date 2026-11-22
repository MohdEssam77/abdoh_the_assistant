/* The board (Act as page): what a role writes instead of only saying it (code, equations,
   worked steps, tables, word lists). Claude writes a little Markdown with LaTeX math; `parse`
   turns it into plain data and `render` into page elements with text only (never innerHTML),
   so nothing Claude writes can run as HTML. Math goes to KaTeX (vendor/katex, `trust` off).
   `Typist` writes the newest card out word by word, like a teacher at a whiteboard. */
"use strict";

const Board = (() => {
  const FENCE = /^\s*```\s*([\w+#.-]*)\s*$/;
  const FENCE_END = /^\s*```\s*$/;
  const HEADING = /^\s*(#{1,4})\s+(.*)$/;
  const ITEM = /^\s*(?:([-*•])|(\d+)[.)])\s+(.*)$/;
  const TABLE = /^\s*\|/;
  const RULE = /^:?-{2,}:?$/;
  // A formula on a line of its own: $$...$$ or \[...\], or opened on this line, closed later.
  const MATH_LINE = /^\s*(?:\$\$(.+)\$\$|\\\[(.+)\\\])\s*$/;
  const MATH_OPEN = /^\s*(\$\$|\\\[)(.*)$/;
  const MATH_CLOSE = { "$$": "$$", "\\[": "\\]" };
  // Inside a line: `code`, $$display$$, \(math\), $math$ (not "$5 and $10"), **bold**, *italic*.
  const INLINE = /(`[^`]+`|(?<!\\)\$\$[^$]+\$\$|\\\(.+?\\\)|(?<!\\)\$(?!\s)[^$\n]+?(?<!\s)\$(?!\d)|\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g;

  /* A line that starts a formula of several lines: its opening ($$ or \[), else null. */
  function opensMath(line) {
    const open = MATH_OPEN.exec(line);
    if (!open || MATH_LINE.test(line) || open[2].includes(MATH_CLOSE[open[1]])) return null;
    return open[1];
  }

  /* `code`, math, **bold** and *italic* inside a line -> [{t: "text"|"code"|"math"|"b"|"i", text}] */
  function inline(text) {
    const spans = [];
    const plain = (s) => spans.push({ t: "text", text: s.replace(/\\\$/g, "$") });
    let last = 0;
    for (const found of text.matchAll(INLINE)) {
      if (found.index > last) plain(text.slice(last, found.index));
      const token = found[0];
      if (token.startsWith("`")) spans.push({ t: "code", text: token.slice(1, -1) });
      else if (token.startsWith("$$")) spans.push({ t: "math", text: token.slice(2, -2), display: true });
      else if (token.startsWith("\\(")) spans.push({ t: "math", text: token.slice(2, -2) });
      else if (token.startsWith("$")) spans.push({ t: "math", text: token.slice(1, -1) });
      else if (token.startsWith("**")) spans.push({ t: "b", text: token.slice(2, -2) });
      else spans.push({ t: "i", text: token.slice(1, -1) });
      last = found.index + token.length;
    }
    if (last < text.length) plain(text.slice(last));
    return spans;
  }

  const special = (line) => FENCE.test(line) || HEADING.test(line) || ITEM.test(line) || TABLE.test(line)
    || MATH_LINE.test(line) || opensMath(line) !== null;

  /* The board's text -> blocks: code, math, heading, list, table, or a paragraph (its line
     breaks kept: worked steps are often one per line). */
  function parse(text) {
    const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
    const blocks = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      const fence = FENCE.exec(line);
      const formula = MATH_LINE.exec(line);
      const opened = opensMath(line);
      if (fence) {
        const body = [];
        for (i += 1; i < lines.length && !FENCE_END.test(lines[i]); i += 1) body.push(lines[i]);
        i += 1; // past the closing fence
        blocks.push({ type: "code", lang: fence[1] || "", text: body.join("\n") });
      } else if (formula) {
        blocks.push({ type: "math", text: (formula[1] ?? formula[2]).trim() });
        i += 1;
      } else if (opened) {
        const close = MATH_CLOSE[opened];
        const rest = MATH_OPEN.exec(line)[2];
        const body = rest.trim() ? [rest] : [];
        for (i += 1; i < lines.length; i += 1) {
          const at = lines[i].indexOf(close);
          if (at >= 0) {
            body.push(lines[i].slice(0, at));
            break;
          }
          body.push(lines[i]);
        }
        i += 1; // past the closing line
        blocks.push({ type: "math", text: body.join("\n").trim() });
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

  /* ---------- writing it out, word by word ---------- */

  // How fast the board is written, in characters a second. Abdoh waits about as long before
  // speaking on (daemon.BOARD_CHARS_PER_SECOND), so it talks about a line once it's written.
  const CHARS_PER_SECOND = 40;
  // One step of writing: a line's "## " / "- " / "1. " with its first word, a whole formula,
  // `code`, **bold** or *italic*, otherwise a word.
  const STEP = /^\s*(?:#{1,4}|[-*•]|\d+[.)])\s+\S*|`[^`]*`|(?<!\\)\$\$.+?\$\$|\\\(.+?\\\)|\\\[.+?\\\]|(?<!\\)\$(?!\s)[^$]+?(?<!\s)\$(?!\d)|\*\*[^*]+\*\*|\*[^*\s][^*]*\*|\S+/g;
  const WORD = /\S+/g;

  /* Where writing may pause (offsets into text): after a step, never inside a formula or a
     table row. A formula of several lines appears once it's closed. */
  function stops(text) {
    const cuts = [];
    let offset = 0;
    let fence = false;
    let mathClose = null; // inside a formula of several lines: what closes it
    for (const line of String(text || "").split("\n")) {
      const end = offset + line.length;
      const steps = (pattern) => {
        for (const m of line.matchAll(pattern)) cuts.push(offset + m.index + m[0].length);
      };
      if (mathClose) {
        if (line.includes(mathClose)) {
          mathClose = null;
          cuts.push(end);
        }
      } else if (fence) {
        if (FENCE_END.test(line)) {
          fence = false;
          cuts.push(end);
        } else steps(WORD);
      } else if (FENCE.test(line)) {
        fence = true;
        cuts.push(end);
      } else if (opensMath(line)) {
        mathClose = MATH_CLOSE[opensMath(line)];
      } else if (TABLE.test(line) || MATH_LINE.test(line)) {
        if (line.trim()) cuts.push(end);
      } else steps(STEP);
      offset = end + 1;
    }
    return cuts;
  }

  /* Writes the newest card out step by step; draw(text) shows what's written so far. */
  class Typist {
    constructor(draw, speed = CHARS_PER_SECOND) {
      Object.assign(this, { draw, speed, id: null, text: "", at: 0, timer: null });
    }

    /* The newest card ({id, text}; null: none). live: write what's new; otherwise show it all. */
    set(card, live = true) {
      if (!card) {
        this.stop();
        Object.assign(this, { id: null, text: "", at: 0 });
        return;
      }
      if (card.id !== this.id || !card.text.startsWith(this.text.slice(0, this.at))) this.at = 0;
      Object.assign(this, { id: card.id, text: card.text });
      if (!live) {
        this.stop();
        this.at = card.text.length;
      } else if (this.timer === null) {
        this.timer = setTimeout(() => this.step(), 0); // after the page has drawn the card
      }
    }

    /* What to show of a card: all of it, unless it's the one being written. */
    shown(card) {
      return card.id === this.id ? this.text.slice(0, this.at) : card.text;
    }

    step() {
      this.timer = null;
      const next = stops(this.text).find((at) => at > this.at);
      if (next === undefined) return; // all written (or a formula isn't finished yet)
      const wait = ((next - this.at) * 1000) / this.speed;
      this.at = next;
      this.draw(this.text.slice(0, this.at));
      this.timer = setTimeout(() => this.step(), wait);
    }

    stop() {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }

  /* ---------- on the page (text only) ---------- */

  function math(tex, display) {
    const node = document.createElement("span");
    node.className = display ? "board-math display" : "board-math";
    try {
      // trust off: no links, classes or styles from the formula; errors show in red, no throw.
      katex.render(tex, node, { displayMode: !!display, throwOnError: false, trust: false, strict: "ignore" });
    } catch (e) { // no KaTeX: the LaTeX itself
      node.textContent = tex;
    }
    return node;
  }

  function spans(tag, list) {
    const node = document.createElement(tag);
    for (const s of list) {
      if (s.t === "text") node.append(document.createTextNode(s.text));
      else if (s.t === "math") node.append(math(s.text, s.display));
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
    if (b.type === "math") return math(b.text, true);
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

  return { parse, render, stops, Typist, CHARS_PER_SECOND };
})();

if (typeof module !== "undefined") module.exports = Board; // tests run parse() in Node
