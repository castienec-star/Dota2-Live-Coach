"""The app's Progress page: your MMR over time, your best heroes and your
recent matches.

- MMR: the player types it in the app. Each entry is kept in mmr.json (one per
  day, the last one wins) and also tells the coach the player's medal (the
  same rank.json the voice answer writes), so it stops asking. After
  ASK_EVERY_DAYS without an update the app asks for a fresh number.
- Heroes and matches: from the coach's own match recordings (coach/profile.py
  summarizes them), so nothing leaves the PC. Only the player's own hero and
  numbers are used. Each match links to its public OpenDota page by match id.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from . import rank as rank_mod
from .profile import MatchSummary, Profile

ASK_EVERY_DAYS = 3
MMR_FILE = "mmr.json"
RANK_FILE = "rank.json"  # PlayerRank's store (coach/__main__.make_rank)
MAX_MMR = 15000
OPENDOTA_MATCH = "https://www.opendota.com/matches/{}"


@dataclass(frozen=True)
class MmrPoint:
    day: str  # YYYY-MM-DD
    mmr: int


class MmrHistory:
    def __init__(self, app_dir: Path, today=date.today) -> None:
        self.file = app_dir / MMR_FILE
        self.rank_file = app_dir / RANK_FILE
        self._today = today

    def points(self) -> list[MmrPoint]:
        try:
            raw = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        out = []
        for entry in raw if isinstance(raw, list) else []:
            try:
                out.append(MmrPoint(str(date.fromisoformat(entry["day"])), int(entry["mmr"])))
            except (KeyError, TypeError, ValueError):
                continue
        return sorted(out, key=lambda p: p.day)

    def add(self, value) -> tuple[bool, str]:
        text = str(value).strip().replace(",", "").replace(".", "")
        if not text.isdigit() or not 0 < int(text) <= MAX_MMR:
            return False, f"Write your MMR as a number, like 2450."
        mmr = int(text)
        today = str(self._today())
        points = [p for p in self.points() if p.day != today] + [MmrPoint(today, mmr)]
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps([p.__dict__ for p in sorted(points, key=lambda p: p.day)]), encoding="utf-8")
        medal = rank_mod.from_mmr(mmr)
        if medal:  # the coach compares you with this medal and stops asking
            self.rank_file.write_text(json.dumps({"rank": medal, "asked": True}), encoding="utf-8")
        return True, f"Saved: {mmr} MMR ({rank_mod.name(medal)})." if medal else f"Saved: {mmr} MMR."

    def due(self) -> bool:
        """True when there is no MMR yet, or the last one is ASK_EVERY_DAYS old."""
        points = self.points()
        if not points:
            return True
        return (self._today() - date.fromisoformat(points[-1].day)).days >= ASK_EVERY_DAYS


def hero_label(key: str, names: dict[str, str]) -> str:
    return names.get(key) or key.replace("_", " ").title()


def hero_stats(matches: list[MatchSummary], names: dict[str, str], min_games: int = 1) -> list[dict]:
    """Per hero: games, wins and win rate (finished games only), average K/D/A.
    Most games first, then best win rate."""
    by_hero: dict[str, list[MatchSummary]] = {}
    for m in matches:
        by_hero.setdefault(m.hero, []).append(m)
    out = []
    for hero, games in by_hero.items():
        finished = [g for g in games if g.won is not None]
        if len(games) < min_games:
            continue
        wins = sum(1 for g in finished if g.won)
        out.append({
            "hero": hero,
            "name": hero_label(hero, names),
            "games": len(games),
            "wins": wins,
            "losses": len(finished) - wins,
            "win_rate": round(100 * wins / len(finished)) if finished else None,
            "kda": "/".join(f"{sum(getattr(g, k) for g in games) / len(games):.1f}" for k in ("kills", "deaths", "assists")),
        })
    out.sort(key=lambda h: (-h["games"], -(h["win_rate"] or 0)))
    return out


def match_rows(matches: list[MatchSummary], names: dict[str, str], limit: int = 30,
               heroes_by_key: dict | None = None, items: dict | None = None) -> list[dict]:
    rows = []
    for m in sorted(matches, key=lambda m: m.started, reverse=True)[:limit]:
        when = datetime.fromtimestamp(m.started) if m.started else None
        rows.append({
            "date": when.strftime("%Y-%m-%d %H:%M") if when else "",
            "hero": hero_label(m.hero, names),
            "result": {True: "Win", False: "Loss"}.get(m.won, "-"),
            "kda": f"{m.kills}/{m.deaths}/{m.assists}",
            "last_hits": "-" if m.last_hits is None else f"{m.last_hits}/{m.denies or 0}",
            "gpm": m.gpm if m.gpm is not None else "-",
            "xpm": m.xpm if m.xpm is not None else "-",
            "duration": f"{m.duration // 60}:{m.duration % 60:02d}",
            "link": OPENDOTA_MATCH.format(m.match_id) if m.match_id and str(m.match_id).isdigit() and m.match_id != "0" else "",
            "match_id": m.match_id or "",
            "account_id": m.account_id or "",
            "last_hits_10": m.last_hits_10,
            "deaths_early": sum(1 for t in m.death_times if t < 600),
            "notes": notes(m, heroes_by_key, items) if items is not None else [],
        })
    return rows


RECENT = 20  # games the trends and recommendations look at
MIN_HERO_GAMES = 3  # games on a hero before calling it a strength or weakness


def notes(m: MatchSummary, heroes_by_key: dict, items: dict) -> list[dict]:
    """What the coach would say about one match: the post-game review's
    points to fix, then what went well (coach/review.py)."""
    from . import review
    from .benchmarks import is_support

    support = is_support(heroes_by_key.get(m.hero))
    out = [{"tone": "fix", "kind": kind, "text": text} for kind, text in review.found_points(m, support, items)]
    out += [{"tone": "good", "kind": "praise", "text": text} for text in review.praise(m, support)]
    if not out:
        out.append({"tone": "good", "kind": "steady", "text": "A steady game with nothing big to fix."})
    return out


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def recommendations(matches: list[MatchSummary], heroes_by_key: dict, items: dict, names: dict[str, str]) -> list[dict]:
    """A few plain recommendations from the recent games, most useful first:
    the point to fix that keeps coming back, how deaths and last hits are
    trending, and which heroes win and lose most."""
    from . import review

    recent = sorted(matches, key=lambda m: m.started)[-RECENT:]
    if not recent:
        return []
    out = []
    counts = {kind: 0 for kind in review.NEXT_GAME}
    for m in recent:
        for item in notes(m, heroes_by_key, items):
            if item["kind"] in counts:
                counts[item["kind"]] += 1
    kind, times = max(counts.items(), key=lambda kv: kv[1])
    if times >= 2:
        what, tip = review.NEXT_GAME[kind]
        out.append({"tone": "fix", "title": f"{what}: your main thing to fix",
                    "text": f"It came up in {times} of your last {len(recent)} games. Next game, {tip}."})

    half = len(recent) // 2
    if half >= 3:
        before, after = recent[:half], recent[half:]
        d0, d1 = _mean([m.deaths for m in before]), _mean([m.deaths for m in after])
        if d1 <= d0 - 1:
            out.append({"tone": "good", "title": "Fewer deaths",
                        "text": f"You die {d1:.1f} times a game now, down from {d0:.1f}. Staying alive wins games: keep it up."})
        elif d1 >= d0 + 1:
            out.append({"tone": "fix", "title": "More deaths lately",
                        "text": f"You die {d1:.1f} times a game now, up from {d0:.1f}. Check the minimap before you walk forward, and back off when you're low."})
        l0 = _mean([m.last_hits_10 for m in before if m.last_hits_10 is not None])
        l1 = _mean([m.last_hits_10 for m in after if m.last_hits_10 is not None])
        if l0 is not None and l1 is not None and abs(l1 - l0) >= 5:
            better = l1 > l0
            out.append({"tone": "good" if better else "fix",
                        "title": "Last hits " + ("improving" if better else "dropping"),
                        "text": f"{l1:.0f} last hits at 10 minutes on average, {'up' if better else 'down'} from {l0:.0f}."
                        + ("" if better else " Five minutes of last hitting in a lobby before you queue helps.")})

    stats = [h for h in hero_stats(matches, names) if h["win_rate"] is not None and h["wins"] + h["losses"] >= MIN_HERO_GAMES]
    if stats:
        best = max(stats, key=lambda h: (h["win_rate"], h["games"]))
        if best["win_rate"] >= 55:
            out.append({"tone": "good", "title": f"Your best hero: {best['name']}",
                        "text": f"{best['win_rate']}% wins in {best['games']} games. Pick it when you want a win, like in ranked."})
        worst = min(stats, key=lambda h: (h["win_rate"], -h["games"]))
        if worst is not best and worst["win_rate"] <= 40:
            out.append({"tone": "fix", "title": f"{worst['name']} isn't working yet",
                        "text": f"{worst['win_rate']}% wins in {worst['games']} games. Practise it in unranked, or play your better heroes in ranked."})
    return out


def trend(matches: list[MatchSummary]) -> list[dict]:
    """The recent games, oldest first, for the trend chart."""
    return [
        {"date": datetime.fromtimestamp(m.started).strftime("%b %d") if m.started else "",
         "won": m.won, "deaths": m.deaths, "last_hits_10": m.last_hits_10, "gpm": m.gpm}
        for m in sorted(matches, key=lambda m: m.started)[-RECENT:]
    ]


# OpenDota's per-player benchmarks: how this game's numbers compare with
# everyone's games on the same hero (0.73 = better than 73%).
BENCHMARKS = {
    "gold_per_min": ("Gold per minute", "Farm the jungle camps next to your lane between waves."),
    "xp_per_min": ("Experience per minute", "Stay near creep waves and fights instead of walking around the map."),
    "last_hits_per_min": ("Last hits per minute", "Last hit every creep you can; push a wave out, then take a camp."),
    "kills_per_min": ("Kills per minute", "Join fights your team starts near you; look for kills after your team wins a fight."),
    "hero_damage_per_min": ("Hero damage per minute", "Use your spells in fights, and stay close enough to hit."),
    "tower_damage": ("Tower damage", "After a won fight, hit towers before going back to farm."),
}
OWN_STATS = (
    ("net_worth", "Net worth"), ("hero_damage", "Hero damage"), ("tower_damage", "Tower damage"),
    ("hero_healing", "Healing"), ("obs_placed", "Observer wards"), ("sen_placed", "Sentry wards"),
    ("camps_stacked", "Camps stacked"), ("rune_pickups", "Runes taken"), ("stuns", "Stun seconds"),
)


def match_details(get, match_id: str, account_id: str | None) -> dict:
    """The player's own row of OpenDota's public match page: extra numbers and
    how they rank against everyone on that hero, with a tip for the weakest.
    get is OpenDota.get. Other players' rows are not used."""
    from .opendota import account_id as to_account

    me = to_account(account_id)
    if not str(match_id).isdigit() or me is None:
        return {"ok": False, "message": "This match has no match id or account id to look up."}
    try:
        match = get(f"matches/{match_id}")
    except Exception:  # offline, rate limited, a changed reply
        match = None
    row = next((p for p in (match or {}).get("players", []) if p.get("account_id") == me), None)
    if row is None:
        return {"ok": False, "message": "OpenDota doesn't have this match for you yet. It needs "
                "\"Expose Public Match Data\" on in Dota's settings, and can take a few minutes after the game."}
    stats = [{"label": label, "value": round(row[key]) if isinstance(row[key], float) else row[key]}
             for key, label in OWN_STATS if isinstance(row.get(key), (int, float))]
    ranks = []
    for key, (label, tip) in BENCHMARKS.items():
        pct = (row.get("benchmarks") or {}).get(key, {}).get("pct")
        if isinstance(pct, (int, float)):
            ranks.append({"key": key, "label": label, "pct": round(100 * pct), "tip": tip})
    tips = [f"{r['label']}: better than only {r['pct']}% of games on this hero. {r['tip']}"
            for r in sorted(ranks, key=lambda r: r["pct"])[:2] if r["pct"] < 40]
    best = max(ranks, key=lambda r: r["pct"]) if ranks else None
    if best and best["pct"] >= 70:
        tips.append(f"{best['label']}: better than {best['pct']}% of games on this hero. That's a strength.")
    return {"ok": True, "stats": stats, "ranks": ranks, "tips": tips}


def summary(app_dir: Path, record_dir: Path, today=date.today) -> dict:
    """Everything the Progress page shows."""
    from .heroes import load_heroes
    from .items import load_items

    history = MmrHistory(app_dir, today)
    points = history.points()
    heroes_by_key = {h.key: h for h in load_heroes().values()}
    names = {k: h.name for k, h in heroes_by_key.items()}
    items = load_items()
    matches = Profile(record_dir, app_dir / "profile.json", items).update()
    finished = [m for m in matches if m.won is not None]
    return {
        "mmr": [p.__dict__ for p in points],
        "mmr_due": history.due(),
        "medal": rank_mod.name(rank_mod.from_mmr(points[-1].mmr)) if points else "",
        "ask_every_days": ASK_EVERY_DAYS,
        "heroes": hero_stats(matches, names),
        "matches": match_rows(matches, names, heroes_by_key=heroes_by_key, items=items),
        "recommendations": recommendations(matches, heroes_by_key, items, names),
        "trend": trend(matches),
        "games": len(matches),
        "wins": sum(1 for m in finished if m.won),
        "finished": len(finished),
        "updated": time.time(),
    }
