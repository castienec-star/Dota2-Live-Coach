"""Review a replay with the coach: py -m coach replay-review

While you watch one of your replays in Dota, the coach follows your own hero
only, as if you were playing the game again: it runs the same reminders as a
live match on the same data your game sent you, and drops the other nine
heroes the replay knows about. On top, a vision model on your PC looks at the
replay on screen and suggests micro decisions, like a coach next to you.

Two ways to look, so you can pick what your time and graphics card allow:

- "moments": at your deaths (the frame from a few seconds before), when your
  health drops fast, when you pause, and every 90 s otherwise.
- "continuous": every few seconds the whole replay. Needs a strong graphics
  card, and lines can arrive a little late.

Fair play: the screen is only captured while Dota sends spectator updates, as
it does in a replay (replay_view.ScreenGate). A live match of your own shuts it
at once, and this mode then says to use the live coach instead.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from .replay_view import ScreenGate, find_slot, is_own_match, is_spectating, own_payload
from .speaker import HIGH, NORMAL
from .state import MatchState, Snapshot
from .vision import Frame, Grab, SeeAsk

log = logging.getLogger(__name__)

MODES = ("moments", "continuous")
DEFAULT_INTERVAL = {"moments": 90.0, "continuous": 8.0}
# A frame kept every this many seconds, so a death can be judged from just
# before it (the screen goes grey once you are dead).
FRAME_EVERY = 2.0
FRAMES_KEPT = 3
# Health lost within HURT_WINDOW seconds that counts as a fight going badly.
HURT_SHARE = 0.35
HURT_WINDOW = 3.0
# Moments closer together than this are one moment.
MOMENT_GAP = 12.0

DIED, HURT, PAUSED, REGULAR = "died", "hurt", "paused", "regular"
REASONS = {
    DIED: "The player's hero is about to die in this frame, a few seconds before the death. "
          "Say what they should have done differently in those seconds.",
    HURT: "The player's hero just lost a lot of health quickly. Say what to do right now.",
    PAUSED: "The player paused the replay here to talk about this moment. "
            "Say what is going on and the best next decision.",
    REGULAR: "A regular check. Say the most useful micro decision for the next seconds.",
}

SYSTEM = """\
You are a Dota 2 coach sitting next to a player while they watch a replay of \
their own game. You see one frame of the replay. Give one or two concrete \
micro decisions the player should make in the next seconds: positioning, last \
hits and denies, creep equilibrium, spell and item use, when to fight, chase \
or back off, where to look on the minimap. Use only what the player could \
see in their own game: their hero, their screen and their team's vision. \
Never mention the scoreboard, enemy gold or items you can't see on screen. \
If the frame shows no game (a menu or loading), answer only: skip. \
Speak to the player as "you". At most 35 words, plain sentences, no lists."""


class ReplayReview:
    """Feeds the coach your own hero from a replay and asks the vision model.

    `see` sits in front of the coach's state (gsi_server.Coach.replay); the
    object itself is a listener on that state; `tick` runs once a second.
    """

    def __init__(
        self,
        accounts: set[int],
        hero: str | None,
        mode: str,
        ask: SeeAsk | None,
        grab: Grab,
        say: Callable[..., None],
        interval: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        run: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.accounts, self.hero, self.mode = accounts, hero, mode
        self.ask, self.grab, self.say, self.clock = ask, grab, say, clock
        self.interval = interval or DEFAULT_INTERVAL[mode]
        self.gate = ScreenGate(clock)
        self.where: tuple[str, str] | None = None
        self.snap = Snapshot()
        self.frames: deque[tuple[float, Frame]] = deque(maxlen=FRAMES_KEPT)
        self.health: deque[tuple[float, int]] = deque()
        self.recent: deque[str] = deque(maxlen=3)
        self._run = run or (lambda job: threading.Thread(target=job, daemon=True).start())
        self._lock = threading.Lock()
        self._busy = False
        self._last_ask = clock()
        self._last_moment = -MOMENT_GAP
        self._last_frame = -FRAME_EVERY
        self._told: set[str] = set()

    # Game state ---------------------------------------------------------

    def see(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """The update the coach should see: your hero only, or None."""
        self.gate.see(payload)
        if is_own_match(payload):
            self._tell_once("live", "Replay review: this is a live match, so the screen stays off. "
                                    "Close Replay review and start the live coach instead.")
            return None
        if not is_spectating(payload):
            return payload  # the menu: nothing about any hero
        where = find_slot(payload, self.accounts, self.hero)
        if where is None:
            self._tell_once("hero", "Replay review: can't tell which hero is yours yet. "
                                    "Pick your hero in the Replay review window.")
            return None
        if where != self.where:
            self.where = where
            hero = ((payload.get("hero") or {}).get(where[0]) or {}).get(where[1], {}).get("name", "")
            log.info("Replay review: following your hero %s", hero.removeprefix("npc_dota_hero_"))
        return own_payload(payload, where)

    def __call__(self, state: MatchState) -> None:
        cur, prev = state.current, state.previous
        self.snap = cur
        now = self.clock()
        self.health.append((now, cur.health))
        while self.health and now - self.health[0][0] > HURT_WINDOW:
            self.health.popleft()
        if self.mode != "moments" or not cur.in_game or cur.hero_name is None:
            return
        if prev.alive and not cur.alive and prev.hero_name == cur.hero_name:
            self.moment(DIED)
        elif cur.paused and not prev.paused:
            self.moment(PAUSED)
        elif cur.alive and cur.max_health and max(h for _, h in self.health) - cur.health >= HURT_SHARE * cur.max_health:
            self.health.clear()
            self.moment(HURT)

    # Looking at the screen ----------------------------------------------

    def tick(self) -> None:
        """Once a second: keep recent frames, and the regular checks."""
        if not self.gate.open or self.ask is None:
            self.frames.clear()
            return
        now = self.clock()
        if self.mode == "moments" and now - self._last_frame >= FRAME_EVERY:
            self._last_frame = now
            frame = self.grab()
            if frame is not None:
                self.frames.append((now, frame))
        if now - self._last_ask >= self.interval and self.snap.in_game and not self.snap.paused:
            self.look(REGULAR)

    def moment(self, reason: str) -> None:
        now = self.clock()
        if now - self._last_moment < MOMENT_GAP:
            return
        self._last_moment = now
        self.look(reason)

    def look(self, reason: str) -> bool:
        """Ask the model about the screen now (or just before a death).
        False when the gate is shut, the model is busy or there is no frame."""
        if self.ask is None or not self.gate.open:
            return False
        with self._lock:
            if self._busy:
                return False
            self._busy = True
        self._last_ask = self.clock()
        frame = self.frames[0][1] if reason == DIED and self.frames else self.grab()
        if frame is None:
            self._busy = False
            return False
        prompt = self.prompt(reason)
        self._run(lambda: self._answer(prompt, frame, reason))
        return True

    def _answer(self, prompt: str, frame: Frame, reason: str) -> None:
        try:
            reply = self.ask(prompt, frame)
        finally:
            self._busy = False
        if not reply or reply.strip(" .").lower() == "skip" or not self.gate.open:
            return
        self.recent.append(reply)
        if reason == REGULAR:
            # Says what to do in the next seconds: late is useless.
            self.say(reply, priority=NORMAL, max_delay=6)
        else:
            self.say(reply, priority=HIGH, max_delay=20)

    def prompt(self, reason: str) -> str:
        s = self.snap
        hero = (s.hero_name or "unknown").removeprefix("npc_dota_hero_").replace("_", " ")
        clock = "" if s.clock_time is None else f"{s.clock_time // 60}:{s.clock_time % 60:02d}"
        items = ", ".join(i.name.removeprefix("item_").replace("_", " ") for i in s.items if i.slot.startswith("slot"))
        ready = ", ".join(a.name.split("_", 1)[-1].replace("_", " ") for a in s.abilities if a.can_cast and a.level)
        facts = [
            f"Game time {clock}." if clock else "",
            f"The player is {hero}, level {s.level}, {s.health_percent:.0f}% health"
            + (f", {100 * s.mana / s.max_mana:.0f}% mana" if s.max_mana else "") + ".",
            f"Gold {s.gold}. Kills/deaths/assists {s.kills}/{s.deaths}/{s.assists}. Last hits {s.last_hits}.",
            f"Items: {items}." if items else "",
            f"Spells ready: {ready}." if ready else "",
            REASONS[reason],
        ]
        if self.recent:
            facts.append("Don't repeat what you already said: " + " | ".join(self.recent))
        return "\n".join(f for f in facts if f)

    def _tell_once(self, key: str, text: str) -> None:
        if key not in self._told:
            self._told.add(key)
            log.warning("%s", text)
