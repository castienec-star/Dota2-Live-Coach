"""Reminders for the timings found in the pre-game briefing.

The briefing works out when your lineup and the enemy lineup are strongest;
this rule says so again when each of those stretches begins.
"""

from __future__ import annotations

import threading

from ..draft import Window
from ..state import MatchState
from .timers import MAX_TICK

OURS = "Your team's strongest stretch starts now, until about {end} minutes. Group up and look for fights."
THEIRS = "The enemy lineup is strongest from now until about {end} minutes. Play safe and only fight with an advantage."


class PowerWindows:
    name = "power_window"

    def __init__(self, lead: int = 10) -> None:
        self.lead = lead
        self._windows: list[Window] = []
        self._fired: set[Window] = set()
        self._lock = threading.Lock()

    def set(self, windows: list[Window]) -> None:
        with self._lock:
            self._windows = list(windows)
            self._fired = set()

    def check(self, state: MatchState) -> list[str]:
        before, now = state.previous.clock_time, state.current.clock_time
        if before is None or now is None or not 0 < now - before <= MAX_TICK:
            return []
        lines = []
        with self._lock:
            for w in self._windows:
                at = w.start * 60 - self.lead
                if before < at <= now and w not in self._fired:
                    self._fired.add(w)
                    lines.append((OURS if w.ours else THEIRS).format(end=w.end))
        return lines[-1:]

    def reset(self) -> None:
        self.set([])


def build(settings: dict) -> list[PowerWindows]:
    options = dict(settings.get("power_window", {}))
    if not options.pop("enabled", True):
        return []
    return [PowerWindows(**options)]
