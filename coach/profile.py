"""Your playstyle, learned from your own match recordings.

After each match the coach reads its recording and keeps a short summary:
your hero, result, deaths and when they happened, last hits at 10 minutes,
and when you finished your big items. The pre-game briefing uses these
summaries, so its advice follows how you actually play. Nothing here is about
other players.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean

from .items import ItemInfo, load_items
from .recorder import read_recording
from .state import Snapshot

log = logging.getLogger(__name__)

MIN_GAME_SECONDS = 300  # shorter recordings are tests or abandons
BIG_ITEM_COST = 1800  # items worth tracking as timings
RECENT_GAMES = 20


@dataclass
class MatchSummary:
    hero: str
    duration: int  # game clock seconds
    won: bool | None
    kills: int
    deaths: int
    assists: int
    last_hits_10: int | None
    death_times: list[int] = field(default_factory=list)
    item_times: dict[str, int] = field(default_factory=dict)  # item key -> clock seconds
    started: float = 0.0  # wall-clock time of the first update


class Tally:
    """Builds a MatchSummary one snapshot at a time, from a recording or live
    from the game (the post-game review)."""

    def __init__(self, items: dict[str, ItemInfo]) -> None:
        self.items = items
        self.hero: str | None = None
        self.last = Snapshot()
        self.team = self.win_team = None
        self.last_hits_10: int | None = None
        self.death_times: list[int] = []
        self.item_times: dict[str, int] = {}
        self.deaths = 0

    def add(self, snap: Snapshot) -> None:
        self.team = snap.team or self.team
        if snap.win_team in ("radiant", "dire"):
            self.win_team = snap.win_team
        if not snap.in_game or snap.clock_time is None:
            return
        self.hero = snap.hero_name or self.hero
        if snap.deaths > self.deaths:
            self.death_times.extend([snap.clock_time] * (snap.deaths - self.deaths))
        self.deaths = snap.deaths
        if self.last_hits_10 is None and snap.clock_time >= 600:
            self.last_hits_10 = snap.last_hits
        for item in snap.items:
            info = self.items.get(item.name)
            if info and info.cost >= BIG_ITEM_COST and item.name not in self.item_times:
                self.item_times[item.name] = snap.clock_time
        self.last = snap

    def summary(self, started: float = 0.0) -> MatchSummary | None:
        """None if no real game was seen."""
        last = self.last
        if self.hero is None or (last.clock_time or 0) < MIN_GAME_SECONDS:
            return None
        won = self.win_team == self.team if self.win_team and self.team else None
        return MatchSummary(
            hero=self.hero.removeprefix("npc_dota_hero_"),
            duration=last.clock_time or 0,
            won=won,
            kills=last.kills,
            deaths=last.deaths,
            assists=last.assists,
            last_hits_10=self.last_hits_10,
            death_times=list(self.death_times),
            item_times=dict(self.item_times),
            started=started,
        )


def summarize(path: Path, items: dict[str, ItemInfo]) -> MatchSummary | None:
    """Summarize one recording, or None if it holds no real game."""
    tally = Tally(items)
    started = None
    try:
        for t, payload in read_recording(path):
            started = started or t
            tally.add(Snapshot.from_payload(payload))
    except (OSError, ValueError, KeyError) as exc:
        log.warning("Skipped recording %s: %s", path.name, exc)
        return None
    return tally.summary(started or 0.0)


class Profile:
    """Summaries of your recorded matches, kept in profile.json."""

    def __init__(
        self,
        record_dir: Path,
        store: Path,
        items: dict[str, ItemInfo] | None = None,
    ) -> None:
        self.record_dir = record_dir
        self.store = store
        self.items = items if items is not None else load_items()
        self.matches: list[MatchSummary] = []

    def update(self) -> list[MatchSummary]:
        """Read new recordings; ones already summarized are not read again."""
        cache: dict[str, dict] = {}
        if self.store.is_file():
            try:
                cache = json.loads(self.store.read_text(encoding="utf-8"))
            except ValueError:
                cache = {}
        fresh: dict[str, dict] = {}
        paths = sorted(self.record_dir.glob("*.jsonl")) if self.record_dir.is_dir() else []
        for path in paths:
            stat = path.stat()
            stamp = f"{stat.st_size}:{int(stat.st_mtime)}"
            entry = cache.get(path.name)
            if entry is None or entry.get("stamp") != stamp:
                summary = summarize(path, self.items)
                entry = {"stamp": stamp, "match": asdict(summary) if summary else None}
            fresh[path.name] = entry
        if fresh != cache:
            self.store.parent.mkdir(parents=True, exist_ok=True)
            self.store.write_text(json.dumps(fresh), encoding="utf-8")
        self.matches = [
            MatchSummary(**e["match"]) for e in fresh.values() if e.get("match")
        ]
        self.matches.sort(key=lambda m: m.started)
        return self.matches

    def describe(self, hero: str | None) -> list[str]:
        """Facts about how you play, for the briefing. Empty with no recordings."""
        hero = (hero or "").removeprefix("npc_dota_hero_")
        recent = self.matches[-RECENT_GAMES:]
        if not recent:
            return []
        lines = []
        on_hero = [m for m in self.matches if m.hero == hero][-RECENT_GAMES:]
        games = on_hero or recent
        label = f"your last {len(games)} recorded games on this hero" if on_hero else (
            f"your last {len(games)} recorded games"
        )
        results = [m.won for m in games if m.won is not None]
        if results:
            lines.append(f"In {label} you won {sum(results)} of {len(results)}.")
        lines.append(
            f"In {label} you averaged {mean(m.deaths for m in games):.1f} deaths"
            f" and {mean(m.kills + m.assists for m in games):.1f} kills plus assists."
        )
        early = [sum(1 for t in m.death_times if t < 600) for m in games]
        if mean(early) >= 1.5:
            lines.append(
                f"You die {mean(early):.1f} times before 10 minutes on average, so the laning stage is a weak spot."
            )
        lh = [m.last_hits_10 for m in games if m.last_hits_10 is not None]
        if lh:
            lines.append(f"Your last hits at 10 minutes average {mean(lh):.0f}.")
        death_minutes = [t // 60 for m in games for t in m.death_times]
        if len(death_minutes) >= 5:
            bucket = max(range(0, 60, 10), key=lambda b: sum(b <= d < b + 10 for d in death_minutes))
            lines.append(f"Most of your deaths happen between {bucket} and {bucket + 10} minutes.")
        if on_hero:
            timings = []
            for key in self._common_items(on_hero):
                times = [m.item_times[key] for m in on_hero if key in m.item_times]
                name = self.items[key].name if key in self.items else key
                timings.append(f"{name} at {round(mean(times) / 60)} minutes")
            if timings:
                lines.append("You usually finish " + ", ".join(timings) + ".")
        return lines

    @staticmethod
    def _common_items(games: list[MatchSummary], top: int = 3) -> list[str]:
        """Big items bought in at least half the games, in the order you finish them."""
        counts: dict[str, list[int]] = {}
        for m in games:
            for key, t in m.item_times.items():
                counts.setdefault(key, []).append(t)
        common = [k for k, ts in counts.items() if len(ts) * 2 >= len(games)]
        common.sort(key=lambda k: mean(counts[k]))
        return common[:top]
