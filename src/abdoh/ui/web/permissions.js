/* The Permissions page: what Claude may do and see, whether your commands may run programs,
   and your own instructions for Abdoh. Every switch saves right away (AppApi.save_settings). */
"use strict";

(() => {
  const CLAUDE_ACTIONS = [
    ["open_url", "Open websites", "Links and web searches, in your browser."],
    ["open_app", "Open apps", "Programs installed on this computer, by name."],
    ["play_youtube", "Play on YouTube", "Starts the top video for a search."],
    ["media", "Music and volume", "Play, pause, skip tracks, volume up and down, mute."],
    ["timer", "Timers", "Abdoh tells you when the time is up."],
    ["remind", "Reminders", "Abdoh says them aloud at their time."],
    ["note", "Notes", "Adds lines to your notes file."],
    ["volume", "Exact volume", "Sets the speakers to a level you name."],
    ["brightness", "Screen brightness", "Changes the laptop screen's brightness."],
  ];
  const MAX_INSTRUCTIONS = 2000;
  let draft = null; // instructions being typed, kept across redraws

  function card(title, lead, rows) {
    return el("div", { class: "card" }, el("h2", {}, title), lead ? el("p", { class: "lead" }, lead) : null, rows);
  }

  async function saveOrUndo(changes, input) {
    if (!(await saveSettings(changes))) input.checked = !input.checked;
  }

  function claudeSwitch(key) {
    const claude = App.settings.claude || {};
    return toggle(claude[key], (on, input) => saveOrUndo({ claude: { [key]: on } }, input), key);
  }

  function actionSwitch(name) {
    const allowed = new Set((App.settings.claude || {}).actions || []);
    return toggle(allowed.has(name), (on, input) => {
      const next = CLAUDE_ACTIONS.map(([n]) => n).filter((n) => (n === name ? on : allowed.has(n)));
      saveOrUndo({ claude: { actions: next } }, input);
    }, name);
  }

  function folderBlock() {
    const claude = App.settings.claude || {};
    const folders = claude.folders || [];
    const save = (next) => saveSettings({ claude: { folders: next } });
    const add = async () => {
      const folder = await call("pick_folder");
      if (folder && !folders.includes(folder)) save([...folders, folder]);
    };
    const list = folders.map((folder) => el("div", { class: "folder" },
      el("span", { html: svg("file"), style: "display:contents" }), el("span", { title: folder }, folder),
      el("button", { class: "icon-btn", title: "Remove", html: svg("x"), onclick: () => save(folders.filter((f) => f !== folder)) })));
    return el("div", { class: claude.allow_files ? "" : "off" },
      row("Folders Claude may use",
        folders.length ? "Only these folders. Claude is told to stay in them, and its file tools are limited to them."
          : "Anywhere in your user folder (Desktop, Documents, Downloads, ...).",
        el("div", { class: "btn-row" },
          folders.length ? el("button", { class: "btn small", onclick: () => save([]) }, "Allow my whole user folder") : null,
          el("button", { class: "btn small", onclick: add }, el("span", { html: svg("plus") }), "Add a folder"))),
      folders.length ? el("div", { class: "folders" }, list) : null);
  }

  function instructionsCard() {
    const saved = (App.settings.claude || {}).instructions || "";
    const text = el("textarea", { class: "input", maxlength: MAX_INSTRUCTIONS, rows: 5,
      placeholder: "For example: Call me Mo. I live in Berlin, so use Celsius and euros. Keep answers short. Never buy anything or send messages for me." });
    text.value = draft ?? saved;
    const counter = el("span", { class: "counter" });
    const button = el("button", { class: "btn primary" }, "Save instructions");
    const update = () => {
      draft = text.value;
      counter.textContent = `${text.value.length} / ${MAX_INSTRUCTIONS}`;
      button.disabled = text.value.trim() === saved.trim();
    };
    text.addEventListener("input", update);
    button.addEventListener("click", async () => {
      button.disabled = true;
      if (await saveSettings({ claude: { instructions: text.value } })) draft = null;
      else update();
    });
    update();
    return card("Your instructions for Abdoh",
      "Tell Claude about yourself and how Abdoh should behave. They're sent with every request to Claude.",
      [text, el("div", { class: "row", style: "border:0;padding-bottom:0" }, counter, el("div", { class: "spacer" }), button)]);
  }

  function render() {
    const settings = App.settings;
    $("#perm-content").replaceChildren(
      el("div", { class: "page-head" }, el("h1", {}, "Permissions"),
        el("p", {}, "What Abdoh may do on your computer when Claude handles a request. Your own commands always work.")),
      card("What Claude may do", "When you ask Claude for something, Abdoh can also do these things for you.",
        CLAUDE_ACTIONS.map(([name, title, help]) => row(title, help, actionSwitch(name)))),
      card("What Claude may see and use", null, [
        row("Search the web", "For news, weather, prices and anything recent.", claudeSwitch("allow_web")),
        row("Look at your screen when you ask",
          "When what you say is about something on your screen (“what does this error mean?”, “read this to me”), Claude asks to see it, and Abdoh sends a picture of the screen you're using. Abdoh always says when it looks.",
          claudeSwitch("allow_screen")),
        row("Work with your files and run PowerShell",
          "Create, read, change and sort files. Claude asks before deleting or overwriting anything, and deletes to the Recycle Bin.",
          claudeSwitch("allow_files")),
        folderBlock(),
      ]),
      card("Your commands", null, [
        row("Your commands may run programs", "Needed for the “Run a program” action on the Commands page.",
          toggle(settings.allow_run, (on, input) => saveOrUndo({ allow_run: on }, input), "allow_run")),
      ]),
      instructionsCard());
  }

  registerPage("permissions", {
    show: render,
    settingsChanged() { if (App.current === "permissions") render(); },
  });
})();
