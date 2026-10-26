import threading

from coach.items import load_items
from coach.rules import Engine
from coach.rules.death_tip import DeathTip, build, describe
from coach.state import MatchState, Snapshot


def die(payload, state, engine, respawn=25):
    payload["hero"]["alive"] = True
    state.update(payload)
    engine(state)
    payload["hero"]["alive"] = False
    payload["hero"]["respawn_seconds"] = respawn
    payload["map"]["clock_time"] += 1
    state.update(payload)
    engine(state)


def make(ask, **kwargs):
    said = []
    rule = DeathTip(said.append, ask, **kwargs)
    return rule, said


def test_tip_spoken_once_per_death(payload):
    prompts = []
    rule, said = make(lambda p: prompts.append(p) or "Farm the safe lane jungle.")
    state = MatchState()
    engine = Engine([rule], lambda line: None)
    die(payload, state, engine)
    # More updates while dead must not ask again.
    state.update(payload)
    engine(state)
    rule.close()
    assert said == ["Farm the safe lane jungle."]
    assert len(prompts) == 1


def test_no_tip_after_respawn(payload):
    release = threading.Event()

    def slow(prompt):
        release.wait(5)
        return "Too late."

    rule, said = make(slow)
    state = MatchState()
    engine = Engine([rule], lambda line: None)
    die(payload, state, engine)
    payload["hero"]["alive"] = True
    state.update(payload)
    release.set()
    rule.close()
    assert said == []


def test_short_death_timer_skipped(payload):
    rule, said = make(lambda p: "Tip.")
    state = MatchState()
    die(payload, state, Engine([rule], lambda line: None), respawn=5)
    rule.close()
    assert said == []


def test_failed_request_is_silent(payload):
    rule, said = make(lambda p: None)
    state = MatchState()
    die(payload, state, Engine([rule], lambda line: None))
    rule.close()
    assert said == []


def test_prompt_has_only_own_hero_data(payload):
    text = describe(Snapshot.from_payload(payload), load_items())
    assert "Hero: antimage, level 11" in text
    assert "Battle Fury" in text and "Magic Wand" in text
    assert "Gold: 1640; buyback costs 865 (affordable)" in text
    # GSI in player mode has no enemy data, and the prompt adds none.
    assert "enemy" not in text.lower()


def test_build_can_be_switched_off():
    assert build({"death_tip": {"enabled": False}}, print) == []
    rules = build({"death_tip": {"min_respawn": 20}}, print)
    assert rules[0].min_respawn == 20
    rules[0].close()
