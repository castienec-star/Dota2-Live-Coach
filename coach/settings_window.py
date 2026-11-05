"""A small settings window (tkinter, part of Python on Windows; no server).

    py -m coach settings

Turns reminders on and off, picks the mode and the voice, and edits a hero's
build. Saves to the player's own coach.toml (see coach/settings.py); the
running coach picks the changes up when it is started again.
"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from . import config as config_mod
from . import settings
from .heroes import HeroInfo, load_heroes
from .items import ItemInfo, load_items
from .speaker import installed_voices, make_backend

DEFAULT_VOICE = "Windows default"
TEST_LINE = "Power rune in 15 seconds."


class SettingsWindow:
    def __init__(
        self,
        root: tk.Tk,
        user_file: Path,
        defaults: dict,
        user: dict,
        heroes: dict[int, HeroInfo],
        items: dict[str, ItemInfo],
        voices: list[str],
        start_hero: HeroInfo | None = None,
    ) -> None:
        self.root, self.user_file = root, user_file
        self.defaults, self.user, self.items = defaults, user, items
        root.title("Dota 2 Live Coach settings")
        root.resizable(False, False)
        body = ttk.Frame(root, padding=12)
        body.grid(sticky="nsew")

        # Mode
        self.mode = tk.StringVar(value=str(_merged(defaults, user, "coach", "mode", "beginner")).lower())
        self._mode_was = self.mode.get()
        box = ttk.LabelFrame(body, text="How much the coach talks", padding=8)
        box.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ttk.Radiobutton(box, text="Beginner: every reminder and tip", value="beginner",
                        variable=self.mode, command=self._mode_changed).grid(sticky="w")
        ttk.Radiobutton(box, text="Experienced: gold, stacks, power rune, buyback", value="experienced",
                        variable=self.mode, command=self._mode_changed).grid(sticky="w")

        # Voice
        box = ttk.LabelFrame(body, text="Voice", padding=8)
        box.grid(row=0, column=1, sticky="nsew")
        name = str(_merged(defaults, user, "voice", "name", ""))
        choices = [DEFAULT_VOICE] + voices + ([name] if name and name not in voices else [])
        self.voice = tk.StringVar(value=name or DEFAULT_VOICE)
        ttk.Combobox(box, textvariable=self.voice, values=choices, state="readonly", width=36).grid(
            row=0, column=0, columnspan=2, sticky="we")
        ttk.Label(box, text="Speed").grid(row=1, column=0, sticky="w")
        self.rate = tk.IntVar(value=int(_merged(defaults, user, "voice", "rate", 0)))
        tk.Scale(box, from_=-10, to=10, orient="horizontal", variable=self.rate, length=200).grid(
            row=1, column=1, sticky="we")
        ttk.Button(box, text="Test the voice", command=self._test_voice).grid(row=2, column=0, columnspan=2)

        # Reminders
        box = ttk.LabelFrame(body, text="Reminders", padding=8)
        box.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=8)
        self.checks: dict[str, tk.BooleanVar] = {}
        names = settings.reminder_names(defaults)
        half = (len(names) + 1) // 2
        for i, (key, on) in enumerate(settings.checks(defaults, user, self.mode.get()).items()):
            self.checks[key] = tk.BooleanVar(value=on)
            ttk.Checkbutton(box, text=settings.label(key), variable=self.checks[key]).grid(
                row=i % half, column=i // half, sticky="w", padx=(0, 16))

        # Builds
        box = ttk.LabelFrame(body, text="Item build", padding=8)
        box.grid(row=2, column=0, columnspan=2, sticky="nsew")
        self.build_keys = dict(settings.ROLE_BUILDS) | {
            h.key: h.name for h in sorted(heroes.values(), key=lambda h: h.name)
        }
        self.key_by_label = {v: k for k, v in self.build_keys.items()}
        start = start_hero.key if start_hero and start_hero.key in self.build_keys else "default"
        self.hero = tk.StringVar(value=self.build_keys[start])
        pick = ttk.Combobox(box, textvariable=self.hero, values=list(self.build_keys.values()),
                            state="readonly", width=30)
        pick.grid(row=0, column=0, sticky="w")
        pick.bind("<<ComboboxSelected>>", lambda _e: self._show_build())
        ttk.Button(box, text="Use the default build", command=self._reset_build).grid(row=0, column=1, sticky="e")
        self.build_text = tk.Text(box, width=44, height=6)
        self.build_text.grid(row=1, column=0, columnspan=2, sticky="we", pady=4)
        self.build_note = ttk.Label(box, wraplength=380)
        self.build_note.grid(row=2, column=0, columnspan=2, sticky="w")
        # Build key -> box text the player typed (None: back to the default).
        self.edited: dict[str, str | None] = {}
        self.shown = start
        self._fill_build()

        # Save
        row = ttk.Frame(body)
        row.grid(row=3, column=0, columnspan=2, sticky="we", pady=(8, 0))
        self.status = ttk.Label(row, text="", wraplength=360)
        self.status.grid(row=0, column=0, sticky="w")
        ttk.Button(row, text="Save", command=self.save).grid(row=0, column=1, padx=4)
        ttk.Button(row, text="Close", command=root.destroy).grid(row=0, column=2)
        row.columnconfigure(0, weight=1)

    # -- mode and voice

    def _mode_changed(self) -> None:
        current = {k: v.get() for k, v in self.checks.items()}
        for key, on in settings.remode(current, self._mode_was, self.mode.get(), self.defaults).items():
            self.checks[key].set(on)
        self._mode_was = self.mode.get()

    def _voice_name(self) -> str:
        name = self.voice.get()
        return "" if name == DEFAULT_VOICE else name

    def _test_voice(self) -> None:
        name, rate = self._voice_name(), self.rate.get()
        threading.Thread(
            target=lambda: make_backend("sapi", name, rate).speak(TEST_LINE), daemon=True
        ).start()

    # -- builds

    def _box_text(self) -> str:
        return self.build_text.get("1.0", "end").strip()

    def _fill_build(self) -> None:
        key = self.shown
        text = self.edited.get(key)
        if text is None:
            text = "\n".join(settings.build_for(key, self.defaults, {} if key in self.edited else self.user))
        self.build_text.delete("1.0", "end")
        self.build_text.insert("1.0", text)
        self._loaded = self._box_text()
        if key in settings.ROLE_BUILDS:
            note = "One item per line. Every hero without its own build uses this list."
        elif key in self.defaults.get("builds", {}):
            note = "One item per line. Leave it empty to turn item reminders off for this hero."
        else:
            note = ("One item per line. Empty: the coach uses the role default, or the items "
                    "players buy most on this hero.")
        self.build_note.configure(text=note)

    def _keep_edit(self) -> None:
        if self._box_text() != self._loaded:
            self.edited[self.shown] = self._box_text()

    def _show_build(self) -> None:
        self._keep_edit()
        self.shown = self.key_by_label[self.hero.get()]
        self._fill_build()

    def _reset_build(self) -> None:
        self.edited[self.shown] = None
        self._fill_build()
        self.status.configure(text=f"{self.hero.get()} is back on the default build (not saved yet).")

    # -- save

    def save(self) -> bool:
        self._keep_edit()
        builds: dict[str, list[str] | None] = {}
        for key, text in self.edited.items():
            if text is None:
                builds[key] = None
                continue
            names, unknown = settings.build_choice(key, text, self.defaults, self.items)
            if unknown:
                self.status.configure(
                    text=f"Not saved: the coach doesn't know {', '.join(unknown)} "
                    f"({self.build_keys[key]}). Use the item's full name.")
                return False
            builds[key] = names
        data = settings.updated(
            self.defaults,
            self.user,
            mode=self.mode.get(),
            voice_name=self._voice_name(),
            voice_rate=self.rate.get(),
            reminders={k: v.get() for k, v in self.checks.items()},
            builds=builds,
        )
        settings.save(self.user_file, data)
        self.user, self.edited = data, {}
        self._fill_build()
        self.status.configure(text="Saved. Restart the coach to use the new settings.")
        return True


def _merged(defaults: dict, user: dict, section: str, key: str, fallback):
    return user.get(section, {}).get(key, defaults.get(section, {}).get(key, fallback))


def open_window(user_file: Path, record_dir: Path) -> None:
    defaults = config_mod._read_toml(config_mod.DEFAULTS_FILE)
    user = config_mod._read_toml(user_file)
    heroes = load_heroes()
    root = tk.Tk()
    SettingsWindow(
        root, user_file, defaults, user, heroes, load_items(), installed_voices(),
        settings.last_hero(record_dir, heroes),
    )
    root.mainloop()
