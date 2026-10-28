import pytest

from coach.benchmarks import Verdict
from coach.heroes import HeroIndex
from coach.items import load_items
from coach.situational import THREATS, against, recommend, role, spoken
from coach.state import Item, Snapshot
from coach.voice import Answers, intent

ITEMS = load_items()
HEROES = HeroIndex()
BUILDS = {"antimage": ["Power Treads", "Battle Fury", "Manta Style"]}


def enemies(*keys):
    return [HEROES.by_key(k) for k in keys]


class FixedVerdict:
    """Stands in for Benchmarks with one verdict for every snapshot."""

    def __init__(self, kind):
        self.kind = kind

    def verdict(self, snap, support=False):
        return Verdict(self.kind, 0.5, "gold_per_min", (snap.clock_time or 0) // 60) if self.kind else None


@pytest.fixture
def snap(payload):
    return Snapshot.from_payload(payload)  # Anti-Mage at 11:04 with Treads and Battle Fury


def test_every_threat_hero_and_item_exists():
    keys = {h.key for h in HEROES.heroes.values()}
    for threat in THREATS:
        assert threat.heroes <= keys, threat.reason
        assert set(threat.items.values()) <= set(ITEMS), threat.reason


@pytest.mark.parametrize(
    "position, support, expected",
    [(1, False, "core"), (2, False, "core"), (3, False, "offlane"), (4, True, "support"), (0, True, "support")],
)
def test_role(position, support, expected):
    assert role(position, support) == expected


def test_magic_nukers_mean_black_king_bar_for_a_core(snap):
    pick = against(enemies("lina", "lion", "pudge"), "core", snap, ITEMS)
    assert pick.item.name == "Black King Bar"
    assert pick.reason == "Lina and Lion do a lot of magic damage"


def test_one_nuker_is_not_enough_for_an_item(snap):
    assert against(enemies("lina", "antimage"), "core", snap, ITEMS) is None


def test_the_item_depends_on_the_role(snap):
    nukers = enemies("lina", "zuus")
    assert against(nukers, "offlane", snap, ITEMS).item.name == "Pipe of Insight"
    assert against(nukers, "support", snap, ITEMS).item.name == "Glimmer Cape"


def test_specific_counters_come_first(snap):
    pick = against(enemies("lina", "zuus", "phantom_assassin"), "core", snap, ITEMS)
    assert pick.item.name == "Monkey King Bar"
    assert pick.reason == "Phantom Assassin dodges your attacks"


def test_invisible_heroes(snap):
    assert against(enemies("riki"), "support", snap, ITEMS).item.name == "Sentry Ward"
    pick = against(enemies("riki"), "core", snap, ITEMS)
    assert (pick.item.name, pick.reason) == ("Dust of Appearance", "Riki can turn invisible")


def test_owned_items_and_upgrades_are_skipped(snap):
    snap.items.append(Item("slot5", "item_mjollnir", None, True, 0))
    assert against(enemies("phantom_lancer"), "core", snap, ITEMS) is None


def test_behind_without_a_threat_buys_to_stay_alive(snap):
    pick = recommend(snap, FixedVerdict("behind").verdict(snap), [], "support", ITEMS, None)
    assert pick.item.name == "Glimmer Cape"
    assert pick.reason == ""


def test_ahead_or_even_without_a_threat_follows_the_build(snap):
    manta = ITEMS["item_manta"]
    for kind in ("ahead", "even", None):
        pick = recommend(snap, FixedVerdict(kind).verdict(snap), [], "core", ITEMS, manta)
        assert pick.item is manta


def test_spoken_line(snap):
    snap.gold = 1000
    verdict = FixedVerdict("behind").verdict(snap)
    pick = against(enemies("lina", "lion"), "core", snap, ITEMS)
    assert spoken(pick, verdict, snap) == (
        "You're behind for 11 minutes. Get Black King Bar next, 3050 more gold: "
        "Lina and Lion do a lot of magic damage."
    )
    snap.gold = 5000
    assert spoken(pick, None, snap) == "Buy Black King Bar now: Lina and Lion do a lot of magic damage."


def test_spoken_defensive_line(snap):
    snap.gold = 5000
    verdict = FixedVerdict("behind").verdict(snap)
    pick = recommend(snap, verdict, [], "core", ITEMS, None)
    assert spoken(pick, verdict, snap) == "You're behind for 11 minutes. Buy Black King Bar now to stay alive."


@pytest.mark.parametrize("text", ["What should I buy?", "what do I get", "any item to counter them"])
def test_what_to_buy_intent(text):
    assert intent(text) == "what_to_buy"


def test_voice_answer_uses_the_enemy_lineup(snap):
    snap.gold = 500
    lineup = enemies("lina", "lion", "pudge", "sniper", "axe")
    answers = Answers({}, BUILDS, benchmarks=FixedVerdict("even"), enemies=lambda: lineup)
    assert answers.answer("what should I buy", snap) == (
        "You're about even for 11 minutes. Get Black King Bar next, 3550 more gold: "
        "Lina and Lion do a lot of magic damage."
    )


def test_voice_answer_without_a_lineup_is_the_build(snap):
    snap.gold = 500
    answers = Answers({}, BUILDS, benchmarks=FixedVerdict("ahead"))
    manta = ITEMS["item_manta"]
    assert answers.answer("what should I buy", snap) == (
        f"You're ahead for 11 minutes. Get Manta Style next, {manta.cost - 500} more gold."
    )


def test_voice_answer_for_a_support_uses_the_position(snap):
    snap.gold = 3000
    lineup = enemies("lina", "zuus")
    answers = Answers({}, BUILDS, position=lambda s: 5, benchmarks=FixedVerdict(None), enemies=lambda: lineup)
    assert answers.answer("what do I buy", snap) == "Buy Glimmer Cape now: Lina and Zeus do a lot of magic damage."
