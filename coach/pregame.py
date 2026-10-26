"""The spoken briefing before the horn.

When the match reaches the pre-game countdown, the coach works out the draft
(from the top bar if you turned that on, or from picks you typed), analyses
it, adds what it has learned about how you play, and speaks a short briefing.
The timings it finds are handed to the in-game reminders.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import llm
from .draft import Analysis, Draft, analyse
from .heroes import HeroIndex, HeroInfo
from .opendota import OpenDota, account_id
from .profile import Profile
from .rules.windows import PowerWindows
from .state import PRE_GAME, MatchState, Snapshot

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a Dota 2 coach talking to a player through their headset in the last \
seconds before the game starts. Turn the facts below into one spoken briefing \
of at most {words} words of plain English: your team's main strength, its main \
weakness, the enemy hero or threat to watch, and when to fight. If facts about \
the player's own habits are given, add one personal tip from them. Use only the \
facts given: do not invent heroes, items or numbers. No lists, headings or emoji."""

# Reads the ten top-bar heroes: Radiant left to right, then Dire. None = unknown.
Reader = Callable[[], "list[int | None] | None"]


def facts(snap: Snapshot, draft: Draft, analysis: Analysis, personal: list[str]) -> str:
    lines = []
    if draft.me:
        lines.append(f"Player's hero: {draft.me.name}")
    allies = [h.name for h in draft.allies if h != draft.me]
    if allies:
        lines.append("Allies: " + ", ".join(allies))
    if draft.enemies:
        lines.append("Enemies: " + ", ".join(h.name for h in draft.enemies))
    if analysis.strengths:
        lines.append("Team strengths: " + "; ".join(analysis.strengths))
    if analysis.weaknesses:
        lines.append("Team weaknesses: " + "; ".join(analysis.weaknesses))
    lines += analysis.enemy_traits + analysis.counters + analysis.timing_lines()
    if personal:
        lines.append("About the player's own games:")
        lines += personal
    return "\n".join(lines)


def builtin_briefing(analysis: Analysis, personal: list[str]) -> str:
    """A briefing put together from the facts directly, when no model answers."""
    parts = []
    if analysis.strengths:
        parts.append(f"Your team has {analysis.strengths[0]}.")
    if analysis.weaknesses:
        parts.append(f"Watch out: {analysis.weaknesses[0]}.")
    parts += analysis.counters[:1] + analysis.enemy_traits[:1] + analysis.timing_lines()[:2]
    parts += [p for p in personal if "weak spot" in p or "Most of your deaths" in p][:1]
    return " ".join(parts) or "Good luck. Play safe in lane and watch the minimap."


class Pregame:
    def __init__(
        self,
        say: Callable[[str], None],
        index: HeroIndex,
        windows: PowerWindows | None = None,
        stats: OpenDota | None = None,
        profile: Profile | None = None,
        ask: llm.Ask | None = None,
        reader: Reader | None = None,
        my_history: bool = True,
        capture_delay: float = 2.0,
        retry_delay: float = 5.0,
    ) -> None:
        self.say = say
        self.index = index
        self.windows = windows
        self.stats = stats
        self.profile = profile
        self.ask = ask
        self.reader = reader
        self.my_history = my_history
        self.capture_delay = capture_delay
        self.retry_delay = retry_delay
        self.typed_allies: list[HeroInfo] = []
        self.typed_enemies: list[HeroInfo] = []
        self.state: MatchState | None = None
        self._match = 0  # bumped on each new match, to drop a stale briefing
        self._briefed = False
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pregame")

    def __call__(self, state: MatchState) -> None:
        self.state = state
        if state.new_match:
            self._match += 1
            self._briefed = False
            self.typed_allies, self.typed_enemies = [], []
        cur = state.current
        if cur.game_state == PRE_GAME and not self._briefed:
            self._briefed = True
            self._pool.submit(self._brief, cur, self._match, True)

    def typed(self, line: str) -> str:
        """Picks typed in the coach window: "vs am cm lion" or "with luna pudge"."""
        words = line.strip().split(maxsplit=1)
        if not words:
            return ""
        command, rest = words[0].lower(), words[1] if len(words) > 1 else ""
        if command == "clear":
            self.typed_allies, self.typed_enemies = [], []
            return "Typed picks cleared."
        if command not in ("vs", "with"):
            return 'Type "vs" or "with" and hero names, e.g.  vs am cm lion pudge sf'
        heroes, unknown = self.index.parse(rest)
        if command == "vs":
            self.typed_enemies = heroes
        else:
            self.typed_allies = heroes
        reply = f"{'Enemies' if command == 'vs' else 'Allies'}: " + (
            ", ".join(h.name for h in heroes) or "none"
        )
        if unknown:
            reply += f"  (not recognised: {', '.join(unknown)})"
        # Picks typed during the countdown get a fresh briefing.
        state = self.state
        if state is not None and state.current.game_state == PRE_GAME and self._briefed:
            self._pool.submit(self._brief, state.current, self._match, False)
        return reply

    def draft(self, snap: Snapshot) -> Draft:
        me = self.index.by_key(snap.hero_name)
        allies, enemies = [], []
        if self.reader is not None:
            allies, enemies = self._read_top_bar(snap, me)
        return Draft(self.typed_allies or allies, self.typed_enemies or enemies, me)

    def _read_top_bar(self, snap: Snapshot, me: HeroInfo | None) -> tuple[list, list]:
        try:
            ids = self.reader() or []
        except Exception as exc:  # a failed capture must never stop the coach
            log.warning("Could not read the top bar: %s", exc)
            return [], []
        heroes = [self.index.heroes.get(i) if i is not None else None for i in ids]
        radiant = [h for h in heroes[:5] if h]
        dire = [h for h in heroes[5:10] if h]
        log.info(
            "Top bar: Radiant %s | Dire %s",
            ", ".join(h.name for h in radiant) or "-",
            ", ".join(h.name for h in dire) or "-",
        )
        allies, enemies = (dire, radiant) if snap.team == "dire" else (radiant, dire)
        if me is not None and me in enemies and me not in allies:
            allies, enemies = enemies, allies
        return allies, enemies

    def personal(self, snap: Snapshot, me: HeroInfo | None) -> list[str]:
        lines = []
        if self.profile is not None:
            try:
                self.profile.update()
                lines += self.profile.describe(snap.hero_name)
            except OSError as exc:
                log.warning("Could not read your recordings: %s", exc)
        account = account_id(snap.account_id)
        if self.my_history and self.stats is not None and me is not None and account:
            games, wins = self.stats.player_heroes(account).get(me.id, (0, 0))
            if games >= 3:
                lines.append(
                    f"Your public match history on {me.name}: {games} games, "
                    f"{round(100 * wins / games)} percent won."
                )
        return lines

    def _brief(self, snap: Snapshot, match: int, first: bool) -> None:
        if first and self.reader is not None:
            time.sleep(self.capture_delay)  # let the top bar finish loading
            draft = self.draft(snap)
            # Heroes may still be loading in: one more look if some are missing.
            if len(draft.allies) + len(draft.enemies) < 10 and not (
                self.typed_allies and self.typed_enemies
            ):
                time.sleep(self.retry_delay)
                retry = self.draft(snap)
                if len(retry.allies) + len(retry.enemies) > len(draft.allies) + len(draft.enemies):
                    draft = retry
        else:
            draft = self.draft(snap)
        analysis = analyse(draft, self.stats)
        if self.windows is not None:
            self.windows.set(analysis.windows)
        personal = self.personal(snap, draft.me)
        text = self.ask(facts(snap, draft.with_me(), analysis, personal)) if self.ask else None
        text = text or builtin_briefing(analysis, personal)
        state = self.state
        # Say it only for this match and before the game is well under way.
        if match == self._match and (state is None or (state.current.clock_time or 0) < 30):
            self.say(text)

    def close(self) -> None:
        self._pool.shutdown(wait=True)


def build(
    settings: dict,
    say: Callable[[str], None],
    windows: PowerWindows | None,
    app_dir: Path,
    record_dir: Path,
    capture: bool = True,
) -> Pregame | None:
    options = dict(settings)
    if not options.get("enabled", True):
        return None
    index = HeroIndex()
    words = int(options.get("words", 70))
    provider = options.get("provider", "ollama")
    if provider == "ollama":
        ask = llm.ollama_asker(
            options.get("ollama_model", "llama3.1:8b"),
            options.get("ollama_url", "http://127.0.0.1:11434"),
            float(options.get("timeout", 20)),
            SYSTEM_PROMPT.format(words=words),
            num_predict=words * 2,
            label="Briefing",
        )
    elif provider == "builtin":
        ask = None
    else:
        raise ValueError(f"pregame provider must be ollama or builtin, not {provider!r}")
    stats = OpenDota(app_dir / "opendota") if options.get("opendota", True) else None
    profile = Profile(record_dir, app_dir / "profile.json") if options.get("learn", True) else None
    capture_settings = options.get("capture", {})
    reader = None
    if capture and capture_settings.get("enabled", False):
        from .capture import make_reader

        reader = make_reader(capture_settings, index.heroes, app_dir / "hero_images")
    return Pregame(
        say,
        index,
        windows,
        stats,
        profile,
        ask,
        reader,
        my_history=bool(options.get("my_history", True)),
        capture_delay=float(capture_settings.get("delay", 2)),
    )
