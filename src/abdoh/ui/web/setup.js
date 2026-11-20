/* The first-start setup: welcome, microphone, voice, Claude, and how to talk to Xanthos. Shown
   until it's finished or skipped (setup_done); Settings → General can open it again. */
"use strict";

(() => {
  const STEPS = ["Welcome", "Microphone", "Voice", "Claude", "Talk to Xanthos"];
  let overlay = null;
  let step = 0;
  let data = {};

  function wakePhrases() {
    const words = (App.settings.wake_words || []).filter((w) => w.includes(" "));
    const shown = (words.length ? words : ["hey abdoh"]).slice(0, 2);
    return shown.map((w) => `“${w.replace(/\b\w/g, (c) => c.toUpperCase())}”`).join(" or ");
  }

  function welcome() {
    const point = (icon, title, text) => el("div", { class: "point" },
      el("span", { class: "cmd-icon", html: svg(icon) }), el("div", {}, el("b", {}, title), el("p", {}, text)));
    return el("div", { class: "setup-hero" },
      el("div", { class: "orb", html: ICON.logo }),
      el("h1", {}, "Welcome to Xanthos"),
      el("p", { class: "muted" }, "Your voice assistant for this computer. Let's get you set up; it takes about two minutes."),
      el("div", { class: "points" },
        point("say", "Talk or type", "Ask for anything. Xanthos answers out loud."),
        point("bolt", "Your own commands", "The things you do every day, done instantly."),
        point("sparkles", "Your own Claude", "Connect your Claude account for everything else.")));
  }

  function microphone() {
    return el("div", {},
      el("h2", { class: "step-title" }, "Can Xanthos hear you?"),
      el("p", { class: "muted step-lead" }, "Say something. The bar should move. If it doesn't, pick another microphone, or check that it isn't muted in Windows."),
      window.Settings.micCard(data.mics));
  }

  function voice() {
    return el("div", {},
      el("h2", { class: "step-title" }, "How should Xanthos sound?"),
      el("p", { class: "muted step-lead" }, "Pick a voice and a speed, then press Test voice."),
      window.Settings.voiceCard(data.voices));
  }

  function claude() {
    return el("div", {},
      el("h2", { class: "step-title" }, "Connect your Claude"),
      el("p", { class: "muted step-lead" }, "Optional. Your commands, timers, apps and music work without it. With it, Xanthos can answer questions, search the web and do more."),
      window.ClaudeCard());
  }

  function talk() {
    const tip = (title, ...text) => el("div", { class: "point" },
      el("span", { class: "cmd-icon", html: svg("check") }), el("div", {}, el("b", {}, title), el("p", {}, ...text)));
    return el("div", {},
      el("h2", { class: "step-title" }, "You're ready"),
      el("p", { class: "muted step-lead" }, "Three ways to talk to Xanthos:"),
      el("div", { class: "points" },
        tip(`Say ${wakePhrases()}`, "then your request, like “what time is it” or “set a timer for 10 minutes”."),
        tip("Press the hotkey", ...kbds(App.settings.hotkey), " anywhere, then talk. Press it again to stop a reply."),
        tip("Or type", "in the box at the bottom of the window."),
        tip("It stays in the tray", "Closing the window keeps Xanthos running. Click the tray icon to come back.")));
  }

  const BUILD = [welcome, microphone, voice, claude, talk];

  function render() {
    window.Settings.stopMeter();
    const last = step === STEPS.length - 1;
    const body = el("div", { class: "setup-body" }, BUILD[step]());
    const dots = el("div", { class: "steps", "aria-label": `Step ${step + 1} of ${STEPS.length}` },
      STEPS.map((name, i) => el("span", { class: i === step ? "dot on" : i < step ? "dot done" : "dot", title: name })));
    const panel = el("div", { class: "setup", role: "dialog", "aria-modal": "true", "aria-label": "Set up Xanthos" },
      el("div", { class: "setup-head" }, dots, el("span", { class: "faint" }, STEPS[step]), el("div", { class: "spacer" }),
        el("button", { class: "btn ghost small", onclick: () => finish(true) }, "Skip setup")),
      body,
      el("div", { class: "modal-foot" },
        step > 0 ? el("button", { class: "btn", onclick: () => { step -= 1; render(); } }, "Back") : null,
        el("div", { class: "spacer" }),
        el("button", { class: "btn primary", onclick: () => (last ? finish(false) : (step += 1, render())) },
          last ? "Start using Xanthos" : step === 0 ? "Get started" : "Next")));
    const back = el("div", { class: "setup-back" }, panel);
    if (overlay) overlay.replaceWith(back);
    else document.body.append(back);
    overlay = back;
    if (STEPS[step] === "Microphone") window.Settings.startMeter(panel);
  }

  async function open() {
    step = 0;
    const [mics, voices] = await Promise.all([call("microphones"), call("voices")]);
    data = { mics, voices };
    render();
  }

  async function finish(skipped) {
    window.Settings.stopMeter();
    if (overlay) overlay.remove();
    overlay = null;
    await saveSettings({ setup_done: true }, true);
    if (!skipped) {
      showPage("home");
      toast("All set. Say hello to Xanthos!");
    }
  }

  window.Setup = { open };

  registerPage("setup", {
    boot(boot) {
      const forced = App.demo && new URLSearchParams(location.search).get("setup");
      if (forced) {
        open().then(() => { step = Math.min(Number(forced) || 0, STEPS.length - 1); render(); });
      } else if (boot.settings && boot.settings.setup_done === false) {
        open();
      }
    },
  });
})();
