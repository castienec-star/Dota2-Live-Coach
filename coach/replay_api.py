"""What the Replay review window (coach/ui/replay.html) can ask Python for.

The window starts `py -m coach replay-review` as its own process, like the
live coach (coach/app.py). Both listen for Dota on the same port, so starting
one stops the other.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from . import llm, vision
from .app import CoachProcess, Event
from .heroes import load_heroes
from .replay_review import DEFAULT_INTERVAL, MODES

SETTINGS = "replay_review.json"
DEFAULTS = {"mode": "moments", "interval": DEFAULT_INTERVAL["continuous"], "model": vision.DEFAULT_MODEL, "hero": ""}
PREFIX = "Replay review: "


class ReplayApi:
    def __init__(self, app_dir: Path, stop_live: Callable[[], object] = lambda: None,
                 process: Callable[[tuple[str, ...]], CoachProcess] = lambda args: CoachProcess(args=args),
                 installed: Callable[[str, str], bool | None] = vision.installed) -> None:
        self._app_dir = app_dir
        self._stop_live = stop_live
        self._process = process
        self._installed = installed
        self._proc: CoachProcess | None = None
        self._lock = threading.Lock()
        self._following = ""

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.running

    def load(self) -> dict:
        heroes = sorted((h.name, h.key) for h in load_heroes().values())
        return {
            "settings": self._settings(),
            "models": [{"id": k, "label": v} for k, v in vision.MODELS.items()],
            "heroes": [{"key": k, "name": n} for n, k in heroes],
            "intervals": [4, 6, 8, 10, 15, 20, 30],
        }

    def check_model(self, model: str) -> dict:
        have = self._installed(model, llm.DEFAULT_URL)
        if have is None:
            return {"ok": False, "text": "Ollama isn't running. Start Ollama, or the coach reviews without looking at the screen."}
        if not have:
            return {"ok": False, "text": f"Not installed yet. In Command Prompt: ollama pull {model}"}
        return {"ok": True, "text": "Installed and ready."}

    def start(self, sent: dict) -> dict:
        settings = self._save(sent)
        self.stop()
        self._stop_live()
        args = ["replay-review", "--mode", settings["mode"], "--vision-model", settings["model"]]
        if settings["mode"] == "continuous":
            args += ["--interval", str(settings["interval"])]
        if settings["hero"]:
            args += ["--hero", settings["hero"]]
        with self._lock:
            self._following = ""
            self._proc = self._process(tuple(args))
            self._proc.start()
        return self.poll()

    def stop(self) -> dict:
        with self._lock:
            if self._proc is not None:
                self._proc.stop()
        return self.poll()

    def poll(self) -> dict:
        with self._lock:
            events = self._proc.events() if self._proc is not None else []
            shown = []
            for e in events:
                text = e.text.removeprefix(PREFIX)
                if e.text.startswith(PREFIX + "following your hero "):
                    key = text.removeprefix("following your hero ")
                    hero = next((h for h in load_heroes().values() if h.key == key), None)
                    self._following = hero.name if hero is not None else key.replace("_", " ")
                elif e.kind == "log" and e.text.startswith(PREFIX):
                    e = Event("problem" if "can't" in text or "live match" in text else "log", text, e.time)
                shown.append(asdict(e))
            return {"events": shown, "running": self.running, "following": self._following}

    def _settings(self) -> dict:
        try:
            saved = json.loads((self._app_dir / SETTINGS).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        return {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}

    def _save(self, sent: dict) -> dict:
        settings = {**self._settings(), **{k: v for k, v in (sent or {}).items() if k in DEFAULTS}}
        if settings["mode"] not in MODES:
            settings["mode"] = DEFAULTS["mode"]
        try:
            settings["interval"] = max(3.0, min(60.0, float(settings["interval"])))
        except (TypeError, ValueError):
            settings["interval"] = DEFAULTS["interval"]
        settings["model"] = str(settings["model"] or DEFAULTS["model"])
        settings["hero"] = str(settings["hero"] or "")
        try:
            self._app_dir.mkdir(parents=True, exist_ok=True)
            (self._app_dir / SETTINGS).write_text(json.dumps(settings, indent=2), encoding="utf-8")
        except OSError:
            pass
        return settings
