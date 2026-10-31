"""Ahead, even or behind: your own numbers against public numbers for your hero.

The baselines are OpenDota's public hero benchmarks: for each hero, the gold
per minute, experience per minute and last hits per minute that 10%, 20%...
99% of recent public matches reached. A snapshot for every hero ships in
coach/data/benchmarks.json (`py -m coach refresh-benchmarks` rewrites it);
a hero added since is read once from OpenDota and cached, if it is turned on. A hero with no numbers at all is
compared, roughly, with the average bundled core or support, and before 8
minutes the answer is last hits against a simple target and deaths so far.
Only your own hero's GSI numbers are compared; nothing about other players is
looked up.

Once the coach knows your rank (coach/rank.py), each hero's numbers are
scaled to what players of your medal reach, and so is the last-hit target:
a Herald is compared with Heralds, a Legend with Legends.

See docs/strategy/ahead-or-behind.md for how the verdict is chosen.
"""

from __future__ import annotations

import functools
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from . import rank as rank_mod
from .heroes import HeroIndex, HeroInfo
from .rank import PlayerRank
from .state import Snapshot

BENCHMARKS_FILE = Path(__file__).resolve().parent / "data" / "benchmarks.json"

# Metric: what the coach calls it out loud.
METRICS = {"gold_per_min": "gold", "xp_per_min": "experience", "last_hits_per_min": "last hits"}
# Supports aren't meant to farm, so only their experience counts.
SUPPORT_METRICS = ("xp_per_min",)
CORE_METRICS = tuple(METRICS)

EARLIEST = 8 * 60  # before this the numbers say little
# The benchmarks are whole-match averages, and per-minute numbers grow as a
# match goes on, so early on your numbers are scaled up before comparing:
# by 1 / 0.6 at the horn, falling to nothing by 30 minutes.
RAMP_START, RAMP_UNTIL = 0.6, 30 * 60
# Where "behind" ends and "ahead" starts, as a share of public matches.
# Most public matches are played below Divine, so the middle of this band is
# a fair "even" for Herald to Ancient players.
BEHIND, AHEAD = 0.15, 0.55
# Against players of your own rank the middle of the band is their median.
RANK_BEHIND, RANK_AHEAD = 0.25, 0.7
# Early last-hit target for a core: 35 at 10 minutes (ROADMAP item 4), a
# fair lane for Herald to Ancient, not a pro one. Counted from when the
# first creep wave meets in lane, about half a minute in.
LAST_HITS_PER_MIN = 3.5
CREEPS_MEET = 0.5  # minutes

log = logging.getLogger(__name__)


def last_hit_target(minute: float, rank: str | None = None) -> int:
    """Last hits a core should have at this minute, rounded to 5 (15 at 5:00,
    35 at 10:00), and at least 5. With a rank, scaled by how the middle core
    of that medal last-hits against all cores (a Herald's target is lower)."""
    rate = LAST_HITS_PER_MIN * (rank_mod.factor(rank, False, "last_hits_per_min", 0.5) or 1.0)
    return max(5, 5 * round(rate * (minute - CREEPS_MEET) / 5))


Curve = list[tuple[float, float]]  # (percentile, value), rising
Fetch = Callable[[int], dict[str, Curve] | None]


@dataclass(frozen=True)
class Verdict:
    kind: str  # "ahead", "even" or "behind"
    score: float  # average share of public matches you are above, 0 to 1
    weakest: str  # the metric furthest behind, e.g. "last_hits_per_min"
    minute: int
    rough: bool = False  # no numbers for this hero: against all cores or supports
    rank: str | None = None  # compared with players of this medal, e.g. "archon"


def load_benchmarks(path: Path = BENCHMARKS_FILE) -> dict[str, dict[str, Curve]]:
    """{hero key: {metric: curve}} from the bundled snapshot."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    percentiles = data["percentiles"]
    return {
        key: {m: list(zip(percentiles, hero[m])) for m in METRICS if m in hero}
        for key, hero in data["heroes"].items()
    }


@functools.cache
def role_curves() -> dict[bool, dict[str, Curve]]:
    """Rough numbers for any hero, keyed by support or not: the average of
    the bundled supports' curves and of the bundled cores' curves."""
    try:
        bundled = load_benchmarks()
    except (OSError, ValueError, KeyError) as exc:
        log.warning("Can't read %s (%s)", BENCHMARKS_FILE, exc)
        return {}
    index = HeroIndex()
    groups: dict[bool, list[dict[str, Curve]]] = {True: [], False: []}
    for key, curves in bundled.items():
        groups[is_support(index.by_key(key))].append(curves)
    roles: dict[bool, dict[str, Curve]] = {}
    for support, members in groups.items():
        roles[support] = {}
        for metric in METRICS:
            have = [c[metric] for c in members if metric in c]
            if not have or any(len(c) != len(have[0]) for c in have):
                log.debug("Rough %s numbers skipped: the bundled %s curves differ in length", metric, metric)
                continue
            roles[support][metric] = [
                (have[0][i][0], sum(c[i][1] for c in have) / len(have)) for i in range(len(have[0]))
            ]
    return roles


def parse_api(result: dict | None) -> dict[str, Curve] | None:
    """Curves from an OpenDota /benchmarks reply, or None if it holds none."""
    rows = (result or {}).get("result") or {}
    curves = {}
    for metric in METRICS:
        points = [
            (float(r["percentile"]), float(r["value"]))
            for r in rows.get(metric) or []
            if isinstance(r, dict) and "percentile" in r and "value" in r
        ]
        if points:
            curves[metric] = sorted(points)
    return curves or None


def fetch_all(
    get: Callable[[str], Any],
    heroes: dict[int, HeroInfo],
    pause: float = 1.1,
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, dict[str, Curve]]:
    """{hero key: {metric: curve}} for every hero OpenDota answers for with
    all three numbers. "pause" keeps under OpenDota's free rate limit."""
    found: dict[str, dict[str, Curve]] = {}
    for n, hero in enumerate(sorted(heroes.values(), key=lambda h: h.id), 1):
        time.sleep(pause)
        curves = parse_api(get(f"/benchmarks?hero_id={hero.id}"))
        if not curves or set(curves) != set(METRICS):
            progress(f"{n}/{len(heroes)} {hero.name}: no data")
            continue
        found[hero.key] = curves
        progress(f"{n}/{len(heroes)} {hero.name}")
    return found


def save(found: dict[str, dict[str, Curve]], ids: dict[str, int], path: Path = BENCHMARKS_FILE) -> int:
    """Writes the snapshot in the bundled format: one list of percentiles,
    then each hero's values at them. A hero whose curves use other
    percentiles is left out. Returns how many heroes were saved."""
    percentiles = _common_percentiles(found)
    heroes = {}
    for key in sorted(found):
        curves = found[key]
        if any([p for p, _ in curve] != percentiles for curve in curves.values()):
            log.warning("Left out %s: its numbers use other percentiles", key)
            continue
        heroes[key] = {"id": ids[key]} if key in ids else {}
        for metric in METRICS:
            values = [round(v, 2) for _, v in curves[metric]]
            heroes[key][metric] = [int(v) if v.is_integer() else v for v in values]
    data = {
        "source": "OpenDota /api/benchmarks (public aggregate stats of recent public matches), "
        f"fetched {date.today().isoformat()}, patch {_patch()}",
        "note": "Whole-match averages. Values at the percentiles below, in order.",
        "percentiles": percentiles,
        "heroes": heroes,
    }
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    return len(heroes)


def _common_percentiles(found: dict[str, dict[str, Curve]]) -> list[float]:
    """The percentiles most of the curves in found use."""
    counts: dict[tuple[float, ...], int] = {}
    for curves in found.values():
        for curve in curves.values():
            key = tuple(p for p, _ in curve)
            counts[key] = counts.get(key, 0) + 1
    return list(max(counts, key=counts.get)) if counts else []


def _patch() -> str:
    patch = BENCHMARKS_FILE.parent / "PATCH"
    return patch.read_text(encoding="utf-8").strip() if patch.is_file() else "unknown"


def share_below(curve: Curve, value: float) -> float:
    """The share of public matches that did worse than value (0 to 1)."""
    if not curve:
        return 0.5
    low = (0.0, 0.0)
    for point in curve:
        if value <= point[1]:
            span = point[1] - low[1]
            part = (value - low[1]) / span if span > 0 else 1.0
            return low[0] + max(0.0, part) * (point[0] - low[0])
        low = point
    return 1.0


def ramp(clock: int) -> float:
    return min(1.0, RAMP_START + (1.0 - RAMP_START) * clock / RAMP_UNTIL)


def numbers(snap: Snapshot) -> dict[str, float]:
    minutes = max(1, snap.clock_time or 0) / 60
    return {
        "gold_per_min": float(snap.gpm),
        "xp_per_min": float(snap.xpm),
        "last_hits_per_min": snap.last_hits / minutes,
    }


class Benchmarks:
    """Judges a snapshot against the hero's public benchmarks."""

    def __init__(
        self,
        heroes: dict[str, dict[str, Curve]] | None = None,
        fetch: Fetch | None = None,
        hero_ids: dict[str, int] | None = None,
        rank: PlayerRank | None = None,
    ) -> None:
        if heroes is None:
            try:
                heroes = load_benchmarks()
            except (OSError, ValueError, KeyError) as exc:
                log.warning("Can't read %s (%s)", BENCHMARKS_FILE, exc)
                heroes = {}
        self.heroes = heroes
        self._rough_said: set[str | None] = set()  # matches already told "rough"
        self.fetch = fetch
        self.hero_ids = hero_ids or {}
        self.rank = rank

    def bracket(self) -> str | None:
        """The player's medal, when the bundled numbers cover it."""
        mine = self.rank.bracket() if self.rank is not None else None
        return mine if rank_mod.has(mine) else None

    def curves(self, hero: str) -> dict[str, Curve] | None:
        if hero not in self.heroes and self.fetch is not None and hero in self.hero_ids:
            fetched = self.fetch(self.hero_ids[hero])
            if fetched:
                self.heroes[hero] = fetched
        return self.heroes.get(hero)

    def say_rough(self, snap: Snapshot, verdict: Verdict) -> bool:
        """Whether to add the "rough comparison" caveat: only the first time
        a rough verdict is spoken in a match."""
        if not verdict.rough or snap.match_id in self._rough_said:
            return False
        self._rough_said.add(snap.match_id)
        return True

    def verdict(self, snap: Snapshot, support: bool = False) -> Verdict | None:
        """None before EARLIEST, or when there are no numbers at all. A hero
        without its own numbers gets a rough verdict against its role."""
        clock = snap.clock_time or 0
        hero = (snap.hero_name or "").removeprefix("npc_dota_hero_")
        if clock < EARLIEST or not hero:
            return None
        curves = self.curves(hero)
        rough = not curves
        if rough:
            curves = role_curves().get(support)
        if not curves:
            return None
        rank = self.bracket()
        if rank:
            curves = for_rank(curves, rank, support)
        behind, ahead = (RANK_BEHIND, RANK_AHEAD) if rank else (BEHIND, AHEAD)
        mine = numbers(snap)
        scale = ramp(clock)
        shares = {
            m: share_below(curves[m], mine[m] / scale)
            for m in (SUPPORT_METRICS if support else CORE_METRICS)
            if m in curves
        }
        if not shares:
            return None
        score = sum(shares.values()) / len(shares)
        kind = "behind" if score < behind else "ahead" if score >= ahead else "even"
        return Verdict(kind, score, min(shares, key=shares.get), clock // 60, rough, rank)


def for_rank(curves: dict[str, Curve], rank: str, support: bool) -> dict[str, Curve]:
    """A hero's curves scaled to what players of this medal reach."""
    scaled = {}
    for metric, curve in curves.items():
        scaled[metric] = [(p, v * (rank_mod.factor(rank, support, metric, p) or 1.0)) for p, v in curve]
    return scaled


def is_support(hero: HeroInfo | None, position: int = 0) -> bool:
    """Positions 4 and 5; while the position isn't known, a hero that is a
    support and not also a carry by OpenDota's hero roles."""
    if position:
        return position in (4, 5)
    return hero is not None and "Support" in hero.roles and "Carry" not in hero.roles


def spoken(verdict: Verdict, support: bool, items: bool = True, caveat: bool = True) -> str:
    """The verdict as one or two short sentences, with what to do about it.
    items=False leaves out the item advice, when a counter item is named next;
    caveat=False leaves out that a rough verdict is rough."""
    line = _spoken(verdict, support, items)
    if verdict.rough and caveat:
        line += f" That's a rough comparison with {'supports' if support else 'cores'} in general."
    return line


def _spoken(verdict: Verdict, support: bool, items: bool) -> str:
    minutes = f"{verdict.minute} minutes"
    if verdict.rank:
        minutes = f"{rank_mod.name(verdict.rank)} at {minutes}"
    if verdict.kind == "ahead":
        return (
            f"You're ahead for {minutes}. Use it: group with your team "
            "and take a tower, or Roshan after a won fight."
        )
    if verdict.kind == "even":
        return f"You're about even for {minutes}. Keep farming and fight together with your team."
    name = METRICS[verdict.weakest]
    low = f"{name} {'are' if name.endswith('s') else 'is'} low"
    if support:
        if not items:
            return (
                f"You're behind for {minutes}, your {low}. "
                "Stay near your cores and soak experience from fights."
            )
        return (
            f"You're behind for {minutes}, your {low}. Stay near your cores, "
            "soak experience from fights, and buy Glimmer Cape or Force Staff to stay alive."
        )
    if not items:
        return (
            f"You're behind for {minutes}, your {low}. Farm the safe side of the map "
            "near your towers and skip risky fights."
        )
    return (
        f"You're behind for {minutes}, your {low}. Farm the safe side of the map "
        "near your towers, skip risky fights, and buy a Black King Bar or a defensive item."
    )


def early(snap: Snapshot, support: bool, rank: str | None = None) -> str:
    """Before the numbers say much: last hits against a simple target for a
    core, and deaths so far."""
    minute = (snap.clock_time or 0) // 60
    if minute < 2:
        return "The game has just started. Focus on last hits and don't die, and ask me again in a few minutes."
    deaths = snap.deaths
    if deaths == 0:
        died = "No deaths yet, good."
    elif deaths == 1:
        died = "One death so far: stay out of the enemy's reach in lane."
    else:
        died = f"{deaths} deaths already: play safer and stay near your tower."
    if support:
        return (
            f"It's too early to judge a support at {minute} minutes. {died} "
            "Keep your core safe and stack a camp when you can."
        )
    target = last_hit_target(minute, rank)
    if snap.last_hits >= target:
        farm = f"{snap.last_hits} last hits at {minute} minutes, that's on track."
    else:
        farm = f"{snap.last_hits} last hits at {minute} minutes, aim for about {target}."
    return f"{farm} {died}"


def status(benchmarks: Benchmarks, snap: Snapshot, hero: HeroInfo | None, position: int = 0) -> str:
    """The answer to "how am I doing?", for every hero and minute."""
    support = is_support(hero, position)
    verdict = benchmarks.verdict(snap, support)
    if verdict is None:
        return early(snap, support, benchmarks.bracket())
    return spoken(verdict, support, caveat=benchmarks.say_rough(snap, verdict))
