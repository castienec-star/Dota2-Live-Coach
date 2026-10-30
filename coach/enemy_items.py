"""Enemy items the player told the coach about.

GSI never shows enemy items, and the coach never reads the screen. The
player can see them (click an enemy hero, or the scoreboard) and say them:
"Lion has Glimmer and Force Staff", "enemy Sven bought BKB". The coach
keeps what it was told for this match, the latest report for a hero
replacing the older one, and reads it back so a mishearing is caught. See
issue #21; using the record for item advice is the next step.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable

from .heroes import HeroIndex, HeroInfo
from .items import ItemInfo, load_items
from .lineup import _SKIP, _words, parse_heroes
from .state import MatchState

# What players call items, folded like _words(). Full item names work too.
NICKNAMES = {
    "bkb": "item_black_king_bar",
    "black king": "item_black_king_bar",
    "glimmer": "item_glimmer_cape",
    "force": "item_force_staff",
    "force staff": "item_force_staff",
    "pike": "item_hurricane_pike",
    "euls": "item_cyclone",
    "eul's": "item_cyclone",
    "eul": "item_cyclone",
    "ghost": "item_ghost",
    "ghost scepter": "item_ghost",
    "aeon": "item_aeon_disk",
    "lotus": "item_lotus_orb",
    "linkens": "item_sphere",
    "linken's": "item_sphere",
    "linken": "item_sphere",
    "blademail": "item_blade_mail",
    "blade mail": "item_blade_mail",
    "mek": "item_mekansm",
    "mekansm": "item_mekansm",
    "greaves": "item_guardian_greaves",
    "pipe": "item_pipe",
    "mkb": "item_monkey_king_bar",
    "butterfly": "item_butterfly",
    "halberd": "item_heavens_halberd",
    "solar": "item_solar_crest",
    "blink": "item_blink",
    "dagger": "item_blink",
    "shadow blade": "item_invis_sword",
    "silver edge": "item_silver_edge",
    "satanic": "item_satanic",
    "manta": "item_manta",
    "skadi": "item_skadi",
    "shivas": "item_shivas_guard",
    "shiva's": "item_shivas_guard",
    "vessel": "item_spirit_vessel",
    "holy locket": "item_holy_locket",
    "locket": "item_holy_locket",
    "radiance": "item_radiance",
    "deso": "item_desolator",
    "daedalus": "item_greater_crit",
    "basher": "item_basher",
    "abyssal": "item_abyssal_blade",
    "orchid": "item_orchid",
    "bloodthorn": "item_bloodthorn",
    "nullifier": "item_nullifier",
    "atos": "item_rod_of_atos",
    "hex": "item_sheepstick",
    "sheep": "item_sheepstick",
    "scythe": "item_sheepstick",
    "aghs": "item_ultimate_scepter",
    "aghanim's": "item_ultimate_scepter",
    "refresher": "item_refresher",
    "battle fury": "item_bfury",
    "bfury": "item_bfury",
    "mjollnir": "item_mjollnir",
    "heart": "item_heart",
    "crimson": "item_crimson_guard",
    "vanguard": "item_vanguard",
    "disperser": "item_disperser",
    "wind waker": "item_wind_waker",
    "gem": "item_gem",
}
# Said about items an enemy has; "buy" is left out so "should I buy BKB
# against Lina?" stays a question.
_HAS = re.compile(r"\b(has|have|got|bought|built|building|carries|carrying|with)\b")
_FORGET = re.compile(r"\b(forget|clear|reset)\b.*\bitems?\b")
# About the player, not an enemy: "do I have BKB?", "should I get Pipe?".
_SELF = re.compile(r"\b(i|i'm|my|me|should|do|does|what|which)\b")
# One answer can name several heroes: "Lion has Glimmer, and Sven has BKB".
_PARTS = re.compile(r"[,.;!?]|\band\b(?=(?:\s+[\w'-]+){1,3}\s+(?:has|have|got|bought|built|is)\b)", re.I)
# "Lion has Force Staff, not Glimmer": what follows "not" is a correction.
_NOT = re.compile(r"\bnot\b.*")
# Cheap or consumable items say nothing about a fight; not worth keeping.
MIN_COST = 1000


class ItemMatcher:
    """Item names and nicknames in a spoken sentence."""

    def __init__(self, items: dict[str, ItemInfo] | None = None) -> None:
        self.items = items if items is not None else load_items()
        names = {_words(i.name): i.key for i in self.items.values() if i.cost >= MIN_COST}
        names.update({k: v for k, v in NICKNAMES.items() if v in self.items})
        # Longest first, so "force staff" wins over "force".
        self.names = sorted(names.items(), key=lambda kv: -len(kv[0]))

    def find(self, text: str) -> tuple[list[ItemInfo], str]:
        """The items named in text, in order, and the text left without them."""
        words = f" {_words(text)} "
        found: list[tuple[int, ItemInfo]] = []
        for name, key in self.names:
            pattern = f" {name} "
            while (at := words.find(pattern)) >= 0:
                found.append((at, self.items[key]))
                words = words[:at] + " " + "#" * (len(pattern) - 2) + " " + words[at + len(pattern) :]
        items: list[ItemInfo] = []
        for _, item in sorted(found, key=lambda f: f[0]):
            if item not in items:
                items.append(item)
        rest = " ".join(w for w in words.split() if not w.startswith("#"))
        return items, rest


def _list(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


class EnemyItems:
    """What the player said the enemy heroes have, for this match.

    Add it as a GSI listener so a new match starts empty. enemies() is the
    lineup the player told the coach: when it is known, only those heroes
    are taken, so a misheard ally isn't recorded.
    """

    def __init__(
        self,
        index: HeroIndex | None = None,
        enemies: Callable[[], list[HeroInfo]] | None = None,
        matcher: ItemMatcher | None = None,
    ) -> None:
        self.index = index or HeroIndex()
        self.enemies = enemies or list
        self.matcher = matcher or ItemMatcher()
        self._lock = threading.Lock()
        self._told: dict[str, tuple[HeroInfo, tuple[ItemInfo, ...]]] = {}

    def __call__(self, state: MatchState) -> None:
        if state.new_match:
            self.clear()

    def clear(self) -> None:
        with self._lock:
            self._told.clear()

    def told(self) -> dict[HeroInfo, tuple[ItemInfo, ...]]:
        """Each enemy hero and the items the player last said it has."""
        with self._lock:
            return {hero: items for hero, items in self._told.values()}

    def facts(self) -> list[str]:
        """Short sentences for a model's prompt."""
        return [f"{hero.name} has {_list([i.name for i in items])}" for hero, items in self.told().items()]

    def is_report(self, text: str) -> bool:
        """Whether text tells the coach about enemy items (or to forget them),
        rather than asking a question."""
        words = _words(text)
        return bool(_FORGET.search(words)) or self._parse(words) is not None

    def report(self, text: str) -> str | None:
        """Record a report and return the read-back, or None if it isn't one."""
        words = _words(text)
        if not words or _SKIP.search(words):
            return None
        if _FORGET.search(words):
            self.clear()
            return "Okay, I forgot the enemy items."
        parsed = self._parse(words)
        if parsed is None:
            return None
        hero, items = parsed
        with self._lock:
            self._told[hero.key] = (hero, tuple(items))
        return f"Got it, {hero.name} has {_list([i.name for i in items])}."

    def answer(self, text: str) -> str | None:
        """The answer to "check the enemy items": one or more "<hero> has
        <items>", where the verb may be left out ("Lion glimmer and force").
        Records each and returns one read-back, or None if nothing was heard."""
        if not _words(text) or _SKIP.search(_words(text)):
            return None
        said = []
        for part in _PARTS.split(text):
            parsed = self._parse(_words(part), asked=True) if part and part.strip() else None
            if parsed is None:
                continue
            hero, items = parsed
            with self._lock:
                self._told[hero.key] = (hero, tuple(items))
            said.append(f"{hero.name} has {_list([i.name for i in items])}")
        return f"Got it, {' and '.join(said)}." if said else None

    def _parse(self, words: str, asked: bool = False) -> tuple[HeroInfo, list[ItemInfo]] | None:
        """The enemy hero and its items from "<hero> has <items>". asked: an
        answer to the coach's question, where "has" may be left out."""
        items, rest = self.matcher.find(_NOT.sub("", words))
        if not items or not (asked or _HAS.search(rest)) or _SELF.search(rest):
            return None
        heroes = self._heroes(rest)
        return (heroes[0], items) if heroes else None

    def _heroes(self, text: str) -> list[HeroInfo]:
        heroes = parse_heroes(self.index, text)
        enemies = self.enemies()
        return [h for h in heroes if h in enemies] if enemies else heroes
