"""What heroes' abilities and items do, in a few plain words each.

Small local models know little about the current patch: they guess what a
hero's ultimate does or what an item is for, and the guesses are often wrong.
The coach puts short "cards" into its prompts instead, so the model reasons
from facts: the abilities of each hero in the match (which ultimate goes
through spell immunity, which ability is a passive) and what each item on
offer does.

The cards are built from the public dotaconstants data (the same source as
heroes.json and items.json) for the patch in coach/data/PATCH, and carry no
numbers: the coach's checks drop a spoken line with a number that isn't in
its facts, so numbers in the cards would let invented ones through.

Rebuild the bundled file after a patch refresh:

    py -m coach.knowledge path/to/dotaconstants/build
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from .heroes import HeroInfo
from .items import ItemInfo

KNOWLEDGE_FILE = Path(__file__).resolve().parent / "data" / "knowledge.json"

# The longest description kept for an ability or item, in words.
MAX_WORDS = 24
# The ultimate sits in the sixth slot of dotaconstants' ability list.
ULTIMATE_SLOT = 5

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_DIGIT = re.compile(r"\d")
# Numbers go, with the words that only make sense around them: "for 5
# seconds", "up to 1200 units away", "60% of", "+30%".
_NUMBER_PHRASES = (
    (re.compile(r"\s*\b(?:for|after|within|up to|every|over|by|to)\s+(?:a\s+)?\d[\d.]*%?"
                r"(?:\s*(?:seconds?|units?|range)|s\b)?(?:\s+(?:away|delay))?,?", re.IGNORECASE), ""),
    (re.compile(r"\s*\b(?:Lasts|Lasting)\b[^.]*\d[^.]*\.", re.IGNORECASE), ""),
    (re.compile(r"\d[\d.+]*%\s+of\b"), "part of"),
    (re.compile(r"\s*(?:\bper\s+)?\d[\d.]*s\b|/s\b"), ""),
    (re.compile(r"\d[\d.]*\s+units?\b"), ""),
    (re.compile(r"[+-]?\d[\d.,/+]*%?x?\s*"), ""),
    (re.compile(r"\s\+(?=\s)"), ""),
    (re.compile(r"\s+([.,;:!?)])"), r"\1"),
    (re.compile(r"(^|[.!?]\s)[,;]\s*"), r"\1"),
    (re.compile(r"\(\s*\)|\s{2,}"), " "),
)


@dataclass(frozen=True)
class Ability:
    name: str
    what: str  # what it does, in at most MAX_WORDS words
    ultimate: bool = False
    passive: bool = False
    pierces: bool = False  # goes through spell immunity (Black King Bar)

    def line(self) -> str:
        tags = [t for t, on in (("ultimate", self.ultimate), ("passive", self.passive)) if on]
        if self.pierces:
            tags.append("goes through spell immunity")
        head = f"{self.name} ({', '.join(tags)})" if tags else self.name
        return f"{head}: {self.what.rstrip('.')}" if self.what else head


def short(text: str, max_words: int = MAX_WORDS) -> str:
    """Whole sentences with the numbers taken out, up to max_words words (the first
    sentence is cut if it alone is longer)."""
    text = re.sub(r"^[A-Z ]+ - ", "", " ".join((text or "").split()))  # "CHANNELED - ..."
    for pattern, replacement in _NUMBER_PHRASES:
        text = pattern.sub(replacement, text)
    words: list[str] = []
    for sentence in _SENTENCE.split(text.strip()):
        found = sentence.split()
        if len(found) < 2:
            continue
        if words and len(words) + len(found) > max_words:
            break
        words += found
    if len(words) > max_words:
        words = words[:max_words]
        words[-1] = words[-1].rstrip(",;:")
        return " ".join(words) + "..."
    return " ".join(words)


def _behaviors(raw: dict) -> list[str]:
    behavior = raw.get("behavior") or []
    return [behavior] if isinstance(behavior, str) else list(behavior)


def hero_abilities(names: list[str], abilities: dict) -> list[dict]:
    """The abilities a player sees on the hero, from dotaconstants' lists."""
    found = []
    for slot, key in enumerate(names):
        raw = abilities.get(key) or {}
        behaviors = _behaviors(raw)
        if not raw.get("dname") or "Hidden" in behaviors or key.startswith("generic_"):
            continue
        if "empty" in key:  # Invoker's and Rubick's spell slots
            continue
        found.append({
            "name": raw["dname"],
            "what": short(raw.get("desc", "")),
            "ultimate": slot == ULTIMATE_SLOT and not raw.get("is_innate"),
            "passive": behaviors == ["Passive"],
            "pierces": raw.get("bkbpierce") == "Yes" and "Passive" not in behaviors,
        })
    return found


def item_card(raw: dict) -> str:
    """What an item gives and does: stats without numbers, then its active or passive."""
    stats = []
    for attrib in raw.get("attrib") or []:
        display = attrib.get("display")
        if not display or "{value}" not in display:
            continue
        stat = display.replace("{value}", "").replace("+", "").replace("%", "").strip()
        stat = re.sub(r"\s*\(.*\)", "", stat)  # "Move Speed (Melee Heroes)"
        if stat and not _DIGIT.search(stat) and stat not in stats:
            stats.append(stat)
    parts = [", ".join(stats[:4])] if stats else []
    for ability in (raw.get("abilities") or [])[:3]:
        what = short(ability.get("description", ""), 14)
        title = ability.get("title", "")
        if title:
            parts.append(f"{ability.get('type', 'active')} {title}" + (f": {what.rstrip('.')}" if what else ""))
    return "; ".join(p for p in parts if p)


def build_data(build_dir: Path, items_file: Path, patch: str) -> dict:
    """knowledge.json's contents from a dotaconstants build/ folder."""
    def read(name: str) -> dict:
        with (build_dir / name).open(encoding="utf-8") as f:
            return json.load(f)

    hero_lists, abilities, raw_items = read("hero_abilities.json"), read("abilities.json"), read("items.json")
    with items_file.open(encoding="utf-8") as f:
        known_items = json.load(f)["items"]
    heroes = {
        key.removeprefix("npc_dota_hero_"): hero_abilities(entry.get("abilities", []), abilities)
        for key, entry in sorted(hero_lists.items())
    }
    items = {}
    for key in sorted(known_items):
        card = item_card(raw_items.get(key.removeprefix("item_"), {}))
        if card:
            items[key] = card
    return {
        "patch": patch,
        "source": "https://github.com/odota/dotaconstants (build/hero_abilities.json, "
        "abilities.json, items.json, MIT License)",
        "heroes": heroes,
        "items": items,
    }


@cache
def _load(path: Path = KNOWLEDGE_FILE) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def abilities(hero: HeroInfo | str | None) -> list[Ability]:
    if hero is None:
        return []
    key = hero.key if isinstance(hero, HeroInfo) else hero.removeprefix("npc_dota_hero_")
    return [Ability(**a) for a in _load()["heroes"].get(key, [])]


def described(hero: HeroInfo | str | None, ultimate_only: bool = False) -> str:
    """ "Earth Spike: ...; Hex: ...", or just the ultimate; "" when unknown."""
    found = abilities(hero)
    if ultimate_only:
        found = [a for a in found if a.ultimate] or found[-1:]
    return "; ".join(a.line() for a in found)


def hero_card(hero: HeroInfo | None, ultimate_only: bool = False) -> str:
    """ "Lion: Earth Spike: ...; Hex: ...", or "" when the data has nothing on the hero."""
    what = described(hero, ultimate_only)
    return f"{hero.name}: {what}" if hero is not None and what else ""


def item_line(item: ItemInfo) -> str:
    """What an item gives and does, or "" when the data has nothing on it."""
    return _load()["items"].get(item.key, "")


def hero_cards(heroes: list[HeroInfo | None], ultimate_only: bool = False) -> list[str]:
    """One card per hero, without repeats."""
    seen: set[str] = set()
    cards = []
    for hero in heroes:
        if hero is None or hero.key in seen:
            continue
        seen.add(hero.key)
        if card := hero_card(hero, ultimate_only):
            cards.append(card)
    return cards


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("Usage: py -m coach.knowledge path/to/dotaconstants/build")
        return 2
    data_dir = KNOWLEDGE_FILE.parent
    patch = (data_dir / "PATCH").read_text(encoding="utf-8").strip()
    data = build_data(Path(argv[0]), data_dir / "items.json", patch)
    KNOWLEDGE_FILE.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {KNOWLEDGE_FILE}: {len(data['heroes'])} heroes, {len(data['items'])} items")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
