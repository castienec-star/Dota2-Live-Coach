"""Public match statistics from OpenDota, cached on disk.

Only two kinds of data are read: aggregate numbers for a hero (how it does
against other heroes and by game length, and the GPM and last hits public
matches reach on it: the same kind of numbers Dota Plus shows) and your own
account's public match history and medal. Other players' profiles are never
looked up.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .benchmarks import Curve, parse_api

log = logging.getLogger(__name__)

API_URL = "https://api.opendota.com/api"
STEAM64_BASE = 76561197960265728
OFFLINE_RETRY = 600  # seconds to stay offline after a failed request


def account_id(raw: str | int | None) -> int | None:
    """The 32-bit account id OpenDota uses, from an account id or 64-bit Steam id."""
    try:
        value = int(raw or 0)
    except (TypeError, ValueError):
        return None
    if value > STEAM64_BASE:
        return value - STEAM64_BASE
    return value or None


class OpenDota:
    def __init__(
        self,
        cache_dir: Path,
        base_url: str = API_URL,
        timeout: float = 5.0,
        max_age_days: float = 7.0,
    ) -> None:
        self.cache_dir = cache_dir
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_age = max_age_days * 86400
        self._offline_until = 0.0

    def get(self, path: str, max_age: float | None = None) -> Any:
        """GET an API path; serves a fresh cache, else the network, else a stale cache."""
        max_age = self.max_age if max_age is None else max_age
        cache = self.cache_dir / (re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_") + ".json")
        cached = None
        if cache.is_file():
            try:
                cached = json.loads(cache.read_text(encoding="utf-8"))
            except ValueError:
                cached = None
            if cached is not None and time.time() - cache.stat().st_mtime < max_age:
                return cached
        # After a failure, skip the network for a while so a briefing isn't held up.
        if time.monotonic() < self._offline_until:
            return cached
        request = urllib.request.Request(
            self.base_url + path, headers={"User-Agent": "dota2-live-coach"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.load(response)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            self._offline_until = time.monotonic() + OFFLINE_RETRY
            log.warning("OpenDota not reachable (%s); using saved data if any", exc)
            return cached
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data), encoding="utf-8")
        return data

    def matchups(self, hero_id: int) -> dict[int, tuple[int, int]]:
        """{other hero id: (games, wins)} for hero_id against each other hero."""
        rows = self.get(f"/heroes/{hero_id}/matchups") or []
        return {
            int(r["hero_id"]): (int(r["games_played"]), int(r["wins"]))
            for r in rows
            if isinstance(r, dict) and "hero_id" in r
        }

    def durations(self, hero_id: int) -> dict[int, tuple[int, int]]:
        """{game length in whole minutes: (games, wins)} for hero_id, in 5-minute bins."""
        rows = self.get(f"/heroes/{hero_id}/durations") or []
        return {
            int(r["duration_bin"]) // 60: (int(r["games_played"]), int(r["wins"]))
            for r in rows
            if isinstance(r, dict) and "duration_bin" in r
        }

    def benchmarks(self, hero_id: int) -> dict[str, Curve] | None:
        """Public per-hero percentiles of GPM, XPM and last hits per minute."""
        return parse_api(self.get(f"/benchmarks?hero_id={hero_id}", max_age=30 * 86400))

    def player_rank(self, account: int) -> int | None:
        """Your own medal as Dota's rank tier (43 = Archon 3), from your public
        profile; None when it is hidden or you aren't ranked yet."""
        profile = self.get(f"/players/{account}", max_age=86400) or {}
        tier = profile.get("rank_tier") if isinstance(profile, dict) else None
        return int(tier) if isinstance(tier, int) and tier > 0 else None

    def player_heroes(self, account: int) -> dict[int, tuple[int, int]]:
        """{hero id: (games, wins)} from your own public match history."""
        rows = self.get(f"/players/{account}/heroes", max_age=86400) or []
        return {
            int(r["hero_id"]): (int(r["games"]), int(r["win"]))
            for r in rows
            if isinstance(r, dict) and "hero_id" in r
        }
