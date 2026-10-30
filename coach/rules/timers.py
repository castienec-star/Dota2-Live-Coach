"""Reminders tied to the game clock: runes and camp stacking.

The clock is public to every player, so these only save you from watching it.
Timings change between patches, which is why they live in coach.toml.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from ..state import MatchState, Snapshot

CAMPS_FILE = Path(__file__).resolve().parent.parent / "data" / "camps_7_41.json"

# A jump bigger than this (reconnect, replay seek) is not a real tick.
MAX_TICK = 3


@dataclass
class TimedReminder:
    name: str
    message: str
    first: int
    every: int
    until: int | None = None
    lead: int = 0
    # After this game time only every other event is said, so runes don't
    # crowd out the rest late in the game; None or 0 = all of them.
    thin_after: int | None = None
    # Said instead of message for the first event of the match, e.g. to teach
    # a second name for it once.
    first_message: str | None = None
    _fired: set[int] = field(default_factory=set, repr=False)

    def event_times(self, start: int, end: int) -> list[int]:
        """Event times (game clock) whose reminder falls in (start, end]."""
        times = []
        t = self.first
        while t - self.lead <= end:
            if self.until is not None and t > self.until:
                break
            if t - self.lead > start and not self.thinned(t):
                times.append(t)
            if self.every <= 0:
                break
            t += self.every
        return times

    def thinned(self, t: int) -> bool:
        """True for the events left out after thin_after."""
        if not self.thin_after or t <= self.thin_after or self.every <= 0:
            return False
        return (t - self.first) // self.every % 2 == 1

    def check(self, state: MatchState) -> list[str]:
        before, now = state.previous.clock_time, state.current.clock_time
        if before is None or now is None or not 0 < now - before <= MAX_TICK:
            return []
        lines = []
        for t in self.event_times(before, now):
            if t not in self._fired:
                self._fired.add(t)
                line = self.line(state.current, first=t == self.first)
                if line:
                    lines.append(line)
        return lines[-1:]

    def line(self, snap: Snapshot, first: bool = False) -> str | None:
        message = self.first_message if first and self.first_message else self.message
        return message.format(lead=self.lead)

    def reset(self) -> None:
        self._fired.clear()


@dataclass
class Camp:
    type: str
    x: float
    y: float


def load_camps(path: Path = CAMPS_FILE) -> list[Camp]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return [Camp(c["type"], c["x"], c["y"]) for c in data["camps"]]


@dataclass
class StackReminder(TimedReminder):
    """'Stack the camp', said only when your own hero stands near a neutral camp.

    Uses only your hero's position (which you see) and the fixed camp spots on
    the map. GSI does not say whether a camp is alive or blocked, so the coach
    cannot know that either.
    """

    radius: float = 1000
    camps: list[Camp] = field(default_factory=load_camps, repr=False)

    def nearest(self, snap: Snapshot) -> Camp | None:
        if snap.x is None or snap.y is None or not self.camps:
            return None
        camp = min(self.camps, key=lambda c: math.dist((c.x, c.y), (snap.x, snap.y)))
        return camp if math.dist((camp.x, camp.y), (snap.x, snap.y)) <= self.radius else None

    def line(self, snap: Snapshot, first: bool = False) -> str | None:
        if not snap.alive:
            return None
        camp = self.nearest(snap)
        if camp is None:
            return None
        kind = camp.type.removeprefix("flooded_")
        return self.message.format(lead=self.lead, camp=kind)


# Patch 7.41 timings.
DEFAULTS: dict[str, dict] = {
    "power_rune": {"message": "Power rune in {lead} seconds.", "first": 360, "every": 120, "lead": 15, "thin_after": 1200},
    "bounty_rune": {"message": "Gold runes in {lead} seconds.", "first": 240, "every": 240, "lead": 15, "thin_after": 1200},
    # Players call the wisdom shrines' runes XP runes; the first call says both names.
    "wisdom_shrine": {
        "message": "XP runes in {lead} seconds.",
        "first_message": "XP runes, at the wisdom shrines, in {lead} seconds.",
        "first": 420,
        "every": 420,
        "lead": 20,
    },
    "water_rune": {"message": "Water rune in {lead} seconds.", "first": 120, "every": 120, "until": 240, "lead": 10},
    "stack": {"message": "Stack the {camp} camp.", "first": 113, "every": 60, "until": 713, "lead": 0, "radius": 1000},
}


def build(settings: dict[str, dict]) -> list[TimedReminder]:
    """Make reminders from defaults overlaid with the [reminders.*] config tables."""
    reminders = []
    for name, defaults in DEFAULTS.items():
        merged = {**defaults, **settings.get(name, {})}
        if not merged.pop("enabled", True):
            continue
        cls = StackReminder if name == "stack" else TimedReminder
        reminders.append(cls(name=name, **merged))
    return reminders
