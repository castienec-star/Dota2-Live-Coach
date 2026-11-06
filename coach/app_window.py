"""The app's main window (tkinter, part of Python on Windows).

    py -m coach app

Start and stop the coach, see whether Dota 2 is connected, and read back what
the coach said this session. Settings and Dota setup open from here too. The
coach itself runs as its own process (see coach/app.py).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from .app import CoachProcess, Event, Status, _hidden, command

POLL_MS = 200
MAX_LINES = 500

# Black with a deep red accent (Castien, 2026-11-06): the colours only, no
# Valve logo or artwork.
BG, PANEL, TEXT, MUTED = "#0a0a0b", "#17171a", "#ecebea", "#8c8a88"
GREEN, AMBER, RED, ACCENT = "#4cc38a", "#e8b04b", "#ff5a4f", "#b8261c"
ACCENT_HOVER, PANEL_HOVER = "#d4362a", "#24242a"

TAGS = {
    "said": TEXT,
    "skipped": MUTED,
    "connected": GREEN,
    "match": MUTED,
    "problem": RED,
    "stopped": AMBER,
    "version": MUTED,
    "log": MUTED,
}


class AppWindow:
    def __init__(self, root: tk.Tk, app_dir: Path, coach: CoachProcess | None = None) -> None:
        self.root, self.app_dir = root, app_dir
        self.coach = coach or CoachProcess()
        self.status = Status()
        self.show_all = tk.BooleanVar(value=False)

        root.title("Dota 2 Live Coach")
        root.configure(bg=BG)
        root.minsize(560, 420)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 16))
        style.configure("Head.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI Semibold", 11))
        style.configure("TButton", background=PANEL, foreground=TEXT, borderwidth=0, padding=(12, 6))
        style.map("TButton", background=[("active", PANEL_HOVER)])
        style.configure("Go.TButton", background=ACCENT, foreground="white", font=("Segoe UI Semibold", 11),
                        padding=(20, 8))
        style.map("Go.TButton", background=[("active", ACCENT_HOVER)])
        style.configure("TCheckbutton", background=BG, foreground=MUTED,
                        indicatorbackground=PANEL, indicatorforeground=TEXT)
        style.map("TCheckbutton", background=[("active", BG)], indicatorbackground=[("selected", ACCENT)])
        style.configure("Vertical.TScrollbar", background=PANEL_HOVER, troughcolor=PANEL, bordercolor=PANEL,
                        arrowcolor=MUTED, lightcolor=PANEL_HOVER, darkcolor=PANEL_HOVER)

        outer = ttk.Frame(root, padding=16)
        outer.pack(fill="both", expand=True)

        top = ttk.Frame(outer)
        top.pack(fill="x")
        ttk.Label(top, text="Dota 2 Live Coach", style="Title.TLabel").pack(side="left")
        self.version = ttk.Label(top, text="", style="Muted.TLabel")
        self.version.pack(side="left", padx=(10, 0), pady=(6, 0))

        tk.Frame(outer, bg=ACCENT, height=2).pack(fill="x", pady=(10, 0))

        panel = ttk.Frame(outer, style="Panel.TFrame", padding=14)
        panel.pack(fill="x", pady=(12, 12))
        self.light = tk.Canvas(panel, width=14, height=14, bg=PANEL, highlightthickness=0)
        self.light.pack(side="left", padx=(0, 10))
        self.dot = self.light.create_oval(2, 2, 13, 13, fill=MUTED, outline="")
        text = ttk.Frame(panel, style="Panel.TFrame")
        text.pack(side="left", fill="x", expand=True)
        self.headline = ttk.Label(text, text="", style="Head.TLabel")
        self.headline.pack(anchor="w")
        self.detail = ttk.Label(text, text="", style="Panel.TLabel", wraplength=360)
        self.detail.pack(anchor="w")
        self.go = ttk.Button(panel, text="Start", style="Go.TButton", command=self.toggle)
        self.go.pack(side="right")

        log_frame = ttk.Frame(outer)
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(log_frame, bg=PANEL, fg=TEXT, relief="flat", wrap="word", height=14,
                           font=("Segoe UI", 10), padx=10, pady=8, state="disabled", cursor="arrow",
                           borderwidth=0, highlightthickness=0, selectbackground=ACCENT)
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        for kind, colour in TAGS.items():
            self.log.tag_configure(kind, foreground=colour)
        self.log.tag_configure("time", foreground=MUTED)

        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(12, 0))
        ttk.Button(bottom, text="Settings", command=lambda: self._side("settings")).pack(side="left")
        ttk.Button(bottom, text="Set up Dota 2", command=self.set_up).pack(side="left", padx=8)
        ttk.Button(bottom, text="Match reviews", command=self.open_reviews).pack(side="left")
        ttk.Checkbutton(bottom, text="Show details", variable=self.show_all).pack(side="right")

        self._write(Event("log", "Lines the coach says will appear here."))
        self._refresh()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(POLL_MS, self.poll)

    def toggle(self) -> None:
        if self.coach.running:
            self.coach.stop()
        else:
            self.coach.start()
            self.status.running = True
        self._refresh()

    def poll(self) -> None:
        for event in self.coach.events():
            self.status.update(event)
            if event.kind in ("said", "skipped", "connected", "match", "problem", "stopped") or self.show_all.get():
                self._write(event)
        self._refresh()
        self.root.after(POLL_MS, self.poll)

    def _write(self, event: Event) -> None:
        self.log.configure(state="normal")
        if event.time:
            self.log.insert("end", event.time + "  ", "time")
        prefix = "(too late, skipped) " if event.kind == "skipped" else ""
        self.log.insert("end", prefix + event.text + "\n", event.kind)
        excess = int(self.log.index("end-1c").split(".")[0]) - MAX_LINES
        if excess > 0:
            self.log.delete("1.0", f"{excess + 1}.0")
        self.log.configure(state="disabled")
        self.log.see("end")

    def _refresh(self) -> None:
        self.status.running = self.coach.running
        if not self.status.running:
            self.status.connected = False
        colour = GREEN if self.status.connected else (AMBER if self.status.running else MUTED)
        self.light.itemconfigure(self.dot, fill=colour)
        self.headline.configure(text=self.status.headline())
        self.detail.configure(text=self.status.problem or (f"Last line: {self.status.last_said}"
                                                           if self.status.last_said else ""))
        self.go.configure(text="Stop" if self.status.running else "Start")
        self.version.configure(text=f"version {self.status.version}" if self.status.version else "")

    def _side(self, *args: str) -> None:
        """Runs another coach command (settings, install) next to the app."""
        subprocess.Popen(command(*args), stdin=subprocess.DEVNULL, **_hidden())

    def set_up(self) -> None:
        proc = CoachProcess(args=("install",))
        proc.start()
        self._write(Event("log", "Setting up Dota 2's Game State Integration..."))

        def done() -> None:
            if proc.running:
                self.root.after(POLL_MS, done)
                return
            for event in proc.events():
                if event.kind != "stopped":
                    self._write(Event("problem" if event.kind == "problem" else "said", event.text))

        self.root.after(POLL_MS, done)

    def open_reviews(self) -> None:
        folder = self.app_dir / "reviews"
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606 (opens Explorer on the player's own folder)
        else:
            self._write(Event("log", f"Match reviews are in {folder}"))

    def close(self) -> None:
        self.coach.stop()
        self.root.destroy()


def open_window(app_dir: Path) -> None:
    root = tk.Tk()
    AppWindow(root, app_dir)
    root.mainloop()
