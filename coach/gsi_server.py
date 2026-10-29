"""Local HTTP listener that receives Dota 2 Game State Integration updates."""

from __future__ import annotations

import hmac
import logging
import time
from collections.abc import Callable
from typing import Any

from aiohttp import web

from .recorder import MatchRecorder
from .state import MatchState, Snapshot

log = logging.getLogger(__name__)

Listener = Callable[[MatchState], None]


class Coach:
    """Receives each GSI update, keeps match state and hands it to listeners."""

    def __init__(
        self,
        token: str,
        recorder: MatchRecorder | None = None,
        summary_interval: float = 10.0,
    ) -> None:
        self.token = token
        self.recorder = recorder
        self.summary_interval = summary_interval
        self.state = MatchState()
        self.listeners: list[Listener] = []
        self.pregame = None  # the pre-game briefing, which also takes typed picks
        self.questions = None  # the in-match questions, whose answers other advice uses
        self.health = None  # notices when Dota isn't sending updates (coach/health.py)
        self.advice = None  # what to buy now (coach/item_advisor.py)
        self._last_summary = 0.0

    def handle(self, payload: dict[str, Any]) -> Snapshot:
        snap = self.state.update(payload)

        if self.state.new_match:
            log.info("New match %s", snap.match_id)
            if self.recorder is not None:
                path = self.recorder.start(snap.match_id)
                log.info("Recording to %s", path)
        if self.state.game_state_changed and snap.game_state:
            log.info("Game state: %s", snap.game_state)
        if self.recorder is not None:
            self.recorder.write(payload)

        now = time.monotonic()
        if snap.in_game and now - self._last_summary >= self.summary_interval:
            self._last_summary = now
            log.info(snap.summary())

        for listener in self.listeners:
            listener(self.state)
        return snap

    def authorized(self, payload: dict[str, Any]) -> bool:
        sent = (payload.get("auth") or {}).get("token", "")
        return hmac.compare_digest(str(sent), self.token)


async def _receive(request: web.Request) -> web.Response:
    coach: Coach = request.app["coach"]
    try:
        payload = await request.json()
    except ValueError:
        return web.Response(status=400, text="invalid JSON")
    if not isinstance(payload, dict):
        return web.Response(status=400, text="expected a JSON object")
    if not coach.authorized(payload):
        log.warning("Rejected an update with a wrong or missing token")
        if coach.health is not None:
            coach.health.rejected()
        return web.Response(status=401)
    if coach.health is not None:
        coach.health.accepted()
    coach.handle(payload)
    return web.Response(text="ok")


def make_app(coach: Coach) -> web.Application:
    app = web.Application()
    app["coach"] = coach
    app.router.add_post("/", _receive)
    return app
