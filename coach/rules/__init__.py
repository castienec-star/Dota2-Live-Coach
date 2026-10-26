"""Coaching rules: each one looks at the match state and may return a line to say."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from ..state import MatchState


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
