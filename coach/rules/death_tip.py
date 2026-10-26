"""One short tip while you wait to respawn.

Tips come from a local model through Ollama (free, runs on your own GPU), from
Claude (paid API), or from built-in written tips, which are also the fallback
when a model is unavailable or too slow. The prompt holds only your own hero's
data (the same numbers the game shows you), and a tip is spoken only if it is
ready while you are still dead.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from ..items import ItemInfo, load_items
from ..state import MatchState, Snapshot

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a Dota 2 coach talking to a player through their headset while they wait \
to respawn. Give exactly one practical tip for their next life, in at most 20 \
words of plain spoken English: no lists, no emoji, no numbers read as digits \
unless short. Base it only on the player's own data below. Do not guess where \
enemies are or what they are doing."""

Ask = Callable[[str], "str | None"]


def describe(snap: Snapshot, items: dict[str, ItemInfo]) -> str:
    """The player's own state, as the tip prompt sees it."""
    minutes, seconds = divmod(max(snap.clock_time or 0, 0), 60)
    hero = (snap.hero_name or "unknown").removeprefix("npc_dota_hero_").replace("_", " ")
    owned = [items[i.name].name if i.name in items else i.name for i in snap.items]
    buyback = (
        "on cooldown"
        if snap.buyback_cooldown > 0
        else ("affordable" if snap.gold >= snap.buyback_cost else "not affordable")
    )
    return "\n".join([
        f"Hero: {hero}, level {snap.level}",
        f"Game time: {minutes}:{seconds:02d}",
        f"Kills/deaths/assists: {snap.kills}/{snap.deaths}/{snap.assists}",
        f"Last hits/denies: {snap.last_hits}/{snap.denies}",
        f"Gold: {snap.gold}; buyback costs {snap.buyback_cost} ({buyback})",
        f"Respawn in: {snap.respawn_seconds} seconds",
        f"Items: {', '.join(owned) if owned else 'none'}",
    ])


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
        text = " ".join(b.text for b in response.content if b.type == "text").strip()
        return text or None

    return ask


def ollama_asker(model: str, url: str, timeout: float) -> Ask:
    """Ask a local Ollama model; returns None if Ollama is not running or is slow."""
    warned = False

    def ask(prompt: str) -> str | None:
        nonlocal warned
        body = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            # Keep the model loaded between deaths so tips come back fast.
            "keep_alive": "30m",
            "options": {"num_predict": 80, "temperature": 0.7},
        }).encode()
        request = urllib.request.Request(
            url.rstrip("/") + "/api/chat", body, {"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:200]
            log.warning("Ollama tip failed: %s %s", exc.code, detail)
            return None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if not warned:
                warned = True
                log.warning("Ollama not reachable at %s (%s); using built-in tips", url, exc)
            return None
        text = (data.get("message") or {}).get("content", "").strip()
        return text or None

    return ask


BUILTIN_TIPS = [
    "Use your death timer to plan your next item and where you will farm.",
    "Next life, stay near your team and avoid farming alone far from your towers.",
    "Buy a Town Portal scroll if you don't have one, so you can join fights fast.",
    "Check your wards before walking into the jungle again.",
    "Look at the minimap every few seconds when you farm a side lane.",
]


class BuiltinTips:
    """Free written tips picked from your own stats; never fails."""

    def __init__(self) -> None:
        self._next = 0

    def __call__(self, snap: Snapshot) -> str:
        minutes = max(snap.clock_time or 0, 0) / 60
        if minutes >= 30 and snap.buyback_cooldown == 0 and snap.gold < snap.buyback_cost:
            return "Save gold for buyback before you take the next fight."
        if minutes >= 10 and snap.last_hits < minutes * 4:
            return "Your last hits are low. Farm safer lanes and jungle camps next life."
        if snap.deaths >= 3 and snap.deaths > snap.kills + snap.assists:
            return "You are dying often. Play closer to your team and back off earlier."
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
    ) -> None:
        self.say = say
        self.ask = ask
        self.fallback = fallback or BuiltinTips()
        self.min_respawn = min_respawn
        self.items = items if items is not None else load_items()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="death-tip")
        self._death = 0  # bumped on each death and new match, to drop stale tips

    def check(self, state: MatchState) -> list[str]:
        cur, prev = state.current, state.previous
        if prev.alive and not cur.alive and cur.respawn_seconds >= self.min_respawn:
            self._death += 1
            deadline = time.monotonic() + cur.respawn_seconds
            self._pool.submit(self._tip, state, cur, self._death, deadline)
        return []

    def _tip(self, state: MatchState, snap: Snapshot, death: int, deadline: float) -> None:
        tip = self.ask(describe(snap, self.items)) if self.ask else None
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


def build(settings: dict, say: Callable[[str], None]) -> list[DeathTip]:
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
    return [DeathTip(say, ask, **options)]
