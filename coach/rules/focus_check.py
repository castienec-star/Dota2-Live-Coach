"""Says, unasked, what to focus on once the laning phase is over.

Around 10 minutes beginners keep standing in lane when they should start
farming jungle camps between waves and grouping for objectives
(docs/strategy/fundamentals.md). This is the answer to "hey coach, what
should I focus on now?" (see BuiltinTips.focus in death_tip.py), said once.
The stat lines (low last hits and the like) are left to the asked question
and the other reminders, so it is the mid-game line for the player's role.
"""

from __future__ import annotations

from collections.abc import Callable

from ..game_questions import Notes
from ..state import MatchState
from . import PositionOf
from .death_tip import BuiltinTips


class FocusCheck:
    """Speaks once at "at" seconds of game time, while alive. Missed by more
    than "late" seconds (the coach was started later), it is skipped."""

    name = "focus_check"

    def __init__(
        self,
        at: int = 630,
        late: int = 60,
        position: PositionOf | None = None,
        notes: Callable[[], Notes | None] | None = None,
    ) -> None:
        self.at = int(at)
        self.late = int(late)
        self.tips = BuiltinTips(notes, position)
        self._done = False

    def check(self, state: MatchState) -> list[str]:
        snap = state.current
        now = snap.clock_time
        if self._done or now is None or now < self.at:
            return []
        if now >= self.at + self.late:
            self._done = True
            return []
        # Dead: the death tip is talking. Low on health: the low-health
        # reminder is. Try again in a moment.
        if not snap.alive or snap.hero_name is None or (snap.max_health and snap.health_percent < 30):
            return []
        self._done = True
        return [f"The laning phase is over. Your focus now: {self.tips.stage_line(snap)}"]

    def reset(self) -> None:
        self._done = False


def build(
    settings: dict[str, dict],
    position: PositionOf | None = None,
    notes: Callable[[], Notes | None] | None = None,
) -> list[FocusCheck]:
    options = dict(settings.get("focus_check", {}))
    if not options.pop("enabled", True):
        return []
    return [FocusCheck(position=position, notes=notes, **options)]
