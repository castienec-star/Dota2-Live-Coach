"""Your rank, and what players of your rank reach, for fair comparisons.

A Herald and a Legend shouldn't be held to the same numbers. GSI doesn't
send your medal or MMR, so the coach learns it from you: say "hey coach, my
rank is Archon" (or "my MMR is 2500"), answer the one-time question at the
start of a game, or set [player] rank in coach.toml. Failing those, it reads
the medal on your own public OpenDota profile, like the briefing reads your
own match history. Other players' profiles are never looked up.

Once your medal is known, you are compared only with players of that medal
(a Legend 3 only with Legends). Their numbers come from public matches: a
sample of recent ranked matches of each medal on the current patch, read
from OpenDota's public match data (`py -m coach refresh-brackets` rewrites
coach/data/brackets.json). From each match it keeps every player's gold,
experience and last hits per minute, by hero and as cores (the three with
most last hits on each team) or supports, saved at the same percentiles as
coach/data/benchmarks.json. A hero played often enough in your medal is
compared with itself; otherwise with your medal's cores or supports.

The file is plain numbers so other parts of the coach (such as the local
model's facts) can quote them: see describe().
"""

from __future__ import annotations

import functools
import json
import logging
import re
import threading
import time
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

BRACKETS_FILE = Path(__file__).resolve().parent / "data" / "brackets.json"

# Medal by the tens digit of Dota's rank tier (Archon 3 is tier 43).
RANKS = {
    1: "herald",
    2: "guardian",
    3: "crusader",
    4: "archon",
    5: "legend",
    6: "ancient",
    7: "divine",
    8: "immortal",
}
TIERS = {name: tier for tier, name in RANKS.items()}
# Each medal is five stars of about 154 MMR (Herald 1 starts at 0, Immortal
# at about 5620). Approximate: Valve doesn't publish the exact borders.
MMR_PER_MEDAL = 770
# Speech-to-text spellings of the medal names.
_SOUNDS = {
    "herald": "herald", "harold": "herald", "herold": "herald", "heralds": "herald",
    "guardian": "guardian", "guardians": "guardian", "gardian": "guardian",
    "crusader": "crusader", "crusaders": "crusader", "crusade": "crusader",
    "archon": "archon", "archons": "archon", "arkon": "archon", "archan": "archon",
    "arcon": "archon", "archen": "archon", "arkan": "archon",
    "legend": "legend", "legends": "legend",
    "ancient": "ancient", "ancients": "ancient", "ancien": "ancient",
    "divine": "divine", "devine": "divine", "divines": "divine",
    "immortal": "immortal", "immortals": "immortal", "imortal": "immortal",
}
_MMR = re.compile(r"\b(\d{1,2}(?:[.,]\d)?)\s*k\b|\b(\d{1,2}[,.]?\d{3}|\d{3,4})\b")

METRICS = ("gold_per_min", "xp_per_min", "last_hits_per_min")
PERCENTILES = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99]
# The rank tiers each sampled group covers. Few players are Immortal, so
# Divine's sample covers both.
GROUPS = {name: (tier * 10, tier * 10 + 9) for tier, name in RANKS.items() if tier < 7}
GROUPS["divine"] = (70, 89)
RANKED_LOBBY = 7
TURBO = 23
MIN_DURATION = 15 * 60  # shorter games are stomps or abandons
CORES_PER_TEAM = 3


def name(rank: str | None) -> str:
    """ "archon" -> "Archon"."""
    return (rank or "").capitalize()


def from_tier(tier: Any) -> str | None:
    """The medal from Dota's rank tier (43 = Archon 3), or None."""
    try:
        return RANKS.get(int(tier) // 10)
    except (TypeError, ValueError):
        return None


def from_mmr(mmr: int) -> str | None:
    if mmr < 0 or mmr > 15000:
        return None
    return RANKS[min(8, 1 + mmr // MMR_PER_MEDAL)]


def parse(text: Any) -> str | None:
    """The medal from what the player said or set: "Archon", "archon 3",
    "I'm an arkon", "2500", "my MMR is 2,500", "2.5k". None if neither."""
    if isinstance(text, int):
        return from_mmr(text)
    folded = str(text or "").lower()
    for word in re.findall(r"[a-z]+", folded):
        if word in _SOUNDS:
            return _SOUNDS[word]
    match = _MMR.search(folded)
    if match:
        if match.group(1):
            return from_mmr(round(float(match.group(1).replace(",", ".")) * 1000))
        return from_mmr(int(re.sub(r"[,.]", "", match.group(2))))
    return None


class PlayerRank:
    """Which medal to compare the player with.

    In order: what the player said (kept in "store", so it lasts between
    games), [player] rank in coach.toml, then the medal on their own public
    OpenDota profile. Add it as a GSI listener so it can read the profile
    once it sees the account id; "lookup" is OpenDota.player_rank.
    """

    def __init__(
        self,
        configured: Any = "",
        store: Path | None = None,
        lookup: Callable[[int], Any] | None = None,
    ) -> None:
        self.configured = parse(configured) if configured not in ("", 0, None) else None
        if configured not in ("", 0, None) and self.configured is None:
            log.warning("[player] rank = %r isn't a medal or an MMR; it is ignored", configured)
        self.store = store
        self.lookup = lookup
        self.looked_up: str | None = None
        self._account: int | None = None
        self._lock = threading.Lock()
        saved = self._read()
        self.told = saved.get("rank") if saved.get("rank") in TIERS else None
        self.asked = bool(saved.get("asked"))

    def __call__(self, state) -> None:
        if self.lookup is None or self.told or self.configured:
            return
        from .opendota import account_id

        account = account_id(state.current.account_id)
        with self._lock:
            if account is None or account == self._account:
                return
            self._account = account
        threading.Thread(target=self._look_up, args=(account,), name="rank", daemon=True).start()

    def _look_up(self, account: int) -> None:
        try:
            rank = from_tier(self.lookup(account))
        except Exception:  # the network, a changed reply: just don't know
            log.exception("Could not read your rank from OpenDota")
            return
        if rank:
            self.looked_up = rank
            log.info("Your OpenDota profile says %s; comparisons use %s players", name(rank), name(rank))

    def bracket(self) -> str | None:
        return self.told or self.configured or self.looked_up

    @property
    def source(self) -> str:
        if self.told:
            return "you told me"
        if self.configured:
            return "it's set in coach.toml"
        return "your OpenDota profile says so" if self.looked_up else ""

    def should_ask(self) -> bool:
        """Ask at the start of a game only while the rank isn't known, and
        only once: a skipped question isn't asked again."""
        return self.bracket() is None and not self.asked

    def heard(self, rank: str | None) -> None:
        """What the player said; None when they skipped the question."""
        if rank in TIERS:
            self.told = rank
        self.asked = True
        self._write()

    def answer(self, text: str) -> str | None:
        """The reply to the start-of-game question; None when skipped."""
        rank = parse(text)
        self.heard(rank)
        if rank is None:
            if text.strip():
                return "Sorry, I didn't catch your rank. You can tell me any time: say my rank is, and your medal."
            return None
        return confirm(rank)

    def _read(self) -> dict:
        if self.store is None or not self.store.is_file():
            return {}
        try:
            data = json.loads(self.store.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("Can't read %s (%s); asking your rank again", self.store, exc)
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self) -> None:
        if self.store is None:
            return
        try:
            self.store.parent.mkdir(parents=True, exist_ok=True)
            self.store.write_text(json.dumps({"rank": self.told, "asked": self.asked}), encoding="utf-8")
        except OSError as exc:
            log.warning("Can't save your rank to %s (%s)", self.store, exc)


QUESTION = "What's your rank? Say your medal, like Crusader or Legend, or your MMR."


def confirm(rank: str) -> str:
    return f"Got it, {name(rank)}. I'll compare you with {name(rank)} players."


def tell(player: PlayerRank | None, text: str) -> str:
    """The answer to "my rank is Archon" or "what's my rank?"."""
    if player is None:
        return "I can't keep your rank in this mode."
    rank = parse(text)
    if rank is not None:
        player.heard(rank)
        if not load_brackets().get(group_of(rank)):
            return confirm(rank) + " I don't have numbers for each rank yet, so for now it's all players."
        return confirm(rank)
    current = player.bracket()
    if current is None:
        return "I don't know your rank yet. Say my rank is, and your medal, like Archon, or your MMR."
    return f"I compare you with {name(current)} players, because {player.source}. Say my rank is, and your medal, to change it."


# The bracket numbers.

Curve = list[tuple[float, float]]  # (percentile, value), rising
Curves = dict[str, Curve]  # metric: curve
# A hero needs this many games in a medal's sample for its own curves; with
# fewer it is compared with that medal's cores or supports in general.
MIN_HERO_GAMES = 30


@functools.cache
def load_brackets(path: Path = BRACKETS_FILE) -> dict[str, dict]:
    """{medal: {"core": curves, "support": curves, "heroes": {hero key:
    curves}}} from the bundled file; empty when there is none yet."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        percentiles = data["percentiles"]

        def curves(values: dict) -> Curves:
            return {m: list(zip(percentiles, v)) for m, v in values.items() if m in METRICS}

        return {
            group: {
                "core": curves(numbers["core"]),
                "support": curves(numbers["support"]),
                "heroes": {key: curves(hero) for key, hero in numbers.get("heroes", {}).items()},
            }
            for group, numbers in data["brackets"].items()
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        log.warning("Can't read %s (%s); comparing with all players", path, exc)
        return {}


def group_of(rank: str | None) -> str | None:
    """The sampled group a medal is compared with: Immortal uses Divine's."""
    return "divine" if rank == "immortal" else rank


def value_at(curve: Curve, p: float) -> float:
    """The curve's value at percentile p, interpolated, held flat past its ends."""
    if p <= curve[0][0]:
        return curve[0][1]
    for (p0, v0), (p1, v1) in zip(curve, curve[1:]):
        if p <= p1:
            return v0 + (v1 - v0) * (p - p0) / (p1 - p0) if p1 > p0 else v1
    return curve[-1][1]


def has(rank: str | None) -> bool:
    """Whether the bundled numbers cover this medal."""
    return bool(rank) and group_of(rank) in load_brackets()


def curves(rank: str | None, hero: str, support: bool) -> tuple[Curves, bool] | None:
    """Only numbers from players of this medal: the hero's own when enough
    of them played it (True), else the medal's cores or supports (False)."""
    group = load_brackets().get(group_of(rank) or "")
    if not group:
        return None
    own = group["heroes"].get(hero)
    if own:
        return own, True
    return group["support" if support else "core"], False


def last_hits_per_min(rank: str | None) -> float | None:
    """The whole-match last hits a minute of the middle core of this medal."""
    group = load_brackets().get(group_of(rank) or "")
    curve = group["core"].get("last_hits_per_min") if group else None
    return value_at(curve, 0.5) if curve else None


def describe(rank: str | None) -> str:
    """One sentence of what the middle player of a medal reaches on the
    current patch, e.g. for the local model's facts. Empty without data."""
    group = load_brackets().get(group_of(rank) or "")
    if not group or not group["core"]:
        return ""
    core = {m: value_at(c, 0.5) for m, c in group["core"].items()}
    line = (
        f"A typical {name(rank)} core gets about {core.get('gold_per_min', 0):.0f} gold, "
        f"{core.get('xp_per_min', 0):.0f} experience and {core.get('last_hits_per_min', 0):.1f} last hits a minute"
    )
    support = group["support"].get("xp_per_min")
    if support:
        line += f", a support about {value_at(support, 0.5):.0f} experience"
    return line + "."


# Refreshing the numbers from OpenDota's public matches.


def percentiles(values: list[float], at: list[float] = PERCENTILES) -> list[float]:
    """The values at each share, interpolated between sorted samples."""
    ordered = sorted(values)
    out = []
    for p in at:
        x = p * (len(ordered) - 1)
        low = int(x)
        high = min(low + 1, len(ordered) - 1)
        out.append(ordered[low] + (ordered[high] - ordered[low]) * (x - low))
    return out


def patch_start(get: Callable[[str], Any]) -> tuple[str, int]:
    """The live patch's name and start time (Unix seconds) from OpenDota."""
    patches = [p for p in get("/constants/patch") or [] if isinstance(p, dict) and p.get("date")]
    if not patches:
        raise RuntimeError("OpenDota didn't say which patch is live")
    latest = max(patches, key=lambda p: p["date"])
    started = datetime.fromisoformat(str(latest["date"]).replace("Z", "+00:00"))
    return str(latest.get("name", "")), int(started.timestamp())


def players(match: dict) -> list[tuple[int, bool, dict[str, float]]]:
    """(hero id, support, numbers) for each player of a finished match;
    empty when someone abandoned, or the match is too short to count."""
    duration = match.get("duration") or 0
    rows = match.get("players") or []
    if duration < MIN_DURATION or len(rows) != 10:
        return []
    if any((p.get("leaver_status") or 0) > 1 for p in rows):
        return []
    minutes = duration / 60
    out = []
    for radiant in (True, False):
        team = [p for p in rows if (p.get("player_slot", 0) < 128) == radiant]
        team.sort(key=lambda p: p.get("last_hits") or 0, reverse=True)
        for n, p in enumerate(team):
            out.append((
                int(p.get("hero_id") or 0),
                n >= CORES_PER_TEAM,
                {
                    "gold_per_min": float(p.get("gold_per_min") or 0),
                    "xp_per_min": float(p.get("xp_per_min") or 0),
                    "last_hits_per_min": (p.get("last_hits") or 0) / minutes,
                },
            ))
    return out


Sample = dict[str, dict[str, list[float]]]  # "core", "support" or hero id: {metric: values}
# This many matches in a row without an answer: OpenDota stopped answering.
GIVE_UP = 20


def sample(
    get: Callable[[str], Any],
    group: str,
    matches: int,
    since: int,
    pause: float = 1.1,
    progress: Callable[[str], None] = lambda text: None,
    pages: int = 60,
) -> tuple[int, Sample]:
    """(matches read, numbers) for one medal: recent ranked matches whose
    players average that medal, on the current patch, newest first."""
    low, high = GROUPS[group]
    found: Sample = {}
    read, before, missed = 0, None, 0
    for _ in range(pages):
        params = [f"min_rank={low}", f"max_rank={high}"]
        if before:
            params.append(f"less_than_match_id={before}")
        time.sleep(pause)
        listed = [m for m in get("/publicMatches?" + "&".join(params)) or [] if isinstance(m, dict) and m.get("match_id")]
        if not listed:
            break
        before = min(m["match_id"] for m in listed)
        if all((m.get("start_time") or 0) < since for m in listed):
            break  # back before the patch
        for m in listed:
            tier = m.get("avg_rank_tier")
            if (
                m.get("lobby_type") != RANKED_LOBBY
                or m.get("game_mode") == TURBO
                or (m.get("duration") or 0) < MIN_DURATION
                or (m.get("start_time") or 0) < since
                or not (tier and low <= tier <= high)
            ):
                continue
            time.sleep(pause)
            detail = get(f"/matches/{m['match_id']}")
            missed = 0 if detail else missed + 1
            if missed >= GIVE_UP:
                raise RuntimeError("OpenDota stopped answering (its free daily limit?)")
            rows = players(detail or {})
            if not rows:
                continue
            for hero, support, numbers in rows:
                for key in ("support" if support else "core", str(hero)):
                    bucket = found.setdefault(key, {metric: [] for metric in METRICS})
                    for metric, value in numbers.items():
                        bucket[metric].append(value)
            read += 1
            progress(f"{name(group)}: {read}/{matches} matches")
            if read >= matches:
                return read, found
    return read, found


def _rounded(values: list[float]) -> list[float]:
    return [round(v, 2) for v in percentiles(values)]


def fetch(
    get: Callable[[str], Any],
    hero_keys: dict[int, str],
    matches: int = 250,
    pause: float = 1.1,
    progress: Callable[[str], None] = lambda text: None,
) -> dict:
    """The brackets file's contents, sampled from OpenDota. Medals with too
    few matches are left out."""
    patch, since = patch_start(get)
    brackets = {}
    for group in GROUPS:
        read, found = sample(get, group, matches, since, pause, progress)
        if read < max(10, matches // 4) or "core" not in found or "support" not in found:
            progress(f"{name(group)}: only {read} matches on this patch, left out")
            continue
        heroes = {
            hero_keys[int(key)]: {"games": len(values["gold_per_min"])}
            | {m: _rounded(v) for m, v in values.items()}
            for key, values in found.items()
            if key.isdigit() and int(key) in hero_keys and len(values["gold_per_min"]) >= MIN_HERO_GAMES
        }
        brackets[group] = {
            "matches": read,
            "core": {m: _rounded(v) for m, v in found["core"].items()},
            "support": {m: _rounded(v) for m, v in found["support"].items()},
            "heroes": dict(sorted(heroes.items())),
        }
    return {
        "source": "OpenDota public matches (/publicMatches, /matches): ranked, not Turbo, 15 minutes or "
        f"longer, nobody abandoned. Fetched {date.today().isoformat()}, patch {patch}.",
        "note": "Each medal holds only players of that medal (Divine also has Immortal). Whole-match "
        "averages per player. Cores are the 3 players with most last hits on each team. A hero is listed "
        f"with {MIN_HERO_GAMES} or more games. Values at the percentiles below, in order.",
        "patch": patch,
        "percentiles": PERCENTILES,
        "brackets": brackets,
    }


def save(data: dict, path: Path = BRACKETS_FILE) -> int:
    """Writes the file; returns how many medals it holds."""
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    load_brackets.cache_clear()
    return len(data["brackets"])
