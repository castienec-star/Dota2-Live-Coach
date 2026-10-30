import pytest

from coach.benchmarks import (
    Benchmarks,
    early,
    load_benchmarks,
    parse_api,
    ramp,
    role_curves,
    share_below,
)
from coach.heroes import HeroIndex
from coach.items import load_items
from coach.opendota import OpenDota
from coach.rules import game_check
from coach.rules.game_check import GameCheck
from coach.situational import Pick
from coach.state import MatchState, Snapshot
from coach.voice import Answers, intent


def jugg(clock=900, gpm=450, xpm=500, last_hits=75):
    return Snapshot(
        clock_time=clock, hero_name="npc_dota_hero_juggernaut", gpm=gpm, xpm=xpm, last_hits=last_hits
    )


def test_bundled_snapshot_covers_every_hero_with_a_build():
    data = load_benchmarks()
    index = HeroIndex()
    for hero in ["axe", "juggernaut", "lion", "pudge", "skeleton_king", "zuus"]:
        assert index.by_key(hero) is not None
        for curve in data[hero].values():
            values = [v for _, v in curve]
            assert len(values) == 11 and values == sorted(values)


def test_share_below_interpolates():
    curve = [(0.1, 100.0), (0.5, 300.0), (0.9, 500.0)]
    assert share_below(curve, 300) == pytest.approx(0.5)
    assert share_below(curve, 400) == pytest.approx(0.7)
    assert share_below(curve, 50) == pytest.approx(0.05)
    assert share_below(curve, 900) == 1.0


def test_ramp_is_gentler_early_and_gone_by_30_minutes():
    assert ramp(0) == pytest.approx(0.6)
    assert ramp(900) == pytest.approx(0.8)
    assert ramp(1800) == ramp(3000) == 1.0


@pytest.mark.parametrize(
    "gpm, xpm, last_hits, kind",
    [(300, 350, 40, "behind"), (450, 500, 75, "even"), (620, 700, 110, "ahead")],
)
def test_verdicts_for_a_carry_at_15_minutes(gpm, xpm, last_hits, kind):
    verdict = Benchmarks().verdict(jugg(900, gpm, xpm, last_hits))
    assert verdict.kind == kind
    assert verdict.minute == 15


def test_weakest_names_the_number_furthest_behind():
    verdict = Benchmarks().verdict(jugg(900, gpm=600, xpm=700, last_hits=30))
    assert verdict.weakest == "last_hits_per_min"


def test_supports_are_judged_on_experience_only():
    lion = Snapshot(clock_time=1200, hero_name="npc_dota_hero_lion", gpm=150, xpm=420, last_hits=2)
    assert Benchmarks().verdict(lion, support=False).kind == "behind"
    assert Benchmarks().verdict(lion, support=True).kind == "even"


def test_no_verdict_early():
    assert Benchmarks().verdict(jugg(clock=300)) is None


def test_heroes_without_numbers_get_a_rough_verdict_for_their_role():
    am = Snapshot(clock_time=900, hero_name="npc_dota_hero_antimage", gpm=450, xpm=500, last_hits=75)
    verdict = Benchmarks().verdict(am)
    assert verdict.rough and verdict.kind == "even"
    assert not Benchmarks().verdict(jugg()).rough
    roles = role_curves()
    # Cores farm more than supports.
    assert roles[False]["gold_per_min"][4][1] > roles[True]["gold_per_min"][4][1]


def test_a_broken_benchmarks_file_still_answers(monkeypatch, tmp_path):
    broken = tmp_path / "benchmarks.json"
    broken.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("coach.benchmarks.BENCHMARKS_FILE", broken)
    monkeypatch.setattr("coach.benchmarks.load_benchmarks", lambda path=broken: load_benchmarks(path))
    role_curves.cache_clear()
    try:
        benchmarks = Benchmarks()
        assert benchmarks.heroes == {}
        assert benchmarks.verdict(jugg()) is None
        line = Answers({}, {}, benchmarks=benchmarks).answer("how am I doing", jugg(last_hits=30))
        assert line.startswith("30 last hits at 15 minutes, aim for about 50.")
    finally:
        role_curves.cache_clear()


def test_other_heroes_are_fetched_once():
    calls = []

    def fetch(hero_id):
        calls.append(hero_id)
        return {"gold_per_min": [(0.5, 500.0)], "xp_per_min": [(0.5, 600.0)]}

    benchmarks = Benchmarks({}, fetch=fetch, hero_ids={"antimage": 1})
    am = Snapshot(clock_time=1800, hero_name="npc_dota_hero_antimage", gpm=500, xpm=600, last_hits=200)
    assert benchmarks.verdict(am) is not None
    assert benchmarks.verdict(am) is not None
    assert calls == [1]


def test_parse_api_reply():
    reply = {
        "hero_id": 1,
        "result": {
            "gold_per_min": [{"percentile": 0.5, "value": 500}, {"percentile": 0.1, "value": 300}],
            "kills_per_min": [{"percentile": 0.5, "value": 0.2}],
        },
    }
    assert parse_api(reply) == {"gold_per_min": [(0.1, 300.0), (0.5, 500.0)]}
    assert parse_api({}) is None
    assert parse_api(None) is None


def test_opendota_benchmarks_uses_the_cache(tmp_path):
    stats = OpenDota(tmp_path)
    stats.get = lambda path, max_age=None: {"result": {"xp_per_min": [{"percentile": 0.5, "value": 600}]}}
    assert stats.benchmarks(1) == {"xp_per_min": [(0.5, 600.0)]}


def test_gpm_and_xpm_come_from_gsi(payload):
    snap = Snapshot.from_payload(payload)
    assert (snap.gpm, snap.xpm) == (512, 538)


@pytest.mark.parametrize(
    "text", ["How am I doing?", "Am I ahead?", "am I behind", "How's my game going", "are we winning"]
)
def test_how_am_i_doing_intent(text):
    assert intent(text) == "how_am_i_doing"


def test_spoken_verdicts():
    answers = Answers({}, {})
    assert answers.answer("how am I doing", jugg(900, 300, 350, 40)).startswith(
        "You're behind for 15 minutes, your last hits are low."
    )
    assert "Black King Bar" in answers.answer("how am I doing", jugg(900, 300, 350, 40))
    assert answers.answer("am I ahead", jugg(900, 450, 500, 75)).startswith("You're about even")
    assert answers.answer("am I ahead", jugg(900, 620, 700, 110)).startswith("You're ahead for 15 minutes.")
    assert answers.answer("how am I doing", jugg(clock=60)).startswith("The game has just started.")


def test_spoken_verdict_for_a_support_by_position():
    answers = Answers({}, {}, position=lambda snap: 5)
    lion = Snapshot(clock_time=1200, hero_name="npc_dota_hero_lion", gpm=150, xpm=300, last_hits=5)
    line = answers.answer("how am I doing", lion)
    assert line.startswith("You're behind for 20 minutes, your experience is low.")
    assert "Glimmer Cape" in line


def test_spoken_verdict_without_numbers_is_rough():
    am = Snapshot(clock_time=900, hero_name="npc_dota_hero_antimage", gpm=450, xpm=500, last_hits=75)
    answers = Answers({}, {})
    line = answers.answer("how am I doing", am)
    assert line.startswith("You're about even for 15 minutes.")
    assert line.endswith("That's a rough comparison with cores in general.")
    # Said once a match, not every time.
    assert "rough" not in answers.answer("how am I doing", am)
    am.match_id = "next match"
    assert "rough" in answers.answer("how am I doing", am)


def test_game_check_and_question_share_the_rough_caveat():
    benchmarks = Benchmarks()
    am = Snapshot(clock_time=900, hero_name="npc_dota_hero_antimage", gpm=450, xpm=500, last_hits=75)
    (line,) = run_check(GameCheck(benchmarks, minutes=[15]), am)
    assert "rough comparison" in line
    assert "rough" not in Answers({}, {}, benchmarks=benchmarks).answer("how am I doing", am)


@pytest.mark.parametrize(
    "clock, last_hits, deaths, expected",
    [
        (180, 6, 0, "6 last hits at 3 minutes, aim for about 10. No deaths yet, good."),
        (300, 12, 0, "12 last hits at 5 minutes, aim for about 15. No deaths yet, good."),
        (300, 22, 1, "22 last hits at 5 minutes, that's on track. One death so far"),
        (420, 25, 3, "25 last hits at 7 minutes, that's on track. 3 deaths already"),
    ],
)
def test_early_answer_for_a_core(clock, last_hits, deaths, expected):
    snap = jugg(clock=clock, last_hits=last_hits)
    snap.deaths = deaths
    assert Answers({}, {}).answer("how am I doing", snap).startswith(expected)


def test_early_answer_for_a_support():
    lion = Snapshot(clock_time=360, hero_name="npc_dota_hero_lion", last_hits=3, deaths=2)
    line = early(lion, support=True)
    assert line.startswith("It's too early to judge a support at 6 minutes. 2 deaths already")
    assert "last hits" not in line


def run_check(rule, snap):
    state = MatchState()
    state.current = snap
    return rule.check(state)


def test_game_check_speaks_once_at_each_minute():
    rule = GameCheck(Benchmarks(), minutes=[15, 25])
    assert run_check(rule, jugg(clock=899)) == []
    assert run_check(rule, jugg(clock=900, gpm=620, xpm=700, last_hits=110))[0].startswith(
        "You're ahead for 15 minutes."
    )
    assert run_check(rule, jugg(clock=905)) == []
    assert run_check(rule, jugg(clock=1500, gpm=350, xpm=400, last_hits=80))[0].startswith(
        "You're behind for 25 minutes"
    )
    rule.reset()
    assert run_check(rule, jugg(clock=1510)) != []


def test_game_check_skips_a_missed_minute_and_speaks_for_every_hero():
    rule = GameCheck(Benchmarks(), minutes=[15, 25])
    assert run_check(rule, jugg(clock=1000)) == []  # started the coach at 16:40
    am = Snapshot(clock_time=1500, hero_name="npc_dota_hero_antimage", gpm=500, xpm=500)
    (line,) = run_check(rule, am)
    assert "rough comparison with cores" in line


def test_game_check_uses_the_support_verdict_by_position():
    rule = GameCheck(Benchmarks(), minutes=[20], position=lambda snap: 5)
    lion = Snapshot(clock_time=1200, hero_name="npc_dota_hero_lion", gpm=150, xpm=300, last_hits=5)
    assert "Glimmer Cape" in run_check(rule, lion)[0]


def test_game_check_from_config():
    assert game_check.build({"game_check": {"enabled": False}}, Benchmarks()) == []
    (rule,) = game_check.build({"game_check": {"minutes": [10]}}, Benchmarks())
    assert rule.times == [600]
    (rule,) = game_check.build({}, Benchmarks())
    assert rule.times == [900, 1500]


def test_game_check_names_a_counter_from_the_enemy_lineup():
    lineup = [HeroIndex().by_key(k) for k in ("phantom_assassin", "lion")]
    rule = GameCheck(Benchmarks(), minutes=[25], enemies=lambda: lineup)
    snap = jugg(clock=1500, gpm=350, xpm=400, last_hits=80)
    snap.gold = 6000
    (line,) = run_check(rule, snap)
    assert line.startswith("You're behind for 25 minutes")
    assert "Black King Bar or a defensive item" not in line
    assert line.endswith("Buy Monkey King Bar now: Phantom Assassin dodges your attacks.")


def test_game_check_without_a_counter_keeps_the_general_advice():
    lineup = [HeroIndex().by_key("lina")]
    rule = GameCheck(Benchmarks(), minutes=[25], enemies=lambda: lineup)
    (line,) = run_check(rule, jugg(clock=1500, gpm=350, xpm=400, last_hits=80))
    assert line.endswith("buy a Black King Bar or a defensive item.")


def test_game_check_with_advice_always_names_an_item():
    manta = load_items()["item_manta"]
    rule = GameCheck(Benchmarks(), minutes=[15], advice=lambda snap: Pick(manta, ""))
    snap = jugg(clock=900, gpm=620, xpm=700, last_hits=110)
    snap.gold = 1000
    (line,) = run_check(rule, snap)
    assert line.startswith("You're ahead for 15 minutes.")
    assert line.endswith(f"Get Manta Style next, {manta.cost - 1000} more gold.")


def test_game_check_with_advice_but_nothing_to_buy_keeps_the_verdict():
    rule = GameCheck(Benchmarks(), minutes=[25], advice=lambda snap: None)
    (line,) = run_check(rule, jugg(clock=1500, gpm=350, xpm=400, last_hits=80))
    assert line.endswith("buy a Black King Bar or a defensive item.")
