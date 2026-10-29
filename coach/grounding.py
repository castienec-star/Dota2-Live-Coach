"""Checks a model's line against the facts it was given, before it is spoken.

Small local models happily invent heroes ("watch their Phantom Assassin"),
roles Dota doesn't have ("wait for our jungler") and timings ("push at 20
to 25 minutes"). A line that names a hero not in this match, a number not in
the facts, or talks about a team the coach knows nothing about is dropped,
and the coach uses its written line instead.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .heroes import NICKNAMES, HeroIndex, HeroInfo

# Words that are never right in a Dota briefing or tip.
_NEVER = re.compile(r"\b(junglers?|jungling)\b", re.IGNORECASE)
# Talk about teammates or enemies, when none of them are known.
_ALLY_TALK = re.compile(r"\b(our|teammates?|all(y|ies)|your team'?s?|support player)\b", re.IGNORECASE)
_ENEMY_TALK = re.compile(r"\b(enem(y|ies)|their|opponents?|the other team)\b", re.IGNORECASE)

_UNITS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9,
}
_NUMBER_WORDS = {
    "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "eighteen": 18, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
}
_TENS = {"twenty", "thirty", "forty", "fifty", "sixty"}
_NUMBER = re.compile(
    r"\b(\d+)\b|\b(" + "|".join(_NUMBER_WORDS) + r")(?:[- ](" + "|".join(_UNITS) + r"))?\b",
    re.IGNORECASE,
)


def numbers(text: str) -> set[int]:
    """Numbers written as digits, plus "ten", "twenty five" and the like."""
    found = set()
    for digits, word, unit in _NUMBER.findall(text):
        if digits:
            found.add(int(digits))
            continue
        value = _NUMBER_WORDS[word.lower()]
        if unit and word.lower() in _TENS:
            value += _UNITS[unit.lower()]
        found.add(value)
    return found


class Grounding:
    """Finds hero names in text: full names in any case, single-word names
    when capitalised (so "a tiny window" isn't Tiny), and the usual initials
    in capitals ("PA", "CM")."""

    # Initials that mean something else in a Dota sentence.
    NOT_HEROES = {"TP", "VS"}

    def __init__(self, index: HeroIndex | None = None) -> None:
        self.index = index or HeroIndex()
        heroes = self.index.heroes.values()
        by_key = {h.key: h for h in heroes}
        self._patterns: list[tuple[re.Pattern[str], HeroInfo]] = []
        initials: dict[str, set[HeroInfo]] = {}
        for h in heroes:
            if " " in h.name or "-" in h.name:
                name = re.escape(h.name).replace(r"\ ", r"[\s-]+").replace(r"\-", r"[\s-]*")
                self._patterns.append((re.compile(rf"\b{name}\b", re.IGNORECASE), h))
            else:
                self._patterns.append((re.compile(rf"\b{re.escape(h.name)}\b"), h))
            words = re.findall(r"[A-Za-z]+", h.name)
            if len(words) > 1:
                initials.setdefault("".join(w[0] for w in words).upper(), set()).add(h)
        for nick, key in NICKNAMES.items():
            if key in by_key and len(nick) <= 3 and nick.isalpha():
                initials.setdefault(nick.upper(), set()).add(by_key[key])
        # Initials can stand for more than one hero ("ES"): any of them will do.
        self._initials = [
            (re.compile(rf"\b{short}\b"), frozenset(found))
            for short, found in initials.items()
            if short not in self.NOT_HEROES
        ]

    def heroes(self, text: str) -> set[HeroInfo]:
        """Heroes named in full in text."""
        return {h for pattern, h in self._patterns if pattern.search(text)}

    def strangers(self, text: str, allowed: set[HeroInfo]) -> list[str]:
        """Names in text for heroes outside allowed."""
        names = {h.name for h in self.heroes(text) - allowed}
        for pattern, found in self._initials:
            match = pattern.search(text)
            if match and not found & allowed:
                names.add(match.group(0))
        return sorted(names)

    def problem(
        self,
        text: str,
        facts: str,
        heroes: Iterable[HeroInfo | None],
        allies_known: bool = True,
        enemies_known: bool = True,
        check_numbers: bool = True,
    ) -> str | None:
        """Why text can't be spoken, or None when it sticks to the facts.

        heroes are the ones in this match that the coach knows about."""
        allowed = {h for h in heroes if h is not None}
        extra = self.strangers(text, allowed)
        if extra:
            return "names " + ", ".join(extra) + ", not in this match as far as the coach knows"
        never = _NEVER.search(text)
        if never:
            return f'says "{never.group(0)}"'
        if not allies_known and _ALLY_TALK.search(text):
            return f'talks about teammates ("{_ALLY_TALK.search(text).group(0)}") the coach doesn\'t know'
        if not enemies_known and _ENEMY_TALK.search(text):
            return f'talks about enemies ("{_ENEMY_TALK.search(text).group(0)}") the coach doesn\'t know'
        if check_numbers:
            invented = sorted(numbers(text) - numbers(facts))
            if invented:
                return "uses numbers not in the facts: " + ", ".join(map(str, invented))
        return None
