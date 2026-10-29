"""One short tip while you wait to respawn.

Tips come from a local model through Ollama (free, runs on your own GPU), from
Claude (paid API), or from built-in written tips, which are also the fallback
when a model is unavailable or too slow. The prompt holds only your own hero's
data (the same numbers the game shows you), and a tip is spoken only if it is
ready while you are still dead. What you told the coach this match (how
your lane went, who gives you trouble, who wins fights) is used too.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from .. import llm
from ..game_questions import Notes
from ..grounding import Grounding
from ..items import ItemInfo, load_items
from ..lineup import POSITIONS
from ..state import MatchState, Snapshot
from . import PositionOf

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a Dota 2 coach talking to a player through their headset while they wait \
to respawn. Give exactly one practical tip for their next life, in at most 20 \
words of plain spoken English: no lists, no emoji, no numbers read as digits \
unless short. Base it only on the player's own data below and what they told \
you. Do not guess where enemies are or what they are doing, and never name a \
hero that isn't in the data below. Dota has no junglers. Fit the tip to the \
game phase given: last hits, denies and lane tips only in the laning phase; \
after that, talk about farming the map, fighting with the team, objectives, \
items or buyback. Reply with the tip only, without quotes."""

# After the laning phase a tip about denies or the lane is out of date.
LANING_ONLY = ("deny", "denies", "denying", "your lane", "in lane", "the lane")


def phase(snap: Snapshot) -> str:
    minutes = max(snap.clock_time or 0, 0) / 60
    if minutes < 10:
        return "laning phase"
    if minutes < 30:
        return "mid game"
    return "late game"

Ask = llm.Ask


def describe(
    snap: Snapshot, items: dict[str, ItemInfo], position: int = 0, notes: Notes | None = None
) -> str:
    """The player's own state, and what they told the coach, as the tip prompt sees it."""
    minutes, seconds = divmod(max(snap.clock_time or 0, 0), 60)
    hero = (snap.hero_name or "unknown").removeprefix("npc_dota_hero_").replace("_", " ")
    owned = [items[i.name].name if i.name in items else i.name for i in snap.items]
    buyback = (
        "on cooldown"
        if snap.buyback_cooldown > 0
        else ("affordable" if snap.gold >= snap.buyback_cost else "not affordable")
    )
    lines = [
        f"Hero: {hero}, level {snap.level}",
        f"Game time: {minutes}:{seconds:02d} ({phase(snap)})",
        f"Kills/deaths/assists: {snap.kills}/{snap.deaths}/{snap.assists}",
        f"Last hits/denies: {snap.last_hits}/{snap.denies}",
        f"Gold: {snap.gold}; buyback costs {snap.buyback_cost} ({buyback})",
        f"Respawn in: {snap.respawn_seconds} seconds",
        f"Items: {', '.join(owned) if owned else 'none'}",
    ]
    if position in POSITIONS:
        lines.insert(1, f"Position: {position} ({POSITIONS[position]})")
    told = notes.told() if notes is not None else []
    if told:
        lines.append(f"The player told you: {'; '.join(told)}")
    return "\n".join(lines)


def fits(tip: str, snap: Snapshot) -> bool:
    """False for a laning tip after the laning phase, which small models still give."""
    if phase(snap) == "laning phase":
        return True
    lower = tip.lower()
    return not any(word in lower for word in LANING_ONLY)


def claude_asker(model: str, effort: str, timeout: float) -> Ask:
    """Ask Claude for a tip; returns None on any failure so the game goes on."""
    import anthropic

    client = None
    disabled = False
    lock = threading.Lock()

    def ask(prompt: str) -> str | None:
        nonlocal client, disabled
        with lock:
            if disabled:
                return None
            if client is None:
                try:
                    client = anthropic.Anthropic()
                except anthropic.AnthropicError as exc:
                    log.warning("Death tips off: no Claude API credentials (%s)", exc)
                    disabled = True
                    return None
        try:
            response = client.with_options(timeout=timeout, max_retries=0).beta.messages.create(
                model=model,
                max_tokens=2000,
                system=SYSTEM_PROMPT,
                output_config={"effort": effort},
                # Re-run on another model if the safety classifier declines.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.AuthenticationError:
            log.warning("Death tips off: the Claude API key was rejected")
            disabled = True
            return None
        except TypeError as exc:
            # The SDK raises this when no API key or login is set up at all.
            if "authentication" not in str(exc):
                raise
            log.warning("Death tips off: set ANTHROPIC_API_KEY to turn them on")
            disabled = True
            return None
        except anthropic.APITimeoutError:
            log.info("Death tip took longer than %ss; skipped", timeout)
            return None
        except anthropic.APIStatusError as exc:
            log.warning("Death tip failed: %s %s", exc.status_code, exc.message)
            return None
        except anthropic.APIConnectionError:
            log.warning("Death tip failed: no connection to the Claude API")
            return None
        if response.stop_reason == "refusal":
            return None
        return llm.clean(" ".join(b.text for b in response.content if b.type == "text"))

    return ask


def ollama_asker(model: str, url: str, timeout: float) -> Ask:
    """Ask a local Ollama model for a tip; returns None if it is not running or is slow."""
    return llm.ollama_asker(model, url, timeout, SYSTEM_PROMPT, label="Ollama tip", temperature=0.4)


BUILTIN_TIPS = [
    "Use your death timer to plan your next item and where you will farm.",
    "Next life, stay near your team and avoid farming alone far from your towers.",
    "Buy a Town Portal scroll if you don't have one, so you can join fights fast.",
    "Check your wards before walking into the jungle again.",
    "Look at the minimap every few seconds when you farm a side lane.",
]


class BuiltinTips:
    """Free written tips picked from your own stats and what you told the
    coach; never fails."""

    def __init__(self, notes: Callable[[], Notes | None] | None = None) -> None:
        self.notes = notes or (lambda: None)
        self._next = 0
        self._named_trouble = False  # the trouble hero tip was the last one

    def __call__(self, snap: Snapshot) -> str:
        minutes = max(snap.clock_time or 0, 0) / 60
        notes = self.notes()
        if minutes >= 30 and snap.buyback_cooldown == 0 and snap.gold < snap.buyback_cost:
            return "Save gold for buyback before you take the next fight."
        # Every other death, so it doesn't turn into nagging.
        if notes is not None and notes.trouble is not None and not self._named_trouble:
            self._named_trouble = True
            name = notes.trouble.name
            return f"Next life, find {name} on the minimap before you fight, and don't meet {name} alone."
        self._named_trouble = False
        if minutes >= 10 and snap.last_hits < minutes * 4:
            return "Your last hits are low. Farm safer lanes and jungle camps next life."
        if snap.deaths >= 3 and snap.deaths > snap.kills + snap.assists:
            return "You are dying often. Play closer to your team and back off earlier."
        if notes is not None and notes.fights == "lost":
            return "Your team is losing fights. Next life, wait for them and fight together near your towers."
        if not any(i.name == "item_tpscroll" for i in snap.items):
            return "Buy a Town Portal scroll before you leave the fountain."
        tip = BUILTIN_TIPS[self._next % len(BUILTIN_TIPS)]
        self._next += 1
        return tip


class DeathTip:
    name = "death_tip"

    def __init__(
        self,
        say: Callable[[str], None],
        ask: Ask | None,
        min_respawn: int = 10,
        items: dict[str, ItemInfo] | None = None,
        fallback: Callable[[Snapshot], str] | None = None,
        position: PositionOf | None = None,
        notes: Callable[[], Notes | None] | None = None,
    ) -> None:
        self.say = say
        self.ask = ask
        self.notes = notes or (lambda: None)
        self.fallback = fallback or BuiltinTips(self.notes)
        self.min_respawn = min_respawn
        self.position = position
        self.items = items if items is not None else load_items()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="death-tip")
        self._death = 0  # bumped on each death and new match, to drop stale tips
        self._grounding: Grounding | None = None  # loaded on the first model tip

    def check(self, state: MatchState) -> list[str]:
        cur, prev = state.current, state.previous
        if prev.alive and not cur.alive and cur.respawn_seconds >= self.min_respawn:
            self._death += 1
            deadline = time.monotonic() + cur.respawn_seconds
            self._pool.submit(self._tip, state, cur, self._death, deadline)
        return []

    def _tip(self, state: MatchState, snap: Snapshot, death: int, deadline: float) -> None:
        position = self.position(snap) if self.position else 0
        prompt = describe(snap, self.items, position, self.notes())
        tip = self.ask(prompt) if self.ask else None
        if tip and not fits(tip, snap):
            log.info("Dropped an out-of-date tip: %s", tip)
            tip = None
        if tip:
            if self._grounding is None:
                self._grounding = Grounding()
            me = self._grounding.index.by_key(snap.hero_name)
            # Only the player's own hero and heroes named in the prompt (such
            # as one the player said gives them trouble) may be named;
            # numbers like "two wards" are fine in a tip.
            problem = self._grounding.problem(
                tip, "", [me, *self._grounding.heroes(prompt)], check_numbers=False
            )
            if problem:
                log.info("Death tip from the model dropped (it %s): %s", problem, tip)
                tip = None
        tip = tip or self.fallback(snap)
        # Only speak while still in the same death, with time left to hear it.
        if (
            tip
            and death == self._death
            and not state.current.alive
            and time.monotonic() < deadline - 2
        ):
            self.say(tip)

    def reset(self) -> None:
        self._death += 1

    def close(self) -> None:
        self._pool.shutdown(wait=True)


def build(
    settings: dict,
    say: Callable[[str], None],
    position: PositionOf | None = None,
    notes: Callable[[], Notes | None] | None = None,
) -> list[DeathTip]:
    options = dict(settings.get("death_tip", {}))
    if not options.pop("enabled", True):
        return []
    provider = options.pop("provider", "ollama")
    timeout = float(options.pop("timeout", 8))
    ollama_model = options.pop("ollama_model", "llama3.1:8b")
    ollama_url = options.pop("ollama_url", "http://127.0.0.1:11434")
    claude_model = options.pop("claude_model", "claude-opus-5-5")
    effort = options.pop("effort", "low")
    if provider == "ollama":
        ask = ollama_asker(ollama_model, ollama_url, timeout)
    elif provider == "claude":
        ask = claude_asker(claude_model, effort, timeout)
    elif provider == "builtin":
        ask = None
    else:
        raise ValueError(f"death_tip provider must be ollama, claude or builtin, not {provider!r}")
    return [DeathTip(say, ask, position=position, notes=notes, **options)]
