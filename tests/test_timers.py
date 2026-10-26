from coach.rules import Engine
from coach.rules.timers import TimedReminder, build
from coach.state import MatchState


def play(state, payload, clocks, engine):
    """Feed one update per clock value through the engine."""
    for clock in clocks:
        payload["map"]["clock_time"] = clock
        state.update(payload)
        engine(state)


def test_power_rune_called_once_15s_before_10_minutes(payload):
    said = []
    engine = Engine(build({}), said.append)
    # Several updates per clock second, as GSI sends them.
    play(MatchState(), payload, [583, 584, 584, 585, 585, 586], engine)
    assert said == ["Power rune in 15 seconds."]


def test_no_power_rune_call_before_six_minutes(payload):
    said = []
    engine = Engine(build({}), said.append)
    play(MatchState(), payload, range(220, 230), engine)
    assert "Power rune" not in " ".join(said)


def test_same_second_reminders_become_one_line(payload):
    said = []
    engine = Engine(build({}), said.append)
    # 8:00 has both a power rune and gold (bounty) runes, each 15 s ahead.
    play(MatchState(), payload, [464, 465], engine)
    assert said == ["Power rune in 15 seconds. Gold runes in 15 seconds."]


def test_both_water_runes_are_called(payload):
    said = []
    engine = Engine(build({}), said.append)
    play(MatchState(), payload, range(100, 300), engine)
    water = [line for line in said if "Water" in line]
    assert water == ["Water rune in 10 seconds."] * 2


def test_gold_runes_every_four_minutes(payload):
    bounty = next(r for r in build({}) if r.name == "bounty_rune")
    assert bounty.event_times(0, 1000) == [240, 480, 720, 960]


def test_stack_reminder_stops_after_until(payload):
    said = []
    engine = Engine(build({}), said.append)
    play(MatchState(), payload, [112, 113], engine)
    play(MatchState(), payload, [772, 773], engine)
    assert said == ["Stack the camp."]


def test_clock_jump_is_ignored(payload):
    said = []
    engine = Engine(build({}), said.append)
    play(MatchState(), payload, [300, 400], engine)
    assert said == []


def test_paused_or_pregame_is_silent(payload):
    said = []
    engine = Engine(build({}), said.append)
    payload["map"]["paused"] = True
    play(MatchState(), payload, [344, 345], engine)
    payload["map"]["paused"] = False
    payload["map"]["game_state"] = "DOTA_GAMERULES_STATE_PRE_GAME"
    play(MatchState(), payload, [112, 113], engine)
    assert said == []


def test_config_can_disable_and_retime():
    names = [r.name for r in build({"stack": {"enabled": False}, "power_rune": {"lead": 30}})]
    assert "stack" not in names
    power = next(r for r in build({"power_rune": {"lead": 30}}) if r.name == "power_rune")
    assert power.lead == 30


def test_event_times_respect_until():
    water = TimedReminder("water", "Water.", first=120, every=120, until=240, lead=10)
    assert water.event_times(0, 1000) == [120, 240]


def test_new_match_resets_reminders(payload):
    said = []
    state = MatchState()
    engine = Engine(build({}), said.append)
    play(state, payload, [344, 345], engine)
    payload["map"]["game_state"] = "DOTA_GAMERULES_STATE_HERO_SELECTION"
    state.update(payload)
    engine(state)
    payload["map"]["game_state"] = "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"
    play(state, payload, [344, 345], engine)
    assert len(said) == 2
