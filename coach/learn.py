"""'What hero should I learn?': two or three simple heroes that win at your medal.

The answer picks from a short hand-made list of forgiving heroes (simple
spells, tanky or a second life, easy to farm or to support with), keeps the
ones that win at least half their games in the player's own bracket this
patch (coach/data/hero_stats.json, the same numbers the chat uses) and names
the best two or three with why each is easy. Only the player's own medal's
numbers are used, never other brackets mixed in; while the medal isn't known
the coach names the heroes without numbers and asks for it.

The role comes from the question ("a support hero", "carry"), else the
player's position this game, else the answer mixes two cores and a support.
See docs/strategy/low-bracket-meta.md ("Forgiving heroes win at every
medal") and docs/strategy/fundamentals.md ("One role, a few heroes").
"""

from __future__ import annotations

import re

from . import i18n
from . import rank as rank_mod
from .hero_stats import BRACKETS, HeroStat

CORE, SUPPORT = "core", "support"

# Forgiving heroes, hero key: (role, why it is easy), best first when win
# rates tie. Checked against 7.41 Herald-to-Ancient win rates in
# coach/data/hero_stats.json; heroes that lose at these medals (Lion,
# Jakiro, Viper) or punish mistakes (Drow Ranger, Shadow Fiend) stay out.
POOL: dict[str, tuple[str, str]] = {
    "skeleton_king": (CORE, "his ultimate gives you a second life"),
    "dragon_knight": (CORE, "tanky and simple"),
    "juggernaut": (CORE, "spins through fights and heals with his ward"),
    "legion_commander": (CORE, "one button wins a duel"),
    "chaos_knight": (CORE, "tanky with a big stun"),
    "sven": (CORE, "one stun and huge cleave damage"),
    "luna": (CORE, "farms fast from range"),
    "phantom_assassin": (CORE, "simple and hits hard"),
    "axe": (CORE, "tanky and starts fights for his team"),
    "witch_doctor": (SUPPORT, "simple spells that heal and stun"),
    "crystal_maiden": (SUPPORT, "gives the team mana and freezes enemies"),
    "lich": (SUPPORT, "safe spells from far away"),
    "vengefulspirit": (SUPPORT, "a stun and an aura for your carry"),
    "shadow_shaman": (SUPPORT, "lots of disable and wards that push"),
    "ogre_magi": (SUPPORT, "tanky, hard to kill"),
    "dazzle": (SUPPORT, "keeps a teammate from dying"),
}

# Said while the medal isn't known: the safest picks at every low medal
# (low-bracket-meta.md).
DEFAULT = {CORE: ["skeleton_king", "dragon_knight"], SUPPORT: ["witch_doctor", "crystal_maiden"]}

MIN_WIN_RATE = 0.5

STICK = "Pick one and play it for your next ten games."

_SUPPORT_WORDS = re.compile(r"\b(supports?|pos(ition)? ?[45]|soft support|hard support|soporte)\b")
_CORE_WORDS = re.compile(r"\b(carry|carries|core|mid|midlane|offlane|offlaner|safe ?lane|pos(ition)? ?[123])\b")


def role_in(text: str) -> str | None:
    """"support" or "core" when the question names a role, else None."""
    folded = i18n.fold(text or "")
    if _SUPPORT_WORDS.search(folded):
        return SUPPORT
    if _CORE_WORDS.search(folded):
        return CORE
    return None


def role_of(position: int) -> str | None:
    if position in (1, 2, 3):
        return CORE
    if position in (4, 5):
        return SUPPORT
    return None


def pick(in_bracket: dict[str, HeroStat], role: str | None, count: int = 3) -> list[str]:
    """Hero keys from POOL that win at least MIN_WIN_RATE in this bracket,
    best first: "count" of the role, or two cores and a support."""

    def best(of_role: str) -> list[str]:
        keys = [k for k, (r, _) in POOL.items() if r == of_role and k in in_bracket]
        keys = [k for k in keys if in_bracket[k].win_rate >= MIN_WIN_RATE]
        order = list(POOL)
        return sorted(keys, key=lambda k: (-round(in_bracket[k].win_rate, 3), order.index(k)))

    if role is not None:
        return best(role)[:count]
    return best(CORE)[: count - 1] + best(SUPPORT)[:1]


def suggest(
    text: str,
    rank: str | None,
    stats: dict[int, dict[str, HeroStat]],
    names: dict[str, str],
    position: int = 0,
) -> str:
    """The spoken answer. "rank" is the player's medal ("archon") or None,
    "stats" hero_stats.load(), "names" hero key -> display name."""
    role = role_in(text) or role_of(position)
    bracket = rank_mod.TIERS.get(rank or "")
    in_bracket = stats.get(bracket or 0, {})
    keys = pick(in_bracket, role)
    if bracket is None or not keys:
        keys = DEFAULT[role] if role else [*DEFAULT[CORE], DEFAULT[SUPPORT][0]]
        heroes = " ".join(f"{names.get(k, k)}: {POOL[k][1]}." for k in keys)
        if bracket is None:
            ask = " Tell me your rank, say my rank is and your medal, and I'll pick the ones that win most at it."
        else:
            ask = f" I don't have this patch's numbers for {BRACKETS[bracket - 1]} games."
        return f"Good heroes to learn. {heroes}{ask} {STICK}"
    medal = BRACKETS[bracket - 1]
    heroes = " ".join(f"{names.get(k, k)} wins {in_bracket[k].win_rate:.0%}: {POOL[k][1]}." for k in keys)
    return f"In {medal} games this patch: {heroes} {STICK}"
