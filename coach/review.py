"""Post-game review: three things to work on, from your own match.

When the match reaches post-game the coach says up to three short points
(deaths and when they happened, last hits at 10 minutes for a core, how late
the first big item came) and saves them as a text file, so you learn one
thing every game. Everything comes from your own hero's GSI updates; the
targets are explained in docs/strategy/post-game-review.md.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from .benchmarks import CREEPS_MEET, LAST_HITS_PER_MIN, is_support
from .heroes import HeroIndex
from .items import ItemInfo, load_items
from .profile import BIG_ITEM_COST, MatchSummary, Tally
from .state import MatchState, Snapshot

log = logging.getLogger(__name__)

POST_GAME = "DOTA_GAMERULES_STATE_POST_GAME"
MAX_POINTS = 3
EARLY_DEATHS = 2  # deaths before 10:00 that make laning the first point
STREAK_DEATHS = 3  # deaths inside STREAK_WINDOW that count as a streak
STREAK_WINDOW = 300
MANY_DEATHS = 7
FEW_DEATHS = 3  # at most this many in a long game is worth praising
LONG_GAME = 20 * 60
FIRST_ITEM_BY = {False: 20 * 60, True: 25 * 60}  # core, support
LAST_HIT_SHORT = 0.8  # under 80% of the target is a point to fix


def last_hit_target() -> int:
    """Last hits a core should have at 10:00, rounded to 5 (35)."""
    return 5 * round(LAST_HITS_PER_MIN * (10 - CREEPS_MEET) / 5)


def _streak(death_times: list[int]) -> tuple[int, int, int]:
    """The most deaths inside STREAK_WINDOW: (count, first minute, last minute)."""
    best = (0, 0, 0)
    times = sorted(death_times)
    for i, start in enumerate(times):
        inside = [t for t in times[i:] if t - start <= STREAK_WINDOW]
        if len(inside) > best[0]:
            best = (len(inside), start // 60, inside[-1] // 60)
    return best


def death_point(m: MatchSummary) -> str | None:
    early = sum(1 for t in m.death_times if t < 600)
    if early >= EARLY_DEATHS:
        return (
            f"You died {early} times before 10 minutes. In lane, stand behind your "
            "creeps and walk back to your tower when your health is low."
        )
    count, first, last = _streak(m.death_times)
    if count >= STREAK_DEATHS:
        return (
            f"You died {count} times between {first} and {last + 1} minutes. After a "
            "death, farm near your towers for a minute instead of walking back into the same fight."
        )
    if m.deaths >= MANY_DEATHS:
        return (
            f"You died {m.deaths} times. Before you walk forward, think about where "
            "the enemies you can't see might be, and keep a Town Portal scroll."
        )
    return None


def last_hit_point(m: MatchSummary, support: bool) -> str | None:
    if support or m.last_hits_10 is None:
        return None
    target = last_hit_target()
    if m.last_hits_10 >= target * LAST_HIT_SHORT:
        return None
    return (
        f"You had {m.last_hits_10} last hits at 10 minutes; aim for {target}. "
        "Five minutes of last hitting in a lobby before you queue helps a lot."
    )


def item_point(m: MatchSummary, support: bool, items: dict[str, ItemInfo]) -> str | None:
    due = FIRST_ITEM_BY[support]
    if not m.item_times:
        if m.duration < due + 300:
            return None
        if support:
            return (
                f"You didn't finish an item over {BIG_ITEM_COST} gold in {m.duration // 60} "
                "minutes. A support's Glimmer Cape or Force Staff saves lives, so save up for one."
            )
        return (
            f"You didn't finish an item over {BIG_ITEM_COST} gold in {m.duration // 60} "
            "minutes. Farm your lane and the jungle camps next to it between fights."
        )
    key, at = min(m.item_times.items(), key=lambda kv: kv[1])
    if at <= due:
        return None
    name = items[key].name if key in items else key
    if support:
        return f"Your first big item, {name}, came at {at // 60} minutes. Pull or stack a camp when your core can lane alone."
    return (
        f"Your first big item, {name}, came at {at // 60} minutes. Aim for about "
        f"{due // 60}: take the jungle camps near your lane between creep waves."
    )


def praise(m: MatchSummary, support: bool) -> list[str]:
    """Good habits worth keeping, for when there is less than three to fix."""
    good = []
    if m.duration >= LONG_GAME and m.deaths <= FEW_DEATHS:
        good.append(f"Only {m.deaths} deaths in {m.duration // 60} minutes: staying alive like that wins games, keep it up.")
    if not support and m.last_hits_10 is not None and m.last_hits_10 >= last_hit_target():
        good.append(f"{m.last_hits_10} last hits at 10 minutes is right on target.")
    return good


def points(m: MatchSummary, support: bool, items: dict[str, ItemInfo]) -> list[str]:
    """Up to three short spoken points, the most important first."""
    found = [death_point(m), last_hit_point(m, support), item_point(m, support, items)]
    picked = [p for p in found if p]
    picked += praise(m, support)
    if not picked:
        picked = ["A steady game with nothing big to fix. Next game, try to stack a camp or take a rune you'd usually skip."]
    return picked[:MAX_POINTS]


def spoken(lines: list[str]) -> str:
    return "Match review. " + " ".join(lines)


def text(m: MatchSummary, lines: list[str], heroes: HeroIndex | None = None) -> str:
    """The review as a short text file."""
    hero = (heroes or HeroIndex()).by_key(m.hero)
    result = {True: "won", False: "lost", None: "result unknown"}[m.won]
    head = (
        f"{hero.name if hero else m.hero}, {m.duration // 60} minutes, {result}. "
        f"{m.kills} kills, {m.deaths} deaths, {m.assists} assists"
    )
    if m.last_hits_10 is not None:
        head += f", {m.last_hits_10} last hits at 10:00"
    body = "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1))
    return f"{head}\n\n{body}\n"


class Review:
    """Watches the match and gives the review once it reaches post-game."""

    def __init__(
        self,
        say: Callable[[str], None],
        folder: Path | None,
        position: Callable[[Snapshot], int] | None = None,
        heroes: HeroIndex | None = None,
        items: dict[str, ItemInfo] | None = None,
    ) -> None:
        self.say = say
        self.folder = folder
        self.position = position
        self.heroes = heroes or HeroIndex()
        self.items = items if items is not None else load_items()
        self.tally = Tally(self.items)
        self.done = False
        self.saved: Path | None = None

    def __call__(self, state: MatchState) -> None:
        if state.new_match:
            self.tally = Tally(self.items)
            self.done = False
        snap = state.current
        self.tally.add(snap)
        if snap.game_state != POST_GAME or self.done:
            return
        self.done = True
        summary = self.tally.summary()
        if summary is None:
            return  # a test or an abandon: nothing worth reviewing
        position = self.position(snap) if self.position else 0
        support = is_support(self.heroes.by_key(summary.hero), position)
        lines = points(summary, support, self.items)
        self.say(spoken(lines))
        self.saved = self.save(summary, lines)

    def save(self, m: MatchSummary, lines: list[str]) -> Path | None:
        if self.folder is None:
            return None
        path = self.folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{m.hero}.txt"
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            path.write_text(text(m, lines, self.heroes), encoding="utf-8")
        except OSError as exc:
            log.warning("Could not save the match review: %s", exc)
            return None
        log.info("Match review saved to %s", path)
        return path
