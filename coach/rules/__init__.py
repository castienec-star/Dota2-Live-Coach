"""Coaching rules: each one looks at the match state and may return a line to say."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from ..speaker import HIGH, NORMAL, URGENT
from ..state import MatchState, Snapshot

log = logging.getLogger(__name__)

# The player's position, 1 (safe lane carry) to 5 (hard support); 0 = not known.
PositionOf = Callable[[Snapshot], int]


class Rule(Protocol):
    def check(self, state: MatchState) -> list[str]: ...

    def reset(self) -> None: ...


# How important each rule's lines are (see coach/speaker.py); others are NORMAL.
PRIORITY = {
    "low_health": URGENT,
    "buyback": URGENT,
    "wand": URGENT,
    "power_rune": HIGH,
    "bounty_rune": HIGH,
    "wisdom_shrine": HIGH,
    "water_rune": HIGH,
    "stack": HIGH,
}


class Engine:
    """Runs every rule on each update and passes what they say to the speaker.

    When more than max_lines rules speak at the same update, only the most
    important ones are said: a coach that chatters gets turned off. With
    prioritized, say is called as say(text, priority), as Speaker.say takes it.
    """

    def __init__(
        self,
        rules: list[Rule],
        say: Callable[..., None],
        max_lines: int = 2,
        prioritized: bool = False,
    ) -> None:
        self.rules = rules
        self.say = say
        self.max_lines = max_lines
        self.prioritized = prioritized

    def __call__(self, state: MatchState) -> None:
        if state.new_match:
            for rule in self.rules:
                rule.reset()
        if not state.current.in_game or state.current.paused:
            return
        found = [
            (PRIORITY.get(getattr(rule, "name", ""), NORMAL), line)
            for rule in self.rules
            for line in rule.check(state)
        ]
        if not found:
            return
        # Most important first; equal ones keep the rules' order.
        found.sort(key=lambda p: -p[0])
        kept, dropped = found[: self.max_lines], found[self.max_lines :]
        for _, line in dropped:
            log.info("Dropped so as not to talk too much: %s", line)
        # Reminders due at the same second become one spoken line.
        text = " ".join(line for _, line in kept)
        if self.prioritized:
            self.say(text, kept[0][0])
        else:
            self.say(text)


class ForPositions:
    """Runs a rule only for some positions ("positions = [2]" in a reminder's
    table). While the position is not known, the rule always runs."""

    def __init__(self, rule: Rule, positions: set[int], position: PositionOf) -> None:
        self.rule = rule
        self.name = getattr(rule, "name", "")
        self.positions = positions
        self.position = position

    def check(self, state: MatchState) -> list[str]:
        position = self.position(state.current)
        if position and position not in self.positions:
            return []
        return self.rule.check(state)

    def reset(self) -> None:
        self.rule.reset()


def split_positions(settings: dict[str, dict]) -> tuple[dict[str, dict], dict[str, set[int]]]:
    """Takes "positions" out of each [reminders.*] table: the rules don't know
    it, ForPositions does."""
    stripped, positions = {}, {}
    for name, options in settings.items():
        if isinstance(options, dict) and "positions" in options:
            options = dict(options)
            positions[name] = {int(p) for p in options.pop("positions")}
        stripped[name] = options
    return stripped, positions


def for_positions(rules: list[Rule], positions: dict[str, set[int]], position: PositionOf) -> list[Rule]:
    return [
        ForPositions(rule, positions[name], position)
        if (name := getattr(rule, "name", "")) in positions
        else rule
        for rule in rules
    ]
