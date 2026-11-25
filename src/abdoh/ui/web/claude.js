/* The Claude card (top of Settings, and in the first-start setup): connect your own Claude
   account through Claude Code's own sign-in, or your own API key. Abdoh never sees passwords. */
"use strict";

(() => {
  const PLANS_URL = "https://claude.com/pricing";
  const CONSOLE_URL = "https://platform.claude.com/";
  const OPENROUTER_URL = "https://openrouter.ai/keys";
  const POLL_MS = 3000;
  let waiting = null; // {kind: "install" | "sign_in", until: time, url: the sign-in page}

  function link(text, url) {
    return el("a", { href: "#", onclick: (e) => { e.preventDefault(); call("open_link", url); } }, text);
  }

  function stateTag(state) {
    if (state.connected) return el("span", { class: "tag good" }, el("span", { html: svg("check"), style: "display:contents" }), "Connected");
    if (state.backend === "off") return el("span", { class: "tag" }, "Off");
    return el("span", { class: "tag warn" }, "Not connected");
  }

  async function act(button, name, ...args) {
    button.disabled = true;
    const result = await call(name, ...args);
    button.disabled = false;
    if (result && !result.ok) toast(result.error, true);
    return result && result.ok;
  }

  function accountPart(state, body) {
    const buttons = el("div", { class: "btn-row" });
    let help;
    if (state.using === "code" && state.signed_in) {
      help = "Abdoh uses Claude Code, signed in with your own account. Your plan's usage limits apply.";
      buttons.append(
        el("button", { class: "btn small", onclick: (e) => runTest(e.currentTarget) }, "Test"),
        el("button", { class: "btn small", onclick: async (e) => {
          if (await act(e.currentTarget, "claude_sign_out")) { toast("Signed out of Claude."); refresh(body); }
        } }, "Sign out"));
    } else if (state.installed) {
      help = "Sign in with your Claude Pro, Max, Team or Enterprise account, on Anthropic's page in your browser.";
      buttons.append(el("button", { class: "btn primary small", onclick: async (e) => {
        const button = e.currentTarget;
        button.disabled = true;
        const result = await call("claude_sign_in");
        button.disabled = false;
        if (result && !result.ok) toast(result.error, true);
        else if (result) wait("sign_in", body, result.url);
      } }, "Sign in with Claude"));
    } else {
      help = "To use your Claude account, Abdoh needs Claude Code, Anthropic's free app. It installs for you only, no admin rights needed.";
      buttons.append(el("button", { class: "btn primary small", onclick: async (e) => {
        if (await act(e.currentTarget, "install_claude")) wait("install", body);
      } }, "Install Claude Code"));
    }
    if (waiting) {
      help = waiting.kind === "install"
        ? "Installing Claude Code… This takes a minute or two, and this page updates when it's done."
        : el("span", {}, "Finish signing in in your browser… This page updates when you're signed in. ",
          waiting.url ? link("The browser didn't open?", waiting.url) : null);
    }
    return row("Your Claude account", help, buttons);
  }

  /* "How do I get a key?": a few short steps, with the pages to open. */
  const KEY_HELP = {
    anthropic: {
      title: "Get an Anthropic API key",
      intro: "You pay Anthropic for what Abdoh uses, from credit you add. It takes about five minutes.",
      steps: [
        ["Open the Claude Console and sign in, or make a free account.", ["Open the Claude Console", CONSOLE_URL]],
        ["Go to Billing and add some credit, for example $5."],
        ["Go to API keys and press Create key. Call it “Abdoh”."],
        ["Copy the key. It starts with sk-ant- and is shown only once."],
        ["Paste it into the box here and press Save key. Done!"],
      ],
      outro: "Keep your key to yourself, like a password. You can delete it in the Console any time, and Abdoh keeps it only on this computer.",
    },
    openrouter: {
      title: "Get an OpenRouter key",
      intro: "OpenRouter gives you Claude, GPT, Gemini and many more models with one key. You pay for what Abdoh uses, from credit you add.",
      steps: [
        ["Open OpenRouter and sign in, with Google or an email address.", ["Open OpenRouter", "https://openrouter.ai/"]],
        ["Open Credits (in the menu at the top right) and add some, for example $5. A few models are free, but most need credit."],
        ["Open Keys and press Create key. Call it “Abdoh”. You can give it a credit limit too.", ["Open Keys", OPENROUTER_URL]],
        ["Copy the key. It starts with sk-or- and is shown only once."],
        ["Paste it into the box here and press Save key, then pick a model. Done!"],
      ],
      outro: "Keep your key to yourself, like a password. You can delete it on OpenRouter any time, and Abdoh keeps it only on this computer.",
    },
  };

  function keyHelp(kind) {
    const help = KEY_HELP[kind];
    const steps = el("ol", { class: "key-steps" }, help.steps.map(([text, page]) => el("li", {},
      el("span", {}, text),
      page ? el("button", { class: "btn small", type: "button", onclick: () => call("open_link", page[1]) }, page[0]) : null)));
    const dialog = openModal({
      title: help.title,
      body: el("div", { class: "key-help" }, el("p", { class: "muted" }, help.intro), steps, el("p", { class: "fine" }, help.outro)),
      actions: [el("div", { class: "spacer" }), el("button", { class: "btn primary", type: "button", onclick: () => dialog.close() }, "Got it")],
    });
  }

  function howTo(kind) {
    return el("a", { href: "#", class: "how-to", onclick: (e) => { e.preventDefault(); keyHelp(kind); } }, "How do I get a key?");
  }

  function keyPart(state, body) {
    if (state.has_api_key) {
      return row("Your API key", "Saved on this computer only. Used when Claude Code isn't signed in (or if you choose it below).",
        el("div", { class: "btn-row" },
          state.using === "api" ? el("button", { class: "btn small", onclick: (e) => runTest(e.currentTarget) }, "Test") : null,
          el("button", { class: "btn small danger", onclick: async (e) => {
            if (await act(e.currentTarget, "set_api_key", "")) { toast("API key removed."); refresh(body); }
          } }, "Remove key")));
    }
    const input = el("input", { class: "input", type: "password", placeholder: "sk-ant-…", autocomplete: "off", style: "width:220px", "aria-label": "API key" });
    const save = el("button", { class: "btn small", onclick: async (e) => {
      if (!input.value.trim()) return;
      if (await act(e.currentTarget, "set_api_key", input.value)) { toast("API key saved."); refresh(body); }
    } }, "Save key");
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") save.click(); });
    return row("Or use an API key", el("span", {}, "Pay as you go, from the ", link("Claude Console", CONSOLE_URL), ". Stays on this computer. ", howTo("anthropic")),
      el("div", { class: "btn-row" }, input, save));
  }

  /* OpenRouter: Claude, GPT, Gemini and more with one key; the model is yours to pick. */
  function openrouterPart(state, body) {
    if (!state.has_openrouter_key) {
      const input = el("input", { class: "input", type: "password", placeholder: "sk-or-…", autocomplete: "off", style: "width:220px", "aria-label": "OpenRouter key" });
      const save = el("button", { class: "btn small", onclick: async (e) => {
        if (!input.value.trim()) return;
        if (await act(e.currentTarget, "set_openrouter_key", input.value)) { toast("OpenRouter key saved."); refresh(body); }
      } }, "Save key");
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") save.click(); });
      return row("Or use OpenRouter", el("span", {}, "Claude, GPT, Gemini and more with one key, from ", link("OpenRouter", OPENROUTER_URL), ". Stays on this computer. ", howTo("openrouter")),
        el("div", { class: "btn-row" }, input, save));
    }
    const rows = [row("OpenRouter", "Your key is saved on this computer only. Used when there's no Claude account or API key (or if you choose it below).",
      el("div", { class: "btn-row" },
        state.using === "openrouter" ? el("button", { class: "btn small", onclick: (e) => runTest(e.currentTarget) }, "Test") : null,
        el("button", { class: "btn small danger", onclick: async (e) => {
          if (await act(e.currentTarget, "set_openrouter_key", "")) { toast("OpenRouter key removed."); refresh(body); }
        } }, "Remove key")))];
    rows.push(modelPart(state));
    return el("div", {}, ...rows);
  }

  function modelPart(state) {
    const current = state.openrouter_model || "openrouter/auto";
    const select = el("select", { class: "input compact", "aria-label": "OpenRouter model", style: "width:340px;max-width:46vw" },
      el("option", { value: current, selected: true }, current));
    const filter = el("input", { class: "input compact", placeholder: "Search models", "aria-label": "Search models", style: "width:160px" });
    const help = el("span", {}, "Any model on OpenRouter. Smaller models may follow Abdoh's actions less well; one that sees images can look at your screen.");
    let all = [];
    const fill = () => {
      const words = filter.value.toLowerCase().split(/\s+/).filter(Boolean);
      const shown = all.filter((m) => m.id === current || words.every((w) => `${m.name} ${m.id}`.toLowerCase().includes(w)));
      select.replaceChildren(...shown.map((m) => el("option", { value: m.id, selected: m.id === select.value || (!select.value && m.id === current) },
        `${m.name}${m.price ? ` · ${m.price}` : ""}${m.images ? " · sees images" : ""}`)));
    };
    filter.addEventListener("input", fill);
    select.addEventListener("change", async () => {
      if (await saveSettings({ claude: { openrouter_model: select.value } })) toast("Model saved.");
    });
    call("openrouter_models").then((result) => {
      if (!result) return;
      if (!result.ok) { help.textContent = result.error; return; }
      all = result.models;
      if (!all.some((m) => m.id === current)) all.unshift({ id: current, name: current, price: "", images: false });
      fill();
      select.value = current;
    });
    return row("OpenRouter model", help, el("div", { class: "btn-row" }, filter, select));
  }

  function backendPart(state) {
    const choices = [["auto", "Automatic"], ["code", "Only my Claude account"], ["api", "Only my API key"],
      ["openrouter", "Only OpenRouter"], ["off", "Off (no Claude)"]];
    const select = el("select", { class: "input compact", "aria-label": "How Abdoh connects to Claude" },
      choices.map(([v, text]) => el("option", { value: v, selected: v === state.backend }, text)));
    select.addEventListener("change", async () => {
      if (await saveSettings({ claude: { backend: select.value } })) refresh(select.closest(".claude-body"));
    });
    return row("Use", "Automatic: your Claude account, then your API key, then OpenRouter.", select);
  }

  function speedPart(state) {
    if (state.using !== "code") return null;
    const current = (App.settings.claude || {}).code_model || "";
    const choices = [["", "Your Claude Code default"], ["haiku", "Fastest answers (Haiku)"], ["sonnet", "Balanced (Sonnet)"], ["opus", "Most capable (Opus)"]];
    if (!choices.some(([v]) => v === current)) choices.push([current, current]);
    const select = el("select", { class: "input compact", "aria-label": "Claude model" },
      choices.map(([v, text]) => el("option", { value: v, selected: v === current }, text)));
    select.addEventListener("change", () => saveSettings({ claude: { code_model: select.value } }));
    return row("Model", "A faster model starts talking sooner and uses less of your plan.", select);
  }

  async function runTest(button) {
    button.disabled = true;
    const old = button.textContent;
    button.textContent = "Testing…";
    const result = await call("claude_test");
    button.disabled = false;
    button.textContent = old;
    if (!result) return;
    if (result.ok) toast(`Claude answered: “${result.reply}”`);
    else toast(result.error, true);
  }

  function wait(kind, body, url = "") {
    waiting = { kind, url, until: Date.now() + (kind === "install" ? 15 : 10) * 60 * 1000 };
    refresh(body);
    const tick = async () => {
      if (!waiting || !body.isConnected) { waiting = null; return; }
      const state = await App.api.claude_status().catch(() => null);
      const done = state && (waiting.kind === "install" ? state.installed : state.signed_in);
      if (done || Date.now() > waiting.until) {
        const kind = waiting.kind;
        waiting = null;
        if (done) {
          await call("refresh_claude");
          toast(kind === "install" ? "Claude Code is installed. Now sign in." : "Claude is connected.");
        }
        refresh(body);
        return;
      }
      setTimeout(tick, POLL_MS);
    };
    setTimeout(tick, POLL_MS);
  }

  async function refresh(body) {
    if (!body) return;
    const state = await call("claude_status");
    if (!state) return;
    const card = body.closest(".card");
    const tag = card && card.querySelector(".claude-tag");
    if (tag) tag.replaceChildren(stateTag(state));
    body.replaceChildren(
      el("p", { class: "claude-summary" }, state.summary),
      accountPart(state, body),
      keyPart(state, body),
      openrouterPart(state, body),
      backendPart(state),
      speedPart(state),
      el("p", { class: "fine" },
        "Works with Claude Pro, Max, Team and Enterprise. Claude's free plan doesn't include Claude Code: use an API key, or use Abdoh without Claude (your commands, timers, apps and music still work). ",
        link("Compare plans", PLANS_URL), ". You sign in on Anthropic's own page; Abdoh never sees your password."));
  }

  function claudeCard() {
    const body = el("div", { class: "claude-body" }, el("p", { class: "muted" }, "Checking Claude…"));
    const card = el("div", { class: "card" },
      el("h2", {}, el("span", { html: svg("sparkles"), style: "display:contents" }), "Claude", el("span", { class: "spacer" }), el("span", { class: "claude-tag" })),
      el("p", { class: "lead" }, "Abdoh asks Claude about everything your commands don't cover. Connect your own Claude, billed to your own plan."),
      body);
    refresh(body);
    return card;
  }

  window.ClaudeCard = claudeCard;
  (window.SettingsExtras = window.SettingsExtras || []).push(claudeCard);
})();
