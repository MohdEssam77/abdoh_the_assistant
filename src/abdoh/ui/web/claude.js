/* The Claude card (top of Settings, and in the first-start setup): connect your own Claude
   account through Claude Code's own sign-in, or your own API key. Abdoh never sees passwords. */
"use strict";

(() => {
  const PLANS_URL = "https://claude.com/pricing";
  const CONSOLE_URL = "https://platform.claude.com/";
  const POLL_MS = 3000;
  let waiting = null; // {kind: "install" | "sign_in", until: time}

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
      help = "Sign in with your Claude Pro, Max, Team or Enterprise account. It opens Claude Code's sign-in, then your browser.";
      buttons.append(el("button", { class: "btn primary small", onclick: async (e) => {
        if (await act(e.currentTarget, "claude_sign_in")) wait("sign_in", body);
      } }, "Sign in with Claude"));
    } else {
      help = "To use your Claude account, Abdoh needs Claude Code, Anthropic's free app. It installs for you only, no admin rights needed.";
      buttons.append(el("button", { class: "btn primary small", onclick: async (e) => {
        if (await act(e.currentTarget, "install_claude")) wait("install", body);
      } }, "Install Claude Code"));
    }
    if (waiting) {
      help = waiting.kind === "install"
        ? "Installing Claude Code in the other window… This page updates when it's done."
        : "Finish signing in in your browser… This page updates when you're signed in.";
    }
    return row("Your Claude account", help, buttons);
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
    return row("Or use an API key", el("span", {}, "Pay as you go, from the ", link("Claude Console", CONSOLE_URL), ". Stays on this computer."),
      el("div", { class: "btn-row" }, input, save));
  }

  function backendPart(state) {
    const choices = [["auto", "Automatic (account first, then key)"], ["code", "Only my Claude account"], ["api", "Only my API key"], ["off", "Off (no Claude)"]];
    const select = el("select", { class: "input compact", "aria-label": "How Abdoh connects to Claude" },
      choices.map(([v, text]) => el("option", { value: v, selected: v === state.backend }, text)));
    select.addEventListener("change", async () => {
      if (await saveSettings({ claude: { backend: select.value } })) refresh(select.closest(".claude-body"));
    });
    return row("Use", null, select);
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

  function wait(kind, body) {
    waiting = { kind, until: Date.now() + (kind === "install" ? 10 : 5) * 60 * 1000 };
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
      backendPart(state),
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
