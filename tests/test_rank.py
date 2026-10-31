import json
import threading

import pytest

from coach import rank as rank_mod
from coach.__main__ import main
from coach.benchmarks import Benchmarks, early, last_hit_target, status
from coach.lineup import Interview
from coach.rank import PlayerRank, from_mmr, from_tier, parse, players, tell
from coach.rules.last_hits import LastHitPace
from coach.state import MatchState, Snapshot
from coach.voice import Answers, intent
from tests.test_lineup import INDEX, Sink, converse, start

P = rank_mod.PERCENTILES


def curve(middle, spread=0.5):
    """Rising values around "middle" at the bundled percentiles."""
    return [round(middle * (1 - spread + 2 * spread * p), 2) for p in P]


def numbers(scale):
    return {
        "gold_per_min": curve(500 * scale),
        "xp_per_min": curve(600 * scale),
        "last_hits_per_min": curve(5.0 * scale),
    }


def group(scale, heroes=None, matches=100):
    return {
        "matches": matches,
        "core": numbers(scale),
        "support": {"gold_per_min": curve(300), "xp_per_min": curve(450 * scale), "last_hits_per_min": curve(1.0)},
        "heroes": heroes or {},
    }


DATA = {
    "percentiles": P,
    "patch": "7.41",
    "brackets": {
        "herald": group(0.7),
        # Legend Juggernauts farm more than Legend cores in general.
        "legend": group(1.2, {"juggernaut": {"games": 40} | numbers(1.4)}),
        "divine": group(1.3),
    },
}


@pytest.fixture
def brackets(tmp_path, monkeypatch):
    path = tmp_path / "brackets.json"
    path.write_text(json.dumps(DATA), encoding="utf-8")
    loaded = rank_mod.load_brackets.__wrapped__(path)
    monkeypatch.setattr(rank_mod, "load_brackets", lambda: loaded)
    return loaded


class Told:
    """Stands in for PlayerRank with a fixed medal."""

    def __init__(self, rank):
        self.rank = rank

    def bracket(self):
        return self.rank


def jugg(clock=900, gpm=450, xpm=500, last_hits=75):
    return Snapshot(clock_time=clock, hero_name="npc_dota_hero_juggernaut", gpm=gpm, xpm=xpm, last_hits=last_hits)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Archon", "archon"),
        ("my rank is archon 3", "archon"),
        ("I'm an arkon", "archon"),
        ("i'm herald", "herald"),
        ("Legend", "legend"),
        ("2500", "archon"),
        ("my MMR is 2,500", "archon"),
        ("about 4.2k", "ancient"),
        ("600", "herald"),
        ("6000", "immortal"),
        (2000, "crusader"),
        ("rank four", None),
        ("", None),
    ],
)
def test_parse(text, expected):
    assert parse(text) == expected


def test_rank_tier_and_mmr():
    assert from_tier(43) == "archon" and from_tier(80) == "immortal"
    assert from_tier(None) is None and from_tier(0) is None
    assert from_mmr(0) == "herald" and from_mmr(769) == "herald" and from_mmr(770) == "guardian"
    assert from_mmr(4700) == "divine"


def test_said_beats_config_beats_profile(tmp_path):
    store = tmp_path / "rank.json"
    player = PlayerRank("Legend", store)
    assert player.bracket() == "legend" and "coach.toml" in player.source
    player.heard("herald")
    assert player.bracket() == "herald"
    # It lasts between coach starts.
    assert PlayerRank("Legend", store).bracket() == "herald"
    assert PlayerRank("", tmp_path / "other.json").bracket() is None


def test_a_bad_setting_is_ignored(tmp_path, caplog):
    assert PlayerRank("platinum", tmp_path / "rank.json").bracket() is None
    assert "isn't a medal" in caplog.text


def test_reads_the_medal_from_the_players_own_profile(tmp_path):
    looked = []

    def lookup(account):
        looked.append(account)
        return 52

    player = PlayerRank("", tmp_path / "rank.json", lookup)
    state = MatchState()
    state.current = Snapshot(account_id="76561198000000001")
    player(state)
    for thread in threading.enumerate():
        if thread.name == "rank":
            thread.join(2)
    player(state)  # once per account
    assert looked == [39734273]
    assert player.bracket() == "legend" and "OpenDota" in player.source


def test_a_told_rank_skips_the_profile(tmp_path):
    player = PlayerRank("archon", tmp_path / "rank.json", lambda account: pytest.fail("looked up"))
    state = MatchState()
    state.current = Snapshot(account_id="123")
    player(state)


def test_asked_once_even_when_skipped(tmp_path):
    store = tmp_path / "rank.json"
    player = PlayerRank("", store)
    assert player.should_ask()
    assert player.answer("") is None
    assert not player.should_ask()
    assert not PlayerRank("", store).should_ask()


def test_start_of_game_question_comes_last(payload, tmp_path, brackets):
    player = PlayerRank("", tmp_path / "rank.json")
    interview = Interview(INDEX, Sink(), position=1, rank=player)
    start(payload, interview)
    said = converse(interview, ["skip", "skip", "I'm in Guardian"])
    assert said[-2] == rank_mod.QUESTION
    assert said[-1] == "Got it, Guardian. I'll compare you with Guardian players."
    assert player.bracket() == "guardian"
    # Not asked again next match.
    interview = Interview(INDEX, Sink(), position=1, rank=player)
    start(payload, interview)
    assert rank_mod.QUESTION not in converse(interview, ["skip", "skip"])


def test_misheard_rank_answer(payload, tmp_path):
    player = PlayerRank("", tmp_path / "rank.json")
    interview = Interview(INDEX, Sink(), position=1, rank=player)
    start(payload, interview)
    said = converse(interview, ["skip", "skip", "pretty good"])
    assert said[-1].startswith("Sorry, I didn't catch your rank")


@pytest.mark.parametrize(
    "text",
    ["My rank is Archon", "my MMR is 2500", "I'm a Herald", "what's my rank", "I am legend", "my m m r is 3000"],
)
def test_rank_intent(text):
    assert intent(text) == "rank"


def test_other_questions_are_not_rank():
    assert intent("how am I doing") == "how_am_i_doing"
    assert intent("what should I buy") == "what_to_buy"


def test_say_your_rank(tmp_path, brackets):
    player = PlayerRank("", tmp_path / "rank.json")
    answers = Answers({}, {}, benchmarks=Benchmarks(rank=player))
    assert "don't know your rank" in answers.answer("what's my rank", Snapshot())
    assert answers.answer("my rank is legend", Snapshot()) == "Got it, Legend. I'll compare you with Legend players."
    assert answers.answer("what's my rank?", Snapshot()).startswith("I compare you with Legend players, because you told me")


def test_rank_without_numbers_for_it_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(rank_mod, "load_brackets", lambda: {})
    assert tell(PlayerRank("", tmp_path / "r.json"), "archon").endswith("for now it's all players.")


def test_same_numbers_rank_their_own_medal(brackets):
    # A Juggernaut "behind" against everyone is even for a Herald and
    # behind for a Legend.
    snap = jugg(900, gpm=280, xpm=330, last_hits=45)
    assert Benchmarks().verdict(snap).kind == "behind"
    herald = Benchmarks(rank=Told("herald")).verdict(snap)
    assert herald.kind == "even" and herald.rank == "herald"
    assert Benchmarks(rank=Told("legend")).verdict(snap).kind == "behind"


def test_only_numbers_from_the_players_own_medal(brackets):
    # Legend has Juggernaut's own numbers; Herald only its cores in general.
    assert rank_mod.curves("legend", "juggernaut", False) == (brackets["legend"]["heroes"]["juggernaut"], True)
    assert rank_mod.curves("herald", "juggernaut", False) == (brackets["herald"]["core"], False)
    assert rank_mod.curves("herald", "lion", True) == (brackets["herald"]["support"], False)
    assert not Benchmarks(rank=Told("legend")).verdict(jugg()).rough
    # The same numbers beat Legend cores in general by more than Legend Juggernauts.
    snap = jugg(900, gpm=560, xpm=640, last_hits=90)
    legend = Benchmarks(rank=Told("legend"))
    luna = Snapshot(clock_time=900, hero_name="npc_dota_hero_luna", gpm=560, xpm=640, last_hits=90)
    assert legend.verdict(snap).kind == "even"
    assert legend.verdict(luna).score > legend.verdict(snap).score


def test_spoken_names_the_medal(brackets):
    line = status(Benchmarks(rank=Told("herald")), jugg(900, 280, 330, 45), INDEX.by_key("juggernaut"))
    assert line.startswith("You're about even for Herald at 15 minutes.")
    assert line.endswith("That's a rough comparison with Herald cores in general.")


def test_immortal_uses_divine_and_unknown_ranks_use_everyone(brackets):
    assert Benchmarks(rank=Told("immortal")).bracket() == "immortal"
    assert rank_mod.curves("immortal", "lion", False)[0] is brackets["divine"]["core"]
    # No numbers for Archon in this file: compared with everyone, as before.
    assert Benchmarks(rank=Told("archon")).bracket() is None
    assert Benchmarks(rank=Told("archon")).verdict(jugg()).rank is None


def test_last_hit_target_follows_the_medal(brackets):
    assert last_hit_target(10) == 35
    # Herald cores average 3.5 a match, about 2.6 by 10:00.
    assert last_hit_target(10, "herald") == 25
    assert last_hit_target(5, "herald") == 10
    assert last_hit_target(10, "legend") == 40
    assert last_hit_target(10, "archon") == 35  # no numbers: everyone's


def test_early_answer_and_unasked_line_use_the_medal(brackets):
    assert early(jugg(600, last_hits=24), False, "herald").startswith("24 last hits at 10 minutes, aim for about 25.")
    rule = LastHitPace(rank=lambda: "herald")
    state = MatchState()
    state.current = jugg(600, last_hits=26)
    assert rule.check(state) == ["26 last hits at 10 minutes, great farming. Keep it up."]


def test_describe_for_the_local_model(brackets):
    assert rank_mod.describe("herald") == (
        "A typical Herald core gets about 350 gold, 420 experience and 3.5 last hits a minute, "
        "a support about 315 experience."
    )
    assert rank_mod.describe("archon") == "" and rank_mod.describe(None) == ""


def test_missing_or_broken_file(tmp_path):
    assert rank_mod.load_brackets.__wrapped__(tmp_path / "none.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    assert rank_mod.load_brackets.__wrapped__(bad) == {}


# Refreshing from OpenDota's public matches.


def match(match_id, duration=2400, leaver=0):
    rows = []
    for slot in [0, 1, 2, 3, 4, 128, 129, 130, 131, 132]:
        n = slot % 128
        rows.append({
            "player_slot": slot,
            "hero_id": 8 if slot == 0 else 100 + slot,
            "gold_per_min": 600 - 80 * n,
            "xp_per_min": 700 - 60 * n,
            "last_hits": 300 - 60 * n,
            "leaver_status": leaver if slot == 0 else 0,
        })
    return {"match_id": match_id, "duration": duration, "players": rows}


def test_players_splits_cores_and_supports():
    rows = players(match(1))
    assert [support for _, support, _ in rows] == [False] * 3 + [True] * 2 + [False] * 3 + [True] * 2
    assert rows[0] == (8, False, {"gold_per_min": 600.0, "xp_per_min": 700.0, "last_hits_per_min": 7.5})
    assert players(match(1, leaver=2)) == []
    assert players(match(1, duration=600)) == []


START = 1_790_000_000


def fake_opendota(path):
    if path == "/constants/patch":
        return [{"name": "7.40", "date": "2025-12-15T00:00:00Z"}, {"name": "7.41", "date": "2026-09-20T00:00:00Z"}]
    if path.startswith("/publicMatches"):
        if "less_than_match_id" in path:
            return [{"match_id": 5, "start_time": 1}]  # before the patch
        tier = int(path.split("min_rank=")[1].split("&")[0]) + 2 if "min_rank" in path else 44
        listed = [
            {"match_id": 100 + n, "start_time": START, "lobby_type": 7, "game_mode": 22,
             "duration": 2400, "avg_rank_tier": tier}
            for n in range(60)
        ]
        listed[0]["game_mode"] = 23  # Turbo
        listed[1]["lobby_type"] = 0  # unranked
        listed[2]["duration"] = 400
        return listed
    if path.startswith("/matches/"):
        return match(int(path.rsplit("/", 1)[1]))
    return None


def test_fetch_samples_each_group_on_the_live_patch(tmp_path, monkeypatch):
    monkeypatch.setattr("coach.rank.time.sleep", lambda s: None)
    asked = []

    def get(path):
        asked.append(path)
        return fake_opendota(path)

    data = rank_mod.fetch(get, {8: "juggernaut", 101: "lion"}, matches=40)
    assert data["patch"] == "7.41"
    assert set(data["brackets"]) == set(rank_mod.GROUPS)
    herald = data["brackets"]["herald"]
    assert herald["matches"] == 40
    # Juggernaut (40 games) gets its own numbers; unknown heroes don't.
    assert set(herald["heroes"]) == {"juggernaut", "lion"} and herald["heroes"]["juggernaut"]["games"] == 40
    assert herald["heroes"]["juggernaut"]["gold_per_min"][0] == 600
    assert not any(p in asked for p in ("/matches/100", "/matches/101", "/matches/102"))
    assert "/publicMatches?min_rank=10&max_rank=19" in asked
    out = tmp_path / "brackets.json"
    assert rank_mod.save(data, out) == len(rank_mod.GROUPS)
    loaded = rank_mod.load_brackets.__wrapped__(out)
    assert len(loaded["herald"]["core"]["gold_per_min"]) == len(P)
    assert loaded["herald"]["heroes"]["juggernaut"]["gold_per_min"][0] == (0.1, 600)


def test_too_few_matches_leave_a_group_out(monkeypatch):
    monkeypatch.setattr("coach.rank.time.sleep", lambda s: None)
    data = rank_mod.fetch(fake_opendota, {}, matches=400)
    assert data["brackets"] == {}  # under 400 / 4 usable matches each


def test_refresh_brackets_command(tmp_path, monkeypatch):
    monkeypatch.setattr("coach.config.user_dir", lambda: tmp_path)
    monkeypatch.setattr("coach.opendota.OpenDota.get", lambda self, path, max_age=None: fake_opendota(path))
    monkeypatch.setattr("coach.rank.time.sleep", lambda s: None)
    out = tmp_path / "brackets.json"
    args = ["--config", str(tmp_path / "none.toml"), "refresh-brackets", "--out", str(out), "--matches", "40"]
    assert main(args) == 0
    assert set(json.loads(out.read_text(encoding="utf-8"))["brackets"]) == set(rank_mod.GROUPS)


def test_refresh_brackets_saves_nothing_when_offline(tmp_path, monkeypatch):
    monkeypatch.setattr("coach.config.user_dir", lambda: tmp_path)
    monkeypatch.setattr("coach.opendota.OpenDota.get", lambda self, path, max_age=None: None)
    out = tmp_path / "brackets.json"
    assert main(["--config", str(tmp_path / "none.toml"), "refresh-brackets", "--out", str(out)]) == 1
    assert not out.exists()


def test_opendota_player_rank(tmp_path):
    from coach.opendota import OpenDota

    stats = OpenDota(tmp_path)
    stats.get = lambda path, max_age=None: {"rank_tier": 35} if path == "/players/7" else {}
    assert stats.player_rank(7) == 35
    assert stats.player_rank(8) is None


def test_stops_when_opendota_stops_answering(monkeypatch):
    monkeypatch.setattr("coach.rank.time.sleep", lambda s: None)
    get = lambda path: None if path.startswith("/matches/") else fake_opendota(path)  # noqa: E731
    with pytest.raises(RuntimeError, match="stopped answering"):
        rank_mod.fetch(get, {}, matches=40)
