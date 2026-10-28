"""Ahead, even or behind: your own numbers against public numbers for your hero.

The baselines are OpenDota's public hero benchmarks: for each hero, the gold
per minute, experience per minute and last hits per minute that 10%, 20%...
99% of recent public matches reached. A snapshot for the heroes with a
bundled build ships in coach/data/benchmarks.json; other heroes are read once
from OpenDota and cached, if it is turned on. Only your own hero's GSI numbers
are compared; nothing about other players is looked up.

See docs/strategy/ahead-or-behind.md for how the verdict is chosen.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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

Curve = list[tuple[float, float]]  # (percentile, value), rising
Fetch = Callable[[int], dict[str, Curve] | None]


@dataclass(frozen=True)
class Verdict:
    kind: str  # "ahead", "even" or "behind"
    score: float  # average share of public matches you are above, 0 to 1
    weakest: str  # the metric furthest behind, e.g. "last_hits_per_min"
    minute: int


def load_benchmarks(path: Path = BENCHMARKS_FILE) -> dict[str, dict[str, Curve]]:
    """{hero key: {metric: curve}} from the bundled snapshot."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    percentiles = data["percentiles"]
    return {
        key: {m: list(zip(percentiles, hero[m])) for m in METRICS if m in hero}
        for key, hero in data["heroes"].items()
    }


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
    ) -> None:
        self.heroes = load_benchmarks() if heroes is None else heroes
        self.fetch = fetch
        self.hero_ids = hero_ids or {}

    def curves(self, hero: str) -> dict[str, Curve] | None:
        if hero not in self.heroes and self.fetch is not None and hero in self.hero_ids:
            fetched = self.fetch(self.hero_ids[hero])
            if fetched:
                self.heroes[hero] = fetched
        return self.heroes.get(hero)

    def verdict(self, snap: Snapshot, support: bool = False) -> Verdict | None:
        """None before EARLIEST or when there are no numbers for the hero."""
        clock = snap.clock_time or 0
        hero = (snap.hero_name or "").removeprefix("npc_dota_hero_")
        if clock < EARLIEST or not hero:
            return None
        curves = self.curves(hero)
        if not curves:
            return None
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
        kind = "behind" if score < BEHIND else "ahead" if score >= AHEAD else "even"
        return Verdict(kind, score, min(shares, key=shares.get), clock // 60)
