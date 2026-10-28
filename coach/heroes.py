"""Hero names and roles, from a bundled snapshot of OpenDota's dotaconstants."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

HEROES_FILE = Path(__file__).resolve().parent / "data" / "heroes.json"

# Common short names players type. Full names, internal names and initials of
# multi-word names ("cm", "qop") also work without being listed here.
NICKNAMES = {
    "am": "antimage", "bh": "bounty_hunter", "bm": "beastmaster", "bs": "bloodseeker",
    "cent": "centaur", "ck": "chaos_knight", "clock": "rattletrap", "cm": "crystal_maiden",
    "dk": "dragon_knight", "doom": "doom_bringer", "es": "earthshaker", "et": "elder_titan",
    "ember": "ember_spirit", "earth": "earth_spirit", "storm": "storm_spirit",
    "void": "faceless_void", "fv": "faceless_void", "gyro": "gyrocopter", "io": "wisp",
    "wisp": "wisp", "kotl": "keeper_of_the_light", "lc": "legion_commander", "lesh": "leshrac",
    "lich": "lich", "ls": "life_stealer", "naix": "life_stealer", "lone": "lone_druid",
    "ld": "lone_druid", "magnus": "magnataur", "mag": "magnataur", "mk": "monkey_king",
    "necro": "necrolyte", "nature": "furion", "np": "furion", "prophet": "furion",
    "furion": "furion", "ns": "night_stalker", "nyx": "nyx_assassin", "od": "obsidian_destroyer",
    "ogre": "ogre_magi", "pa": "phantom_assassin", "pl": "phantom_lancer", "qop": "queenofpain",
    "rubick": "rubick", "sk": "sand_king", "sd": "shadow_demon", "sf": "nevermore",
    "shaker": "earthshaker", "ss": "shadow_shaman", "rhasta": "shadow_shaman",
    "slark": "slark", "sniper": "sniper", "spec": "spectre", "spirit breaker": "spirit_breaker",
    "sb": "spirit_breaker", "bara": "spirit_breaker", "sven": "sven", "ta": "templar_assassin",
    "tb": "terrorblade", "tide": "tidehunter", "timber": "shredder", "tinker": "tinker",
    "treant": "treant", "troll": "troll_warlord", "tusk": "tusk", "undying": "undying",
    "veno": "venomancer", "viper": "viper", "visage": "visage", "wd": "witch_doctor",
    "wk": "skeleton_king", "wr": "windrunner", "wyvern": "winter_wyvern", "ww": "winter_wyvern",
    "zeus": "zuus", "abba": "abaddon", "alch": "alchemist", "aa": "ancient_apparition",
    "arc": "arc_warden", "bat": "batrider", "brew": "brewmaster", "bristle": "bristleback",
    "bb": "bristleback", "brood": "broodmother", "clinkz": "clinkz",
    "dazzle": "dazzle", "dp": "death_prophet", "disruptor": "disruptor", "drow": "drow_ranger",
    "enchant": "enchantress", "ench": "enchantress", "enigma": "enigma", "huskar": "huskar",
    "invo": "invoker", "jakiro": "jakiro", "jug": "juggernaut", "jugg": "juggernaut",
    "kunkka": "kunkka", "lina": "lina", "lion": "lion", "luna": "luna", "lycan": "lycan",
    "medusa": "medusa", "dusa": "medusa", "meepo": "meepo", "mirana": "mirana",
    "morph": "morphling", "naga": "naga_siren", "oracle": "oracle", "omni": "omniknight",
    "pango": "pangolier", "pudge": "pudge", "pugna": "pugna", "razor": "razor", "riki": "riki",
    "sky": "skywrath_mage", "slardar": "slardar", "snapfire": "snapfire",
    "techies": "techies", "tiny": "tiny", "ursa": "ursa", "vs": "vengefulspirit",
    "venge": "vengefulspirit", "warlock": "warlock", "weaver": "weaver", "hoodwink": "hoodwink",
    "void spirit": "void_spirit", "grim": "grimstroke", "dawn": "dawnbreaker",
    "marci": "marci", "pb": "primal_beast", "muerta": "muerta", "ringmaster": "ringmaster",
}


@dataclass(frozen=True)
class HeroInfo:
    id: int
    key: str  # GSI name without the prefix, e.g. "antimage"
    name: str  # display name, e.g. "Anti-Mage"
    primary_attr: str
    attack_type: str
    roles: tuple[str, ...]


def load_heroes(path: Path = HEROES_FILE) -> dict[int, HeroInfo]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return {
        int(k): HeroInfo(
            id=int(k),
            key=v["name"].removeprefix("npc_dota_hero_"),
            name=v["localized_name"],
            primary_attr=v["primary_attr"],
            attack_type=v["attack_type"],
            roles=tuple(v["roles"]),
        )
        for k, v in data["heroes"].items()
    }


def _fold(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


class HeroIndex:
    """Finds heroes by display name, GSI name, initials or common nickname."""

    def __init__(self, heroes: dict[int, HeroInfo] | None = None) -> None:
        self.heroes = heroes if heroes is not None else load_heroes()
        by_key = {h.key: h for h in self.heroes.values()}
        self._names: dict[str, HeroInfo] = {}
        for h in self.heroes.values():
            words = re.findall(r"[a-z0-9]+", h.name.lower())
            if len(words) > 1:
                self._names.setdefault("".join(w[0] for w in words), h)
        for nick, key in NICKNAMES.items():
            if key in by_key:
                self._names[_fold(nick)] = by_key[key]
        for h in self.heroes.values():
            self._names[_fold(h.name)] = h
            self._names[_fold(h.key)] = h

    def by_key(self, key: str | None) -> HeroInfo | None:
        if not key:
            return None
        key = key.removeprefix("npc_dota_hero_")
        return next((h for h in self.heroes.values() if h.key == key), None)

    def find(self, text: str) -> HeroInfo | None:
        folded = _fold(text.strip().lower().removeprefix("npc_dota_hero_"))
        if not folded:
            return None
        if folded in self._names:
            return self._names[folded]
        # A unique prefix of a display name also works: "bristle", "tre".
        matches = {h for name, h in self._names.items() if name.startswith(folded)}
        return matches.pop() if len(matches) == 1 else None

    def parse(self, text: str) -> tuple[list[HeroInfo], list[str]]:
        """Heroes from a list like "am cm, crystal maiden", plus the words not understood."""
        heroes: list[HeroInfo] = []
        unknown: list[str] = []
        for chunk in text.split(","):
            words = chunk.split()
            i = 0
            while i < len(words):
                # Take the longest run of words that names a hero ("void spirit").
                for j in range(len(words), i, -1):
                    hero = self.find(" ".join(words[i:j]))
                    if hero is not None:
                        if hero not in heroes:
                            heroes.append(hero)
                        i = j
                        break
                else:
                    unknown.append(words[i])
                    i += 1
        return heroes, unknown
