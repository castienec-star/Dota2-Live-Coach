"""Item names and prices, from a bundled snapshot of OpenDota's dotaconstants."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ITEMS_FILE = Path(__file__).resolve().parent / "data" / "items.json"


@dataclass(frozen=True)
class ItemInfo:
    key: str  # GSI name, e.g. "item_blink"
    name: str  # display name, e.g. "Blink Dagger"
    cost: int


def load_items(path: Path = ITEMS_FILE) -> dict[str, ItemInfo]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return {k: ItemInfo(k, v["name"], v["cost"]) for k, v in data["items"].items()}


def lookup(items: dict[str, ItemInfo], wanted: str) -> ItemInfo | None:
    """Find an item by GSI key ("item_blink"), short key ("blink") or name ("Blink Dagger")."""
    key = wanted if wanted.startswith("item_") else f"item_{wanted}"
    if key in items:
        return items[key]
    folded = wanted.strip().lower()
    return next((i for i in items.values() if i.name.lower() == folded), None)
