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
    WorthBuying,
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


def test_any_boots_count_for_the_builds_boots(payload):
    # The sample hero has Power Treads; a build's Arcane Boots are done.
    items = load_items()
    rule = ItemReady(parse_builds({"antimage": ["Arcane Boots", "Glimmer Cape"]}, items))
    said = run(rule, payload, [{"player.gold": 3000}])
    assert said == ["You have gold for Glimmer Cape."]


def test_boots_of_travel_still_come_on_top_of_other_boots(payload):
    items = load_items()
    rule = ItemReady(parse_builds({"antimage": ["Phase Boots", "Boots of Travel"]}, items))
    said = run(rule, payload, [{"player.gold": 5000}])
    assert said == ["You have gold for Boots of Travel."]


def test_an_upgrade_counts_as_owning_the_item(payload):
    payload["items"]["slot3"] = {"name": "item_hurricane_pike", "purchaser": 0, "can_cast": True}
    items = load_items()
    rule = ItemReady(parse_builds({"antimage": ["Force Staff", "Black King Bar"]}, items))
    said = run(rule, payload, [{"player.gold": 5000}])
    assert said == ["You have gold for Black King Bar."]


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


def worth_buying(build, items=("Magic Wand", "stats"), **options):
    from coach.heroes import HeroIndex

    all_items = load_items()
    cheap = [i if i == "stats" else lookup(all_items, i) for i in items]
    return WorthBuying(parse_builds({"antimage": build}, all_items), HeroIndex(), cheap, **options)


def test_worth_buying_while_saving_for_a_big_item(payload):
    payload["items"]["slot2"] = {"name": "empty"}  # no wand
    said = run(worth_buying(["Black King Bar"]), payload, [{"player.gold": 600}])
    assert said == ["Buy a Magic Wand now, you'll get your Black King Bar later."]


def test_worth_buying_skips_owned_items_and_uses_hero_attribute(payload):
    # The sample hero already has a Magic Wand; Anti-Mage is agility.
    said = run(worth_buying(["Black King Bar"]), payload, [{"player.gold": 600}])
    assert said == ["Buy a Wraith Band now, you'll get your Black King Bar later."]


def test_worth_buying_once_per_item_with_cooldown(payload):
    payload["items"]["slot2"] = {"name": "empty"}
    said = run(worth_buying(["Black King Bar"]), payload, [
        {"player.gold": 600},
        {"player.gold": 600, "dt": 60},  # Magic Wand not bought, still in cooldown
        {"player.gold": 600, "dt": 200},
        {"player.gold": 600, "dt": 200},
    ])
    assert said == [
        "Buy a Magic Wand now, you'll get your Black King Bar later.",
        "Buy a Wraith Band now, you'll get your Black King Bar later.",
    ]


def test_worth_buying_quiet_when_big_item_is_close_or_cheap_one_unaffordable(payload):
    payload["items"]["slot2"] = {"name": "empty"}
    rule = worth_buying(["Black King Bar"])
    assert run(rule, payload, [{"player.gold": 3500}]) == []  # BKB is 550 away
    assert run(rule, payload, [{"player.gold": 300}]) == []  # can't afford a wand


def test_worth_buying_while_saving_for_boots(payload):
    # Every build starts with boots of 1500 gold or less: the early game,
    # when a wand helps most, must still get the suggestion.
    payload["items"]["slot0"] = payload["items"]["slot2"] = {"name": "empty"}
    payload["map"]["clock_time"] = 180
    said = run(worth_buying(["Power Treads", "Black King Bar"]), payload, [{"player.gold": 700}])
    assert said == ["Buy a Magic Wand now, you'll get your Power Treads later."]


def test_worth_buying_quiet_late_or_without_a_build(payload):
    payload["items"]["slot2"] = {"name": "empty"}
    payload["map"]["clock_time"] = 26 * 60
    assert run(worth_buying(["Black King Bar"]), payload, [{"player.gold": 600}]) == []
    payload["map"]["clock_time"] = 600
    assert run(worth_buying([]), payload, [{"player.gold": 600}]) == []


def test_worth_buying_unknown_item_is_an_error():
    with pytest.raises(ValueError):
        build({"worth_buying": {"items": ["Not An Item"]}}, {"default": ["blink"]})


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
    assert {r.name for r in rules} >= {
        "low_health", "buyback", "skill_point", "wand", "ward", "item_ready", "worth_buying",
    }
