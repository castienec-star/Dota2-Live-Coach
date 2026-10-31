"""Says, unasked, how your last hits compare with a simple target early on.

At 5:00 and 10:00 a core hears one encouraging line: its last hits against
3.5 a minute from when the creeps meet (15 at 5:00, 35 at 10:00, see
docs/strategy/last-hitting.md), the same target as asking "how am I doing?"
before 8 minutes. Supports hear nothing: their job isn't last hits.
"""

from __future__ import annotations

from ..benchmarks import is_support, last_hit_target
from ..heroes import HeroIndex
from ..state import MatchState, Snapshot
from . import PositionOf

CLOSE = 0.7  # at least 70% of the target is "close"

# What to work on when behind, by minute: in lane, then once lanes open up.
TIPS = {
    5: "Hit a creep when its health drops under one of your attacks, and don't chase kills in lane.",
    10: "Between waves, take the nearest jungle camp instead of walking around.",
}


def spoken(snap: Snapshot, minute: int) -> str:
    target = last_hit_target(minute)
    have = snap.last_hits
    head = f"{have} last hits at {minute} minutes"
    if have >= target:
        return f"{head}, great farming. Keep it up."
    if have >= target * CLOSE:
        return f"{head}, close to the {target} to aim for. Keep at it."
    tip = TIPS.get(minute, TIPS[10] if minute > 10 else TIPS[5])
    return f"{head}; aim for about {target}. {tip}"


class LastHitPace:
    """Speaks once at each of "minutes" for a core. A check missed by more
    than "late" seconds (the coach was started later) is skipped."""

    name = "last_hits"

    def __init__(
        self,
        minutes: list[int] | None = None,
        late: int = 30,
        position: PositionOf | None = None,
        heroes: HeroIndex | None = None,
    ) -> None:
        self.times = sorted(int(m) * 60 for m in (minutes if minutes is not None else [5, 10]))
        self.late = late
        self.position = position
        self.heroes = heroes or HeroIndex()
        self._done: set[int] = set()

    def check(self, state: MatchState) -> list[str]:
        snap = state.current
        now = snap.clock_time
        if now is None:
            return []
        due = [t for t in self.times if t <= now < t + self.late and t not in self._done]
        self._done.update(t for t in self.times if t <= now)
        if not due:
            return []
        position = self.position(snap) if self.position else 0
        if is_support(self.heroes.by_key(snap.hero_name), position):
            return []
        return [spoken(snap, due[-1] // 60)]

    def reset(self) -> None:
        self._done.clear()


def build(settings: dict[str, dict], position: PositionOf | None = None) -> list[LastHitPace]:
    options = dict(settings.get("last_hits", {}))
    if not options.pop("enabled", True):
        return []
    return [LastHitPace(position=position, **options)]
