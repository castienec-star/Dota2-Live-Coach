"""Draft analysis: what your lineup is good and bad at, counters, and timings.

Only heroes you can see in the draft are used, with public aggregate numbers
for those heroes (the same kind of information Dota Plus gives).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from .heroes import HeroInfo
from .opendota import OpenDota

MIN_MATCHUP_GAMES = 20
MIN_DURATION_GAMES = 30
WINDOW_EDGE = 0.02  # win-rate lead that counts as a team's window
FIRST_MINUTE, LAST_MINUTE = 10, 55


@dataclass
class Draft:
    allies: list[HeroInfo] = field(default_factory=list)
    enemies: list[HeroInfo] = field(default_factory=list)
    me: HeroInfo | None = None

    def with_me(self) -> Draft:
        """The same draft with your own hero always counted among your allies."""
        allies = list(self.allies)
        if self.me and self.me not in allies:
            allies.insert(0, self.me)
        return Draft(allies[:5], self.enemies[:5], self.me)


@dataclass(frozen=True)
class Window:
    start: int  # game minute
    end: int
    ours: bool  # True when your lineup is the stronger one


@dataclass
class Analysis:
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    enemy_traits: list[str] = field(default_factory=list)
    counters: list[str] = field(default_factory=list)
    windows: list[Window] = field(default_factory=list)

    def timing_lines(self) -> list[str]:
        lines = []
        for w in self.windows:
            if w.ours:
                lines.append(f"Your lineup is strongest from about {w.start} to {w.end} minutes.")
            else:
                lines.append(f"The enemy lineup is strongest from about {w.start} to {w.end} minutes.")
        return lines


def count_roles(team: list[HeroInfo]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for hero in team:
        for role in hero.roles:
            counts[role] = counts.get(role, 0) + 1
    return counts


def team_traits(team: list[HeroInfo]) -> tuple[list[str], list[str]]:
    """(strengths, weaknesses) of a lineup from its heroes' roles."""
    if len(team) < 3:
        return [], []
    roles = count_roles(team)
    good, bad = [], []
    if roles.get("Disabler", 0) >= 3:
        good.append("lots of stuns and disables")
    elif roles.get("Disabler", 0) <= 1:
        bad.append("little crowd control")
    if roles.get("Initiator", 0) >= 2:
        good.append("strong initiation")
    elif roles.get("Initiator", 0) == 0:
        bad.append("no clear initiator to start fights")
    if roles.get("Pusher", 0) >= 2:
        good.append("fast tower pushing")
    elif roles.get("Pusher", 0) == 0:
        bad.append("slow at taking towers")
    if roles.get("Durable", 0) >= 2:
        good.append("a tanky front line")
    elif roles.get("Durable", 0) == 0:
        bad.append("a fragile front line")
    if roles.get("Nuker", 0) >= 3:
        good.append("high burst damage")
    if roles.get("Carry", 0) >= 3:
        good.append("lots of late game power")
    elif roles.get("Carry", 0) <= 1:
        bad.append("not much late game carry power")
    if sum(h.attack_type == "Melee" for h in team) >= 4:
        bad.append("mostly melee heroes, so kiting hurts")
    return good, bad


def enemy_advice(enemies: list[HeroInfo]) -> list[str]:
    """What to prepare for, from the enemy lineup's roles."""
    if len(enemies) < 3:
        return []
    roles = count_roles(enemies)
    advice = []
    if roles.get("Disabler", 0) >= 3:
        advice.append("The enemy has a lot of disables: spread out in fights and think about Black King Bar.")
    if roles.get("Nuker", 0) >= 3:
        advice.append("The enemy has a lot of magic burst: don't get caught alone with low health.")
    if roles.get("Pusher", 0) >= 2:
        advice.append("The enemy pushes towers fast: answer their pushes early.")
    if roles.get("Escape", 0) >= 3:
        advice.append("The enemy heroes are slippery: save your disables to lock them down.")
    if roles.get("Carry", 0) >= 3:
        advice.append("The enemy scales into the late game: try to end before they come online.")
    return advice


def _base_rate(rows: dict[int, tuple[int, int]]) -> float | None:
    games = sum(g for g, _ in rows.values())
    return sum(w for _, w in rows.values()) / games if games else None


def counter_lines(draft: Draft, stats: OpenDota) -> list[str]:
    """Which visible enemies your heroes struggle against, from public win rates."""
    if not draft.enemies or not draft.allies:
        return []
    # edge[a][e]: how much better (or worse) ally a does against enemy e than usual.
    edge: dict[int, dict[int, float]] = {}
    for ally in draft.allies:
        rows = stats.matchups(ally.id)
        base = _base_rate(rows)
        if base is None:
            continue
        edge[ally.id] = {
            e.id: rows[e.id][1] / rows[e.id][0] - base
            for e in draft.enemies
            if rows.get(e.id, (0, 0))[0] >= MIN_MATCHUP_GAMES
        }
    if not edge:
        return []
    lines = []
    threat = {
        e: mean(v[e.id] for v in edge.values() if e.id in v)
        for e in draft.enemies
        if any(e.id in v for v in edge.values())
    }
    if threat:
        worst = min(threat, key=threat.get)
        if threat[worst] < -0.01:
            lines.append(f"{worst.name} is the hardest enemy for your lineup overall.")
        best = max(threat, key=threat.get)
        if threat[best] > 0.01 and best != worst:
            lines.append(f"Your lineup does well against {best.name}; punish them.")
    mine = edge.get(draft.me.id, {}) if draft.me else {}
    if mine:
        enemies = {e.id: e for e in draft.enemies}
        hard = min(mine, key=mine.get)
        if mine[hard] < -0.02:
            lines.append(f"{enemies[hard].name} counters your {draft.me.name}; be careful around them.")
        easy = max(mine, key=mine.get)
        if mine[easy] > 0.02 and easy != hard:
            lines.append(f"Your {draft.me.name} does well against {enemies[easy].name}.")
    return lines


def _team_curve(team: list[HeroInfo], stats: OpenDota) -> dict[int, float]:
    """Per 5-minute game length: how much better than usual the lineup does."""
    by_minute: dict[int, list[float]] = {}
    for hero in team:
        rows = stats.durations(hero.id)
        base = _base_rate(rows)
        if base is None:
            continue
        for minute, (games, wins) in rows.items():
            if games >= MIN_DURATION_GAMES and FIRST_MINUTE <= minute <= LAST_MINUTE:
                by_minute.setdefault(minute, []).append(wins / games - base)
    return {m: mean(v) for m, v in by_minute.items()}


def power_windows(draft: Draft, stats: OpenDota) -> list[Window]:
    """Stretches of the game where one lineup does clearly better than the other."""
    if not draft.allies or not draft.enemies:
        return []
    ours, theirs = _team_curve(draft.allies, stats), _team_curve(draft.enemies, stats)
    minutes = sorted(set(ours) & set(theirs))
    windows: list[Window] = []
    for minute in minutes:
        lead = ours[minute] - theirs[minute]
        if abs(lead) < WINDOW_EDGE:
            continue
        side = lead > 0
        last = windows[-1] if windows else None
        if last and last.ours == side and last.end == minute:
            windows[-1] = Window(last.start, minute + 5, side)
        else:
            windows.append(Window(minute, minute + 5, side))
    return windows


def analyse(draft: Draft, stats: OpenDota | None) -> Analysis:
    draft = draft.with_me()
    strengths, weaknesses = team_traits(draft.allies)
    analysis = Analysis(strengths, weaknesses, enemy_advice(draft.enemies))
    if stats is not None:
        analysis.counters = counter_lines(draft, stats)
        analysis.windows = power_windows(draft, stats)
    return analysis
