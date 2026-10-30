"""The spoken briefing before the horn.

When the match reaches the pre-game countdown, the coach works out the draft
(from what you told it out loud or typed), analyses it, adds what it has
learned about how you play, and speaks a short briefing. The timings it finds
are handed to the in-game reminders. It never looks at your screen.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import knowledge, llm
from .grounding import Grounding
from .draft import Analysis, Draft, analyse
from .heroes import HeroIndex, HeroInfo
from .lineup import POSITIONS
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
the player's own habits are given, add one personal tip from them. No lists, \
headings or emoji.

Strict rules, because the player will hear any mistake:
- Name only heroes listed in the facts. Never name any other hero.
- If allies or enemies are "not known", say nothing about teammates or enemies.
- Use only numbers that appear in the facts. Never make up a time to fight or push.
- Dota has no junglers. Don't give anyone a role the facts don't give.
- The game hasn't started: never say something already happened in it.
- Don't invent strengths, weaknesses, items or habits that the facts don't state.
- "What the heroes do" is correct for this patch: use it to judge threats, and \
name only abilities listed there."""

def facts(
    snap: Snapshot, draft: Draft, analysis: Analysis, personal: list[str], position: int = 0
) -> str:
    lines = []
    if draft.me:
        lines.append(f"Player's hero: {draft.me.name}")
    if position in POSITIONS:
        lines.append(f"Player's position: {position} ({POSITIONS[position]})")
    allies = [h.name for h in draft.allies if h != draft.me]
    lines.append("Allies: " + (", ".join(allies) if allies else "not known"))
    lines.append("Enemies: " + (", ".join(h.name for h in draft.enemies) if draft.enemies else "not known"))
    if analysis.strengths:
        lines.append("Team strengths: " + "; ".join(analysis.strengths))
    if analysis.weaknesses:
        lines.append("Team weaknesses: " + "; ".join(analysis.weaknesses))
    lines += analysis.enemy_traits + analysis.counters + analysis.timing_lines()
    if personal:
        lines.append("About the player's own games:")
        lines += personal
    # The player's hero and the enemies in full; for allies, their ultimates.
    cards = knowledge.hero_cards([draft.me, *draft.enemies])
    cards += knowledge.hero_cards([h for h in draft.allies if h != draft.me], ultimate_only=True)
    if cards:
        lines.append("What the heroes do:")
        lines += cards
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
        my_history: bool = True,
        waiting: Callable[[], bool] | None = None,
        wait_limit: float = 45.0,
    ) -> None:
        """waiting() is true while the start-of-game questions are still being
        asked; the briefing waits for them, up to wait_limit seconds."""
        self.say = say
        self.index = index
        self.windows = windows
        self.stats = stats
        self.profile = profile
        self.ask = ask
        self.my_history = my_history
        self.waiting = waiting
        self.wait_limit = wait_limit
        # What the player told the coach this match, out loud or typed.
        self.allies: list[HeroInfo] = []
        self.enemies: list[HeroInfo] = []
        self.position = 0  # 1 to 5, 0 = not known
        self.state: MatchState | None = None
        self._match = 0  # bumped on each new match, to drop a stale briefing
        self._briefed = False
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pregame")
        self._grounding = Grounding(index)

    def __call__(self, state: MatchState) -> None:
        self.state = state
        if state.new_match:
            self._match += 1
            self._briefed = False
            self.allies, self.enemies, self.position = [], [], 0
        cur = state.current
        if cur.game_state == PRE_GAME and not self._briefed:
            self._briefed = True
            self._pool.submit(self._brief, cur, self._match, True)

    def typed(self, line: str) -> str:
        """Typed in the coach window: "vs am cm lion", "with luna pudge" or "pos 4"."""
        words = line.strip().split(maxsplit=1)
        if not words:
            return ""
        command, rest = words[0].lower(), words[1] if len(words) > 1 else ""
        if command == "clear":
            self.allies, self.enemies = [], []
            return "Typed picks cleared."
        if command == "pos":
            position = int(rest) if rest.strip() in ("1", "2", "3", "4", "5") else 0
            if not position:
                return "Type your position as a number, e.g.  pos 4"
            self.heard(position=position)
            return f"Position {position}: {POSITIONS[position]}"
        if command not in ("vs", "with"):
            return 'Type "vs" or "with" and hero names, e.g.  vs am cm lion pudge sf'
        heroes, unknown = self.index.parse(rest)
        if command == "vs":
            self.heard(enemies=heroes)
        else:
            self.heard(allies=heroes)
        reply = f"{'Enemies' if command == 'vs' else 'Allies'}: " + (
            ", ".join(h.name for h in heroes) or "none"
        )
        if unknown:
            reply += f"  (not recognised: {', '.join(unknown)})"
        return reply

    def heard(
        self,
        position: int | None = None,
        allies: list[HeroInfo] | None = None,
        enemies: list[HeroInfo] | None = None,
    ) -> None:
        """What the player said or typed; picks given during the countdown,
        after the briefing, get a fresh one."""
        if position is not None:
            self.position = position
        if allies is not None:
            self.allies = list(allies)
        if enemies is not None:
            self.enemies = list(enemies)
        state = self.state
        changed = allies is not None or enemies is not None
        if changed and state is not None and state.current.game_state == PRE_GAME and self._briefed:
            if not (self.waiting and self.waiting()):
                self._pool.submit(self._brief, state.current, self._match, False)

    def draft(self, snap: Snapshot) -> Draft:
        return Draft(self.allies, self.enemies, self.index.by_key(snap.hero_name))

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
        if first and self.waiting is not None:
            # Let the player finish answering the start-of-game questions.
            deadline = time.monotonic() + self.wait_limit
            while self.waiting() and time.monotonic() < deadline and match == self._match:
                time.sleep(0.5)
        draft = self.draft(snap)
        analysis = analyse(draft, self.stats)
        if self.windows is not None:
            self.windows.set(analysis.windows)
        personal = self.personal(snap, draft.me)
        text = self._model_briefing(snap, draft, analysis, personal)
        text = text or builtin_briefing(analysis, personal)
        state = self.state
        # Say it only for this match and before the game is well under way.
        if match == self._match and (state is None or (state.current.clock_time or 0) < 30):
            self.say(text)

    def _model_briefing(
        self, snap: Snapshot, draft: Draft, analysis: Analysis, personal: list[str]
    ) -> str | None:
        """The model's briefing, or None when it has nothing real to work
        from or says something the facts don't back."""
        if self.ask is None:
            return None
        if not (draft.allies or draft.enemies or personal):
            log.info("Briefing: picks not known yet, so the written briefing is used")
            return None
        prompt = facts(snap, draft.with_me(), analysis, personal, self.position)
        text = self.ask(prompt)
        if not text:
            return None
        problem = self._grounding.problem(
            text,
            prompt,
            [draft.me, *draft.allies, *draft.enemies],
            allies_known=bool([h for h in draft.allies if h != draft.me]),
            enemies_known=bool(draft.enemies),
        )
        if problem:
            log.info("Briefing from the model dropped (it %s): %s", problem, text)
            return None
        return text

    def close(self) -> None:
        self._pool.shutdown(wait=True)


def build(
    settings: dict,
    say: Callable[[str], None],
    windows: PowerWindows | None,
    app_dir: Path,
    record_dir: Path,
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
            temperature=0.2,
        )
    elif provider == "builtin":
        ask = None
    else:
        raise ValueError(f"pregame provider must be ollama or builtin, not {provider!r}")
    stats = OpenDota(app_dir / "opendota") if options.get("opendota", True) else None
    profile = Profile(record_dir, app_dir / "profile.json") if options.get("learn", True) else None
    return Pregame(
        say,
        index,
        windows,
        stats,
        profile,
        ask,
        my_history=bool(options.get("my_history", True)),
    )
