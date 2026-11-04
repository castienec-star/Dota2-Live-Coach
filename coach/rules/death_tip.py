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

from .. import knowledge, llm, situational
from ..benchmarks import is_support
from ..game_questions import Notes
from ..grounding import Grounding
from ..heroes import HeroIndex
from ..items import ItemInfo, load_items
from ..lineup import POSITIONS
from ..state import MatchState, Snapshot
from . import PositionOf
from .last_moments import Moments, Recent, notice

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
items or buyback. What the abilities and items do is correct for this patch: \
a tip about using one of them well is welcome. Reply with the tip only, without quotes."""

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
    snap: Snapshot,
    items: dict[str, ItemInfo],
    position: int = 0,
    notes: Notes | None = None,
    moments: Moments | None = None,
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
    # What the hero and items do, so the tip can be about using them well.
    if abilities := knowledge.described(snap.hero_name):
        lines.append(f"Abilities: {abilities}")
    uses = []
    for item in snap.items:
        info = items.get(item.name)
        if info is not None and (line := knowledge.item_line(info)):
            uses.append(f"{info.name}: {line}")
    if uses:
        lines.append(f"What the items do: {'; '.join(uses)}")
    told = notes.told() if notes is not None else []
    if told:
        lines.append(f"The player told you: {'; '.join(told)}")
    if notes is not None and notes.trouble is not None:
        if what := knowledge.described(notes.trouble):
            lines.append(f"What {notes.trouble.name} does: {what}")
    seen = moments.facts() if moments is not None else []
    if seen:
        lines.append(f"In the seconds before dying: {'; '.join(seen)}")
    return "\n".join(lines)


def fits(tip: str, snap: Snapshot) -> bool:
    """False for a laning tip after the laning phase, which small models still give."""
    if phase(snap) == "laning phase":
        return True
    lower = tip.lower()
    return not any(word in lower for word in LANING_ONLY)


def claude_asker(
    model: str, effort: str, timeout: float, system: str = SYSTEM_PROMPT, label: str = "Death tips"
) -> Ask:
    """Ask Claude for a tip; returns None on any failure so the game goes on."""
    import anthropic

    client = None
    disabled = False
    lock = threading.Lock()

    def ask(prompt: str, fmt: dict | None = None) -> str | None:
        # fmt is ignored: the prompt asks Claude for the reply's shape.
        nonlocal client, disabled
        with lock:
            if disabled:
                return None
            if client is None:
                try:
                    client = anthropic.Anthropic()
                except anthropic.AnthropicError as exc:
                    log.warning("%s off: no Claude API credentials (%s)", label, exc)
                    disabled = True
                    return None
        try:
            response = client.with_options(timeout=timeout, max_retries=0).beta.messages.create(
                model=model,
                max_tokens=2000,
                system=system,
                output_config={"effort": effort},
                # Re-run on another model if the safety classifier declines.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.AuthenticationError:
            log.warning("%s off: the Claude API key was rejected", label)
            disabled = True
            return None
        except TypeError as exc:
            # The SDK raises this when no API key or login is set up at all.
            if "authentication" not in str(exc):
                raise
            log.warning("%s off: set ANTHROPIC_API_KEY to turn them on", label)
            disabled = True
            return None
        except anthropic.APITimeoutError:
            log.info("%s: Claude took longer than %ss; skipped", label, timeout)
            return None
        except anthropic.APIStatusError as exc:
            log.warning("%s failed: %s %s", label, exc.status_code, exc.message)
            return None
        except anthropic.APIConnectionError:
            log.warning("%s failed: no connection to the Claude API", label)
            return None
        if response.stop_reason == "refusal":
            return None
        return llm.clean(" ".join(b.text for b in response.content if b.type == "text"))

    return ask


def ollama_asker(model: str, url: str, timeout: float) -> Ask:
    """Ask a local Ollama model for a tip; returns None if it is not running or is slow."""
    return llm.ollama_asker(model, url, timeout, SYSTEM_PROMPT, label="Ollama tip", temperature=0.4)


# Written tips by game stage and role, from docs/strategy/fundamentals.md
# (what to say at each stage, for cores and supports). The offlane gets the
# core lines.
STAGE_TIPS = {
    ("laning phase", "core"): [
        "Next life, last hit when a creep's health drops under one hit, and don't chase kills.",
        "Early deaths usually come from walking past the river without vision. Stay on your side of the lane.",
        "Go back or use your regen when your health is low, instead of staying for one more creep.",
    ],
    ("laning phase", "support"): [
        "Early deaths usually come from walking past the river without vision. Ward before you walk forward.",
        "Stack the nearest camp when the clock shows 53 seconds, and take the gold runes for your team.",
        "Go back or use your regen when your health is low, instead of staying for one more hit.",
    ],
    ("mid game", "core"): [
        "Next life, farm the jungle camp between waves instead of walking around the map.",
        "Farm on your side of the map. The far lanes are where you get caught alone.",
        "After a won fight, take a tower or Roshan instead of going back to farm.",
    ],
    ("mid game", "support"): [
        "As a support, stay with your team, and buy wards and a Glimmer Cape or Force Staff.",
        "Keep wards up on your side of the map and walk with your cores, not alone.",
        "After a won fight, take a tower or Roshan with your team.",
    ],
    ("late game", "core"): [
        "Never farm a side lane alone now. One death this late can lose the game.",
        "Go to the enemy high ground only with your whole team, best with Aegis.",
        "Defend your base together. Don't trade a Barracks for farm in a far lane.",
    ],
    ("late game", "support"): [
        "Stay with your team now. One pick-off this late can lose the game.",
        "Go to the enemy high ground only with your whole team, best with Aegis.",
        "Defend your base together, and keep a Town Portal scroll to get there.",
    ],
}

def now_worded(line: str) -> str:
    """A death tip's line said to a living player: without "Next life,"."""
    if line.startswith("Next life, "):
        rest = line.removeprefix("Next life, ")
        return rest[0].upper() + rest[1:]
    return line


# Heroes that lose at low MMR from where they stand or from farming alone,
# not from their items (docs/strategy/low-bracket-meta.md); after laning.
FRAGILE_RANGED = {"drow_ranger", "sniper", "lina", "nevermore"}
LONE_FARMERS = {"furion", "antimage"}


def hero_tip(snap: Snapshot, name: str) -> str | None:
    """The line for a hero that loses games the same way at every medal."""
    stage = phase(snap)
    if stage == "laning phase":
        return None
    key = (snap.hero_name or "").removeprefix("npc_dota_hero_")
    if key in FRAGILE_RANGED:
        return f"As {name}, stand behind your team and attack from as far away as you can. You are fragile."
    if key in LONE_FARMERS and stage == "mid game":
        return f"As {name}, join the next fight with your team instead of farming alone."
    return None


class BuiltinTips:
    """Free written tips picked from your own stats, your role, the game
    stage and what you told the coach; never fails."""

    def __init__(
        self,
        notes: Callable[[], Notes | None] | None = None,
        position: PositionOf | None = None,
    ) -> None:
        self.notes = notes or (lambda: None)
        self.position = position
        self._next = 0
        self._last = ""  # never the same rotating line twice in a row
        self._named_trouble = False  # the trouble hero tip was the last one
        self._focus_trouble = False  # the same, for "what should I focus on?"
        self._heroes: HeroIndex | None = None

    def role(self, snap: Snapshot) -> str:
        """"support" for positions 4 and 5 (or a support hero while the
        position isn't known), else "core"."""
        position = self.position(snap) if self.position else 0
        if self._heroes is None:
            self._heroes = HeroIndex()
        return "support" if is_support(self._heroes.by_key(snap.hero_name), position) else "core"

    def __call__(self, snap: Snapshot) -> str:
        minutes = max(snap.clock_time or 0, 0) / 60
        notes = self.notes()
        role = self.role(snap)
        if minutes >= 30 and snap.buyback_cooldown == 0 and snap.gold < snap.buyback_cost and role == "core":
            return "Save gold for buyback before you take the next fight."
        # Every other death, so it doesn't turn into nagging.
        if notes is not None and notes.trouble is not None and not self._named_trouble:
            self._named_trouble = True
            name = notes.trouble.name
            return f"Next life, find {name} on the minimap before you fight, and don't meet {name} alone."
        self._named_trouble = False
        if minutes >= 10 and snap.last_hits < minutes * 4 and role == "core":
            return "Your last hits are low. Farm safer lanes and jungle camps next life."
        if snap.deaths >= 3 and snap.deaths > snap.kills + snap.assists:
            return "You are dying often. Play closer to your team and back off earlier."
        if notes is not None and notes.fights == "lost":
            return "Your team is losing fights. Next life, wait for them and fight together near your towers."
        if not any(i.name == "item_tpscroll" for i in snap.items):
            return "Buy a Town Portal scroll before you leave the fountain."
        return self._rotate(self._stage_lines(snap, role))

    def focus(self, snap: Snapshot) -> str:
        """The one thing to focus on now, while alive: "what should I focus
        on?". The same checks and lines as the death tips, worded for now
        instead of the next life, with low health first."""
        if snap.max_health and snap.health_percent < 30:
            return "Your health is low. Back off and heal before anything else."
        minutes = max(snap.clock_time or 0, 0) / 60
        notes = self.notes()
        role = self.role(snap)
        if minutes >= 30 and snap.buyback_cooldown == 0 and snap.gold < snap.buyback_cost and role == "core":
            return "Save gold for buyback before you take the next fight."
        # Every other time, so asking twice gives the next priority too.
        if notes is not None and notes.trouble is not None and not self._focus_trouble:
            self._focus_trouble = True
            name = notes.trouble.name
            return f"Find {name} on the minimap before you fight, and don't meet {name} alone."
        self._focus_trouble = False
        if minutes >= 10 and snap.last_hits < minutes * 4 and role == "core":
            return "Your last hits are low. Farm safe lanes and jungle camps between waves."
        if snap.deaths >= 3 and snap.deaths > snap.kills + snap.assists:
            return "You are dying often. Play closer to your team and back off earlier."
        if notes is not None and notes.fights == "lost":
            return "Your team is losing fights. Wait for them and fight together near your towers."
        if not any(i.name == "item_tpscroll" for i in snap.items):
            return "Buy a Town Portal scroll and keep it on you, so you can join fights and save towers."
        return self._rotate([now_worded(line) for line in self._stage_lines(snap, role)])

    def _stage_lines(self, snap: Snapshot, role: str) -> list[str]:
        lines = list(STAGE_TIPS[(phase(snap), role)])
        hero = self._heroes.by_key(snap.hero_name) if self._heroes else None
        if hero is not None and (line := hero_tip(snap, hero.name)):
            lines.insert(0, line)
        return lines

    def _rotate(self, lines: list[str]) -> str:
        """The next line in turn, never the same one twice in a row."""
        tip = lines[self._next % len(lines)]
        self._next += 1
        if tip == self._last:
            tip = lines[self._next % len(lines)]
            self._next += 1
        self._last = tip
        return tip


def streak_tip(snap: Snapshot, deaths: int, minutes: int, items: dict[str, ItemInfo], role_name: str) -> str:
    """One calm line after several deaths close together: stop the spiral."""
    pick = situational.defensive(snap, role_name, items)
    buy = f" and get {pick.item.name} before anything greedy" if pick is not None else ""
    return (
        f"That's {deaths} deaths in {minutes} minutes. Take a breath: farm near your "
        f"towers until your team groups up{buy}."
    )


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
        streak: int = 3,
        streak_window: int = 360,
    ) -> None:
        """streak deaths within streak_window game seconds get the calm
        streak line instead of a tip (streak = 0 turns it off)."""
        self.say = say
        self.ask = ask
        self.notes = notes or (lambda: None)
        self.fallback = fallback or BuiltinTips(self.notes, position)
        self.min_respawn = min_respawn
        self.position = position
        self.items = items if items is not None else load_items()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="death-tip")
        self._death = 0  # bumped on each death and new match, to drop stale tips
        self._grounding: Grounding | None = None  # loaded on the first model tip
        self._recent = Recent()  # the last seconds alive, for what led to a death
        self.streak = streak
        self.streak_window = streak_window
        self._deaths: list[int] = []  # game clock of each death this match
        self._streak_after = -1  # deaths up to this clock already had the streak line
        self._heroes: HeroIndex | None = None

    def check(self, state: MatchState) -> list[str]:
        cur, prev = state.current, state.previous
        if prev.alive and not cur.alive and cur.clock_time is not None:
            self._deaths.append(cur.clock_time)
        if prev.alive and not cur.alive and cur.respawn_seconds >= self.min_respawn:
            self._death += 1
            deadline = time.monotonic() + cur.respawn_seconds
            streak = self._streak_line(cur)
            if streak is not None:
                # Said at once: it needs no model, and it matters more than a tip.
                self.say(streak)
            else:
                moments = notice(self._recent.snaps, self.items)
                self._pool.submit(self._tip, state, cur, self._death, deadline, moments)
        if not cur.alive:
            self._recent.clear()
        self._recent.add(cur)
        return []

    def _streak_line(self, snap: Snapshot) -> str | None:
        """The streak line if this death completes a streak not yet talked about."""
        if not self.streak or snap.clock_time is None:
            return None
        recent = [t for t in self._deaths if t > self._streak_after and snap.clock_time - t <= self.streak_window]
        if len(recent) < self.streak:
            return None
        self._streak_after = snap.clock_time
        if self._heroes is None:
            self._heroes = HeroIndex()
        position = self.position(snap) if self.position else 0
        role_name = situational.role(position, is_support(self._heroes.by_key(snap.hero_name), position))
        minutes = max(1, -(-(snap.clock_time - recent[0]) // 60))
        return streak_tip(snap, len(recent), minutes, self.items, role_name)

    def _tip(
        self, state: MatchState, snap: Snapshot, death: int, deadline: float, moments: Moments | None = None
    ) -> None:
        position = self.position(snap) if self.position else 0
        prompt = describe(snap, self.items, position, self.notes(), moments)
        tip = self.checked(self.ask(prompt) if self.ask else None, snap, prompt)
        # What led to this death beats a general tip.
        tip = tip or (moments.tip() if moments is not None else None) or self.fallback(snap)
        # Only speak while still in the same death, with time left to hear it.
        if (
            tip
            and death == self._death
            and not state.current.alive
            and time.monotonic() < deadline - 2
        ):
            self.say(tip)

    def checked(self, tip: str | None, snap: Snapshot, prompt: str) -> str | None:
        """The model's tip, or None when it is out of date or names a hero it shouldn't."""
        if tip and not fits(tip, snap):
            log.info("Dropped an out-of-date tip: %s", tip)
            return None
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
                return None
        return tip

    def reset(self) -> None:
        self._death += 1
        self._recent.clear()
        self._deaths.clear()
        self._streak_after = -1

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
