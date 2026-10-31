import pytest

from coach.benchmarks import last_hit_target
from coach.rules import last_hits
from coach.rules.last_hits import LastHitPace, spoken
from coach.state import MatchState, Snapshot


def run(rule, clock, last_hits=0, hero="npc_dota_hero_juggernaut"):
    state = MatchState()
    state.current = Snapshot(clock_time=clock, hero_name=hero, last_hits=last_hits)
    return rule.check(state)


def test_targets_at_5_and_10():
    assert last_hit_target(5) == 15
    assert last_hit_target(10) == 35
    assert last_hit_target(1) == 5


@pytest.mark.parametrize(
    "minute, have, expected",
    [
        (5, 17, "17 last hits at 5 minutes, great farming. Keep it up."),
        (5, 11, "11 last hits at 5 minutes, close to the 15 to aim for. Keep at it."),
        (5, 6, "6 last hits at 5 minutes; aim for about 15. Hit a creep when its health"),
        (10, 20, "20 last hits at 10 minutes; aim for about 35. Between waves, take the nearest jungle camp"),
    ],
)
def test_spoken(minute, have, expected):
    assert spoken(Snapshot(last_hits=have), minute).startswith(expected)


def test_speaks_once_at_each_minute():
    rule = LastHitPace()
    assert run(rule, 299, 14) == []
    assert run(rule, 300, 16) == ["16 last hits at 5 minutes, great farming. Keep it up."]
    assert run(rule, 301, 16) == []
    (line,) = run(rule, 600, 20)
    assert line.startswith("20 last hits at 10 minutes")
    assert run(rule, 610, 20) == []
    rule.reset()
    assert run(rule, 300, 16) != []


def test_skips_a_check_missed_when_started_late():
    rule = LastHitPace()
    assert run(rule, 420, 20) == []
    assert run(rule, 600, 35) != []


def test_silent_for_supports():
    assert run(LastHitPace(), 300, 2, hero="npc_dota_hero_lion") == []
    # A core hero played as a support, by the position the player told.
    assert run(LastHitPace(position=lambda snap: 5), 300, 2) == []
    # A support hero played in a core position hears it.
    assert run(LastHitPace(position=lambda snap: 2), 300, 2, hero="npc_dota_hero_lion") != []


def test_build_reads_settings():
    assert last_hits.build({"last_hits": {"enabled": False}}) == []
    (rule,) = last_hits.build({"last_hits": {"minutes": [4]}})
    assert run(rule, 240, 15) != []
    assert last_hits.build({})[0].times == [300, 600]


def test_says_when_last_hits_beat_last_game_at_10():
    rule = LastHitPace(previous=lambda: 18)
    assert run(rule, 300, 16) == ["16 last hits at 5 minutes, great farming. Keep it up."]
    (line,) = run(rule, 600, 30)
    assert line == "30 last hits at 10 minutes, up from 18 last game, close to the 35 to aim for. Keep at it."
    rule = LastHitPace(previous=lambda: 40)
    assert "last game" not in run(rule, 600, 30)[0]
