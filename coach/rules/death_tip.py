"""One short Claude tip while you wait to respawn.

The prompt holds only your own hero's data (the same numbers the game shows
you), and the tip is spoken only if it arrives while you are still dead.
"""

from __future__ import annotations

import logging
import threading
import time
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


class DeathTip:
    name = "death_tip"

    def __init__(
        self,
        say: Callable[[str], None],
        ask: Ask,
        min_respawn: int = 10,
        items: dict[str, ItemInfo] | None = None,
    ) -> None:
        self.say = say
        self.ask = ask
        self.min_respawn = min_respawn
        self.items = items if items is not None else load_items()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="death-tip")
        self._death = 0  # bumped on each death and new match, to drop stale tips

    def check(self, state: MatchState) -> list[str]:
        cur, prev = state.current, state.previous
        if prev.alive and not cur.alive and cur.respawn_seconds >= self.min_respawn:
            self._death += 1
            deadline = time.monotonic() + cur.respawn_seconds
            self._pool.submit(self._tip, state, describe(cur, self.items), self._death, deadline)
        return []

    def _tip(self, state: MatchState, prompt: str, death: int, deadline: float) -> None:
        tip = self.ask(prompt)
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
    ask = claude_asker(
        model=options.pop("model", "claude-opus-5-5"),
        effort=options.pop("effort", "low"),
        timeout=float(options.pop("timeout", 8)),
    )
    return [DeathTip(say, ask, **options)]
