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

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .opendota import account_id

TEAMS = {"team2": "radiant", "team3": "dire"}

# A spectator update older than this no longer counts. Dota sends updates
# many times a second while a replay plays, and a heartbeat every 30 s while
# it is paused (install.py), so a paused replay keeps the gate open.
FRESH_SECONDS = 35.0


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


# The blocks GSI keys by team and player slot while you spectate.
PER_PLAYER = ("player", "hero", "abilities", "items", "wearables")


def find_slot(payload: dict[str, Any], accounts: set[int], hero: str | None = None) -> tuple[str, str] | None:
    """(team key, slot) of the player's own hero in a replay: the hero they
    picked in the replay window, else the one played from their Steam
    account. None while neither is in this update."""
    if not is_spectating(payload):
        return None
    players = payload.get("player") or {}
    heroes = payload.get("hero") or {}
    for team_key in TEAMS:
        for slot, p in (players.get(team_key) or {}).items():
            h = (heroes.get(team_key) or {}).get(slot) or {}
            if hero:
                if h.get("name") == hero:
                    return team_key, slot
            elif isinstance(p, dict) and (
                account_id(p.get("accountid")) in accounts or account_id(p.get("steamid")) in accounts
            ):
                return team_key, slot
    return None


def own_payload(payload: dict[str, Any], where: tuple[str, str]) -> dict[str, Any]:
    """The replay update cut down to what your own game sent you: your hero
    only, in the same shape as a live match. The other nine heroes are
    dropped, so the coach knows no more than you did while playing."""
    team_key, slot = where
    out = {k: v for k, v in payload.items() if k not in PER_PLAYER and k not in ("minimap", "allplayers")}
    for key in PER_PLAYER:
        block = payload.get(key)
        if isinstance(block, dict):
            mine = (block.get(team_key) or {}).get(slot)
            if isinstance(mine, dict):
                out[key] = dict(mine)
    player = out.get("player")
    if isinstance(player, dict):
        player.setdefault("team_name", TEAMS[team_key])
    return out


def known_accounts(record_dir: Path, files: int = 10, lines: int = 400) -> set[int]:
    """Steam accounts seen in your own recorded matches: your own account,
    since live GSI only ever describes you."""
    found: set[int] = set()
    try:
        paths = sorted(record_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:files]
    except OSError:
        return found
    for path in paths:
        try:
            with path.open(encoding="utf-8") as f:
                for _, line in zip(range(lines), f):
                    try:
                        player = (json.loads(line).get("payload") or {}).get("player") or {}
                    except (ValueError, AttributeError):
                        continue
                    if not isinstance(player, dict) or any(k in player for k in TEAMS):
                        continue
                    acc = account_id(player.get("accountid")) or account_id(player.get("steamid"))
                    if acc:
                        found.add(acc)
                        break
        except OSError:
            continue
    return found


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
