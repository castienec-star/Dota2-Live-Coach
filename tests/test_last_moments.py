import copy

from coach.items import load_items
from coach.rules import Engine
from coach.rules.death_tip import DeathTip, describe
from coach.rules.last_moments import Moments, notice, spell_name
from coach.state import MatchState, Snapshot

ITEMS = load_items()


def snaps(payload, steps):
    """One snapshot per step; each step changes a copy of the payload."""
    out = []
    for i, change in enumerate(steps):
        p = copy.deepcopy(payload)
        p["map"]["clock_time"] += i
        change(p)
        out.append(Snapshot.from_payload(p))
    return out


def ult_on_cooldown(p):
    """Nothing else to point at: ultimate on cooldown, the wand empty."""
    p["abilities"]["ability3"]["cooldown"] = 60
    p["items"]["slot2"]["charges"] = 0


def test_unused_ultimate_and_item(payload):
    payload["items"]["slot1"] = {"name": "item_invis_sword", "can_cast": True, "cooldown": 0}
    moments = notice(snaps(payload, [lambda p: None]), ITEMS)
    assert moments.unused_item == "Shadow Blade"
    assert moments.unused_ultimate == "Mana Void"
    assert moments.tip() == "You died with your Shadow Blade ready. Press it as soon as the fight turns."


def test_full_wand(payload):
    def wand(p):
        ult_on_cooldown(p)
        p["items"]["slot2"]["charges"] = 12

    moments = notice(snaps(payload, [wand]), ITEMS)
    assert moments.wand_charges == 12
    assert "12 wand charges" in moments.tip()


def test_spell_cast_at_low_health(payload):
    def low(p):
        ult_on_cooldown(p)
        p["hero"]["health"] = 300  # 22%

    def cast(p):
        low(p)
        p["abilities"]["ability1"]["cooldown"] = 12

    moments = notice(snaps(payload, [low, cast]), ITEMS)
    assert moments.low_cast == "Blink"
    assert moments.tip() == "You used Blink at low health. Heal up before you start the next fight."
    assert "cast Blink at 22% health" in moments.facts()[0]


def test_nothing_to_point_at(payload):
    moments = notice(snaps(payload, [ult_on_cooldown]), ITEMS)
    assert moments == Moments() and moments.tip() is None


def test_spell_name():
    assert spell_name("spirit_breaker_charge_of_darkness", "npc_dota_hero_spirit_breaker") == "Charge of Darkness"


def test_prompt_has_the_last_moments(payload):
    snap = Snapshot.from_payload(payload)
    text = describe(snap, ITEMS, moments=Moments(unused_ultimate="Mana Void"))
    assert "In the seconds before dying: their ultimate, Mana Void, was ready and not used" in text


def test_death_tip_says_what_led_to_the_death(payload):
    payload["items"]["slot2"]["charges"] = 0
    said = []
    rule = DeathTip(said.append, None, fallback=lambda snap: "Built-in tip.")
    state, engine = MatchState(), Engine([rule], lambda line: None)
    for _ in range(3):
        payload["map"]["clock_time"] += 1
        state.update(payload)
        engine(state)
    payload["hero"]["alive"] = False
    payload["hero"]["respawn_seconds"] = 25
    payload["map"]["clock_time"] += 1
    state.update(payload)
    engine(state)
    rule.close()
    assert said == ["You died with Mana Void ready. Use your ultimate earlier in the fight."]
