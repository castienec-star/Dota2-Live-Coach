"""What real players build on each hero, from OpenDota's public item popularity.

`py -m coach refresh-items` reads OpenDota's public aggregate
/heroes/{id}/itemPopularity for every hero (how often each item is bought in
the start, early, mid and late game) and saves the most bought items per
stage to coach/data/item_popularity.json. Only public aggregate numbers are
read, never a player's profile or match.

Heroes without their own [builds] list in coach.toml then get a build made
from it (boots first, then the most bought big items of the mid and late
game) instead of the one generic default list.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from .heroes import HeroInfo
from .items import ItemInfo
from .rules.hero import BOOTS

log = logging.getLogger(__name__)

POPULARITY_FILE = Path(__file__).resolve().parent / "data" / "item_popularity.json"
PATCH_FILE = Path(__file__).resolve().parent / "data" / "PATCH"

# OpenDota's stage names, and the shorter ones saved.
STAGES = {
    "start_game_items": "start",
    "early_game_items": "early",
    "mid_game_items": "mid",
    "late_game_items": "late",
}
TOP = 10  # items kept per stage
# Items cheaper than this are components or utility, not build items.
MIN_COST = 2000
BUILD_SIZE = 5  # boots plus four big items


def top_items(counts: dict[str, int], item_ids: dict[str, str], top: int = TOP) -> list[str]:
    """The item keys bought most, from OpenDota's {item id: count}."""
    keys = []
    for item_id, _ in sorted(counts.items(), key=lambda kv: -int(kv[1])):
        name = item_ids.get(str(item_id))
        if name and not name.startswith("recipe_"):
            keys.append(f"item_{name}")
        if len(keys) == top:
            break
    return keys


def fetch(
    get: Callable[[str], Any],
    heroes: dict[str, HeroInfo],
    pause: float = 1.1,
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, dict[str, list[str]]]:
    """{hero key: {stage: [item keys, most bought first]}} for every hero
    OpenDota answers for. "pause" keeps under OpenDota's free rate limit."""
    item_ids = get("/constants/item_ids") or {}
    if not item_ids:
        raise RuntimeError("OpenDota did not send the item list")
    found: dict[str, dict[str, list[str]]] = {}
    for n, hero in enumerate(sorted(heroes.values(), key=lambda h: h.id), 1):
        time.sleep(pause)
        data = get(f"/heroes/{hero.id}/itemPopularity")
        if not isinstance(data, dict):
            progress(f"{n}/{len(heroes)} {hero.name}: no data")
            continue
        found[hero.key] = {
            short: top_items(data.get(stage) or {}, item_ids) for stage, short in STAGES.items()
        }
        progress(f"{n}/{len(heroes)} {hero.name}")
    return found


def save(found: dict[str, dict[str, list[str]]], path: Path = POPULARITY_FILE) -> None:
    patch = PATCH_FILE.read_text(encoding="utf-8").strip() if PATCH_FILE.is_file() else "unknown"
    data = {
        "source": "OpenDota /api/heroes/{id}/itemPopularity (public aggregate stats of recent public matches)",
        "fetched": date.today().isoformat(),
        "patch": patch,
        "note": f"Up to {TOP} most bought items per hero and game stage, most bought first.",
        "heroes": found,
    }
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def load(path: Path = POPULARITY_FILE) -> dict[str, dict[str, list[str]]]:
    """The saved snapshot, or {} before the first refresh."""
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("heroes", {})
    except (OSError, ValueError, AttributeError):
        log.warning("Could not read %s; using the default builds", path)
        return {}


def popular_build(stages: dict[str, list[str]], items: dict[str, ItemInfo]) -> list[ItemInfo]:
    """Boots, then the most bought big items of the mid and late game. [] when
    there are too few to call it a build."""
    boots = next(
        (k for k in stages.get("early", []) + stages.get("mid", []) if k in BOOTS and k in items),
        None,
    )
    big: list[str] = []
    for key in stages.get("mid", []) + stages.get("late", []):
        if key in items and key not in BOOTS and items[key].cost >= MIN_COST and key not in big:
            big.append(key)
    if len(big) < 2:
        return []
    keys = ([boots] if boots else []) + big
    return [items[k] for k in keys[:BUILD_SIZE]]


def popular_builds(
    items: dict[str, ItemInfo], snapshot: dict[str, dict[str, list[str]]] | None = None
) -> dict[str, list[ItemInfo]]:
    """{hero key: build} for every hero in the snapshot with enough data."""
    snapshot = load() if snapshot is None else snapshot
    builds = {}
    for hero, stages in snapshot.items():
        build = popular_build(stages, items)
        if build:
            builds[hero] = build
    return builds
