"""Review a replay with the coach: py -m coach replay-review

While you watch one of your replays in Dota, the coach follows your own hero
only, on the same data your game sent you, and drops the other nine heroes
the replay knows about. It grabs a frame of the replay every second, and a
vision model on your PC looks back over the last seconds (a few frames plus
your numbers second by second) and talks the mistakes over with you, in the
past tense, like a coach watching the replay next to you.

Two ways to look, so you can pick what your time and graphics card allow:

- "moments": at your deaths (the seconds before), when your health drops
  fast, when you pause, and every 90 s otherwise.
- "continuous": every few seconds (10 by default), whenever the model and
  the voice are free, over everything since the last look.

The coach doesn't talk over itself: no new look while a line is still being
said, and a point it already made isn't said again.

Fair play: the screen is only captured while Dota sends spectator updates, as
it does in a replay (replay_view.ScreenGate). A live match of your own shuts it
at once, and this mode then says to use the live coach instead.
"""

from __future__ import annotations

import difflib
import logging
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from . import lessons as lessons_mod
from .replay_view import ScreenGate, find_slot, is_own_match, is_spectating, own_payload
from .speaker import HIGH, NORMAL
from .state import MatchState, Snapshot
from .vision import Frame, Grab

log = logging.getLogger(__name__)

MODES = ("moments", "continuous")
DEFAULT_INTERVAL = {"moments": 90.0, "continuous": 10.0}
# A frame every second (Castien, 2026-11-06), kept for this long.
FRAME_EVERY = 1.0
FRAMES_KEPT = 30
# At most this many frames go to the model per look, spread over the seconds
# it looks back on: more would be slow and overflow a 7B model's context.
FRAMES_PER_LOOK = 4
# How far back each kind of look reaches, in seconds.
LOOK_BACK = {"died": 10.0, "hurt": 6.0, "paused": 8.0, "regular": 30.0}
# Health lost within HURT_WINDOW seconds that counts as a fight going badly.
HURT_SHARE = 0.35
HURT_WINDOW = 3.0
# Moments closer together than this are one moment.
MOMENT_GAP = 12.0
# A reply this similar to one of the last few is a repeat and isn't said.
SAME = 0.6
# The coach comments on the past, so a line may wait a while for its turn.
MAX_DELAY = 30.0

DIED, HURT, PAUSED, REGULAR = "died", "hurt", "paused", "regular"
REASONS = {
    DIED: "The player died at the end of these seconds. Say what they did wrong just before it.",
    HURT: "The player lost a lot of health in these seconds. Say what went wrong.",
    PAUSED: "The player paused the replay here to talk about what just happened.",
    REGULAR: "Look over these seconds for the biggest mistake.",
}

SYSTEM = """\
You are a friendly Dota 2 coach watching a replay of the player's own game \
together with them, chatting casually. You get a few frames from the last \
seconds of the replay, oldest first, and the player's own numbers over those \
seconds. Talk over a mistake you can actually see, in the past tense, the way \
a coach talks a replay through: what they did, why it hurt them, and what \
would have been better. For example: "There you stayed at half health with \
three of them missing from the map. Backing off to the tower would have saved \
that death."

Rules:
- Only what the frames and numbers show. Never invent heroes, items or events.
- Only what the player could know in their game: their own screen and their \
team's vision. Never the scoreboard, enemy gold or net worth.
- Fit the advice to the game time. In the laning stage (before about 10:00) \
talk about last hits, denies, trading hits, creep equilibrium, staying near \
your creeps, runes and rotations; never tell them to leave their lane or \
move to another lane.
- Items: Magic Wand and Magic Stick charges are saved for fights and \
escapes (a fight over the lotus, a gank) and used when health is low; they \
have nothing to do with farming, last hits or denies. Potions and other \
items are for health, mana, fights and escapes. Only mention using an item \
when it would have changed a fight or a death, for example dying with wand \
charges still unused.
- Last hits are creeps the player finished for gold. A kill means an enemy \
hero died. Never call last hits kills.
- If nothing clearly went wrong, answer only: skip
- Don't repeat a point you already made, even in other words.
- One or two short sentences, at most 30 words, spoken aloud, no lists."""


class ReplayReview:
    """Feeds the coach your own hero from a replay and asks the vision model.

    `see` sits in front of the coach's state (gsi_server.Coach.replay); the
    object itself is a listener on that state; `tick` runs once a second.
    `ask(prompt, frames)` asks the vision model about several frames.
    """

    def __init__(
        self,
        accounts: set[int],
        hero: str | None,
        mode: str,
        ask: Callable[[str, list[Frame]], str | None] | None,
        grab: Grab,
        say: Callable[..., None],
        interval: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        run: Callable[[Callable[[], None]], None] | None = None,
        busy: Callable[[], bool] = lambda: False,
        lessons: list | None = None,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.accounts, self.hero, self.mode = accounts, hero, mode
        self.ask, self.grab, self.say, self.clock = ask, grab, say, clock
        self.speaking = busy
        self.lessons = lessons or []  # lesson cards from coaching videos (coach/lessons.py)
        self.interval = interval or DEFAULT_INTERVAL[mode]
        self.gate = ScreenGate(clock)
        self.where: tuple[str, str] | None = None
        self.snap = Snapshot()
        self.frames: deque[tuple[float, Frame]] = deque(maxlen=FRAMES_KEPT)
        # (time, snapshot) once a second, for the numbers behind each look.
        self.history: deque[tuple[float, Snapshot]] = deque(maxlen=FRAMES_KEPT)
        self.health: deque[tuple[float, int]] = deque()
        self.recent: deque[str] = deque(maxlen=6)
        self._run = run or (lambda job: threading.Thread(target=job, daemon=True).start())
        self._lock = threading.Lock()
        self._busy = False
        self._last_ask = clock()
        self._last_moment = -MOMENT_GAP
        self._last_frame = -FRAME_EVERY
        self._told: set[str] = set()
        self._focus = -1

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
        if cur.clock_time is not None and prev.clock_time is not None and cur.clock_time < prev.clock_time - 5:
            self._forget()  # the replay was rewound: those seconds are gone
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
        """Once a second: a frame and the numbers, and the regular looks."""
        if not self.gate.open or self.ask is None:
            self._forget()
            return
        now = self.clock()
        playing = self.snap.in_game and not self.snap.paused
        if playing and now - self._last_frame >= FRAME_EVERY:
            self._last_frame = now
            frame = self.grab()
            if frame is not None:
                self.frames.append((now, frame))
                self.history.append((now, self.snap))
        if playing and now - self._last_ask >= self.interval:
            self.look(REGULAR)

    def moment(self, reason: str) -> None:
        now = self.clock()
        if now - self._last_moment < MOMENT_GAP:
            return
        self._last_moment = now
        self.look(reason)

    def look(self, reason: str) -> bool:
        """Ask the model about the last seconds. False when the gate is
        shut, the model or the voice is busy, or there are no frames."""
        if self.ask is None or not self.gate.open or self.speaking():
            return False
        with self._lock:
            if self._busy:
                return False
            self._busy = True
        now = self.clock()
        since = max(now - LOOK_BACK[reason], self._last_ask) if reason == REGULAR else now - LOOK_BACK[reason]
        frames = [f for t, f in self.frames if t >= since] or [f for _, f in list(self.frames)[-1:]]
        if not frames:
            frame = self.grab()
            frames = [frame] if frame is not None else []
        if not frames:
            self._busy = False
            return False
        self._last_ask = now
        window = [snap for t, snap in self.history if t >= since] + [self.snap]
        unused = unused_at_death(window) if reason == DIED else []
        fought = any(s.kills > window[0].kills or s.deaths > window[0].deaths or not s.alive for s in window)
        prompt = self.prompt(reason, since, unused)
        picked = spread(frames, FRAMES_PER_LOOK)
        self._run(lambda: self._answer(prompt, picked, reason, unused, fought))
        return True

    def _answer(self, prompt: str, frames: list[Frame], reason: str, unused: list[str] | None = None,
                fought: bool = False) -> None:
        started = time.monotonic()
        try:
            reply = self.ask(prompt, frames)
        finally:
            self._busy = False
        took = f"{time.monotonic() - started:.0f} s"
        # Notes for the window, so the player sees why the coach is quiet.
        if not reply:
            log.info("Replay review: the vision model gave no answer (%s). Is Ollama running?", took)
            return
        if reply.strip(" .\"'").lower() in ("skip", "omitir") or not self.gate.open:
            log.info("Replay review: looked, nothing clearly went wrong (%s)", took)
            return
        # Small vision models tie items to farming ("use your wand to farm
        # creeps") and call last hits kills (Castien, 2026-11-06): those go.
        if items_for_farming(reply, self.snap):
            log.info("Replay review: dropped item advice about farming (%s): %s", took, reply)
            return
        if not fought and KILLS.search(reply):
            log.info("Replay review: dropped a line about kills that didn't happen (%s): %s", took, reply)
            return
        if self.repeats(reply):
            log.info("Replay review: dropped a repeat (%s): %s", took, reply)
            return
        if reason == REGULAR and time.monotonic() - started > self.interval:
            log.info("Replay review: the vision model took %s, longer than the %.0f s you set, so it looks "
                     "less often. Try the lighter model or a longer time.", took, self.interval)
        self.recent.append(reply)
        self.say(reply, priority=NORMAL if reason == REGULAR else HIGH, max_delay=MAX_DELAY)

    def repeats(self, reply: str) -> bool:
        words = _words(reply)
        return any(difflib.SequenceMatcher(None, words, _words(old)).ratio() >= SAME for old in self.recent)

    def prompt(self, reason: str, since: float, unused: list[str] | None = None) -> str:
        s = self.snap
        hero = (s.hero_name or "unknown").removeprefix("npc_dota_hero_").replace("_", " ")
        items = ", ".join(
            i.name.removeprefix("item_").replace("_", " ") + (f" ({i.charges} charges)" if i.charges else "")
            for i in s.items if i.slot.startswith("slot")
        )
        facts = [
            f"The player is {hero}, level {s.level}.",
            stage(s.clock_time),
            numbers([snap for t, snap in self.history if t >= since] + [s]),
            f"Items: {items}." if items else "",
            f"When they died they still had ready: {', '.join(unused)}." if unused else "",
            REASONS[reason],
            f"This time, look most at: {self.focus()}." if reason == REGULAR else "",
        ]
        examples = lessons_mod.matching(self.lessons, reason, stage_name(s.clock_time))
        if examples:
            facts.append("A real coach's lessons from similar moments, for how to think about it "
                         "(only use one if the frames show the same thing):")
            facts += [f"- {ex.text()}" for ex in examples]
        if self.recent:
            facts.append("Points you already made: " + " | ".join(self.recent))
        return "\n".join(f for f in facts if f)

    def focus(self) -> str:
        """A different thing to look at each regular look, so the coach
        notices different mistakes instead of one theme."""
        topics = FOCUS[stage_name(self.snap.clock_time)]
        self._focus = (self._focus + 1) % len(topics)
        return topics[self._focus]

    def _forget(self) -> None:
        self.frames.clear()
        self.history.clear()

    def _tell_once(self, key: str, text: str) -> None:
        if key not in self._told:
            self._told.add(key)
            log.warning("%s", text)


def spread(items: list, n: int) -> list:
    """Up to n items, evenly spread and always ending with the newest."""
    if len(items) <= n:
        return list(items)
    step = (len(items) - 1) / (n - 1)
    return [items[round(i * step)] for i in range(n)]


def stage(clock: int | None) -> str:
    if clock is None:
        return ""
    when = f"{clock // 60}:{clock % 60:02d}" if clock >= 0 else "before the horn"
    if clock < 600:
        return f"Game time {when}: the laning stage."
    if clock < 1800:
        return f"Game time {when}: the mid game."
    return f"Game time {when}: the late game."


# What a regular look focuses on, in turn, by stage of the game.
FOCUS = {
    "laning": ("last hits and denies", "trading hits with the enemy laner", "where you stood compared with your creeps",
               "the creep equilibrium (where the waves meet)", "the minimap and missing enemies",
               "using your spells well (mana, timing)"),
    "mid": ("where you farmed and how safe it was", "the minimap and missing enemies",
            "how you joined or avoided fights", "towers, Roshan and other objectives", "using your spells well"),
    "late": ("positioning in fights", "buyback and dying before objectives", "the minimap and missing enemies",
             "farming safe areas between fights", "using your spells and items in fights"),
}


def stage_name(clock: int | None) -> str:
    """The lesson cards' name for the stage: laning, mid or late."""
    if clock is None or clock < 600:
        return "laning"
    return "mid" if clock < 1800 else "late"


def numbers(snaps: list[Snapshot]) -> str:
    """The player's own numbers from the first to the last of these seconds."""
    snaps = [s for s in snaps if s.clock_time is not None and s.hero_name]
    if not snaps:
        return ""
    a, b = snaps[0], snaps[-1]

    def clock(s: Snapshot) -> str:
        return f"{s.clock_time // 60}:{s.clock_time % 60:02d}"

    parts = [f"health {a.health_percent:.0f}% to {b.health_percent:.0f}%"]
    if b.max_mana:
        parts.append(f"mana {100 * a.mana / max(a.max_mana, 1):.0f}% to {100 * b.mana / b.max_mana:.0f}%")
    parts.append(f"last hits {a.last_hits} to {b.last_hits}")
    parts.append(f"denies {a.denies} to {b.denies}")
    parts.append(f"gold {a.gold} to {b.gold}")
    deaths = b.deaths - a.deaths
    if deaths > 0 or not b.alive:
        parts.append("died" if deaths <= 1 else f"died {deaths} times")
    if b.kills > a.kills:
        parts.append(f"{b.kills - a.kills} kill(s)")
    span = f"From {clock(a)} to {clock(b)}" if b.clock_time != a.clock_time else f"At {clock(b)}"
    return f"{span}: " + ", ".join(parts) + "."


# Item words; the player's own item names are added.
ITEM_WORDS = {"wand", "stick", "item", "items", "potion", "salve", "tango", "tangos", "clarity", "mango",
              "faerie", "bottle", "varita", "objeto", "objetos", "poción", "pocion"}
# Farming words: an item in the same sentence as one of these is the wrong idea.
FARM_WORDS = {"farm", "farming", "farmed", "creep", "creeps", "last", "hit", "hits", "deny", "denies",
              "denying", "cs", "wave", "experience", "xp", "granjear", "farmear", "farmeo", "creeps",
              "súbditos", "subditos", "negar", "oleada"}
KILLS = re.compile(r"\b(kills?|asesinatos?|kill\s+gold)\b", re.IGNORECASE)
# Charges worth saving for a fight.
CHARGES_WORTH = 5


def items_for_farming(reply: str, snap: Snapshot) -> bool:
    """True when a sentence ties using an item to farming or last hits."""
    spells = {w for a in snap.abilities for w in a.name.split("_")}
    own = {w for i in snap.items for w in i.name.removeprefix("item_").split("_") if len(w) > 3} - spells
    for sentence in re.split(r"[.!?]+", reply):
        words = set(_words(sentence))
        if words & (ITEM_WORDS | own) and words & FARM_WORDS:
            return True
    return False


def unused_at_death(snaps: list[Snapshot]) -> list[str]:
    """Items and spells the player could still use right before dying."""
    alive = [s for s in snaps if s.alive and s.hero_name]
    if not alive:
        return []
    last = alive[-1]
    out = []
    for i in last.items:
        if not i.slot.startswith("slot") or not i.can_cast or i.cooldown:
            continue
        if i.name in ("item_magic_wand", "item_magic_stick") and (i.charges or 0) < CHARGES_WORTH:
            continue
        name = i.name.removeprefix("item_").replace("_", " ")
        out.append(f"{name} ({i.charges} charges)" if i.charges else name)
    for a in last.abilities:
        if a.can_cast and a.level and not a.cooldown:
            out.append(a.name.split("_", 1)[-1].replace("_", " "))
    return out


def _words(text: str) -> list[str]:
    return [w.strip(".,!?\"'").lower() for w in text.split()]
