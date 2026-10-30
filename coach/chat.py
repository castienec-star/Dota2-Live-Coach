"""Ask the coach anything: questions the built-in answers don't cover go to a model.

"Hey coach, how do I play against Pudge?" isn't one of the coach's fixed
questions, so it goes to the same model as the death tips (Ollama on your PC
by default, or Claude). The prompt holds only your own hero's GSI numbers,
your build and what to buy now, the ahead/behind verdict, the heroes you told
the coach and your answers to its in-match questions, plus the last few
questions of this match so "and after that?" works.

The model must answer in a sentence or two. A reply that names a hero nobody
told the coach about is dropped, and one that comes back after you started
losing health or died is not said at all: by then you're in a fight.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from . import llm, situational
from .game_questions import Notes
from .grounding import Grounding
from .heroes import HeroInfo
from .item_advisor import Advice
from .items import ItemInfo, load_items
from .lineup import POSITIONS
from .rules import PositionOf
from .rules.death_tip import phase
from .state import Snapshot

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a friendly Dota 2 coach for new and low-ranked players, talking through \
their headset during a match. Answer the player's question in one or two short \
sentences of plain spoken English: no lists, no emoji. Use only the player's own \
data below, what they told you and general Dota knowledge. You cannot see the \
map, the enemies or their items: never claim to know where enemies are or what \
they have unless the player told you, and never name a hero that isn't in the \
data below. If you don't know, say so in a few words. For what to buy, use the \
item the coach suggests below. Reply with the answer only, without quotes."""

# Said when the model is off or too slow.
OFF = (
    "I can't answer that one without the AI model. Ask me how you're doing, what to "
    "buy, or about your next item, buyback or runes."
)
OLLAMA_OFF = OFF + " Start Ollama to ask me anything."
# Said when the model's reply couldn't be trusted.
UNSURE = "I'm not sure about that one. Try asking another way."

# The longest reply spoken; the rest is cut at a sentence end.
MAX_WORDS = 45
# A drop this big in health percent while the model thought means a fight.
HURT = 20


def _cut(text: str) -> str:
    """At most two sentences and MAX_WORDS words, so it stays short to hear."""
    sentences: list[str] = []
    words = 0
    for part in text.replace("!", "!|").replace("?", "?|").replace(". ", ".|").split("|"):
        part = part.strip()
        if not part:
            continue
        count = len(part.split())
        if sentences and (len(sentences) == 2 or words + count > MAX_WORDS):
            break
        sentences.append(part)
        words += count
    line = " ".join(sentences)
    if len(line.split()) > MAX_WORDS:
        line = " ".join(line.split()[:MAX_WORDS]).rstrip(",;:") + "."
    return line


def stale(before: Snapshot, after: Snapshot) -> bool:
    """True when the player died or lost a lot of health while waiting."""
    if before.hero_name is None or after.hero_name is None:
        return False
    if before.alive and not after.alive:
        return True
    return before.alive and after.health_percent < before.health_percent - HURT


class Chat:
    """Answers a free question from the match facts, or None when the model
    is off, missing or slow."""

    HISTORY = 3  # earlier questions and answers kept, this match only

    def __init__(
        self,
        ask: llm.Ask | None,
        advice: Advice | None = None,
        position: PositionOf | None = None,
        allies: Callable[[], list[HeroInfo]] | None = None,
        enemies: Callable[[], list[HeroInfo]] | None = None,
        notes: Callable[[], Notes | None] | None = None,
        current: Callable[[], Snapshot] | None = None,
        items: dict[str, ItemInfo] | None = None,
        off: str = OFF,
    ) -> None:
        """current() is the latest snapshot, checked once the reply is back."""
        self.ask = ask
        self.advice = advice
        self.position = position
        self.allies = allies or list
        self.enemies = enemies or list
        self.notes = notes or (lambda: None)
        self.current = current
        self.items = items if items is not None else load_items()
        self.off = off
        self.history: list[tuple[str, str]] = []
        self._match: tuple | None = None
        self._grounding: Grounding | None = None  # loaded on the first reply

    def __call__(self, question: str, snap: Snapshot) -> str | None:
        """The spoken reply; "" when it came too late to say."""
        if self.ask is None:
            return None
        match = (snap.match_id, snap.hero_name)
        if match != self._match:
            self._match, self.history = match, []
        prompt = self.describe(question, snap)
        reply = self.ask(prompt)
        if not reply:
            return None
        if self.current is not None and stale(snap, self.current()):
            log.info("Chat reply dropped, you were in a fight by then: %s", reply)
            return ""
        reply = _cut(reply)
        problem = self.problem(reply, snap)
        if problem:
            log.info("Chat reply dropped (it %s): %s", problem, reply)
            return UNSURE
        self.history = (self.history + [(question, reply)])[-self.HISTORY :]
        return reply

    def heroes(self, snap: Snapshot) -> tuple[HeroInfo | None, list[HeroInfo], list[HeroInfo]]:
        if self._grounding is None:
            self._grounding = Grounding()
        return self._grounding.index.by_key(snap.hero_name), self.allies(), self.enemies()

    def problem(self, reply: str, snap: Snapshot) -> str | None:
        me, allies, enemies = self.heroes(snap)
        notes = self.notes()
        trouble = notes.trouble if notes is not None else None
        return self._grounding.problem(
            reply,
            "",
            [me, trouble, *allies, *enemies],
            allies_known=bool(allies),
            enemies_known=bool(enemies),
            check_numbers=False,
        )

    def describe(self, question: str, snap: Snapshot) -> str:
        """The prompt: the player's own facts, the last few questions, and this one."""
        me, allies, enemies = self.heroes(snap)
        lines: list[str] = []
        if snap.hero_name is None:
            lines.append("The game hasn't started yet; the coach can't see a hero.")
        else:
            minutes, seconds = divmod(max(snap.clock_time or 0, 0), 60)
            name = me.name if me else snap.hero_name.removeprefix("npc_dota_hero_").replace("_", " ")
            hero = f"Your hero: {name}, level {snap.level}"
            if me is not None:
                hero += f" ({me.attack_type.lower()}, {', '.join(me.roles)})"
            owned = [self.items[i.name].name if i.name in self.items else i.name for i in snap.items]
            lines += [
                hero,
                f"Game time: {minutes}:{seconds:02d} ({phase(snap)})",
                f"Kills/deaths/assists: {snap.kills}/{snap.deaths}/{snap.assists}; "
                f"last hits {snap.last_hits}, denies {snap.denies}",
                f"Gold: {snap.gold}; GPM {snap.gpm}, XPM {snap.xpm}",
                f"Health: {snap.health_percent:.0f}%" if snap.alive else f"Dead, respawn in {snap.respawn_seconds} seconds",
                f"Items: {', '.join(owned) if owned else 'none'}",
            ]
            position = self.position(snap) if self.position else 0
            if position in POSITIONS:
                lines.insert(1, f"Position: {position} ({POSITIONS[position]})")
            lines += self._advice(snap)
        others = [h for h in allies if h != me]
        lines.append("Teammates: " + (", ".join(h.name for h in others) if others else "not known"))
        lines.append("Enemies: " + (", ".join(h.name for h in enemies) if enemies else "not known"))
        notes = self.notes()
        told = notes.told() if notes is not None else []
        if told:
            lines.append(f"The player told you: {'; '.join(told)}")
        if self.history:
            lines.append("Earlier this match:")
            for asked, said in self.history:
                lines += [f"- Player: {asked}", f"- You: {said}"]
        lines.append(f"The player asks: {question}")
        return "\n".join(lines)

    def _advice(self, snap: Snapshot) -> list[str]:
        """The verdict, next build item and what to buy now, as the built-in
        answers would say them (never waiting for the item model)."""
        if self.advice is None:
            return []
        pick, verdict, next_item = self.advice(snap, wait=False)
        lines = []
        if verdict is not None:
            lines.append(f"Compared with public games on this hero: {verdict.kind}")
        if next_item is not None:
            lines.append(f"Next item on the build: {next_item.name}")
        if pick is not None:
            line = f"The coach suggests buying: {pick.item.name}"
            if pick.reason and pick.reason != situational.BUILD_DONE:
                line += f" ({pick.reason})"
            lines.append(line)
        return lines


def build(
    listen: dict,
    tip: dict,
    advice: Advice | None = None,
    position: PositionOf | None = None,
    allies: Callable[[], list[HeroInfo]] | None = None,
    enemies: Callable[[], list[HeroInfo]] | None = None,
    notes: Callable[[], Notes | None] | None = None,
    current: Callable[[], Snapshot] | None = None,
) -> Chat | None:
    """[listen] chat, with the death tips' model and provider; None when off."""
    if not listen.get("chat", True):
        return None
    # The death tips' provider even when the tips are off; "builtin" means no model.
    provider = tip.get("provider", "ollama")
    timeout = float(listen.get("chat_timeout", 6))
    off = OFF
    if provider == "ollama":
        ask = llm.ollama_asker(
            tip.get("ollama_model", llm.DEFAULT_MODEL),
            tip.get("ollama_url", llm.DEFAULT_URL),
            timeout,
            SYSTEM_PROMPT,
            num_predict=90,
            label="Ollama chat",
            temperature=0.5,
        )
        off = OLLAMA_OFF
    elif provider == "claude":
        from .rules.death_tip import claude_asker

        ask = claude_asker(
            tip.get("claude_model", "claude-opus-5-5"),
            tip.get("effort", "low"),
            timeout,
            system=SYSTEM_PROMPT,
            label="Chat",
        )
    else:
        ask = None
    return Chat(ask, advice, position, allies, enemies, notes, current, off=off)
