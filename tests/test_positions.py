"""Per-position builds and reminders (issue #11)."""

import dataclasses

from coach.__main__ import make_coach, position_of
from coach.heroes import HeroIndex
from coach.items import load_items
from coach.lineup import configured_position
from coach.rules import Engine, ForPositions, for_positions, split_positions
from coach.rules.hero import ItemReady, WorthBuying, parse_builds
from coach.rules.timers import build as build_timers
from coach.speaker import Speaker
from coach.state import MatchState, Snapshot
from coach.voice import Answers

BUILDS = {
    "default": ["Battle Fury"],
    "default_support": ["Glimmer Cape"],
    "pos2": ["Bottle"],
    "pudge": ["Tranquil Boots"],
    "pudge_pos2": ["Phase Boots"],
}


def names(build):
    return [i.name for i in build]


def test_build_order_by_position():
    rule = ItemReady(parse_builds(BUILDS, load_items()), HeroIndex(), popular={})
    assert names(rule.build_for("pudge", 2)) == ["Phase Boots"]
    assert names(rule.build_for("pudge", 4)) == ["Tranquil Boots"]
    assert names(rule.build_for("pudge")) == ["Tranquil Boots"]
    assert names(rule.build_for("antimage", 2)) == ["Bottle"]
    assert names(rule.build_for("antimage", 1)) == ["Battle Fury"]


def test_position_beats_hero_roles_for_the_default_build():
    rule = ItemReady(parse_builds(BUILDS, load_items()), HeroIndex(), popular={})
    # Crystal Maiden is a support by role, Anti-Mage a carry.
    assert names(rule.build_for("crystal_maiden")) == ["Glimmer Cape"]
    assert names(rule.build_for("crystal_maiden", 1)) == ["Battle Fury"]
    assert names(rule.build_for("antimage", 5)) == ["Glimmer Cape"]


def test_item_ready_asks_for_the_position(payload):
    snap = Snapshot.from_payload(payload)  # Anti-Mage with Treads and Battle Fury
    snap.gold = 10000
    builds = parse_builds({"antimage": ["Manta Style"], "antimage_pos5": ["Glimmer Cape"]}, load_items())
    position = 0
    rule = ItemReady(builds, HeroIndex(), lambda s: position)
    assert rule.next_item(snap).name == "Manta Style"
    position = 5
    assert rule.next_item(snap).name == "Glimmer Cape"


def test_worth_buying_follows_the_position_build(payload):
    snap = Snapshot.from_payload(payload)
    builds = parse_builds({"antimage_pos3": ["Black King Bar"]}, load_items())
    rule = WorthBuying(builds, HeroIndex(), position=lambda s: 3)
    assert rule.next_item(snap).name == "Black King Bar"


def test_voice_answer_uses_the_position(payload):
    snap = Snapshot.from_payload(payload)
    snap.gold = 0
    answers = Answers({}, {"antimage": ["Manta Style"], "pos5": ["Glimmer Cape"]}, lambda s: 5)
    assert answers.answer("what's my next item", snap).startswith("Next is Manta Style.")
    answers = Answers({}, {"antimage_pos5": ["Glimmer Cape"]}, lambda s: 5)
    assert answers.answer("what's my next item", snap).startswith("Next is Glimmer Cape.")


def test_split_positions_leaves_the_rest():
    stripped, positions = split_positions({"water_rune": {"positions": [2], "lead": 10}, "ward": {}})
    assert stripped == {"water_rune": {"lead": 10}, "ward": {}}
    assert positions == {"water_rune": {2}}


def water_rune_lines(payload, position):
    said = []
    reminders, positions = split_positions({"water_rune": {"positions": [2]}})
    rules = for_positions(build_timers(reminders), positions, lambda s: position)
    engine = Engine(rules, said.append)
    state = MatchState()
    for clock in range(100, 115):
        payload["map"]["clock_time"] = clock
        state.update(payload)
        engine(state)
    return [line for line in said if "Water rune" in line]


def test_reminder_only_for_its_positions(payload):
    assert water_rune_lines(payload, 2) == ["Water rune in 10 seconds."]
    assert water_rune_lines(payload, 1) == []


def test_reminder_said_while_position_unknown(payload):
    assert water_rune_lines(payload, 0) == ["Water rune in 10 seconds."]


def test_wrapped_rule_keeps_its_name_and_resets():
    rule = build_timers({})[0]
    wrapped = ForPositions(rule, {2}, lambda s: 0)
    assert wrapped.name == rule.name
    wrapped.reset()


def test_configured_position():
    settings = {"position": 1, "positions": {"pudge": 4}}
    assert configured_position(settings, "npc_dota_hero_pudge") == 4
    assert configured_position(settings, "npc_dota_hero_antimage") == 1
    assert configured_position({"position": 0}, "npc_dota_hero_pudge") == 0
    assert configured_position({"position": 9}, None) == 0


def test_coach_uses_told_then_configured_position(tmp_path, payload):
    from coach import config

    cfg = config.load(app_dir=tmp_path)
    cfg = dataclasses.replace(cfg, pregame={**cfg.pregame, "position": 3, "opendota": False, "learn": False})
    coach = make_coach(cfg, Speaker(), tips=True)
    position = position_of(cfg, coach)
    snap = Snapshot.from_payload(payload)
    assert position(snap) == 3
    coach.pregame.heard(position=5)
    assert position(snap) == 5
    coach.pregame.close()


def test_default_config_limits_water_rune_to_mid(tmp_path):
    from coach import config

    cfg = config.load(app_dir=tmp_path)
    _, positions = split_positions(cfg.reminders)
    assert positions == {"water_rune": {2}}
    # Every rule still builds with the "positions" keys in the config.
    make_coach(cfg, Speaker(), tips=False)
