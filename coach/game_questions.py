"""Short questions during the match about what GSI can't see.

GSI only describes your own hero, so the coach can't tell how your lane
went, which enemy keeps killing you or whether your team wins fights. Now
and then it simply asks, at a calm moment: while you wait to respawn, or
when your hero is healthy and hasn't been hit for a while. Never in a fight,
at most one question every few minutes, each question once a match. If you
don't answer, it drops the question. Answers only last for the match, and
"what should I buy?", the 15/25 minute check and death tips use them. See
docs/strategy/game-state-questions.md.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from .heroes import HeroIndex, HeroInfo
from .items import ItemInfo
from .lineup import _SKIP, Question, _words, parse_heroes
from .state import MatchState

# Lane and fight answers, checked in this order ("not bad" is even, not lost).
_EVEN = re.compile(r"\b(even|equal|okay|ok|fine|alright|all right|so so|not bad|same|close|draw)\b")
_LOST = re.compile(r"\b(lost|lose|losing|bad|badly|behind|terrible|awful|hard|rough|died|dying|feeding)\b")
_WON = re.compile(r"\b(won|win|winning|good|great|well|ahead|easy|crushed|crushing)\b")
_YES = re.compile(r"\b(yes|yeah|yep|yup|sure|definitely|totally|he is|she is|they are|a lot|free)\b")
_NO = re.compile(r"\b(no|nope|nah|not)\b")


def parse_result(text: str) -> str | None:
    """"won", "even" or "lost" from a short spoken answer."""
    words = _words(text)
    for result, pattern in (("even", _EVEN), ("lost", _LOST), ("won", _WON)):
        if pattern.search(words):
            return result
    return None


def parse_yes_no(text: str) -> bool | None:
    words = _words(text)
    if _NO.search(words):  # "not really", "no he isn't"
        return False
    return True if _YES.search(words) else None


@dataclass
class Notes:
    """What the player told the coach this match (None = not asked or no answer)."""

    lane: str | None = None  # "won", "even" or "lost"
    trouble: HeroInfo | None = None  # the enemy giving them the most trouble
    carry_free: bool | None = None  # is the enemy carry farming freely?
    fights: str | None = None  # "won", "even" or "lost": team fights so far
    # Enemy items the player said they saw (coach/enemy_items.py).
    enemy_items: dict[HeroInfo, tuple[ItemInfo, ...]] = field(default_factory=dict)

    def told(self) -> list[str]:
        """The answers as short phrases, for the death tip prompt."""
        lines = []
        if self.lane is not None:
            lines.append(f"their lane was {self.lane}")
        if self.trouble is not None:
            lines.append(f"{self.trouble.name} gives them the most trouble")
        if self.carry_free is not None:
            lines.append(f"the enemy carry is {'' if self.carry_free else 'not '}farming freely")
        if self.fights is not None:
            fights = {"won": "winning", "even": "about even", "lost": "losing"}[self.fights]
            lines.append(f"their team is {fights} in fights")
        for hero, items in self.enemy_items.items():
            lines.append(f"{hero.name} has {' and '.join(i.name for i in items)}")
        return lines


@dataclass(frozen=True)
class _Ask:
    key: str
    text: str
    after: int  # game-clock seconds
    until: int | None = None  # too late to ask after this


ITEMS_CHECK = "Check the enemy items, then tell me what you see."

ASKS = (
    _Ask("lane", "How did your lane go: won, even or lost?", 600, until=1080),
    _Ask("trouble", "Which enemy hero is giving you the most trouble?", 720),
    _Ask("carry_free", "Is their carry farming freely?", 900),
    _Ask("fights", "Is your team ahead or behind in fights?", 1200),
)


class GameQuestions:
    """Asks the questions in ASKS through the voice loop, at calm moments.

    Add it as a GSI listener and pass pending to the voice loop. Calm means
    dead with at least min_respawn seconds to wait, or alive with at least
    healthy % health and no damage taken for quiet seconds. every is the
    shortest game-clock gap between two questions.
    """

    def __init__(
        self,
        index: HeroIndex,
        enemies: Callable[[], list[HeroInfo]] | None = None,
        every: int = 300,
        min_respawn: int = 10,
        healthy: float = 80,
        quiet: int = 10,
        check_items: Callable[[str], str | None] | None = None,
        item_checks: tuple[int, ...] = (720, 1200, 1800),
        item_check_every: int = 600,
    ) -> None:
        self.index = index
        # Asked again and again, unlike ASKS: enemy items change all game.
        self.check_items = check_items
        self.item_checks = item_checks
        self.item_check_every = item_check_every
        self._item_check = 0  # index of the next check time
        self.enemies = enemies or list
        self.every = every
        self.min_respawn = min_respawn
        self.healthy = healthy
        self.quiet = quiet
        self.notes = Notes()
        self._lock = threading.Lock()
        self._asked: set[str] = set()
        self._last_asked: int | None = None
        self._last_hurt: int | None = None
        self._now = 0
        self._ready: Question | None = None

    def __call__(self, state: MatchState) -> None:
        cur, prev = state.current, state.previous
        with self._lock:
            if state.new_match:
                self.notes = Notes()
                self._asked.clear()
                self._last_asked = self._last_hurt = None
                self._item_check = 0
            if not cur.in_game or cur.paused or cur.clock_time is None:
                self._ready = None
                return
            self._now = cur.clock_time
            if cur.alive and prev.alive and cur.health < prev.health:
                self._last_hurt = self._now
            self._ready = self._due() if self._calm(state) else None

    def _calm(self, state: MatchState) -> bool:
        cur = state.current
        if not cur.alive:
            return cur.respawn_seconds >= self.min_respawn
        hurt = self._last_hurt is not None and self._now - self._last_hurt < self.quiet
        return cur.health_percent >= self.healthy and not hurt

    def _due(self) -> Question | None:
        if self._last_asked is not None and self._now - self._last_asked < self.every:
            return None
        for ask in ASKS:
            if ask.key in self._asked or self._now < ask.after:
                continue
            if ask.until is not None and self._now > ask.until:
                continue
            return Question(ask.text, lambda text, key=ask.key: self._answer(key, text))
        if self.check_items is not None and self.item_checks and self._now >= self._check_time(self._item_check):
            return Question(ITEMS_CHECK, self._answer_items)
        return None

    def _check_time(self, n: int) -> int:
        """When the n-th enemy items check is due (game clock)."""
        if n < len(self.item_checks):
            return self.item_checks[n]
        return self.item_checks[-1] + (n - len(self.item_checks) + 1) * self.item_check_every

    def _answer_items(self, text: str) -> str | None:
        with self._lock:
            self._last_asked = self._now
            self._ready = None
            # Skip the checks missed while busy: one question, not a backlog.
            while self._check_time(self._item_check) <= self._now:
                self._item_check += 1
        if not text or _SKIP.search(_words(text)):
            return None
        return self.check_items(text)

    def pending(self) -> Question | None:
        """The question to ask now, if any; the voice loop calls this when it is free."""
        with self._lock:
            return self._ready

    def _answer(self, key: str, text: str) -> str | None:
        with self._lock:
            # Asked once a match, answered or not, and the wait starts now.
            self._asked.add(key)
            self._last_asked = self._now
            self._ready = None
        if not text or _SKIP.search(_words(text)):
            return None
        return getattr(self, f"_{key}")(text)

    def _lane(self, text: str) -> str | None:
        result = parse_result(text)
        self.notes.lane = result
        if result == "lost":
            return "Okay, it happens. Farm the safe camps near your towers and catch up; the game is long."
        if result == "won":
            return "Nice. Use the lead: push a tower or help another lane."
        if result == "even":
            return "Okay. Keep last hitting and watch the minimap."
        return None

    def _trouble(self, text: str) -> str | None:
        heroes = parse_heroes(self.index, text)
        enemies = self.enemies()
        # Only a hero the player named as an enemy, so a misheard ally isn't
        # countered; any hero while no enemies are known.
        if enemies:
            hero = next((h for h in heroes if h in enemies), None)
        else:
            hero = heroes[0] if heroes else None
        if hero is None:
            return None
        self.notes.trouble = hero
        return f"Got it, {hero.name}. Check where {hero.name} is on the map before you fight, and don't fight them alone."

    def _carry_free(self, text: str) -> str | None:
        free = parse_yes_no(text)
        self.notes.carry_free = free
        if free:
            return "Then group up with your team and go find their carry, or they will win the late game."
        if free is False:
            return "Good. Keep putting pressure on them."
        return None

    def _fights(self, text: str) -> str | None:
        result = parse_result(text)
        self.notes.fights = result
        if result == "lost":
            return "Then stay together, don't fight in the open and farm until your big item is ready."
        if result == "won":
            return "Then after each won fight take a tower or Roshan; don't just go back to farming."
        if result == "even":
            return "Okay. Fight when your key spells and items are ready, and together."
        return None


def build(
    settings: dict,
    index: HeroIndex,
    enemies: Callable[[], list[HeroInfo]] | None = None,
    check_items: Callable[[str], str | None] | None = None,
) -> GameQuestions | None:
    """From [listen]: game_questions turns them on, question_every is the gap,
    enemy_items_check / _at / _every the checks of enemy items (check_items
    takes the answer)."""
    if not settings.get("game_questions", True):
        return None
    if not settings.get("enemy_items_check", True):
        check_items = None
    at = tuple(int(float(m) * 60) for m in settings.get("enemy_items_at", [12, 20, 30]))
    every = int(float(settings.get("enemy_items_every", 10)) * 60)
    return GameQuestions(
        index,
        enemies,
        every=int(settings.get("question_every", 300)),
        check_items=check_items,
        item_checks=at,
        item_check_every=every,
    )
