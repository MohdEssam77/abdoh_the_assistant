"""The one simple window. It only displays events and forwards requests; no logic here."""

import tkinter as tk
from tkinter import scrolledtext, simpledialog

from abdoh.events import Bus

HISTORY_LINES = 50
POLL_MS = 100


class Window:
    def __init__(self, bus: Bus, start_hidden: bool = False, tray=None):
        self.bus = bus
        self.tray = tray  # the tray icon also shows status and voice state
        self.root = tk.Tk()
        self.root.title("Xanthos")
        self.root.geometry("520x420")
        self.root.protocol("WM_DELETE_WINDOW", self.root.withdraw)  # closing only hides

        menu = tk.Menu(self.root)
        app_menu = tk.Menu(menu, tearoff=False)
        app_menu.add_command(label="Hide window", command=self.root.withdraw)
        app_menu.add_separator()
        app_menu.add_command(label="Quit", command=self.quit)
        menu.add_cascade(label="Xanthos", menu=app_menu)
        self.root.config(menu=menu)

        self.status = tk.StringVar(value="Status: Starting...")
        self.claude = tk.StringVar(value="Claude: ...")
        self.wake = tk.StringVar(value="Wake word: ...")
        status_label = tk.Label(self.root, textvariable=self.status, anchor="w")
        status_label.pack(fill="x", padx=8, pady=(8, 0))
        tk.Label(self.root, textvariable=self.claude, anchor="w").pack(fill="x", padx=8)
        tk.Label(self.root, textvariable=self.wake, anchor="w").pack(fill="x", padx=8)

        self.history = scrolledtext.ScrolledText(
            self.root, height=12, state="disabled", wrap="word"
        )
        self.history.pack(fill="both", expand=True, padx=8, pady=8)

        entry_row = tk.Frame(self.root)
        entry_row.pack(fill="x", padx=8)
        self.entry = tk.Entry(entry_row)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda e: self.send())
        tk.Button(entry_row, text="Send", command=self.send).pack(side="left", padx=(4, 0))
        tk.Button(entry_row, text="Stop", command=lambda: bus.request("stop_speaking")).pack(
            side="left", padx=(4, 0)
        )

        buttons = tk.Frame(self.root)
        buttons.pack(fill="x", padx=8, pady=8)
        self.paused = False
        self.voice_on = True
        self.pause_button = tk.Button(buttons, text="Pause listening", command=self.toggle_pause)
        self.pause_button.pack(side="left")
        tk.Button(buttons, text="Edit commands", command=lambda: bus.request("edit_commands")).pack(
            side="left", padx=4
        )
        tk.Button(buttons, text="Reload commands", command=lambda: bus.request("reload")).pack(
            side="left"
        )
        self.voice_button = tk.Button(buttons, text="Voice replies: On", command=self.toggle_voice)
        self.voice_button.pack(side="left", padx=4)
        tk.Button(buttons, text="Set Claude key", command=self.set_key).pack(side="left")

        if start_hidden:
            self.root.withdraw()
        self.root.after(POLL_MS, self.poll)

    # ----- requests to the daemon -----

    def send(self) -> None:
        text = self.entry.get().strip()
        if text:
            self.entry.delete(0, "end")
            self.bus.request("text", text)

    def toggle_pause(self) -> None:
        self.bus.request("resume" if self.paused else "pause")

    def toggle_voice(self) -> None:
        self.bus.request("voice", not self.voice_on)  # the daemon confirms with a "voice" event

    def set_key(self) -> None:
        key = simpledialog.askstring(
            "Set Claude key", "Paste your Anthropic API key:", show="*", parent=self.root
        )
        if key is not None:
            self.bus.request("set_key", key)

    def quit(self) -> None:
        self.bus.request("quit")
        self.root.destroy()

    # ----- events from the daemon -----

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def append_history(self, line: str) -> None:
        self.history.config(state="normal")
        self.history.insert("end", line + "\n")
        extra = int(self.history.index("end-1c").split(".")[0]) - 1 - HISTORY_LINES
        if extra > 0:
            self.history.delete("1.0", f"{extra + 1}.0")
        self.history.see("end")
        self.history.config(state="disabled")

    def poll(self) -> None:
        for kind, value in self.bus.pending_events():
            if kind == "status":
                self.status.set(f"Status: {value}")
                if self.tray:
                    self.tray.show_status(value)
                if value in ("Listening", "Paused"):
                    self.paused = value == "Paused"
                    self.pause_button.config(
                        text="Resume listening" if self.paused else "Pause listening"
                    )
            elif kind == "claude":
                self.claude.set(f"Claude: {value}")
            elif kind == "wake":
                self.wake.set(f"Wake word: {value}")
            elif kind == "voice":
                self.voice_on = bool(value)
                self.voice_button.config(text=f"Voice replies: {'On' if value else 'Off'}")
                if self.tray:
                    self.tray.show_voice(self.voice_on)
            elif kind == "history":
                self.append_history(value)
            elif kind == "show":
                self.show()
            elif kind == "page" and value == "commands":
                self.bus.request("edit_commands")  # this simple window has no Commands page
            elif kind == "quit":
                self.root.destroy()
                return
        self.root.after(POLL_MS, self.poll)

    def mainloop(self) -> None:
        self.root.mainloop()
