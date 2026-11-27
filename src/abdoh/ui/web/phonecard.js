/* Settings → Phone (ABDOH_EPIC_10.md, 3.4): use Abdoh from your phone. Tailscale connects the
   phone and this computer privately; a QR code pairs a phone once. */
"use strict";

(() => {
  const POLL_MS = 5000;
  let httpsLink = ""; // Tailscale asked to allow HTTPS for the tailnet: its page
  let pairing = null; // the pairing code being shown: {url, qr, minutes}

  function link(text, url) {
    return el("a", { href: "#", onclick: (e) => { e.preventDefault(); call("open_link", url); } }, text);
  }

  function ready(state) {
    const t = state.tailscale || {};
    return state.on && state.running && t.running && t.shared;
  }

  function stateTag(state) {
    if (!state.on) return el("span", { class: "tag" }, "Off");
    if (ready(state)) return el("span", { class: "tag good" }, el("span", { html: svg("check"), style: "display:contents" }), "Ready");
    return el("span", { class: "tag warn" }, "Needs setup");
  }

  /* "5 minutes ago", "yesterday", "27 Nov" (times are seconds since 1970). */
  function ago(seconds) {
    if (!seconds) return "";
    const s = Math.max(0, Date.now() / 1000 - seconds);
    if (s < 90) return "just now";
    if (s < 3600) return `${Math.round(s / 60)} minutes ago`;
    if (s < 86400) return `${Math.round(s / 3600)} hours ago`;
    if (s < 2 * 86400) return "yesterday";
    return new Date(seconds * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short" });
  }

  function step(n, done, title, help, control) {
    return el("div", { class: `phone-step${done ? " done" : ""}` },
      el("span", { class: "num", html: done ? svg("check") : String(n) }),
      el("div", { class: "label" }, el("b", {}, title), help ? el("small", {}, help) : null),
      control || null);
  }

  function steps(state, redraw) {
    const t = state.tailscale || {};
    const share = async (button) => {
      button.disabled = true;
      button.textContent = "Sharing…";
      const result = (await call("phone_share")) || {};
      if (result.ok) { httpsLink = ""; toast("Abdoh is shared in your Tailscale network."); }
      else if (result.link) httpsLink = result.link;
      else toast(result.error || "Couldn't share Abdoh.", true);
      redraw();
    };
    const third = t.shared
      ? step(3, true, "Shared in your Tailscale network", el("span", {}, "Your phone page: ", el("code", { class: "phone-address" }, t.address)))
      : httpsLink
        ? step(3, false, "Allow HTTPS in your Tailscale network",
          "Tailscale asks once: on its page, allow HTTPS certificates. Then press Share again.",
          el("div", { class: "btn-row" },
            el("button", { class: "btn small", onclick: () => call("open_link", httpsLink) }, "Allow HTTPS"),
            el("button", { class: "btn primary small", onclick: (e) => share(e.currentTarget) }, "Share")))
        : step(3, false, "Share Abdoh in your Tailscale network",
          "Only your own devices can reach it. Nothing is open to the internet.",
          t.running ? el("button", { class: "btn primary small", onclick: (e) => share(e.currentTarget) }, "Share") : null);
    return el("div", { class: "phone-steps" },
      step(1, t.installed, "Install Tailscale on this computer",
        t.installed ? "Installed." : "Free. It connects your phone and this computer privately, at home or anywhere.",
        t.installed ? null : el("button", { class: "btn primary small", onclick: () => call("open_link", state.download) }, "Get Tailscale")),
      step(2, t.running, "Sign in and turn it on",
        t.running ? "Tailscale is on." : (t.installed && t.error) || "Open Tailscale from the Start menu and sign in. Use the same account on your phone."),
      third,
      el("div", { class: "btn-row", style: "justify-content:flex-start;margin-top:4px" },
        el("button", { class: "btn small", onclick: redraw }, "Check again")));
  }

  function pairPart(state, redraw) {
    if (!ready(state)) return null;
    const start = async (button) => {
      button.disabled = true;
      const result = (await call("phone_pair")) || {};
      button.disabled = false;
      if (!result.ok) return toast(result.error || "Couldn't make a code.", true);
      pairing = result;
      redraw();
    };
    if (!pairing) {
      return row("Pair a phone", "Show a code to scan with your phone's camera.",
        el("button", { class: "btn primary small", onclick: (e) => start(e.currentTarget) }, el("span", { html: svg("plus") }), "Pair a phone"));
    }
    const field = el("input", { class: "input", readonly: true, value: pairing.url, "aria-label": "Pairing link", onfocus: (e) => e.target.select() });
    const copy = async () => {
      try { await navigator.clipboard.writeText(pairing.url); } catch (e) { field.select(); document.execCommand("copy"); }
      toast("Link copied");
    };
    return el("div", { class: "phone-pair" },
      el("div", { class: "phone-qr", html: pairing.qr, role: "img", "aria-label": "QR code that pairs your phone" }),
      el("div", { class: "phone-pair-text" },
        el("b", {}, "On your phone"),
        el("ol", {},
          el("li", {}, "Install Tailscale (App Store or Google Play), sign in with the same account, and turn it on."),
          el("li", {}, "Scan this code with the camera, and open the link."),
          el("li", {}, "iPhone: tap Share, then Add to Home Screen, and open Abdoh from your Home Screen. Android: tap Install app.")),
        el("small", { class: "muted" }, `The code works once, for ${pairing.minutes} minutes. Or send yourself the link:`),
        el("div", { class: "phone-link" }, field, el("button", { class: "btn small", onclick: copy }, "Copy")),
        el("div", { class: "btn-row", style: "justify-content:flex-start" },
          el("button", { class: "btn small", onclick: () => { pairing = null; redraw(); } }, "Done"),
          el("button", { class: "btn small", onclick: (e) => start(e.currentTarget) }, "New code"))));
  }

  function phonesPart(state, redraw) {
    const phones = state.phones || [];
    if (!phones.length) return state.on ? row("Your phones", "None paired yet.", null) : null;
    return el("div", { class: "phone-list" },
      el("div", { class: "phone-list-head" }, el("b", {}, "Your phones")),
      phones.map((p) => row(p.name, `Paired ${ago(p.added)} · used ${ago(p.seen)}`,
        el("button", { class: "btn small", onclick: async (e) => {
          e.currentTarget.disabled = true;
          await call("phone_remove", p.id);
          toast(`Removed. That ${p.name} can't reach Abdoh any more.`);
          redraw();
        } }, "Remove"))));
  }

  async function draw(card, body) {
    const state = (await call("phone_state")) || {};
    if (!card.isConnected && body.dataset.drawn) return;  // the page was redrawn meanwhile
    body.dataset.drawn = "1";
    card.querySelector(".phone-tag").replaceChildren(stateTag(state));
    const redraw = () => draw(card, body);
    const onOff = row("Use Abdoh from your phone", "Talk and type to Abdoh from your phone, and hear its answers there.",
      toggle(state.on, async (on, input) => {
        input.disabled = true;
        const saved = await saveSettings({ phone: on }, true);
        if (!saved) { input.checked = !on; input.disabled = false; return; }
        if (!on && state.tailscale && state.tailscale.shared) await call("phone_unshare");
        if (!on) pairing = null;
        toast(on ? "Abdoh can be used from your phone." : "Your phone can't reach Abdoh now.");
        setTimeout(redraw, 700);  // Abdoh starts or stops the page
      }, "Use Abdoh from your phone"));
    const parts = [onOff];
    if (state.error) parts.push(el("div", { class: "banner", "data-kind": "error" }, el("div", { class: "text" }, state.error)));
    if (state.on) {
      parts.push(steps(state, redraw), pairPart(state, redraw), phonesPart(state, redraw),
        row("Keep this computer awake", "Your phone reaches Abdoh only while this computer is on and awake. When it's plugged in, let it never sleep.",
          el("button", { class: "btn small", onclick: () => call("open_power_settings") }, "Power settings")));
    } else parts.push(phonesPart(state, redraw));
    body.replaceChildren(...parts.filter(Boolean));
    clearTimeout(card.poll);
    if (state.on && !ready(state)) {  // waiting for Tailscale: look again by itself
      card.poll = setTimeout(() => { if (card.isConnected && App.current === "settings" && !httpsLink) redraw(); }, POLL_MS);
    }
  }

  function phoneCard() {
    const body = el("div", {}, el("p", { class: "muted" }, "Checking…"));
    const card = el("div", { class: "card", id: "phone-card" },
      el("h2", {}, el("span", { html: svg("phone"), style: "display:contents" }), "Phone", el("span", { class: "spacer" }), el("span", { class: "phone-tag" })),
      el("p", { class: "lead" }, "Use Abdoh from your phone, at home or anywhere. ",
        link("Tailscale", "https://tailscale.com"), " (free) connects your phone and this computer privately: nothing is open to the internet, and only phones you pair can use Abdoh."),
      body);
    draw(card, body);
    return card;
  }

  window.PhoneCard = phoneCard;
})();
