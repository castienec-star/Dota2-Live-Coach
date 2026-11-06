from coach.replay_view import ReplayView, ScreenGate, is_own_match, is_spectating


def spectator_payload() -> dict:
    return {
        "map": {"matchid": "8000000001", "clock_time": 860, "paused": True},
        "player": {
            "team2": {"player0": {"name": "Ana", "team_name": "radiant", "gold": 900, "kills": 2, "deaths": 1, "last_hits": 80}},
            "team3": {"player5": {"name": "Bo", "team_name": "dire", "gold": 300, "deaths": 4}},
        },
        "hero": {
            "team2": {"player0": {"name": "npc_dota_hero_juggernaut", "xpos": -4000, "ypos": -3500,
                                  "level": 9, "health": 400, "max_health": 1000}},
            "team3": {"player5": {"name": "npc_dota_hero_lion", "xpos": 100, "ypos": 200, "alive": False}},
        },
        "items": {
            "team2": {"player0": {"slot0": {"name": "item_power_treads"}, "slot1": {"name": "empty"},
                                  "stash0": {"name": "item_tango"}}},
        },
    }


def own_payload() -> dict:
    return {"player": {"steamid": "765", "gold": 100}, "hero": {"name": "npc_dota_hero_axe"}}


def test_spectator_shape_is_detected():
    assert is_spectating(spectator_payload())
    assert not is_own_match(spectator_payload())
    assert is_own_match(own_payload())
    assert not is_spectating(own_payload())
    assert not is_spectating({"provider": {"name": "Dota 2"}})


def test_replay_view_reads_every_hero():
    view = ReplayView.from_payload(spectator_payload())
    assert view.match_id == "8000000001" and view.paused
    jugg = view.hero("npc_dota_hero_juggernaut")
    assert jugg.team == "radiant" and jugg.x == -4000
    assert round(jugg.health_percent) == 40
    assert jugg.items == ["item_power_treads"]
    lion = view.team("dire")[0]
    assert lion.hero_name == "npc_dota_hero_lion" and not lion.alive and lion.deaths == 4


def test_own_match_has_no_replay_view():
    assert ReplayView.from_payload(own_payload()) is None


def test_screen_gate_opens_only_while_spectating():
    now = [0.0]
    gate = ScreenGate(clock=lambda: now[0], fresh_seconds=10)
    assert not gate.open
    gate.see(spectator_payload())
    assert gate.open
    now[0] = 11
    assert not gate.open  # replay closed, updates stopped
    gate.see(spectator_payload())
    assert gate.open
    gate.see(own_payload())
    assert not gate.open  # a live match shuts it at once
    gate.see({"provider": {"name": "Dota 2"}})
    assert not gate.open
