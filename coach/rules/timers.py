"""Reminders tied to the game clock: runes and camp stacking.

The clock is public to every player, so these only save you from watching it.
Timings change between patches, which is why they live in coach.toml.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..state import MatchState

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
    _fired: set[int] = field(default_factory=set, repr=False)

    def event_times(self, start: int, end: int) -> list[int]:
        """Event times (game clock) whose reminder falls in (start, end]."""
        times = []
        t = self.first
        while t - self.lead <= end:
            if self.until is not None and t > self.until:
                break
            if t - self.lead > start:
                times.append(t)
            if self.every <= 0:
                break
            t += self.every
        return times

    def check(self, state: MatchState) -> list[str]:
        before, now = state.previous.clock_time, state.current.clock_time
        if before is None or now is None or not 0 < now - before <= MAX_TICK:
            return []
        lines = []
        for t in self.event_times(before, now):
            if t not in self._fired:
                self._fired.add(t)
                lines.append(self.message.format(lead=self.lead))
        return lines[-1:]

    def reset(self) -> None:
        self._fired.clear()


DEFAULTS: dict[str, dict] = {
    "power_rune": {"message": "Power rune in {lead} seconds.", "first": 360, "every": 120, "lead": 15},
    "bounty_rune": {"message": "Bounty runes in {lead} seconds.", "first": 180, "every": 180, "lead": 15},
    "wisdom_rune": {"message": "Wisdom runes in {lead} seconds.", "first": 420, "every": 420, "lead": 20},
    "water_rune": {"message": "Water rune in {lead} seconds.", "first": 120, "every": 120, "until": 240, "lead": 10},
    "stack": {"message": "Stack the camp.", "first": 113, "every": 60, "until": 713, "lead": 0},
}


def build(settings: dict[str, dict]) -> list[TimedReminder]:
    """Make reminders from defaults overlaid with the [reminders.*] config tables."""
    reminders = []
    for name, defaults in DEFAULTS.items():
        merged = {**defaults, **settings.get(name, {})}
        if not merged.pop("enabled", True):
            continue
        reminders.append(TimedReminder(name=name, **merged))
    return reminders
