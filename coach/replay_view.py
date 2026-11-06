"""What Game State Integration sends while you watch a replay, and when the
coach may look at the screen.

In your own match GSI only describes your hero (see ``state.py``). While you
spectate, which includes watching a replay, Dota sends the same blocks keyed
by team and player slot instead: ``player.team2.player0`` and so on, for all
ten heroes. That shape is the signal this module uses.

Fair play: screen capture is only allowed while the latest GSI update is a
spectator update and arrived recently. One update from your own match closes
the gate at once, and it stays closed until spectator updates come back.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

TEAMS = {"team2": "radiant", "team3": "dire"}

# A spectator update older than this no longer counts: Dota sends a heartbeat
# at least every 30 s, and far more often while a replay plays.
FRESH_SECONDS = 10.0


def is_spectating(payload: dict[str, Any]) -> bool:
    """True when the update describes every player, as in a replay."""
    player = payload.get("player")
    return isinstance(player, dict) and any(k in player for k in TEAMS)


def is_own_match(payload: dict[str, Any]) -> bool:
    """True when the update describes the local player's own hero."""
    player = payload.get("player")
    if not isinstance(player, dict) or is_spectating(payload):
        return False
    return bool(player.get("steamid") or player.get("accountid") or payload.get("hero"))


@dataclass
class HeroView:
    slot: str  # "player0".."player9"
    team: str  # "radiant" or "dire"
    name: str | None = None  # Steam name of the player
    hero_name: str | None = None
    x: float | None = None
    y: float | None = None
    alive: bool = True
    level: int = 0
    health: int = 0
    max_health: int = 0
    mana: int = 0
    max_mana: int = 0
    gold: int = 0
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    last_hits: int = 0
    items: list[str] = field(default_factory=list)

    @property
    def health_percent(self) -> float:
        return 100.0 * self.health / self.max_health if self.max_health else 0.0


@dataclass
class ReplayView:
    match_id: str | None = None
    clock_time: int | None = None
    paused: bool = False
    heroes: list[HeroView] = field(default_factory=list)

    def team(self, team: str) -> list[HeroView]:
        return [h for h in self.heroes if h.team == team]

    def hero(self, hero_name: str) -> HeroView | None:
        return next((h for h in self.heroes if h.hero_name == hero_name), None)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ReplayView | None:
        if not is_spectating(payload):
            return None
        game = payload.get("map") or {}
        players = payload.get("player") or {}
        heroes_raw = payload.get("hero") or {}
        items_raw = payload.get("items") or {}
        heroes = []
        for team_key, team in TEAMS.items():
            for slot, p in sorted((players.get(team_key) or {}).items(), key=lambda kv: _slot_index(kv[0])):
                if not isinstance(p, dict):
                    continue
                h = (heroes_raw.get(team_key) or {}).get(slot) or {}
                inv = (items_raw.get(team_key) or {}).get(slot) or {}
                heroes.append(HeroView(
                    slot=slot,
                    team=p.get("team_name") or team,
                    name=p.get("name"),
                    hero_name=h.get("name"),
                    x=h.get("xpos"),
                    y=h.get("ypos"),
                    alive=bool(h.get("alive", True)),
                    level=int(h.get("level", 0)),
                    health=int(h.get("health", 0)),
                    max_health=int(h.get("max_health", 0)),
                    mana=int(h.get("mana", 0)),
                    max_mana=int(h.get("max_mana", 0)),
                    gold=int(p.get("gold", 0)),
                    kills=int(p.get("kills", 0)),
                    deaths=int(p.get("deaths", 0)),
                    assists=int(p.get("assists", 0)),
                    last_hits=int(p.get("last_hits", 0)),
                    items=[
                        i["name"] for s, i in sorted(inv.items())
                        if s.startswith("slot") and isinstance(i, dict) and i.get("name", "empty") != "empty"
                    ],
                ))
        return cls(
            match_id=game.get("matchid"),
            clock_time=game.get("clock_time"),
            paused=bool(game.get("paused", False)),
            heroes=heroes,
        )


class ScreenGate:
    """Decides whether the coach may capture the screen right now.

    Feed it every GSI update. It opens only on fresh spectator updates and
    shuts on the first update from your own match.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic, fresh_seconds: float = FRESH_SECONDS) -> None:
        self._clock = clock
        self._fresh = fresh_seconds
        self._last_spectator: float | None = None

    def see(self, payload: dict[str, Any]) -> None:
        if is_spectating(payload):
            self._last_spectator = self._clock()
        elif is_own_match(payload):
            self._last_spectator = None

    @property
    def open(self) -> bool:
        if self._last_spectator is None:
            return False
        return self._clock() - self._last_spectator <= self._fresh


def _slot_index(key: str) -> int:
    digits = "".join(ch for ch in key if ch.isdigit())
    return int(digits) if digits else 0
