from coach.rules import Engine
from coach.rules.timers import StackReminder, TimedReminder, build, load_camps
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


def stand_at_camp(payload, kind="large"):
    camp = next(c for c in load_camps() if c.type == kind)
    payload["hero"]["xpos"], payload["hero"]["ypos"] = camp.x + 300, camp.y - 200


def test_stack_reminder_stops_after_until(payload):
    said = []
    engine = Engine(build({}), said.append)
    stand_at_camp(payload)
    play(MatchState(), payload, [112, 113], engine)
    play(MatchState(), payload, [772, 773], engine)
    assert said == ["Stack the large camp."]


def test_no_stack_call_away_from_camps(payload):
    said = []
    engine = Engine(build({}), said.append)
    payload["hero"]["xpos"], payload["hero"]["ypos"] = 0, 0  # middle of the river
    play(MatchState(), payload, [112, 113], engine)
    assert said == []


def test_no_stack_call_while_dead(payload):
    said = []
    engine = Engine(build({}), said.append)
    stand_at_camp(payload)
    payload["hero"]["alive"] = False
    play(MatchState(), payload, [112, 113], engine)
    assert said == []


def test_stack_names_nearest_camp_type(payload):
    said = []
    engine = Engine(build({}), said.append)
    stand_at_camp(payload, "ancient")
    play(MatchState(), payload, [112, 113], engine)
    assert said == ["Stack the ancient camp."]


def test_camp_data_covers_both_jungles():
    camps = load_camps()
    assert len(camps) >= 20
    # Map coordinates are centred on 0: camps on both sides of the river.
    assert any(c.x < 0 and c.y < 0 for c in camps)
    assert any(c.x > 0 and c.y > 0 for c in camps)


def test_stack_radius_from_config():
    stack = next(r for r in build({"stack": {"radius": 500}}) if r.name == "stack")
    assert isinstance(stack, StackReminder)
    assert stack.radius == 500


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


def test_runes_are_thinned_after_twenty_minutes(payload):
    said = []
    engine = Engine(build({"bounty_rune": {"enabled": False}, "wisdom_shrine": {"enabled": False}, "stack": {"enabled": False}}), said.append)
    play(MatchState(), payload, range(1000, 1700), engine)
    # Power runes at 18:00 and 20:00 are said; after 20:00 every other one.
    assert said.count("Power rune in 15 seconds.") == 4  # 18:00, 20:00, 22:00, 26:00


def test_thinning_can_be_turned_off(payload):
    said = []
    engine = Engine(build({"power_rune": {"thin_after": 0}}), said.append)
    rule = engine.rules[0]
    assert rule.name == "power_rune" and not rule.thinned(1320)


def test_neutral_tiers_called_once_each(payload):
    said = []
    engine = Engine(build({}), said.append)
    state = MatchState()
    for start in (300, 900, 1500, 2100, 3600):
        play(state, payload, [start - 1, start, start, start + 1], engine)
    neutral = [line for line in said if "eutral items" in line]
    assert len(neutral) == 5
    assert "Madstone" in neutral[0] and "Tier" not in neutral[0]
    assert neutral[1].startswith("Tier 2 neutral items are open.")
    assert neutral[4].startswith("Tier 5")


def test_neutral_tiers_follow_config(payload):
    said = []
    engine = Engine(build({"neutral_items": {"at": [150, 450]}}), said.append)
    play(MatchState(), payload, [449, 450], engine)
    assert said == ["Tier 2 neutral items are open. Click the Madstone counter when it flashes to upgrade yours."]


def test_neutral_tiers_can_be_turned_off():
    assert all(r.name != "neutral_items" for r in build({"neutral_items": {"enabled": False}}))
