"""Notices when Dota isn't sending game state, and says what to check.

"It does nothing" is the most common setup problem: the GSI config file is
missing or out of date, the -gamestateintegration launch option isn't set, or
Dota was already running when the file was written. Dota sends an update at
least every 30 seconds (the "heartbeat" in the config file) while it runs, so
a minute of silence means something is wrong.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path

from aiohttp import web

from .config import Config
from .install import CFG_NAME, GSI_SUBDIR, find_dota, render_cfg

log = logging.getLogger(__name__)


def cfg_problem(config: Config, dota: Path | None) -> str | None:
    """What is wrong with Dota's GSI config file for the coach, or None."""
    if dota is None:
        return "Could not find Dota 2 through Steam, so the config file could not be checked."
    target = dota / GSI_SUBDIR / CFG_NAME
    if not target.is_file():
        return f"The config file is missing: {target}"
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        return f"Could not read {target} ({exc})"
    if text != render_cfg(config):
        return f"The config file is out of date (another port or token): {target}"
    return None


class Health:
    """Tracks GSI updates; check() returns a line to say when something is wrong."""

    def __init__(
        self,
        config: Config,
        wait: float = 60,
        clock: Callable[[], float] = time.monotonic,
        dota: Callable[[], Path | None] = find_dota,
    ) -> None:
        self.config = config
        self.wait = wait
        self.clock = clock
        self.dota = dota
        self._since = clock()
        self._connected = False
        self._rejected = 0
        self._warned = False

    def accepted(self) -> None:
        """Dota sent an update with the right token."""
        self._connected = True

    def rejected(self) -> None:
        """Dota (or something else) sent an update with a wrong token."""
        self._rejected += 1

    def check(self) -> str | None:
        """A line to say: once if Dota stays silent, once when it connects after that."""
        if self._connected:
            if self._warned:
                self._warned = False
                log.info("Dota 2 is connected now")
                return "Dota is connected. Good luck!"
            return None
        if self._warned or self.clock() - self._since < self.wait:
            return None
        self._warned = True
        if self._rejected:
            log.warning(
                "Dota sends game state with an old token. Run  py -m coach install  again, "
                "then restart Dota 2."
            )
            return "Dota sends game data with an old setup. Run coach install again, then restart Dota."
        problem = cfg_problem(self.config, self.dota())
        steps = [
            "No game state from Dota 2 yet. Check:",
            f"  - The config file: {problem or 'OK'}" + ("  ->  run  py -m coach install" if problem else ""),
            "  - Steam > Dota 2 > Properties > Launch Options has  -gamestateintegration",
            "  - Dota 2 was started (or restarted) after  py -m coach install",
            f"  - Nothing else uses port {self.config.port}, and the firewall allows local connections",
        ]
        log.warning("\n".join(steps))
        return "I haven't heard from Dota yet. Check the coach window for what to fix."


def watch(app: web.Application, health: Health, say: Callable[[str], None], every: float = 5) -> None:
    """Run health.check() every few seconds while the server runs."""

    def check() -> None:
        line = health.check()
        if line:
            say(line)

    repeat(app, every, check)


def repeat(app: web.Application, seconds: float, job: Callable[[], None]) -> None:
    """Run job() every few seconds while the server runs."""

    async def loop() -> None:
        while True:
            await asyncio.sleep(seconds)
            job()

    tasks: list[asyncio.Task] = []

    async def start(app: web.Application) -> None:
        tasks.append(asyncio.create_task(loop()))

    async def stop(app: web.Application) -> None:
        for task in tasks:
            task.cancel()

    app.on_startup.append(start)
    app.on_cleanup.append(stop)
