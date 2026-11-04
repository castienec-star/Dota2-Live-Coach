from coach.rules import focus_check
from coach.rules.death_tip import STAGE_TIPS, now_worded
from coach.rules.focus_check import FocusCheck
from coach.state import MatchState, Snapshot


def run(rule, clock, hero="npc_dota_hero_axe", alive=True, health=1000):
    state = MatchState()
    state.current = Snapshot(clock_time=clock, hero_name=hero, alive=alive, health=health, max_health=1000)
    return rule.check(state)


def test_speaks_once_after_laning_with_the_role_line():
    rule = FocusCheck(position=lambda s: 3)
    assert run(rule, 629) == []
    (line,) = run(rule, 630)
    prefix = "The laning phase is over. Your focus now: "
    assert line.startswith(prefix)
    assert line.removeprefix(prefix) in {now_worded(t) for t in STAGE_TIPS[("mid game", "core")]}
    assert run(rule, 640) == []


def test_support_hears_the_support_line():
    (line,) = run(FocusCheck(position=lambda s: 5), 630)
    assert line.split(": ", 1)[1] in {now_worded(t) for t in STAGE_TIPS[("mid game", "support")]}


def test_waits_while_dead_or_low_and_skips_when_late():
    rule = FocusCheck()
    assert run(rule, 630, alive=False) == []
    assert run(rule, 640, health=100) == []
    assert run(rule, 650) != []
    rule = FocusCheck()
    assert run(rule, 700) == []  # started the coach after 11:30
    assert run(rule, 710) == []


def test_reset_for_a_new_match_and_switch_off():
    rule = FocusCheck()
    assert run(rule, 630)
    rule.reset()
    assert run(rule, 630)
    assert focus_check.build({"focus_check": {"enabled": False}}) == []
    assert len(focus_check.build({"focus_check": {"at": 600}})) == 1
