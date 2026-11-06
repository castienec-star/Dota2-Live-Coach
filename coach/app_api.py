"""What the app window's page can ask Python for (pywebview's js_api).

Every public method here is callable from coach/ui/app.js as
`await pywebview.api.<name>(...)`, and returns plain JSON data. The coach
itself runs as its own process (coach/app.py); settings are read from and
saved to the player's own coach.toml (coach/options.py).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import webbrowser
from dataclasses import asdict
from pathlib import Path

from . import config as config_mod
from . import i18n
from . import license as license_mod
from . import options, settings
from .app import CoachProcess, Status, _hidden, command


class Api:
    def __init__(self, app_dir: Path, coach: CoachProcess | None = None,
                 lic: license_mod.License | None = None, voices=None) -> None:
        self._app_dir = app_dir
        self._user_file = app_dir / "coach.toml"
        self._coach = coach or CoachProcess()
        self._status = Status()
        self._license = lic or license_mod.License(app_dir)
        self._voices = voices
        self._lock = threading.Lock()
        self._replay = None  # the Replay review window's api, once opened
        self._replay_window = None
        self._lang: str | None = None  # read from coach.toml once, again after Save

    # Language ------------------------------------------------------------

    def language(self) -> str:
        """"en" or "es": the language the page shows ([coach] language)."""
        if self._lang is None:
            self._lang = options.language_of(self._defaults(), self._user())
        return self._lang

    def _t(self, text: str) -> str:
        return i18n.ui(text, self.language()) if isinstance(text, str) else text

    # The coach -----------------------------------------------------------

    def start(self) -> dict:
        if self._replay is not None:
            self._replay.stop()  # both listen on the same port
        self._coach.start()
        self._status.running = True
        return self.poll()

    def stop(self) -> dict:
        self._coach.stop()
        return self.poll()

    def poll(self) -> dict:
        """New lines since the last call, and the header's status."""
        with self._lock:
            events = self._coach.events()
            for event in events:
                self._status.update(event)
            self._status.running = self._coach.running
            if not self._status.running:
                self._status.connected = False
            lang = self.language()
            shown = []
            for event in events:
                row = asdict(event)
                if event.kind in ("stopped", "problem", "connected"):
                    # The coach's own spoken lines are in the language already.
                    row["text"] = i18n.ui(event.text, lang)
                shown.append(row)
            status = asdict(self._status)
            if status.get("problem"):
                status["problem"] = i18n.ui(status["problem"], lang)
            return {
                "events": shown,
                "status": {**status, "headline": i18n.ui(self._status.headline(), lang)},
            }

    def shutdown(self) -> None:
        """The main window closed: stop the coach and any replay review."""
        self.stop()
        if self._replay is not None:
            self._replay.stop()

    # Replay review -------------------------------------------------------

    def open_replay(self) -> None:
        """The Replay review window, a second window next to this one."""
        import webview

        from .app_web import UI
        from .replay_api import ReplayApi

        if self._replay is None:
            self._replay = ReplayApi(self._app_dir, stop_live=self.stop)
        if self._replay_window is not None:
            try:
                self._replay_window.show()
                self._replay_window.restore()
                return
            except Exception:
                self._replay_window = None
        window = webview.create_window(
            "Replay review", url=str(UI / "replay.html"), js_api=self._replay,
            width=980, height=760, min_size=(760, 600), background_color="#070708",
        )
        self._replay_window = window

        def closed() -> None:
            self._replay.stop()
            self._replay_window = None

        window.events.closed += closed

    # Settings ------------------------------------------------------------

    def _defaults(self) -> dict:
        return config_mod._read_toml(config_mod.DEFAULTS_FILE)

    def _user(self) -> dict:
        return config_mod._read_toml(self._user_file) if self._user_file.is_file() else {}

    def load_settings(self) -> dict:
        if self._voices is None:
            from .speaker import installed_voices

            self._voices = installed_voices()
        return {
            "language": self.language(),
            "schema": options.schema(self.language()),
            "values": options.values(self._defaults(), self._user()),
            "defaults": options.values(self._defaults(), {}),
            "voices": list(self._voices),
            "file": str(self._user_file),
        }

    def switch_mode(self, sent: dict, new: str) -> dict:
        return options.remode(sent, str(sent.get("mode", "beginner")), new, self._defaults())

    def reset_settings(self, mode: str = "beginner") -> dict:
        """The defaults for a mode (not saved until Save)."""
        return options.values(self._defaults(), {"coach": {"mode": mode}})

    def save_settings(self, sent: dict) -> dict:
        data, errors = options.saved(self._defaults(), self._user(), sent)
        if errors:
            return {"ok": False, "errors": [self._t(e) for e in errors]}
        before = self.language()
        settings.save(self._user_file, data)
        self._lang = None
        restarted = False
        if self._coach.running:  # new settings take effect at once
            self._coach.stop()
            self._coach.start()
            restarted = True
        return {"ok": True, "restarted": restarted, "values": options.values(self._defaults(), data),
                "language_changed": self.language() != before}

    def test_voice(self, voice: str = "", rate: int = 0) -> None:
        # Said in the coach's language: coach.toml's, as saved.
        args = ["say", "Power rune in 15 seconds.", "--voice", voice or "", "--rate", str(int(rate))]
        subprocess.Popen(command(*args), stdin=subprocess.DEVNULL, **_hidden())

    # Setup and folders ---------------------------------------------------

    def set_up_dota(self) -> dict:
        proc = subprocess.run(command("install"), capture_output=True, text=True, timeout=60, **_hidden())
        out = (proc.stdout + proc.stderr).strip()
        return {"ok": proc.returncode == 0, "text": out or "Done."}

    def open_folder(self, which: str) -> None:
        folder = self._app_dir / ("reviews" if which == "reviews" else "")
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606 (the player's own folder)

    def open_builds(self) -> None:
        """The item build editor (the tkinter settings window) for now."""
        subprocess.Popen(command("settings"), stdin=subprocess.DEVNULL, **_hidden())

    def open_url(self, url: str) -> None:
        if url.startswith("https://"):
            webbrowser.open(url)

    # Progress ------------------------------------------------------------

    def _record_dir(self) -> Path:
        own = str(self._user().get("recording", {}).get("directory") or "")
        return Path(own) if own else self._app_dir / "recordings"

    def progress(self) -> dict:
        from . import progress

        out = progress.summary(self._app_dir, self._record_dir())
        for rec in out.get("recommendations", []):
            rec["title"] = self._t(rec.get("title", ""))
            rec["text"] = self._t(rec.get("text", ""))
        for match in out.get("matches", []):
            for note in match.get("notes", []):
                note["text"] = self._t(note.get("text", ""))
        return out

    def match_details(self, match_id: str, account_id: str) -> dict:
        """The player's own numbers for one match from OpenDota's public page."""
        from . import progress
        from .opendota import OpenDota

        opendota = OpenDota(self._app_dir / "opendota")
        # Re-asked after 6 hours: OpenDota adds parsed numbers after a while.
        out = progress.match_details(lambda path: opendota.get(path, 6 * 3600), match_id, account_id)
        if "message" in out:
            out["message"] = self._t(out["message"])
        for row in out.get("stats", []) + out.get("ranks", []):
            row["label"] = self._t(row["label"])
        out["tips"] = [self._t(t) for t in out.get("tips", [])]
        return out

    def add_mmr(self, value) -> dict:
        from . import progress

        ok, message = progress.MmrHistory(self._app_dir).add(value)
        return {"ok": ok, "message": self._t(message)}

    # Licence -------------------------------------------------------------

    def license_state(self) -> dict:
        result = self._license.check()
        return {"required": license_mod.required(), "ok": result.ok, "message": self._t(result.message),
                "store": license_mod.STORE_URL}

    def activate(self, key: str) -> dict:
        result = self._license.activate(key)
        return {"ok": result.ok, "message": self._t(result.message)}
