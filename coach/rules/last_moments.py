"""What happened in the seconds before a death, from your own hero's GSI data.

A tip about the death you just had beats a general one: "you died with your
Shadow Blade ready" or "you started that fight at low health". Everything
here is your own hero's health, spells and items, which the game shows you.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..items import ItemInfo
from ..state import Snapshot

# How far back to look, in game seconds.
WINDOW = 15

# Items that could have saved you or got you out, if pressed in time.
SAVES = (
    "item_black_king_bar",
    "item_invis_sword",
    "item_silver_edge",
    "item_blink",
    "item_overwhelming_blink",
    "item_swift_blink",
    "item_arcane_blink",
    "item_force_staff",
    "item_hurricane_pike",
    "item_glimmer_cape",
    "item_ghost",
    "item_cyclone",
    "item_wind_waker",
    "item_manta",
    "item_satanic",
    "item_lotus_orb",
    "item_blade_mail",
)
WANDS = ("item_magic_wand", "item_magic_stick")
FULL_WAND = 10  # charges worth pressing for


@dataclass(frozen=True)
class Moments:
    """What the coach noticed about one death."""

    unused_item: str | None = None  # a save or escape item that was ready
    unused_ultimate: str | None = None
    wand_charges: int = 0  # charges left on a wand that wasn't used
    low_cast: str | None = None  # a spell cast at low health shortly before
    low_cast_health: float = 0.0

    def facts(self) -> list[str]:
        """Plain sentences for a model's prompt."""
        found = []
        if self.unused_item:
            found.append(f"{self.unused_item} was ready and not used")
        if self.unused_ultimate:
            found.append(f"their ultimate, {self.unused_ultimate}, was ready and not used")
        if self.wand_charges:
            found.append(f"their wand had {self.wand_charges} charges and was not used")
        if self.low_cast:
            found.append(f"they cast {self.low_cast} at {self.low_cast_health:.0f}% health and then died")
        return found

    def tip(self) -> str | None:
        """One built-in line about the most useful thing noticed, or None."""
        if self.low_cast:
            return f"You used {self.low_cast} at low health. Heal up before you start the next fight."
        if self.unused_item:
            return f"You died with your {self.unused_item} ready. Press it as soon as the fight turns."
        if self.unused_ultimate:
            return f"You died with {self.unused_ultimate} ready. Use your ultimate earlier in the fight."
        if self.wand_charges:
            return f"You died with {self.wand_charges} wand charges. Press your wand when you get low."
        return None


def spell_name(ability: str, hero: str | None) -> str:
    """ "spirit_breaker_charge_of_darkness" -> "Charge of Darkness"."""
    prefix = (hero or "").removeprefix("npc_dota_hero_") + "_"
    words = ability.removeprefix(prefix).split("_")
    small = {"of", "the", "and", "a", "to", "in"}
    return " ".join(w if i and w in small else w.capitalize() for i, w in enumerate(words))


def notice(history: list[Snapshot], items: dict[str, ItemInfo]) -> Moments:
    """Look at the snapshots while alive before a death (oldest first)."""
    if not history:
        return Moments()
    last = history[-1]
    unused_item = next(
        (
            items[key].name if key in items else key
            for key in SAVES
            if (item := last.item(key)) is not None and item.can_cast and item.cooldown == 0
        ),
        None,
    )
    ultimate = next(
        (a for a in last.abilities if a.ultimate and a.level > 0 and a.can_cast and a.cooldown == 0),
        None,
    )
    wand = next((w for key in WANDS if (w := last.item(key)) is not None), None)
    charges = wand.charges or 0 if wand is not None and wand.can_cast else 0
    low_cast, low_health = None, 0.0
    for before, after in zip(history, history[1:]):
        cooldowns = {a.name: a.cooldown for a in before.abilities}
        for a in after.abilities:
            # A spell went on cooldown: it was cast between these two updates.
            if cooldowns.get(a.name) == 0 and a.cooldown > 0 and before.health_percent < 35:
                low_cast, low_health = a.name, before.health_percent
    return Moments(
        unused_item=unused_item,
        unused_ultimate=spell_name(ultimate.name, last.hero_name) if ultimate else None,
        wand_charges=charges if charges >= FULL_WAND else 0,
        low_cast=spell_name(low_cast, last.hero_name) if low_cast else None,
        low_cast_health=low_health,
    )


class Recent:
    """The snapshots of the last WINDOW game seconds while alive."""

    def __init__(self, window: int = WINDOW) -> None:
        self.window = window
        self.snaps: list[Snapshot] = []

    def add(self, snap: Snapshot) -> None:
        if not snap.alive or snap.clock_time is None:
            return
        now = snap.clock_time
        self.snaps = [s for s in self.snaps if now - (s.clock_time or 0) <= self.window] + [snap]

    def clear(self) -> None:
        self.snaps = []
