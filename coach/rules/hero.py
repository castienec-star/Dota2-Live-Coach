"""Reminders about your own hero: gold, health, skill points and items.

Everything here comes from your own hero's GSI data, which the game already
shows you. These rules only point at it at the right moment.
"""

from __future__ import annotations

from ..heroes import HeroIndex
from ..items import ItemInfo, load_items, lookup
from ..state import MatchState, Snapshot
from . import PositionOf


class HeroRule:
    """A rule with a cooldown measured on the game clock."""

    name = "hero_rule"

    def __init__(self, cooldown: int = 0) -> None:
        self.cooldown = cooldown
        self._last: int | None = None

    def check(self, state: MatchState) -> list[str]:
        snap = state.current
        if snap.clock_time is None:
            return []
        line = self.evaluate(snap)
        if line is None:
            return []
        if self._last is not None and snap.clock_time - self._last < self.cooldown:
            return []
        self._last = snap.clock_time
        return [line]

    def evaluate(self, snap: Snapshot) -> str | None:
        raise NotImplementedError

    def reset(self) -> None:
        self._last = None


# Regen the player may carry, in the order worth reaching for.
REGEN = (
    ("item_flask", "Healing Salve"),
    ("item_bottle", "Bottle"),
    ("item_tango", "Tango"),
    ("item_faerie_fire", "Faerie Fire"),
)


class LowHealth(HeroRule):
    """Two warnings about your own health.

    "Back off" when health drops under below %, but not while it is still
    falling fast: mid-fight, a second before dying, the line only distracts.
    It comes once the burst stops, when backing off can still save you.
    "Go heal" when health stays under linger_below % for linger seconds with
    no damage taken, the slow bleed that loses the next fight. Each is said
    once until health climbs back over rearm %.
    """

    name = "low_health"

    def __init__(
        self,
        below: float = 25,
        rearm: float = 40,
        cooldown: int = 20,
        fast: float = 15,
        linger_below: float = 40,
        linger: int = 10,
        quiet: int = 3,
    ) -> None:
        super().__init__(cooldown)
        self.below = below
        self.rearm = rearm
        self.fast = fast
        self.linger_below = linger_below
        self.linger = linger
        self.quiet = quiet
        self._history: list[tuple[int, float]] = []  # (clock, health %), last few seconds
        self._low_since: int | None = None
        self._hurt_at: int | None = None
        self._armed = True
        self._linger_armed = True

    def evaluate(self, snap: Snapshot) -> str | None:
        if not snap.alive or not snap.max_health:
            self._forget()
            return None
        now, hp = snap.clock_time or 0, snap.health_percent
        if self._history and hp < self._history[-1][1]:
            self._hurt_at = now
        self._history = [(t, h) for t, h in self._history if now - t <= 2] + [(now, hp)]
        if hp >= self.rearm:
            self._armed = self._linger_armed = True
        self._low_since = (self._low_since if self._low_since is not None else now) if hp < self.linger_below else None

        if self._last is not None and now - self._last < self.cooldown:
            return None  # keep the warnings armed until they can be said
        falling = max(h for _, h in self._history) - hp >= self.fast
        if hp < self.below and self._armed and not falling:
            self._armed = False
            return "Low health, back off."
        if (
            self._linger_armed
            and self._low_since is not None
            and now - self._low_since >= self.linger
            and (self._hurt_at is None or now - self._hurt_at >= self.quiet)
        ):
            self._linger_armed = False
            return self._heal_line(snap, hp)
        return None

    @staticmethod
    def _heal_line(snap: Snapshot, hp: float) -> str:
        regen = next((name for key, name in REGEN if snap.item(key) is not None), None)
        if regen:
            return f"You're at {hp:.0f} percent health. Use your {regen} before the next fight."
        return f"You're at {hp:.0f} percent health. Go heal before the next fight."

    def _forget(self) -> None:
        self._history = []
        self._low_since = self._hurt_at = None
        self._armed = self._linger_armed = True

    def reset(self) -> None:
        super().reset()
        self._forget()


class Buyback(HeroRule):
    name = "buyback"

    def __init__(self, from_minute: int = 30, cooldown: int = 60) -> None:
        super().__init__(cooldown)
        self.from_clock = from_minute * 60
        self._below: bool | None = None

    def evaluate(self, snap: Snapshot) -> str | None:
        if (
            snap.clock_time < self.from_clock
            or not snap.alive
            or snap.buyback_cost <= 0
            or snap.buyback_cooldown > 0
        ):
            self._below = None
            return None
        below = snap.gold < snap.buyback_cost
        crossed = below and self._below is not True
        self._below = below
        if crossed:
            return f"You are under buyback gold. Buyback costs {snap.buyback_cost}."
        return None

    def reset(self) -> None:
        super().reset()
        self._below = None


class SkillPoint(HeroRule):
    """Counts levels gained against points spent, so innate abilities don't matter."""

    name = "skill_point"

    def __init__(self, delay: int = 10, max_level: int = 16) -> None:
        super().__init__(0)
        self.delay = delay
        self.max_level = max_level
        self._level: int | None = None
        self._spent = 0
        self._owed = 0
        self._owed_since = 0
        self._reminded = False

    def evaluate(self, snap: Snapshot) -> str | None:
        now, spent = snap.clock_time, snap.skill_points_spent
        if self._level is None or snap.level < self._level:
            self._level, self._spent = snap.level, spent
            return None
        if snap.level > self._level:
            gained = min(snap.level, self.max_level) - min(self._level, self.max_level)
            if gained > 0:
                if self._owed == 0:
                    self._owed_since = now
                self._owed += gained
            self._level = snap.level
        if spent > self._spent:
            self._owed = max(0, self._owed - (spent - self._spent))
        self._spent = spent
        if self._owed == 0:
            self._reminded = False
            return None
        if not self._reminded and now - self._owed_since >= self.delay:
            self._reminded = True
            return "Skill point unused."
        return None

    def reset(self) -> None:
        super().reset()
        self._level = None
        self._spent = self._owed = self._owed_since = 0
        self._reminded = False


# Boots share one slot: owning any pair means a build's boots are done.
# Boots of Travel are the exception, an upgrade bought on top of other boots.
BOOTS = {
    "item_phase_boots",
    "item_power_treads",
    "item_arcane_boots",
    "item_tranquil_boots",
    "item_guardian_greaves",
    "item_boots_of_bearing",
    "item_travel_boots",
    "item_travel_boots_2",
}
TRAVEL = ("item_travel_boots", "item_travel_boots_2")

# Items that already hold a build item, so owning them counts as owning it.
UPGRADES = {
    "item_arcane_boots": ("item_guardian_greaves",),
    "item_tranquil_boots": ("item_boots_of_bearing",),
    "item_travel_boots": ("item_travel_boots_2",),
    "item_blink": ("item_overwhelming_blink", "item_swift_blink", "item_arcane_blink"),
    "item_force_staff": ("item_hurricane_pike",),
    "item_maelstrom": ("item_mjollnir", "item_gungir"),
    "item_diffusal_blade": ("item_disperser",),
    "item_vanguard": ("item_crimson_guard",),
    "item_basher": ("item_abyssal_blade",),
    "item_kaya": ("item_kaya_and_sange", "item_yasha_and_kaya"),
    "item_urn_of_shadows": ("item_spirit_vessel",),
}


def owns(snap: Snapshot, key: str) -> bool:
    """True if you have the item, an upgrade of it, or (for boots) any boots."""
    if key in BOOTS and key not in TRAVEL and any(snap.has_item(k) for k in BOOTS):
        return True
    return any(snap.has_item(k) for k in (key, *UPGRADES.get(key, ())))


class ItemReady(HeroRule):
    """Says when you can afford the next item on your build list for this hero.

    The build is the first that exists of: "<hero>_pos<N>" for your position,
    "<hero>", the hero's popular items from OpenDota (coach/popularity.py,
    after `py -m coach refresh-items`), "pos<N>", then "default_support" for
    positions 4 and 5 (or, while the position is not known, for heroes that
    are a support and not also a carry by OpenDota's hero roles), otherwise
    "default".
    """

    name = "item_ready"

    def __init__(
        self,
        builds: dict[str, list[ItemInfo]],
        heroes: HeroIndex | None = None,
        position: PositionOf | None = None,
        popular: dict[str, list[ItemInfo]] | None = None,
    ) -> None:
        super().__init__(0)
        self.builds = builds
        if popular is None:
            from ..popularity import popular_builds

            popular = popular_builds(load_items())
        self.popular = popular
        self.heroes = heroes
        self.position = position
        self._announced: set[str] = set()

    def is_support(self, hero: str) -> bool:
        info = self.heroes.by_key(hero) if self.heroes else None
        return info is not None and "Support" in info.roles and "Carry" not in info.roles

    def build_for(self, hero: str, position: int = 0) -> list[ItemInfo]:
        for key in (f"{hero}_pos{position}", hero, f"pos{position}"):
            if key in self.builds:
                return self.builds[key]
            if key == hero and hero in self.popular:
                return self.popular[hero]
        support = position in (4, 5) if position else self.is_support(hero)
        if "default_support" in self.builds and support:
            return self.builds["default_support"]
        return self.builds.get("default", [])

    def next_item(self, snap: Snapshot) -> ItemInfo | None:
        hero = (snap.hero_name or "").removeprefix("npc_dota_hero_")
        build = self.build_for(hero, self.position(snap) if self.position else 0)
        return next((i for i in build if not owns(snap, i.key)), None)

    def evaluate(self, snap: Snapshot) -> str | None:
        target = self.next_item(snap)
        if target is None or target.key in self._announced or snap.gold < target.cost:
            return None
        self._announced.add(target.key)
        return f"You have gold for {target.name}."

    def reset(self) -> None:
        super().reset()
        self._announced.clear()


# Cheap items that help any hero, by primary attribute ("stats" in the config).
STAT_ITEMS = {"str": "item_bracer", "agi": "item_wraith_band", "int": "item_null_talisman"}


class WorthBuying(ItemReady):
    """Suggests a cheap item while you save up for a big one.

    Said when the next item on your build is still at least "far" gold away
    and you can afford one of "items" you don't own yet. Each item is
    suggested at most once a match, and nothing after "until_minute".
    """

    name = "worth_buying"

    def __init__(
        self,
        builds: dict[str, list[ItemInfo]],
        heroes: HeroIndex | None = None,
        items: list[ItemInfo | str] | None = None,
        far: int = 600,
        until_minute: int = 25,
        cooldown: int = 180,
        position: PositionOf | None = None,
    ) -> None:
        super().__init__(builds, heroes, position)
        self.cooldown = cooldown
        self.items = items or []
        self.far = far
        self.until_clock = until_minute * 60
        self._all_items: dict[str, ItemInfo] | None = None

    def candidates(self, hero: str) -> list[ItemInfo]:
        found = []
        for item in self.items:
            if item == "stats":
                info = self.heroes.by_key(hero) if self.heroes else None
                key = STAT_ITEMS.get(info.primary_attr) if info else None
                if key is None:
                    continue
                if self._all_items is None:
                    self._all_items = load_items()
                item = self._all_items[key]
            found.append(item)
        return found

    def evaluate(self, snap: Snapshot) -> str | None:
        if not 0 <= snap.clock_time < self.until_clock:
            return None
        if self._last is not None and snap.clock_time - self._last < self.cooldown:
            return None  # checked here so an item isn't used up while it can't be said
        target = self.next_item(snap)
        if target is None or target.cost - snap.gold < self.far:
            return None
        hero = (snap.hero_name or "").removeprefix("npc_dota_hero_")
        for item in self.candidates(hero):
            if item.key in self._announced or snap.has_item(item.key) or item.cost > snap.gold:
                continue
            self._announced.add(item.key)
            article = "an" if item.name[0] in "AEIOU" else "a"
            return f"Buy {article} {item.name} now, you'll get your {target.name} later."
        return None


class WandCharges(HeroRule):
    """Said once each time you get hurt while holding a charged wand."""

    name = "wand"

    def __init__(self, min_charges: int = 10, below: float = 50, cooldown: int = 30) -> None:
        super().__init__(cooldown)
        self.min_charges = min_charges
        self.below = below
        self._armed = True

    def evaluate(self, snap: Snapshot) -> str | None:
        if not snap.alive or snap.health_percent >= self.below:
            self._armed = True
            return None
        wand = snap.item("item_magic_wand") or snap.item("item_magic_stick")
        if (
            not self._armed
            or wand is None
            or not wand.can_cast
            or (wand.charges or 0) < self.min_charges
        ):
            return None
        self._armed = False
        return f"Use your wand, {wand.charges} charges."

    def reset(self) -> None:
        super().reset()
        self._armed = True


class WardReminder(HeroRule):
    name = "ward"

    def __init__(self, hold_seconds: int = 60, cooldown: int = 90) -> None:
        super().__init__(cooldown)
        self.hold_seconds = hold_seconds
        self._since: int | None = None

    def evaluate(self, snap: Snapshot) -> str | None:
        holding = snap.item("item_ward_observer") or snap.item("item_ward_dispenser")
        if holding is None or not snap.alive:
            self._since = None
            return None
        if self._since is None:
            self._since = snap.clock_time
        if snap.clock_time - self._since >= self.hold_seconds:
            return "Place your observer ward."
        return None

    def reset(self) -> None:
        super().reset()
        self._since = None


RULES = {
    "low_health": LowHealth,
    "buyback": Buyback,
    "skill_point": SkillPoint,
    "wand": WandCharges,
    "ward": WardReminder,
}


def _find(items: dict[str, ItemInfo], name: str, where: str) -> ItemInfo:
    info = lookup(items, name)
    if info is None:
        raise ValueError(f"Unknown item {name!r} in {where}")
    return info


def parse_builds(raw: dict[str, list[str]], items: dict[str, ItemInfo]) -> dict[str, list[ItemInfo]]:
    builds = {}
    for hero, names in raw.items():
        found = []
        for name in names:
            found.append(_find(items, name, f"the build for {hero}"))
        builds[hero.lower()] = found
    return builds


def build(
    settings: dict[str, dict],
    builds: dict[str, list[str]],
    position: PositionOf | None = None,
) -> list[HeroRule]:
    """Make hero rules from the [reminders.*] and [builds] config tables.
    position() gives the player's position, for per-position builds."""
    rules: list[HeroRule] = []
    for name, cls in RULES.items():
        options = dict(settings.get(name, {}))
        if options.pop("enabled", True):
            rules.append(cls(**options))
    item_options = settings.get("item_ready", {})
    if item_options.get("enabled", True) and builds:
        rules.append(ItemReady(parse_builds(builds, load_items()), HeroIndex(), position))
    worth = dict(settings.get("worth_buying", {}))
    if worth.pop("enabled", True) and builds:
        items = load_items()
        names = worth.pop("items", ["Magic Wand", "stats"])
        cheap = [name if name == "stats" else _find(items, name, "worth_buying") for name in names]
        rules.append(WorthBuying(parse_builds(builds, items), HeroIndex(), cheap, position=position, **worth))
    return rules
