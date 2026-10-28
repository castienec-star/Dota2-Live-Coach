"""Situational items: what to buy now, from how your game is going and the
enemy heroes you told the coach about.

The enemy lineup only comes from you (the start-of-game questions or typed
picks); the coach never looks it up. Only hero names are used, never enemy
items, positions or net worth. See docs/strategy/situational-items.md for
where each rule comes from.
"""

from __future__ import annotations

from dataclasses import dataclass

from .benchmarks import Verdict
from .heroes import HeroInfo
from .items import ItemInfo
from .state import Snapshot


@dataclass(frozen=True)
class Threat:
    reason: str  # said after the hero names, e.g. "do a lot of magic damage"
    heroes: frozenset[str]  # hero keys
    items: dict[str, str]  # role ("core", "offlane", "support") -> item key
    least: int = 1  # how many enemies with it before it is worth an item


def _keys(text: str) -> frozenset[str]:
    return frozenset(text.split())


# In the order they are checked; the first one a role has an item for wins.
THREATS = [
    Threat(
        "can turn invisible",
        _keys("riki clinkz bounty_hunter weaver nyx_assassin mirana treant sand_king"),
        {"core": "item_dust", "offlane": "item_dust", "support": "item_ward_sentry"},
    ),
    Threat(
        "dodge your attacks",
        _keys("phantom_assassin windrunner brewmaster"),
        {"core": "item_monkey_king_bar"},
    ),
    Threat(
        "make illusions",
        _keys("phantom_lancer naga_siren chaos_knight terrorblade meepo"),
        {"core": "item_maelstrom", "offlane": "item_maelstrom"},
    ),
    Threat(
        "heal a lot",
        _keys(
            "huskar alchemist necrolyte abaddon life_stealer oracle omniknight witch_doctor"
            " dazzle shredder"
        ),
        {"core": "item_skadi", "offlane": "item_spirit_vessel", "support": "item_spirit_vessel"},
    ),
    Threat(
        "do a lot of magic damage",
        _keys(
            "lina lion zuus leshrac skywrath_mage queenofpain tinker necrolyte pugna"
            " death_prophet ogre_magi witch_doctor jakiro lich invoker storm_spirit puck"
            " nyx_assassin nevermore huskar sand_king keeper_of_the_light ember_spirit"
            " phoenix disruptor grimstroke muerta snapfire"
        ),
        {"core": "item_black_king_bar", "offlane": "item_pipe", "support": "item_glimmer_cape"},
        least=2,
    ),
    Threat(
        "have a lot of stuns",
        _keys(
            "lion shadow_shaman earthshaker sand_king tidehunter magnataur enigma faceless_void"
            " bane legion_commander doom_bringer batrider axe centaur slardar sven"
            " dragon_knight ogre_magi crystal_maiden witch_doctor jakiro kunkka mars"
            " primal_beast spirit_breaker chaos_knight skeleton_king pudge"
        ),
        {"core": "item_black_king_bar", "offlane": "item_black_king_bar", "support": "item_force_staff"},
        least=2,
    ),
    Threat(
        "hit hard with attacks",
        _keys(
            "phantom_assassin sven troll_warlord ursa slark juggernaut skeleton_king drow_ranger"
            " sniper luna faceless_void medusa life_stealer monkey_king chaos_knight"
            " templar_assassin clinkz riki bloodseeker weaver phantom_lancer terrorblade"
        ),
        {"offlane": "item_blade_mail", "support": "item_ghost"},
        least=2,
    ),
]

# When you are behind and no threat calls for something, buy to stay alive.
DEFENSIVE = {
    "core": ["item_black_king_bar"],
    "offlane": ["item_black_king_bar", "item_blade_mail"],
    "support": ["item_glimmer_cape", "item_force_staff"],
}

# Items that already hold a cheaper one, so owning them counts as owning it.
UPGRADES = {
    "item_maelstrom": ("item_mjollnir", "item_gungir"),
    "item_ghost": ("item_ethereal_blade",),
    "item_force_staff": ("item_hurricane_pike",),
    "item_ward_sentry": ("item_ward_dispenser",),
}


@dataclass(frozen=True)
class Pick:
    item: ItemInfo
    reason: str  # "" when it isn't about the enemy heroes


def role(position: int, support: bool) -> str:
    """"core" for positions 1 and 2, "offlane" for 3, "support" for 4 and 5;
    while the position isn't known, support or core from the hero."""
    if position == 3:
        return "offlane"
    return "support" if support else "core"


def owns(snap: Snapshot, key: str) -> bool:
    return any(snap.has_item(k) for k in (key, *UPGRADES.get(key, ())))


def _names(heroes: list[HeroInfo]) -> str:
    names = [h.name for h in heroes[:2]]
    return " and ".join(names)


def against(enemies: list[HeroInfo], role_name: str, snap: Snapshot, items: dict[str, ItemInfo]) -> Pick | None:
    """The first threat in the enemy lineup with an item for your role that
    you don't own yet."""
    for threat in THREATS:
        found = [h for h in enemies if h.key in threat.heroes]
        key = threat.items.get(role_name)
        if len(found) < threat.least or key is None or owns(snap, key) or key not in items:
            continue
        verb = threat.reason if len(found) > 1 else _singular(threat.reason)
        return Pick(items[key], f"{_names(found)} {verb}")
    return None


def _singular(reason: str) -> str:
    """"do a lot of magic damage" -> "does a lot of magic damage"."""
    verb, _, rest = reason.partition(" ")
    verb = {"do": "does", "have": "has", "can": "can"}.get(verb, verb + "s")
    return f"{verb} {rest}"


def recommend(
    snap: Snapshot,
    verdict: Verdict | None,
    enemies: list[HeroInfo],
    role_name: str,
    items: dict[str, ItemInfo],
    next_item: ItemInfo | None,
) -> Pick | None:
    """What to buy now. A threat from the enemy lineup comes first; when you
    are behind, a defensive item; otherwise the next item on your build."""
    pick = against(enemies, role_name, snap, items)
    if pick is not None:
        return pick
    if verdict is not None and verdict.kind == "behind":
        for key in DEFENSIVE[role_name]:
            if not owns(snap, key) and key in items:
                return Pick(items[key], "")
    return Pick(next_item, "") if next_item is not None else None


def spoken(pick: Pick | None, verdict: Verdict | None, snap: Snapshot) -> str:
    """One or two short sentences: the verdict, then the item and why."""
    parts = []
    if verdict is not None:
        minutes = f"{verdict.minute} minutes"
        parts.append(
            {
                "ahead": f"You're ahead for {minutes}.",
                "even": f"You're about even for {minutes}.",
                "behind": f"You're behind for {minutes}.",
            }[verdict.kind]
        )
    if pick is None:
        parts.append("Your build list is done. Buy what the game needs, like a Black King Bar.")
    else:
        item = pick.item
        if snap.gold >= item.cost:
            buy = f"Buy {item.name} now"
        else:
            buy = f"Get {item.name} next, {item.cost - snap.gold} more gold"
        if pick.reason:
            buy += f": {pick.reason}"
        elif verdict is not None and verdict.kind == "behind":
            buy += " to stay alive"
        parts.append(buy + ".")
    return " ".join(parts)
