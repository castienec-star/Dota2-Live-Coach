"""A typed view of the latest Game State Integration update for your own hero.

In player mode GSI only describes the local player, so nothing here can hold
information about enemies that the player could not already see.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

IN_PROGRESS = "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"
# Phases a match passes through before the game starts. Entering one of these
# from any other phase means a new match, even when the match id stays the same
# (bot and lobby games all report match id 0).
LOBBY_STATES = {
    "DOTA_GAMERULES_STATE_INIT",
    "DOTA_GAMERULES_STATE_WAIT_FOR_PLAYERS_TO_LOAD",
    "DOTA_GAMERULES_STATE_HERO_SELECTION",
}


@dataclass
class Ability:
    name: str
    level: int
    can_cast: bool
    cooldown: int
    ultimate: bool


@dataclass
class Item:
    slot: str
    name: str
    charges: int | None
    can_cast: bool
    cooldown: int


@dataclass
class Snapshot:
    match_id: str | None = None
    game_state: str | None = None
    clock_time: int | None = None
    daytime: bool | None = None
    paused: bool = False

    gold: int = 0
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    last_hits: int = 0
    denies: int = 0

    hero_name: str | None = None
    level: int = 0
    alive: bool = True
    respawn_seconds: int = 0
    health: int = 0
    max_health: int = 0
    mana: int = 0
    max_mana: int = 0
    buyback_cost: int = 0
    buyback_cooldown: int = 0

    abilities: list[Ability] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)

    @property
    def in_game(self) -> bool:
        return self.game_state == IN_PROGRESS

    @property
    def health_percent(self) -> float:
        return 100.0 * self.health / self.max_health if self.max_health else 0.0

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Snapshot:
        game = payload.get("map") or {}
        player = payload.get("player") or {}
        hero = payload.get("hero") or {}
        return cls(
            match_id=game.get("matchid"),
            game_state=game.get("game_state"),
            clock_time=game.get("clock_time"),
            daytime=game.get("daytime"),
            paused=bool(game.get("paused", False)),
            gold=int(player.get("gold", 0)),
            kills=int(player.get("kills", 0)),
            deaths=int(player.get("deaths", 0)),
            assists=int(player.get("assists", 0)),
            last_hits=int(player.get("last_hits", 0)),
            denies=int(player.get("denies", 0)),
            hero_name=hero.get("name"),
            level=int(hero.get("level", 0)),
            alive=bool(hero.get("alive", True)),
            respawn_seconds=int(hero.get("respawn_seconds", 0)),
            health=int(hero.get("health", 0)),
            max_health=int(hero.get("max_health", 0)),
            mana=int(hero.get("mana", 0)),
            max_mana=int(hero.get("max_mana", 0)),
            buyback_cost=int(hero.get("buyback_cost", 0)),
            buyback_cooldown=int(hero.get("buyback_cooldown", 0)),
            abilities=_abilities(payload.get("abilities") or {}),
            items=_items(payload.get("items") or {}),
        )

    def summary(self) -> str:
        clock = "--:--" if self.clock_time is None else _clock(self.clock_time)
        hero = (self.hero_name or "no hero").removeprefix("npc_dota_hero_")
        status = "alive" if self.alive else f"dead {self.respawn_seconds}s"
        return (
            f"[{clock}] {hero} lvl {self.level} {status} "
            f"hp {self.health_percent:.0f}% gold {self.gold} "
            f"k/d/a {self.kills}/{self.deaths}/{self.assists} lh {self.last_hits}"
        )


def _clock(seconds: int) -> str:
    sign = "-" if seconds < 0 else ""
    minutes, secs = divmod(abs(seconds), 60)
    return f"{sign}{minutes:02d}:{secs:02d}"


def _abilities(raw: dict[str, Any]) -> list[Ability]:
    abilities = []
    for key in sorted(raw, key=_slot_index):
        a = raw[key]
        # Attribute bonus and empty slots report as abilities too; keep real ones.
        if not isinstance(a, dict) or not a.get("name"):
            continue
        abilities.append(
            Ability(
                name=a["name"],
                level=int(a.get("level", 0)),
                can_cast=bool(a.get("can_cast", False)),
                cooldown=int(a.get("cooldown", 0)),
                ultimate=bool(a.get("ultimate", False)),
            )
        )
    return abilities


def _items(raw: dict[str, Any]) -> list[Item]:
    items = []
    for slot, i in raw.items():
        if not isinstance(i, dict) or i.get("name", "empty") == "empty":
            continue
        items.append(
            Item(
                slot=slot,
                name=i["name"],
                charges=int(i["charges"]) if "charges" in i else None,
                can_cast=bool(i.get("can_cast", False)),
                cooldown=int(i.get("cooldown", 0)),
            )
        )
    return items


def _slot_index(key: str) -> int:
    digits = "".join(ch for ch in key if ch.isdigit())
    return int(digits) if digits else 0


class MatchState:
    """Holds the latest snapshot and notices when a new match starts."""

    def __init__(self) -> None:
        self.current = Snapshot()
        self.previous = Snapshot()

    def update(self, payload: dict[str, Any]) -> Snapshot:
        self.previous, self.current = self.current, Snapshot.from_payload(payload)
        return self.current

    @property
    def new_match(self) -> bool:
        cur, prev = self.current, self.previous
        if cur.match_id is None:
            return False
        if cur.match_id != prev.match_id:
            return True
        return cur.game_state in LOBBY_STATES and prev.game_state not in LOBBY_STATES

    @property
    def game_state_changed(self) -> bool:
        return self.current.game_state != self.previous.game_state
