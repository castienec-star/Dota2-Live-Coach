"""What the app window does, without the window (so it can be tested).

The window (coach/app_window.py) starts the coach as its own process, the same
`run` command as `py -m coach` or a double-clicked DotaCoach.exe, and reads
its log lines. A separate process keeps the coach exactly as it runs today:
its web server, voice and models own their own main thread, and Stop can
always end it, even mid-sentence. Match recordings are flushed line by line
(coach/recorder.py), so stopping never loses a recording.

Nothing here reads the game; the window only shows what the coach logs.
"""

from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass

# "17:35:12 Coach: Power rune in 15 seconds." (logging format in __main__.main)
_STAMP = re.compile(r"^(\d{2}:\d{2}:\d{2}) (.*)$")


@dataclass(frozen=True)
class Event:
    """One log line, sorted for the window.

    kind: "said" (a line the coach spoke), "skipped" (a line dropped as too
    late), "connected" (Dota is sending game state), "match" (a new match),
    "problem" (a warning or error the player may need to act on), "version",
    or "log" (anything else).
    """

    kind: str
    text: str
    time: str = ""


def classify(line: str) -> Event:
    """Sorts one line of the coach's output."""
    line = line.rstrip("\r\n")
    found = _STAMP.match(line)
    time, text = (found.group(1), found.group(2)) if found else ("", line)
    if text.startswith("Coach: "):
        return Event("said", text.removeprefix("Coach: "), time)
    if text.startswith("Skipped late line: "):
        return Event("skipped", text.removeprefix("Skipped late line: "), time)
    if text.startswith("Dota 2 is connected now") or text.startswith("Game state: "):
        return Event("connected", text, time)
    if text.startswith("New match "):
        return Event("match", text, time)
    if text.startswith("Dota 2 Live Coach, version from "):
        return Event("version", text.removeprefix("Dota 2 Live Coach, version from "), time)
    lowered = text.lower()
    if lowered.startswith(("traceback", "error", "could not", "no game state", "dota sends game state with an old")) or "not found" in lowered:
        return Event("problem", text, time)
    return Event("log", text, time)


def command(*args: str) -> list[str]:
    """How to start the coach with these arguments, from the app or from Python."""
    if getattr(sys, "frozen", False):  # DotaCoach.exe / DotaCoach App.exe
        return [_console_exe(), *args]
    return [sys.executable, "-m", "coach", *args]


def _console_exe() -> str:
    """The console build next to this one: the window build has no stdout."""
    here = os.path.dirname(sys.executable)
    console = os.path.join(here, "DotaCoach.exe")
    return console if os.path.exists(console) else sys.executable


def _hidden() -> dict:
    """Keeps a console window from popping up next to the app on Windows."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


class CoachProcess:
    """The running coach: start, stop, and its output as Events.

    Output is read on a background thread into a queue; the window drains it
    with `events()` from its own thread (tkinter isn't thread-safe).
    """

    def __init__(
        self,
        args: tuple[str, ...] = ("run",),
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
    ) -> None:
        self.args = args
        self._popen = popen
        self._proc: subprocess.Popen | None = None
        self._queue: queue.Queue[Event] = queue.Queue()

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        if self.running:
            return
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        self._proc = self._popen(
            command(*self.args),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            **_hidden(),
        )
        threading.Thread(target=self._read, args=(self._proc,), daemon=True).start()

    def _read(self, proc: subprocess.Popen) -> None:
        for line in proc.stdout:
            if line.strip():
                self._queue.put(classify(line))
        code = proc.wait()
        self._queue.put(Event("stopped", f"The coach stopped (exit code {code})." if code else "The coach stopped."))

    def stop(self, timeout: float = 5.0) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()

    def events(self) -> list[Event]:
        """Every event since the last call, oldest first."""
        out = []
        while True:
            try:
                out.append(self._queue.get_nowait())
            except queue.Empty:
                return out


@dataclass
class Status:
    """What the window's header shows, updated from Events."""

    running: bool = False
    connected: bool = False
    version: str = ""
    last_said: str = ""
    problem: str = ""

    def update(self, event: Event) -> None:
        if event.kind == "version":
            self.version = event.text
        elif event.kind == "connected":
            self.connected, self.problem = True, ""
        elif event.kind == "said":
            self.last_said = event.text
        elif event.kind == "problem":
            self.problem = event.text
        elif event.kind == "stopped":
            self.running = self.connected = False

    def headline(self) -> str:
        if not self.running:
            return "The coach is off. Press Start before your match."
        if self.connected:
            return "Coaching: Dota 2 is connected."
        return "Waiting for Dota 2. Start a match (a bot match works)."
