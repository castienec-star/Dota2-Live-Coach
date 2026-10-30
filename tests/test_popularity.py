import json

from coach import popularity
from coach.__main__ import main
from coach.heroes import HeroIndex, load_heroes
from coach.items import load_items
from coach.rules.hero import ItemReady, parse_builds

ITEMS = load_items()
HEROES = HeroIndex()
ITEM_IDS = {"1": "blink", "29": "boots", "50": "phase_boots", "63": "power_treads", "116": "black_king_bar",
            "112": "ultimate_scepter", "36": "magic_wand", "208": "abyssal_blade", "121": "recipe_bkb",
            "147": "manta"}
POPULARITY = {
    "start_game_items": {"36": 900},
    "early_game_items": {"36": 800, "50": 700, "29": 900},
    "mid_game_items": {"1": 500, "116": 400, "36": 300, "121": 200},
    "late_game_items": {"112": 300, "116": 250, "208": 200},
}


def fake_get(path):
    if path == "/constants/item_ids":
        return ITEM_IDS
    if path.endswith("/itemPopularity"):
        return POPULARITY
    return None


def test_top_items_are_ordered_and_skip_recipes():
    assert popularity.top_items(POPULARITY["mid_game_items"], ITEM_IDS) == [
        "item_blink", "item_black_king_bar", "item_magic_wand",
    ]


def test_fetch_every_hero_and_save_and_load(tmp_path):
    heroes = dict(list(load_heroes().items())[:3])
    said = []
    found = popularity.fetch(fake_get, heroes, pause=0, progress=said.append)
    assert set(found) == {h.key for h in heroes.values()}
    assert len(said) == 3
    path = tmp_path / "pop.json"
    popularity.save(found, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["patch"] == (popularity.PATCH_FILE.read_text(encoding="utf-8").strip())
    assert popularity.load(path) == found


def test_load_without_a_snapshot_is_empty(tmp_path):
    assert popularity.load(tmp_path / "missing.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert popularity.load(bad) == {}


def test_popular_build_is_boots_then_big_items():
    stages = {short: popularity.top_items(POPULARITY[stage], ITEM_IDS) for stage, short in popularity.STAGES.items()}
    names = [i.name for i in popularity.popular_build(stages, ITEMS)]
    # Plain Boots of Speed and Magic Wand are left out; BKB is not repeated.
    assert names == ["Phase Boots", "Blink Dagger", "Black King Bar", "Aghanim's Scepter", "Abyssal Blade"]


def test_too_little_data_is_no_build():
    assert popularity.popular_build({"mid": ["item_blink"], "late": []}, ITEMS) == []


def test_hero_without_a_build_gets_the_popular_one():
    builds = parse_builds({"default": ["Power Treads", "Satanic"], "pudge": ["Blink Dagger"]}, ITEMS)
    stages = {"early": ["item_power_treads"], "mid": ["item_manta", "item_black_king_bar"], "late": []}
    rule = ItemReady(builds, popular=popularity.popular_builds(ITEMS, {"lina": stages, "pudge": stages}))
    assert [i.name for i in rule.build_for("lina")] == ["Power Treads", "Manta Style", "Black King Bar"]
    # Your own build list always wins.
    assert [i.name for i in rule.build_for("pudge")] == ["Blink Dagger"]
    assert rule.build_for("axe")[1].name == "Satanic"
    # A position list of your own wins too; the popular one comes before the defaults.
    builds["pos2"] = [ITEMS["item_bottle"]]
    assert [i.name for i in rule.build_for("lina", 2)] == ["Bottle"]
    assert rule.build_for("lina", 1)[0].name == "Power Treads"


def test_refresh_items_command(tmp_path, monkeypatch):
    monkeypatch.setattr("coach.config.user_dir", lambda: tmp_path)
    monkeypatch.setattr("coach.opendota.OpenDota.get", lambda self, path, max_age=None: fake_get(path))
    monkeypatch.setattr("coach.popularity.time.sleep", lambda s: None)
    out = tmp_path / "pop.json"
    assert main(["--config", str(tmp_path / "none.toml"), "refresh-items", "--out", str(out)]) == 0
    assert len(popularity.load(out)) == len(load_heroes())


def test_refresh_items_saves_nothing_when_offline(tmp_path, monkeypatch):
    monkeypatch.setattr("coach.config.user_dir", lambda: tmp_path)
    monkeypatch.setattr("coach.opendota.OpenDota.get", lambda self, path, max_age=None: None)
    out = tmp_path / "pop.json"
    assert main(["--config", str(tmp_path / "none.toml"), "refresh-items", "--out", str(out)]) == 1
    assert not out.exists()


def test_components_and_replaced_parts_are_left_out():
    stages = {
        "early": ["item_boots", "item_travel_boots", "item_power_treads"],
        "mid": ["item_yasha", "item_ultimate_orb", "item_kaya", "item_yasha_and_kaya"],
        "late": ["item_rapier", "item_black_king_bar", "item_mystic_staff"],
    }
    names = [i.name for i in popularity.popular_build(stages, ITEMS)]
    # Travel boots aren't the first boots; Yasha and Kaya replace their parts.
    assert names == ["Power Treads", "Yasha and Kaya", "Black King Bar"]


def test_bundled_snapshot_covers_every_hero_with_real_items():
    snapshot = popularity.load()
    heroes = {h.key for h in load_heroes().values()}
    assert set(snapshot) == heroes
    builds = popularity.popular_builds(ITEMS, snapshot)
    assert len(builds) >= len(heroes) * 0.9
    for hero, build in builds.items():
        keys = [i.key for i in build]
        assert len(keys) == len(set(keys)), hero
        assert not set(keys) & popularity.COMPONENTS, hero


def test_a_support_skips_a_carry_build():
    builds = parse_builds({"default": ["Power Treads"], "default_support": ["Glimmer Cape"]}, ITEMS)
    carry = [ITEMS[k] for k in ("item_phase_boots", "item_radiance", "item_manta", "item_butterfly")]
    support = [ITEMS[k] for k in ("item_arcane_boots", "item_glimmer_cape", "item_force_staff")]
    assert popularity.carry_build(carry)
    assert not popularity.carry_build(support)
    rule = ItemReady(builds, HEROES, popular={"abaddon": carry, "lion": support})
    assert rule.build_for("abaddon", 1) == carry
    assert [i.name for i in rule.build_for("abaddon", 5)] == ["Glimmer Cape"]
    assert rule.build_for("lion", 5) == support


def test_expensive_items_alone_make_a_carry_build():
    build = [ITEMS[k] for k in ("item_ultimate_scepter", "item_shivas_guard", "item_assault")]
    assert popularity.carry_build(build)


def test_aghanims_blessing_is_left_out():
    stages = {"mid": ["item_ultimate_scepter_2", "item_black_king_bar", "item_blink"], "late": []}
    assert [i.name for i in popularity.popular_build(stages, ITEMS)] == ["Black King Bar", "Blink Dagger"]
