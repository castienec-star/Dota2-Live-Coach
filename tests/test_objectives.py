from coach.rules import Engine
from coach.rules.objectives import NIGHT, ROSHAN, NightStart, RoshanReminder, build
from coach.state import MatchState


def play(state, payload, steps, engine):
    """Feed one update per (clock, daytime) step through the engine."""
    for clock, day in steps:
        payload["map"]["clock_time"] = clock
        payload["map"]["daytime"] = day
        state.update(payload)
        engine(state)


def cycle(nights):
    """Clock and daytime for a match with day/night switching every 5 minutes."""
    return [(t, (t // 300) % 2 == 0) for t in range(295, nights * 600, 5)]


def test_night_start_is_said_for_the_first_nights_only(payload):
    said = []
    play(MatchState(), payload, cycle(5), Engine([NightStart(nights=3)], said.append))
    assert said == [NIGHT] * 3


def test_night_stalker_ultimate_is_not_night(payload):
    said = []
    engine = Engine([NightStart()], said.append)
    state = MatchState()
    play(state, payload, [(100, True)], engine)
    payload["map"]["nightstalker_night"] = True
    play(state, payload, [(101, False)], engine)
    assert said == []


def test_roshan_reminder_once_at_its_minute(payload):
    said = []
    play(MatchState(), payload, [(t, True) for t in range(1195, 1300)], Engine([RoshanReminder()], said.append))
    assert said == [ROSHAN]


def test_roshan_reminder_skips_a_clock_jump(payload):
    said = []
    play(MatchState(), payload, [(1100, True), (1300, True)], Engine([RoshanReminder()], said.append))
    assert said == []


def test_new_match_says_them_again(payload):
    said = []
    state = MatchState()
    engine = Engine(build({}), said.append)
    play(state, payload, [(299, True), (300, False)], engine)
    payload["map"]["matchid"] = "other"
    play(state, payload, [(299, True), (300, False)], engine)
    assert said == [NIGHT, NIGHT]


def test_config_can_turn_off_and_retime():
    assert build({"night": {"enabled": False}, "roshan": {"enabled": False}}) == []
    (night, roshan) = build({"night": {"nights": 1}, "roshan": {"minute": 15}})
    assert night.nights == 1 and roshan.at == 900
