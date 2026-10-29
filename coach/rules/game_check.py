"""Says, unasked, whether you are ahead, even or behind at a few set minutes.

The same verdict as asking "hey coach, how am I doing?" (see
coach/benchmarks.py): your own hero's GSI numbers against public numbers
for your hero. When you told the coach the enemy heroes and one of them
calls for a counter item, it is named too (see coach/situational.py). So is
a defensive item when you said your team is losing fights or their carry is
farming freely (see coach/game_questions.py).

With "advice" (the same pick as "what should I buy?", coach/item_advisor.py)
it always names an item: the counter or defensive item, else the next one on
your build, else a late-game item once the build is done.
"""

from __future__ import annotations

from collections.abc import Callable

from .. import situational
from ..benchmarks import Benchmarks, is_support, spoken
from ..game_questions import Notes
from ..heroes import HeroIndex, HeroInfo
from ..items import load_items
from ..situational import Pick
from ..state import MatchState, Snapshot
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
        enemies: Callable[[], list[HeroInfo]] | None = None,
        notes: Callable[[], Notes | None] | None = None,
        advice: Callable[[Snapshot], Pick | None] | None = None,
    ) -> None:
        self.benchmarks = benchmarks
        self.times = sorted(int(m) * 60 for m in (minutes if minutes is not None else [15, 25]))
        self.late = late
        self.position = position
        self.heroes = heroes or HeroIndex()
        self.enemies = enemies or list
        self.notes = notes or (lambda: None)
        self.advice = advice
        self._items = load_items()
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
        position = self.position(snap) if self.position else 0
        support = is_support(hero, position)
        verdict = self.benchmarks.verdict(snap, support)
        if verdict is None:
            return []
        if self.advice is not None:
            pick = self.advice(snap)
            if pick is not None:
                return [f"{spoken(verdict, support, items=False)} {situational.spoken(pick, None, snap)}"]
            return [spoken(verdict, support)]
        role = situational.role(position, support)
        notes = self.notes()
        counter = situational.against(self.enemies(), role, snap, self._items, notes.trouble if notes else None)
        if counter is None and verdict.kind == "even":
            # "Behind" already says to buy a defensive item.
            reason = situational.struggling(verdict, notes)
            if reason:
                counter = situational.defensive(snap, role, self._items, reason)
        if counter is None:
            return [spoken(verdict, support)]
        return [f"{spoken(verdict, support, items=False)} {situational.spoken(counter, None, snap)}"]

    def reset(self) -> None:
        self._done.clear()


def build(
    settings: dict[str, dict],
    benchmarks: Benchmarks,
    position: PositionOf | None = None,
    enemies: Callable[[], list[HeroInfo]] | None = None,
    notes: Callable[[], Notes | None] | None = None,
    advice: Callable[[Snapshot], Pick | None] | None = None,
) -> list[GameCheck]:
    options = dict(settings.get("game_check", {}))
    if not options.pop("enabled", True):
        return []
    return [GameCheck(benchmarks, position=position, enemies=enemies, notes=notes, advice=advice, **options)]
