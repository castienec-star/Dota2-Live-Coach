"""The model picks what to buy, from a short list the rules make.

The rules in situational.py know a few things well (your build, counters to
the enemy heroes you named, a defensive item when you're behind), but can't
weigh them against each other. So they put up to four candidates on a short
list, and a model (Ollama on your PC by default, or Claude) chooses one of
them and says why in a few words, from your own hero's numbers and what you
told the coach. A small model chooses well from four items and badly from
two hundred, and it can only ever answer with an item on the list.

If the model is off, missing, slow or gives a bad answer, the rules' own pick
is used, so the answer is never worse than without a model. The same
question with nothing changed is answered from a cache.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable

from . import llm, situational
from .benchmarks import Verdict
from .game_questions import Notes
from .grounding import Grounding
from .heroes import HeroInfo
from .items import ItemInfo
from .lineup import POSITIONS
from .situational import Pick
from .state import Snapshot

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a Dota 2 coach for new and low-ranked players. The player asked what \
to buy next. Choose exactly one item from the candidates given, using only the \
player's own data and what they told you. Reply with JSON only: \
{"item": "<candidate key>", "why": "<reason>"}. The reason is said out loud \
after the item's name: one short clause of at most 15 words, plain spoken \
English, no numbers, and only name heroes listed in the data."""

# The longest reason spoken; a longer one is cut to the rule's own reason.
MAX_WORDS = 18

_STAGES = ((10, "laning phase"), (30, "mid game"))


def _stage(snap: Snapshot) -> str:
    minutes = max(snap.clock_time or 0, 0) / 60
    return next((name for end, name in _STAGES if minutes < end), "late game")


def candidates(
    snap: Snapshot,
    verdict: Verdict | None,
    enemies: list[HeroInfo],
    role_name: str,
    items: dict[str, ItemInfo],
    next_item: ItemInfo | None,
    notes: Notes | None = None,
) -> list[Pick]:
    """Up to four items worth buying, the rules' own pick first: the next
    build item, a counter to the enemy heroes, and a defensive item. None
    are owned and none repeat."""
    trouble = notes.trouble if notes else None
    reason = situational.struggling(verdict, notes)
    found = [
        situational.recommend(snap, verdict, enemies, role_name, items, next_item, notes),
        Pick(next_item, "") if next_item is not None else None,
        situational.against(enemies, role_name, snap, items, trouble),
        situational.defensive(snap, role_name, items, reason or ""),
    ]
    picks: list[Pick] = []
    for pick in found:
        if pick is not None and all(p.item.key != pick.item.key for p in picks):
            picks.append(pick)
    return picks[:4]


def describe(
    snap: Snapshot,
    picks: list[Pick],
    verdict: Verdict | None,
    enemies: list[HeroInfo],
    items: dict[str, ItemInfo],
    hero: HeroInfo | None = None,
    position: int = 0,
    notes: Notes | None = None,
) -> str:
    """The prompt: your own hero, how the game goes, and the candidates."""
    minutes, seconds = divmod(max(snap.clock_time or 0, 0), 60)
    name = hero.name if hero else (snap.hero_name or "unknown").removeprefix("npc_dota_hero_")
    owned = [items[i.name].name if i.name in items else i.name for i in snap.items]
    lines = [f"Hero: {name}, level {snap.level}"]
    if hero is not None:
        lines[0] += f" ({hero.attack_type.lower()}, {', '.join(hero.roles)})"
    if position in POSITIONS:
        lines.append(f"Position: {position} ({POSITIONS[position]})")
    lines += [
        f"Game time: {minutes}:{seconds:02d} ({_stage(snap)})",
        f"Gold: {snap.gold}; GPM {snap.gpm}, XPM {snap.xpm}",
        f"Kills/deaths/assists: {snap.kills}/{snap.deaths}/{snap.assists}; last hits {snap.last_hits}",
        f"Items: {', '.join(owned) if owned else 'none'}",
    ]
    if verdict is not None:
        lines.append(f"Compared with public games on this hero: {verdict.kind}")
    if enemies:
        lines.append("Enemy heroes: " + "; ".join(
            f"{h.name} ({h.attack_type.lower()}, {', '.join(h.roles)})" for h in enemies
        ))
    told = notes.told() if notes is not None else []
    if told:
        lines.append(f"The player told you: {'; '.join(told)}")
    lines.append("Candidates:")
    for pick in picks:
        line = f"- {pick.item.key}: {pick.item.name}, {pick.item.cost} gold"
        if pick.reason:
            line += f" (rule: {pick.reason})"
        lines.append(line)
    return "\n".join(lines)


def schema(picks: list[Pick]) -> dict:
    """The reply Ollama must give: one of the candidate keys and a reason."""
    return {
        "type": "object",
        "properties": {
            "item": {"type": "string", "enum": [p.item.key for p in picks]},
            "why": {"type": "string"},
        },
        "required": ["item", "why"],
    }


def parse(reply: str | None, picks: list[Pick]) -> tuple[Pick, str] | None:
    """The chosen candidate and the model's reason, or None for a reply that
    isn't JSON or names an item that isn't on the list."""
    if not reply:
        return None
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    try:
        data = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    key = str(data.get("item", "")).strip()
    chosen = next((p for p in picks if key in (p.item.key, p.item.key.removeprefix("item_"))), None)
    if chosen is None:
        return None
    why = data.get("why")
    return chosen, why.strip() if isinstance(why, str) else ""


class ItemAdvisor:
    """Asks the model to choose among the rules' candidates, with the rules'
    pick as the fallback."""

    def __init__(self, ask: Callable[[str, dict], str | None] | None) -> None:
        self.ask = ask
        self._cache: dict[tuple, Pick | None] = {}
        self._grounding: Grounding | None = None  # loaded on the first model reply

    def choose(
        self,
        snap: Snapshot,
        verdict: Verdict | None,
        enemies: list[HeroInfo],
        role_name: str,
        items: dict[str, ItemInfo],
        next_item: ItemInfo | None,
        notes: Notes | None = None,
        hero: HeroInfo | None = None,
        position: int = 0,
    ) -> Pick | None:
        picks = candidates(snap, verdict, enemies, role_name, items, next_item, notes)
        if self.ask is None or len(picks) < 2:
            return picks[0] if picks else None
        told = tuple(notes.told()) if notes is not None else ()
        key = (
            snap.hero_name,
            max(snap.clock_time or 0, 0) // 60,
            tuple(p.item.key for p in picks),
            tuple(h.key for h in enemies),
            told,
            verdict.kind if verdict else None,
        )
        if key not in self._cache:
            prompt = describe(snap, picks, verdict, enemies, items, hero, position, notes)
            reply = self.ask(prompt, schema(picks))
            self._cache[key] = self._pick(reply, picks, enemies, notes, hero)
        return self._cache[key]

    def _pick(
        self,
        reply: str | None,
        picks: list[Pick],
        enemies: list[HeroInfo],
        notes: Notes | None,
        hero: HeroInfo | None,
    ) -> Pick:
        parsed = parse(reply, picks)
        if parsed is None:
            if reply is not None:
                log.info("Item advice: unusable model reply %r; using the rules", reply[:200])
            return picks[0]
        chosen, why = parsed
        why = why.rstrip(" .!")
        if why and (problem := self.problem(why, enemies, notes, hero)):
            log.info("Item advice: dropped the reason (it %s): %s", problem, why)
            why = ""
        return Pick(chosen.item, why or chosen.reason)


    def problem(
        self, why: str, enemies: list[HeroInfo], notes: Notes | None, hero: HeroInfo | None
    ) -> str | None:
        """Why a reason can't be spoken: too long, any number (small models
        invent them), or a hero nobody told the coach about."""
        if len(why.split()) > MAX_WORDS:
            return "is too long"
        if self._grounding is None:
            self._grounding = Grounding()
        trouble = notes.trouble if notes else None
        return self._grounding.problem(why, "", [hero, trouble, *enemies], enemies_known=bool(enemies))


def ollama_asker(model: str, url: str, timeout: float) -> Callable[[str, dict], str | None]:
    """Ollama answers in the candidates' JSON schema, so the item is always one of them."""
    return llm.ollama_asker(
        model, url, timeout, SYSTEM_PROMPT, label="Ollama item advice", temperature=0.2
    )


def build(settings: dict) -> ItemAdvisor:
    """The [items] settings: advisor = "ollama", "claude" or "rules"."""
    advisor = settings.get("advisor", "ollama")
    timeout = float(settings.get("timeout", 4))
    if advisor == "ollama":
        ask = ollama_asker(
            settings.get("ollama_model", "llama3.1:8b"),
            settings.get("ollama_url", "http://127.0.0.1:11434"),
            timeout,
        )
    elif advisor == "claude":
        from .rules.death_tip import claude_asker

        claude = claude_asker(
            settings.get("claude_model", "claude-opus-5-5"),
            settings.get("effort", "low"),
            timeout,
            system=SYSTEM_PROMPT,
            label="Item advice",
        )
        ask = lambda prompt, fmt: claude(prompt)  # noqa: E731
    elif advisor == "rules":
        ask = None
    else:
        raise ValueError(f"items advisor must be ollama, claude or rules, not {advisor!r}")
    return ItemAdvisor(ask)
