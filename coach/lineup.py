"""The start-of-game questions: your position, your teammates and the enemies.

GSI only describes your own hero, so before the horn the coach simply asks
you, out loud, what you can see on the top bar: "What position are you
playing?", "Who's on your team?", "Who are the enemy heroes?". It reads back
what it understood so you can correct it ("no, Lina not Lion"). Answers only
last for the match and feed the briefing and the rest of the coaching. The
coach never looks at your screen. While it doesn't know your rank, it also
asks that once, ever (coach/rank.py).
"""

from __future__ import annotations

import difflib
import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass

from .heroes import HeroIndex, HeroInfo, _fold
from .rank import QUESTION
from .state import IN_PROGRESS, MatchState

log = logging.getLogger(__name__)

POSITIONS = {1: "safe lane carry", 2: "mid", 3: "offlane", 4: "soft support", 5: "hard support"}

# Game states after the draft and before the horn: everyone has picked.
ASK_STATES = {
    "DOTA_GAMERULES_STATE_STRATEGY_TIME",
    "DOTA_GAMERULES_STATE_TEAM_SHOWCASE",
    "DOTA_GAMERULES_STATE_WAIT_FOR_MAP_TO_LOAD",
    "DOTA_GAMERULES_STATE_PRE_GAME",
}
# Started the coach late? Still ask in the first minute after the horn.
LATE_ASK_UNTIL = 60

# Speech-to-text often writes numbers as words that sound alike.
_NUMBERS = {
    "1": 1, "one": 1, "won": 1, "first": 1, "2": 2, "two": 2, "to": 2, "too": 2, "second": 2,
    "3": 3, "three": 3, "tree": 3, "third": 3, "4": 4, "four": 4, "for": 4, "fore": 4,
    "fourth": 4, "5": 5, "five": 5, "fifth": 5,
}
_ROLES = [
    (re.compile(r"\b(soft support|roam(er|ing)?)\b"), 4),
    (re.compile(r"\b(hard support|support)\b"), 5),
    (re.compile(r"\b(off ?lane|offlaner)\b"), 3),
    (re.compile(r"\b(mid|middle|midlane|midlaner)\b"), 2),
    (re.compile(r"\b(carry|safe ?lane)\b"), 1),
]
_SKIP = re.compile(r"\b(skip|never ?mind|don'?t know|no idea|stop)\b")
_YES = re.compile(r"^(yes|yeah|yep|yup|right|correct|ok|okay|sure|good|that'?s (right|it|all|correct))\b")
_DONE = re.compile(r"^(no|nope|nah|none|nobody|that'?s (it|all))$")
_CORRECTION = re.compile(r"^(?:no\b)?\W*(.+?)\s+not\s+(.+)$")
# Words people say around hero names that must not be read as heroes
# ("we" would otherwise match Weaver, "the" nothing useful).
_FILLER = {
    "a", "an", "and", "the", "we", "we've", "we're", "they", "they've", "they're", "have",
    "has", "got", "are", "is", "on", "our", "my", "their", "team", "enemy", "enemies",
    "heroes", "hero", "with", "plus", "also", "um", "uh", "er", "erm", "so", "then", "i",
    "think", "it's", "its", "there's", "playing", "me", "them", "us", "of", "picked",
}


def configured_position(settings: dict, hero: str | None) -> int:
    """The position set in coach.toml: [pregame.positions] for this hero, else
    [pregame] position. 0 when none is set."""
    key = (hero or "").removeprefix("npc_dota_hero_")
    position = int(settings.get("positions", {}).get(key, 0) or settings.get("position", 0))
    return position if position in POSITIONS else 0


def parse_position(text: str) -> int | None:
    """1 to 5 from "four", "pos 4", "position four", "support", "mid"..."""
    folded = _words(text)
    for word in folded.split():
        if word in _NUMBERS:
            return _NUMBERS[word]
        digits = re.fullmatch(r"(?:pos|p)?([1-5])", word)
        if digits:
            return int(digits.group(1))
    return next((pos for pattern, pos in _ROLES if pattern.search(folded)), None)


def _words(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9' ]+", " ", text.lower().replace("-", " ")).split())


def parse_heroes(index: HeroIndex, text: str) -> list[HeroInfo]:
    """Heroes from a spoken list, forgiving filler words and small mishearings."""
    words = [w for w in _words(text).split() if w not in _FILLER]
    heroes, unknown = index.parse(" ".join(words))
    for word in unknown:
        hero = _close(index, word)
        if hero is not None and hero not in heroes:
            heroes.append(hero)
    return heroes


def _close(index: HeroIndex, word: str) -> HeroInfo | None:
    """A hero whose name sounds written almost the same ("pudj", "sniber")."""
    if len(word) < 4:
        return None
    names = {_fold(h.name): h for h in index.heroes.values()}
    match = difflib.get_close_matches(_fold(word), list(names), n=1, cutoff=0.8)
    return names[match[0]] if match else None


@dataclass
class Question:
    """One spoken question: the coach says text, beeps, and passes the answer
    (empty when the player said nothing) to answer, which returns the reply."""

    text: str
    answer: Callable[[str], str | None]


class Interview:
    """Asks the start-of-game questions once a match, through the voice loop.

    Add it as a GSI listener and pass pending to the voice loop. sink gets
    what the player said: sink.heard(position=..., allies=..., enemies=...).
    Whatever sink already knows (sink.position, sink.allies, sink.enemies,
    e.g. from typed picks) is not asked again. A position set in coach.toml,
    for all heroes or per hero, is used without asking. With "rank" (a
    coach.rank.PlayerRank) it asks the player's rank last, if it should.
    """

    MAX_ROUNDS = 4  # read-backs per list, so a misheard answer can't loop forever

    def __init__(
        self,
        index: HeroIndex,
        sink,
        position: int = 0,
        hero_positions: dict[str, int] | None = None,
        rank=None,
    ) -> None:
        self.index = index
        self.sink = sink
        self.rank = rank
        self.position = position
        self.hero_positions = hero_positions or {}
        self._lock = threading.Lock()
        self._queue: list[Question] = []
        self._asked = False
        self._me: HeroInfo | None = None

    def __call__(self, state: MatchState) -> None:
        cur = state.current
        with self._lock:
            if state.new_match:
                self._asked, self._queue = False, []
            ready = cur.game_state in ASK_STATES or (
                cur.game_state == IN_PROGRESS and (cur.clock_time or 0) < LATE_ASK_UNTIL
            )
            if self._asked or not ready or cur.hero_name is None:
                return
            self._asked = True
            self._me = self.index.by_key(cur.hero_name)
            self._queue = self._questions()

    def _questions(self) -> list[Question]:
        questions = []
        key = self._me.key if self._me else ""
        position = self.hero_positions.get(key) or self.position
        if position in POSITIONS:
            self.sink.heard(position=position)
        elif not self.sink.position:
            questions.append(self._ask("What position are you playing, one to five?", self._position))
        if not self.sink.allies:
            questions.append(self._list_question("allies"))
        if not self.sink.enemies:
            questions.append(self._list_question("enemies"))
        if self.rank is not None and self.rank.should_ask():
            questions.append(self._ask(QUESTION, self._rank))
        return questions

    def _rank(self, text: str) -> str | None:
        self._next()
        return self.rank.answer("" if _SKIP.search(_words(text)) else text)

    @property
    def busy(self) -> bool:
        """True while questions are still waiting to be asked or answered."""
        with self._lock:
            return bool(self._queue)

    def pending(self) -> Question | None:
        """The next question to ask; the voice loop calls this when it is free."""
        with self._lock:
            return self._queue[0] if self._queue else None

    def _ask(self, text: str, handle: Callable[[str], str | None]) -> Question:
        def answer(reply: str) -> str | None:
            try:
                return handle(reply)
            except Exception:  # never ask the same question forever
                log.exception("Could not use the answer %r", reply)
                self._next()
                return None

        return Question(text, answer)

    def _next(self, follow_up: Question | None = None) -> None:
        with self._lock:
            if self._queue:
                self._queue.pop(0)
            if follow_up is not None:
                self._queue.insert(0, follow_up)

    def _position(self, text: str) -> str | None:
        position = parse_position(text)
        self._next()
        if position is None:
            return None if not text or _SKIP.search(_words(text)) else "Sorry, I didn't catch that. Skipping."
        self.sink.heard(position=position)
        return f"Position {position}, {POSITIONS[position]}."

    def _list_question(self, side: str) -> Question:
        text = "Who's on your team?" if side == "allies" else "Who are the enemy heroes?"
        return self._ask(text, lambda answer: self._list_answer(side, [], answer, 0))

    def _list_answer(self, side: str, heroes: list[HeroInfo], text: str, rounds: int) -> str | None:
        """Handles both the first answer and the replies to each read-back."""
        words = _words(text)
        full = 4 if side == "allies" else 5
        if not words or _SKIP.search(words) or (heroes and _YES.match(words)):
            return self._finish()
        if heroes and _DONE.match(words):
            if len(heroes) < full:  # "anyone else?" "no"
                return self._finish()
            if rounds + 1 >= self.MAX_ROUNDS:
                return self._finish("Okay, skipping.")
            self.sink.heard(**{side: []})
            self._next(self._list_question(side))  # "right?" "no": start over
            return "Okay, say them again."
        correction = _CORRECTION.match(words)
        if heroes and correction:
            right = parse_heroes(self.index, correction.group(1))
            wrong = parse_heroes(self.index, correction.group(2))
            heroes = [right[0] if right and h in wrong else h for h in heroes]
            if right and not wrong and right[0] not in heroes:
                heroes.append(right[0])
        else:
            heroes = heroes + [h for h in parse_heroes(self.index, words) if h not in heroes]
        heroes = [h for h in dict.fromkeys(heroes) if h != self._me][:full]
        if not heroes:
            self._next()
            return "Sorry, I didn't catch any heroes. You can type them instead."
        self.sink.heard(**{side: heroes})
        label = "Your team" if side == "allies" else "Enemies"
        readback = f"{label}: {', '.join(h.name for h in heroes)}."
        if rounds + 1 >= self.MAX_ROUNDS:
            self._next()
            return readback
        follow = readback + (" Right?" if len(heroes) >= full else " Anyone else?")
        self._next(self._ask(follow, lambda answer: self._list_answer(side, heroes, answer, rounds + 1)))
        return None  # the read-back is the next question

    def _finish(self, reply: str | None = None) -> str | None:
        self._next()
        return reply


class TypedQuestions:
    """The start-of-game questions in the coach window, for when the coach
    can't hear you (no microphone, or the voice packages aren't installed).

    Add it as a GSI listener right after the Interview: it prints each
    question when it comes up, and says once a match, out loud, to answer in
    the window. Pass each typed line to answer().
    """

    def __init__(
        self,
        interview: Interview,
        say: Callable[[str], None],
        show: Callable[[str], None] = print,
    ) -> None:
        self.interview = interview
        self.say = say
        self.show = show
        self._lock = threading.Lock()
        self._shown: Question | None = None
        self._told = False

    def __call__(self, state: MatchState) -> None:
        if state.new_match:
            self._told = False
        self._show_next()

    def answer(self, line: str) -> bool:
        """Answers the waiting question; False when none is waiting."""
        question = self.interview.pending()
        if question is None:
            return False
        reply = question.answer(line.strip())
        if reply:
            self.show(reply)
        self._show_next()
        return True

    def _show_next(self) -> None:
        with self._lock:
            question = self.interview.pending()
            if question is None or question is self._shown:
                return
            self._shown = question
            if not self._told:
                self._told = True
                self.say("Type your position, your team and the enemy heroes in the coach window.")
        self.show(f"Coach asks: {question.text}  (type the answer and press Enter; Enter alone skips)")
