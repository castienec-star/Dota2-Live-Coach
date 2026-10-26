"""Feeds a recorded match back through the coach, for testing without Dota."""

from __future__ import annotations

import time
from pathlib import Path

from .gsi_server import Coach
from .recorder import read_recording


def replay(coach: Coach, path: Path, speed: float = 0.0) -> int:
    """Replay a recording. speed=1.0 keeps real timing, 0 runs as fast as possible."""
    count = 0
    last_t: float | None = None
    for t, payload in read_recording(path):
        if speed > 0 and last_t is not None:
            time.sleep(max(0.0, (t - last_t) / speed))
        last_t = t
        coach.handle(payload)
        count += 1
    return count
