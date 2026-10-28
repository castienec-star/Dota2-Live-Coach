"""Says, unasked, whether you are ahead, even or behind at a few set minutes.

The same verdict as asking "hey coach, how am I doing?" (see
coach/benchmarks.py): your own hero's GSI numbers against public numbers
for your hero.
"""

from __future__ import annotations

from ..benchmarks import Benchmarks, is_support, spoken
from ..heroes import HeroIndex
from ..state import MatchState
from . import PositionOf


class GameCheck:
    """Speaks the verdict once at each of "minutes". A check missed by more
    than "late" seconds (the coach was started later) is skipped."""

    name = "game_check"

    def __init__(
        self,
        benchmarks: Benchmarks,
        minutes: list[int] | None = None,
        late: int = 60,
        position: PositionOf | None = None,
        heroes: HeroIndex | None = None,
    ) -> None:
        self.benchmarks = benchmarks
        self.times = sorted(int(m) * 60 for m in (minutes if minutes is not None else [15, 25]))
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
        if not due:
            return []
        self._done.update(t for t in self.times if t <= now)
        hero = self.heroes.by_key(snap.hero_name)
        support = is_support(hero, self.position(snap) if self.position else 0)
        verdict = self.benchmarks.verdict(snap, support)
        return [spoken(verdict, support)] if verdict else []

    def reset(self) -> None:
        self._done.clear()


def build(
    settings: dict[str, dict], benchmarks: Benchmarks, position: PositionOf | None = None
) -> list[GameCheck]:
    options = dict(settings.get("game_check", {}))
    if not options.pop("enabled", True):
        return []
    return [GameCheck(benchmarks, position=position, **options)]
