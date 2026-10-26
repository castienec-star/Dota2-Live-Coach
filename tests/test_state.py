from coach.state import MatchState, Snapshot


def test_snapshot_reads_own_hero(payload):
    snap = Snapshot.from_payload(payload)
    assert snap.match_id == "8012345678"
    assert snap.in_game
    assert snap.clock_time == 664
    assert snap.hero_name == "npc_dota_hero_antimage"
    assert snap.gold == 1640
    assert snap.buyback_cost == 865
    assert round(snap.health_percent) == 30


def test_empty_item_slots_are_skipped(payload):
    snap = Snapshot.from_payload(payload)
    names = [i.name for i in snap.items]
    assert "empty" not in names
    wand = next(i for i in snap.items if i.name == "item_magic_wand")
    assert wand.charges == 14


def test_abilities_keep_slot_order(payload):
    snap = Snapshot.from_payload(payload)
    assert [a.name for a in snap.abilities][0] == "antimage_mana_break"
    assert snap.abilities[-1].ultimate


def test_menu_payload_without_game_data():
    snap = Snapshot.from_payload({"provider": {"name": "Dota 2"}})
    assert not snap.in_game
    assert snap.health_percent == 0
    assert "--:--" in snap.summary()


def test_summary_line(payload):
    line = Snapshot.from_payload(payload).summary()
    assert line.startswith("[11:04] antimage lvl 11 alive")
    assert "gold 1640" in line


def test_negative_clock_before_horn(payload):
    payload["map"]["clock_time"] = -75
    assert Snapshot.from_payload(payload).summary().startswith("[-01:15]")


def test_match_state_detects_new_match(payload):
    state = MatchState()
    state.update(payload)
    assert state.new_match
    state.update(payload)
    assert not state.new_match
    payload["map"]["matchid"] = "8012345679"
    state.update(payload)
    assert state.new_match


def test_back_to_back_bot_matches_are_separate(payload):
    payload["map"]["matchid"] = "0"
    state = MatchState()
    state.update(payload)
    assert state.new_match
    state.update(payload)
    assert not state.new_match

    payload["map"]["game_state"] = "DOTA_GAMERULES_STATE_HERO_SELECTION"
    state.update(payload)
    assert state.new_match
    payload["map"]["game_state"] = "DOTA_GAMERULES_STATE_STRATEGY_TIME"
    state.update(payload)
    assert not state.new_match
