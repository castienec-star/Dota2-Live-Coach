"""Day/night and Roshan basics, from the game clock and `daytime` only.

Newer players miss that night shortens everyone's vision, and that a won
fight is the moment to take Roshan. The coach says so a few times early on
and then trusts the player to know.
"""

from __future__ import annotations

from ..state import MatchState
from .timers import MAX_TICK

NIGHT = "Night has started: vision is shorter, so stay near your team and ward the paths you use."
ROSHAN = "From now on, when your team wins a fight, think Roshan: the Aegis is worth more than one more kill."


class NightStart:
    """Says when night starts, for the first few nights of a match."""

    name = "night"

    def __init__(self, nights: int = 3) -> None:
        self.nights = nights
        self._said = 0

    def check(self, state: MatchState) -> list[str]:
        before, now = state.previous, state.current
        # Night Stalker's ultimate also turns the day to night; that is not
        # the cycle, so it says nothing.
        if self._said >= self.nights or now.nightstalker_night:
            return []
        if before.daytime is True and now.daytime is False:
            self._said += 1
            return [NIGHT]
        return []

    def reset(self) -> None:
        self._said = 0


class RoshanReminder:
    """One reminder, at a set minute, that a won fight should become Roshan."""

    name = "roshan"

    def __init__(self, minute: int = 20) -> None:
        self.at = minute * 60
        self._said = False

    def check(self, state: MatchState) -> list[str]:
        before, now = state.previous.clock_time, state.current.clock_time
        if self._said or before is None or now is None or not 0 < now - before <= MAX_TICK:
            return []
        if before < self.at <= now:
            self._said = True
            return [ROSHAN]
        return []

    def reset(self) -> None:
        self._said = False


def build(settings: dict) -> list[NightStart | RoshanReminder]:
    rules: list[NightStart | RoshanReminder] = []
    night = dict(settings.get("night", {}))
    if night.pop("enabled", True):
        rules.append(NightStart(**night))
    roshan = dict(settings.get("roshan", {}))
    if roshan.pop("enabled", True):
        rules.append(RoshanReminder(**roshan))
    return rules
