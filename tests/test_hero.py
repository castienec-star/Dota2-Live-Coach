import pytest

from coach.items import load_items, lookup
from coach.rules import Engine
from coach.rules.hero import (
    Buyback,
    ItemReady,
    LowHealth,
    SkillPoint,
    WandCharges,
    WardReminder,
    build,
    parse_builds,
)
from coach.state import MatchState


def run(rule, payload, steps):
    """Apply each step's changes to the payload, tick the clock, collect lines."""
    said = []
    engine = Engine([rule], said.append)
    state = MatchState()
    clock = payload["map"]["clock_time"]
    for step in steps:
        clock += step.pop("dt", 1)
        payload["map"]["clock_time"] = clock
        for path, value in step.items():
            section, key = path.split(".")
            payload[section][key] = value
        state.update(payload)
        engine(state)
    return said


def test_low_health_once_until_healed(payload):
    said = run(LowHealth(), payload, [
        {"hero.health": 1000},
        {"hero.health": 300},  # 22%
        {"hero.health": 250},
        {"hero.health": 1300, "dt": 30},
        {"hero.health": 200},
    ])
    assert said == ["Low health, back off."] * 2


def test_low_health_silent_when_dead(payload):
    said = run(LowHealth(), payload, [{"hero.health": 0, "hero.alive": False}])
    assert said == []


def test_buyback_warns_when_gold_drops_under_cost(payload):
    payload["map"]["clock_time"] = 1900
    payload["hero"]["buyback_cost"] = 2000
    said = run(Buyback(), payload, [
        {"player.gold": 2500},
        {"player.gold": 1800},
        {"player.gold": 1700},
    ])
    assert said == ["You are under buyback gold. Buyback costs 2000."]


def test_buyback_quiet_early_or_on_cooldown(payload):
    payload["hero"]["buyback_cost"] = 2000
    payload["player"]["gold"] = 100
    assert run(Buyback(), payload, [{}]) == []  # 11:05, before 30:00
    payload["map"]["clock_time"] = 1900
    payload["hero"]["buyback_cooldown"] = 300
    assert run(Buyback(), payload, [{}]) == []


def test_skill_point_after_delay(payload):
    steps = [{"hero.level": 12}] + [{} for _ in range(12)]
    said = run(SkillPoint(), payload, [{}] + steps)
    assert said == ["Skill point unused."]


def test_skill_point_spent_in_time(payload):
    said = run(SkillPoint(), payload, [
        {},
        {"hero.level": 12},
        {"abilities.ability2": {"name": "antimage_counterspell", "level": 2}},
    ] + [{} for _ in range(15)])
    assert said == []


def test_skill_point_counts_talents(payload):
    said = run(SkillPoint(), payload, [
        {},
        {"hero.level": 12},
        {"hero.talent_1": True},
    ] + [{} for _ in range(15)])
    assert said == []


def test_skill_point_quiet_past_max_level(payload):
    payload["hero"]["level"] = 16
    said = run(SkillPoint(), payload, [{}, {"hero.level": 17}] + [{} for _ in range(15)])
    assert said == []


def test_item_ready_announces_next_unowned_item(payload):
    items = load_items()
    rule = ItemReady(parse_builds({"antimage": ["Power Treads", "Manta Style"]}, items))
    said = run(rule, payload, [
        {"player.gold": 3000},
        {"player.gold": 4700},
        {"player.gold": 4800},
    ])
    # Treads are already owned (sample inventory), so Manta is next.
    assert said == ["You have gold for Manta Style."]


def test_item_ready_uses_default_build():
    items = load_items()
    rule = ItemReady(parse_builds({"default": ["blink"]}, items))
    assert rule.builds["default"][0].name == "Blink Dagger"


def test_support_without_build_uses_support_default(payload):
    from coach.heroes import HeroIndex

    builds = parse_builds({"default": ["Battle Fury"], "default_support": ["Glimmer Cape"]}, load_items())
    rule = ItemReady(builds, HeroIndex())
    assert rule.build_for("crystal_maiden")[0].name == "Glimmer Cape"
    assert rule.build_for("antimage")[0].name == "Battle Fury"
    # Without hero roles every hero falls back to "default".
    assert ItemReady(builds).build_for("crystal_maiden")[0].name == "Battle Fury"


def test_empty_hero_build_turns_reminder_off(payload):
    from coach.heroes import HeroIndex

    builds = parse_builds({"default": ["Battle Fury"], "pudge": []}, load_items())
    assert ItemReady(builds, HeroIndex()).build_for("pudge") == []


def test_default_builds_name_real_heroes_and_items(tmp_path):
    from coach import config
    from coach.heroes import HeroIndex

    cfg = config.load(app_dir=tmp_path)
    keys = {h.key for h in HeroIndex().heroes.values()}
    assert {"default", "default_support"} <= set(cfg.builds)
    for hero, names in cfg.builds.items():
        assert hero in keys | {"default", "default_support"}, f"no hero called {hero!r}"
        assert len(names) == len(set(names)), f"repeated item in the build for {hero}"
    # Fails loudly if a patch removes an item a build names.
    parse_builds(cfg.builds, load_items())


def test_unknown_item_is_an_error():
    with pytest.raises(ValueError):
        parse_builds({"luna": ["Not An Item"]}, load_items())


def test_lookup_accepts_names_and_keys():
    items = load_items()
    assert lookup(items, "Black King Bar").key == "item_black_king_bar"
    assert lookup(items, "black_king_bar").cost == lookup(items, "item_black_king_bar").cost


def test_wand_once_per_time_hurt(payload):
    # Sample wand has 14 charges; 412/1380 hp is about 30%.
    said = run(WandCharges(), payload, [
        {},
        {"dt": 40},
        {"hero.health": 1300},
        {"hero.health": 400, "dt": 31},
    ])
    assert said == ["Use your wand, 14 charges."] * 2


def test_wand_quiet_when_healthy(payload):
    assert run(WandCharges(), payload, [{"hero.health": 1300}]) == []


def test_ward_after_holding(payload):
    payload["items"]["slot3"] = {"name": "item_ward_observer", "can_cast": True, "charges": 1}
    said = run(WardReminder(), payload, [{} for _ in range(61)])
    assert said == ["Place your observer ward."]


def test_build_reads_config_switches():
    rules = build({"wand": {"enabled": False}, "low_health": {"below": 30}}, {})
    names = [r.name for r in rules]
    assert "wand" not in names and "item_ready" not in names
    low = next(r for r in rules if r.name == "low_health")
    assert low.below == 30


def test_default_config_builds(tmp_path):
    from coach import config

    cfg = config.load(app_dir=tmp_path)
    rules = build(cfg.reminders, cfg.builds)
    assert {r.name for r in rules} >= {"low_health", "buyback", "skill_point", "wand", "ward", "item_ready"}
