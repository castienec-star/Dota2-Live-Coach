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

    # The coach -----------------------------------------------------------

    def start(self) -> dict:
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
            return {
                "events": [asdict(e) for e in events],
                "status": {**asdict(self._status), "headline": self._status.headline()},
            }

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
            "schema": options.schema(),
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
            return {"ok": False, "errors": errors}
        settings.save(self._user_file, data)
        restarted = False
        if self._coach.running:  # new settings take effect at once
            self._coach.stop()
            self._coach.start()
            restarted = True
        return {"ok": True, "restarted": restarted, "values": options.values(self._defaults(), data)}

    def test_voice(self, voice: str = "", rate: int = 0) -> None:
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

        return progress.summary(self._app_dir, self._record_dir())

    def match_details(self, match_id: str, account_id: str) -> dict:
        """The player's own numbers for one match from OpenDota's public page."""
        from . import progress
        from .opendota import OpenDota

        opendota = OpenDota(self._app_dir / "opendota")
        # Re-asked after 6 hours: OpenDota adds parsed numbers after a while.
        return progress.match_details(lambda path: opendota.get(path, 6 * 3600), match_id, account_id)

    def add_mmr(self, value) -> dict:
        from . import progress

        ok, message = progress.MmrHistory(self._app_dir).add(value)
        return {"ok": ok, "message": message}

    # Licence -------------------------------------------------------------

    def license_state(self) -> dict:
        result = self._license.check()
        return {"required": license_mod.required(), "ok": result.ok, "message": result.message,
                "store": license_mod.STORE_URL}

    def activate(self, key: str) -> dict:
        result = self._license.activate(key)
        return {"ok": result.ok, "message": result.message}
