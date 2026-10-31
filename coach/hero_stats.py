"""How each hero does this patch in Herald to Ancient public games.

`py -m coach refresh-hero-stats` reads OpenDota's public /heroStats (picks
and wins per hero and rank bracket in public ranked matches of the last
seven days) and saves them to coach/data/hero_stats.json. It refuses when
OpenDota's newest patch isn't the one in coach/data/PATCH, or came out less
than a week ago, so the numbers are always from the patch the coach's other
data is for and never mix two patches. Only public aggregate numbers are
read, never a player's profile or match.

The free chat puts the win rates of your hero and the heroes you told the
coach about in its prompt, so "is Pudge strong right now?" gets a real
answer. A file saved for another patch is ignored.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .heroes import HeroInfo

log = logging.getLogger(__name__)

STATS_FILE = Path(__file__).resolve().parent / "data" / "hero_stats.json"
PATCH_FILE = Path(__file__).resolve().parent / "data" / "PATCH"

# OpenDota's rank brackets: 1 Herald ... 8 Immortal.
BRACKETS = ("Herald", "Guardian", "Crusader", "Archon", "Legend", "Ancient", "Divine", "Immortal")
# The players the coach is for: Herald to Ancient.
LOW = range(1, 7)
WINDOW_DAYS = 7  # /heroStats counts the last week of public matches
MIN_GAMES = 1000  # fewer than this in Herald to Ancient and the rate is noise


@dataclass(frozen=True)
class HeroStat:
    picks: int
    wins: int
    rank: int  # by win rate among heroes with enough games, 1 = best
    of: int  # how many heroes were ranked
    pick_share: float  # share of matches this hero is in, 0 to 1

    @property
    def win_rate(self) -> float:
        return self.wins / self.picks if self.picks else 0.0


def current_patch(path: Path = PATCH_FILE) -> str:
    return path.read_text(encoding="utf-8").strip() if path.is_file() else "unknown"


def check_patch(patches: Any, recorded: str, today: date | None = None) -> str | None:
    """Why the stats can't be saved now, or None. "patches" is OpenDota's
    /constants/patch list; its names have no letter ("7.41" for 7.41f)."""
    if not isinstance(patches, list) or not patches:
        return "OpenDota did not send the patch list"
    newest = patches[-1]
    name = str(newest.get("name", ""))
    # 7.41f is a lettered update of 7.41, which OpenDota doesn't tell apart.
    letter = recorded[len(name) :]
    if not name or not recorded.startswith(name) or not (letter == "" or letter.isalpha()):
        return (
            f"Dota {name} is out but the coach's data is for {recorded}. "
            "The hero and item data needs refreshing first (see CLAUDE.md)"
        )
    try:
        released = datetime.fromisoformat(str(newest["date"]).replace("Z", "+00:00")).date()
    except (KeyError, ValueError):
        return None
    today = today or datetime.now(timezone.utc).date()
    if (today - released).days < WINDOW_DAYS:
        return f"{name} came out {(today - released).days} days ago, so last week's games mix two patches. Try again in a few days"
    return None


def fetch(get: Callable[[str], Any], heroes: dict[int, HeroInfo]) -> dict[str, dict[str, Any]]:
    """{hero key: {"id", "picks": [per bracket], "wins": [per bracket]}}."""
    data = get("/heroStats")
    if not isinstance(data, list):
        raise RuntimeError("OpenDota did not send the hero stats")
    found = {}
    for row in data:
        hero = heroes.get(int(row.get("id", 0)))
        if hero is None:
            continue
        picks = [int(row.get(f"{b}_pick") or 0) for b in range(1, len(BRACKETS) + 1)]
        wins = [int(row.get(f"{b}_win") or 0) for b in range(1, len(BRACKETS) + 1)]
        if sum(picks):
            found[hero.key] = {"id": hero.id, "picks": picks, "wins": wins}
    return found


def save(found: dict[str, dict[str, Any]], path: Path = STATS_FILE, patch: str | None = None) -> None:
    data = {
        "source": "OpenDota /api/heroStats (public ranked matches of the last 7 days)",
        "fetched": date.today().isoformat(),
        "patch": patch or current_patch(),
        "note": "Picks and wins per hero in each rank bracket, Herald first: " + ", ".join(BRACKETS),
        "heroes": found,
    }
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def load(path: Path = STATS_FILE, patch: str | None = None) -> dict[str, HeroStat]:
    """{hero key: Herald to Ancient numbers}; {} before the first refresh or
    when the file is from another patch."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        saved, rows = data["patch"], data["heroes"]
        totals = {
            key: (sum(row["picks"][b - 1] for b in LOW), sum(row["wins"][b - 1] for b in LOW))
            for key, row in rows.items()
        }
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        log.warning("Could not read %s; the chat goes without hero win rates", path)
        return {}
    patch = patch or current_patch()
    if saved != patch:
        log.info("%s is for patch %s, not %s; not used", path.name, saved, patch)
        return {}
    # Ten heroes per match.
    matches = sum(p for p, _ in totals.values()) / 10 or 1
    ranked = sorted((k for k, (p, _) in totals.items() if p >= MIN_GAMES), key=lambda k: -totals[k][1] / totals[k][0])
    place = {key: n for n, key in enumerate(ranked, 1)}
    return {
        key: HeroStat(p, w, place.get(key, 0), len(ranked), p / matches)
        for key, (p, w) in totals.items()
        if p >= MIN_GAMES
    }


def describe(stats: dict[str, HeroStat], heroes: list[HeroInfo], patch: str | None = None) -> list[str]:
    """Prompt lines for these heroes, e.g. "Pudge: wins 48.1% (98th of 127),
    in 21% of matches"; [] when there are no numbers for any of them."""
    parts = []
    for hero in dict.fromkeys(h for h in heroes if h is not None):
        stat = stats.get(hero.key)
        if stat is not None:
            parts.append(
                f"{hero.name}: wins {stat.win_rate:.1%} ({ordinal(stat.rank)} of {stat.of}), "
                f"in {stat.pick_share:.0%} of matches"
            )
    if not parts:
        return []
    return [
        f"Patch {patch or current_patch()} win rates in Herald to Ancient public games this week "
        "(about 50% is normal, a few points either way matters little):",
        *(f"- {part}" for part in parts),
    ]


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
