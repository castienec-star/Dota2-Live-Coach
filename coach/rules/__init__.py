"""Coaching rules: each one looks at the match state and may return a line to say."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from ..state import MatchState, Snapshot

# The player's position, 1 (safe lane carry) to 5 (hard support); 0 = not known.
PositionOf = Callable[[Snapshot], int]


class Rule(Protocol):
    def check(self, state: MatchState) -> list[str]: ...

    def reset(self) -> None: ...


class Engine:
    """Runs every rule on each update and passes what they say to the speaker."""

    def __init__(self, rules: list[Rule], say: Callable[[str], None]) -> None:
        self.rules = rules
        self.say = say

    def __call__(self, state: MatchState) -> None:
        if state.new_match:
            for rule in self.rules:
                rule.reset()
        if not state.current.in_game or state.current.paused:
            return
        lines = [line for rule in self.rules for line in rule.check(state)]
        if lines:
            # Reminders due at the same second become one spoken line.
            self.say(" ".join(lines))


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
