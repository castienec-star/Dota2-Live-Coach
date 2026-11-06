import json
from datetime import date

from coach import progress
from coach.heroes import load_heroes
from coach.items import load_items
from coach.profile import MatchSummary
from coach.rank import PlayerRank

HEROES = {h.key: h for h in load_heroes().values()}
NAMES = {k: h.name for k, h in HEROES.items()}
ITEMS = load_items()


def game(hero="antimage", won=True, deaths=3, lh10=40, started=1.0, **kw):
    return MatchSummary(hero=hero, duration=kw.pop("duration", 1800), won=won, kills=kw.pop("kills", 5),
                        deaths=deaths, assists=kw.pop("assists", 4), last_hits_10=lh10, started=started,
                        match_id=kw.pop("match_id", "8012345678"), account_id="39734272",
                        last_hits=200, denies=10, gpm=520, xpm=600,
                        item_times=kw.pop("item_times", {"black_king_bar": 900}), **kw)


def test_mmr_is_kept_per_day_and_tells_the_coach_the_medal(tmp_path):
    days = iter([date(2026, 11, 1), date(2026, 11, 1), date(2026, 11, 3)])
    history = progress.MmrHistory(tmp_path, today=lambda: next(days))
    assert history.add("2,450")[0]
    assert history.add("2500")[0]  # same day: replaces
    assert history.add("2520")[0]
    assert [(p.day, p.mmr) for p in history.points()] == [("2026-11-01", 2500), ("2026-11-03", 2520)]
    # The coach reads this and stops asking the rank at the start of games.
    rank = PlayerRank("", tmp_path / "rank.json")
    assert rank.bracket() == "archon" and not rank.should_ask()


def test_bad_mmr_is_refused(tmp_path):
    history = progress.MmrHistory(tmp_path)
    assert not history.add("archon")[0] and not history.add("99999")[0]
    assert history.points() == []


def test_mmr_update_is_due_every_three_days(tmp_path):
    today = [date(2026, 11, 1)]
    history = progress.MmrHistory(tmp_path, today=lambda: today[0])
    assert history.due()
    history.add("3000")
    assert not history.due()
    today[0] = date(2026, 11, 3)
    assert not history.due()
    today[0] = date(2026, 11, 4)
    assert history.due()


def test_hero_stats_most_played_first_with_win_rates():
    games = [game("antimage", True), game("antimage", False), game("antimage", True),
             game("lion", False), game("lion", None)]
    stats = progress.hero_stats(games, NAMES)
    assert [s["name"] for s in stats] == ["Anti-Mage", "Lion"]
    assert stats[0]["win_rate"] == 67 and (stats[0]["wins"], stats[0]["losses"]) == (2, 1)
    assert stats[1]["games"] == 2 and stats[1]["win_rate"] == 0  # the unfinished game doesn't count


def test_match_rows_newest_first_with_review_notes_and_link():
    rows = progress.match_rows([game(started=1.0, deaths=9), game(started=2.0, match_id="0")], NAMES,
                               heroes_by_key=HEROES, items=ITEMS)
    assert rows[0]["link"] == "" and rows[1]["link"].endswith("/matches/8012345678")
    assert rows[1]["kda"] == "5/9/4" and rows[1]["result"] == "Win"
    assert any(n["tone"] == "fix" and "died 9 times" in n["text"] for n in rows[1]["notes"])


def test_recommendations_name_the_recurring_point_trends_and_heroes():
    games = []
    for i in range(6):  # deaths rising, early deaths every game
        games.append(game("antimage", i % 2 == 0, deaths=2 + i, started=float(i), death_times=[100, 200]))
    for i in range(4):
        games.append(game("lion", False, deaths=6, started=10.0 + i))
    recs = progress.recommendations(games, HEROES, ITEMS, NAMES)
    titles = [r["title"] for r in recs]
    assert titles[0] == "Deaths: your main thing to fix"
    assert "More deaths lately" in titles
    assert "Lion isn't working yet" in titles


def test_no_games_no_recommendations():
    assert progress.recommendations([], HEROES, ITEMS, NAMES) == []


def opendota(match):
    calls = []

    def get(path):
        calls.append(path)
        return match

    return get, calls


def test_match_details_use_only_the_players_own_row():
    other = {"account_id": 1, "hero_damage": 99999, "benchmarks": {}}
    mine = {"account_id": 39734272, "hero_damage": 12345.0, "obs_placed": 4, "net_worth": 15000,
            "benchmarks": {"gold_per_min": {"pct": 0.2}, "xp_per_min": {"pct": 0.35}, "hero_damage_per_min": {"pct": 0.81}}}
    get, calls = opendota({"players": [other, mine]})
    out = progress.match_details(get, "8012345678", "39734272")
    assert calls == ["matches/8012345678"]
    assert {"label": "Hero damage", "value": 12345} in out["stats"]
    assert out["tips"][0].startswith("Gold per minute: better than only 20%")
    assert out["tips"][-1].endswith("That's a strength.")


def test_match_details_explain_a_private_or_missing_match():
    get, _ = opendota({"players": [{"account_id": None}]})
    out = progress.match_details(get, "8012345678", "39734272")
    assert not out["ok"] and "Expose Public Match Data" in out["message"]

    def offline(path):
        raise OSError("offline")

    assert not progress.match_details(offline, "8012345678", "39734272")["ok"]
    assert not progress.match_details(get, "", "39734272")["ok"]


def test_summary_reads_recordings(tmp_path):
    rec = tmp_path / "recordings"
    rec.mkdir()
    payload = json.load(open("tests/data/sample_payload.json", encoding="utf-8"))
    lines = []
    for clock in range(0, 1900, 60):
        p = json.loads(json.dumps(payload))
        p["map"]["clock_time"] = clock
        lines.append(json.dumps({"t": 1000.0 + clock, "payload": p}))
    end = json.loads(json.dumps(payload))
    end["map"].update(clock_time=1900, game_state="DOTA_GAMERULES_STATE_POST_GAME", win_team="radiant")
    lines.append(json.dumps({"t": 3000.0, "payload": end}))
    (rec / "20261106-180000-match-8012345678.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = progress.summary(tmp_path, rec, today=lambda: date(2026, 11, 6))
    assert out["games"] == 1 and out["wins"] == 1 and out["mmr_due"]
    assert out["heroes"][0]["name"] == "Anti-Mage"
    assert out["matches"][0]["match_id"] == "8012345678" and out["matches"][0]["gpm"] == 512
    assert len(out["trend"]) == 1
