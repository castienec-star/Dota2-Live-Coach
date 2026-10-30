import json

from coach import knowledge
from coach.draft import Analysis, Draft
from coach.game_questions import Notes
from coach.grounding import Grounding
from coach.heroes import HeroIndex
from coach.item_advisor import describe as item_prompt
from coach.items import load_items
from coach.pregame import facts
from coach.rules.death_tip import describe as tip_prompt
from coach.situational import Pick
from coach.state import Snapshot

HEROES = HeroIndex()
ITEMS = load_items()


def test_short_drops_numbers_and_the_words_around_them():
    assert knowledge.short("Teleport to a target point up to 1200 units away.") == (
        "Teleport to a target point."
    )
    assert knowledge.short("Deals 60% of attack damage as physical damage.") == (
        "Deals part of attack damage as physical damage."
    )
    assert knowledge.short("CHANNELED - Summons a vortex.") == "Summons a vortex."


def test_short_keeps_whole_sentences_up_to_the_word_limit():
    text = "One two three. Four five six seven. Eight."
    assert knowledge.short(text, 7) == "One two three. Four five six seven."
    assert knowledge.short("one two three four five", 3) == "one two three..."


def test_hero_abilities_skip_hidden_slots_and_mark_the_ultimate():
    abilities = {
        "x_q": {"dname": "Q", "desc": "Stuns.", "behavior": "Unit Target", "bkbpierce": "No"},
        "x_e": {"dname": "E", "desc": "Hits harder.", "behavior": "Passive"},
        "x_r": {"dname": "R", "desc": "Big damage.", "behavior": ["Unit Target"], "bkbpierce": "Yes"},
        "x_hidden": {"dname": "H", "behavior": ["No Target", "Hidden"]},
    }
    found = knowledge.hero_abilities(
        ["x_q", "generic_hidden", "x_e", "x_hidden", "generic_hidden", "x_r"], abilities
    )
    assert [a["name"] for a in found] == ["Q", "E", "R"]
    assert [a["passive"] for a in found] == [False, True, False]
    assert found[-1]["ultimate"] and found[-1]["pierces"]


def test_bundled_cards_have_every_hero_and_no_numbers():
    with knowledge.KNOWLEDGE_FILE.open(encoding="utf-8") as f:
        data = json.load(f)
    assert {h.key for h in HEROES.heroes.values()} <= set(data["heroes"])
    text = json.dumps([data["heroes"], list(data["items"].values())], ensure_ascii=False)
    assert not any(c.isdigit() for c in text)


def test_cards_for_heroes_and_items():
    lion = HEROES.by_key("lion")
    assert knowledge.hero_card(lion).startswith("Lion: Earth Spike: ")
    assert knowledge.hero_card(lion, ultimate_only=True).startswith("Lion: Finger of Death (ultimate)")
    culling = knowledge.hero_card(HEROES.by_key("axe"), ultimate_only=True)
    assert "Culling Blade (ultimate, goes through spell immunity)" in culling
    assert "Avatar" in knowledge.item_line(ITEMS["item_black_king_bar"])
    assert knowledge.hero_card(None) == ""
    assert knowledge.hero_cards([lion, lion, None]) == [knowledge.hero_card(lion)]


def test_death_tip_prompt_says_what_own_abilities_and_items_do(payload):
    text = tip_prompt(Snapshot.from_payload(payload), ITEMS, notes=Notes(trouble=HEROES.by_key("lion")))
    assert "Abilities: Mana Break (passive): " in text
    assert "Mana Void (ultimate)" in text
    assert "What the items do: Power Treads: " in text
    assert "What Lion does: Earth Spike" in text


def test_briefing_facts_have_full_enemy_cards_and_ally_ultimates(payload):
    snap = Snapshot.from_payload(payload)
    me = HEROES.by_key("antimage")
    draft = Draft([me, HEROES.by_key("lion")], [HEROES.by_key("axe")], me)
    text = facts(snap, draft, Analysis(), [])
    cards = text.split("What the heroes do:\n", 1)[1].splitlines()
    assert cards[0].startswith("Anti-Mage: Mana Break")
    assert cards[1].startswith("Axe: Berserker's Call")
    assert cards[2].startswith("Lion: Finger of Death (ultimate)") and "Hex" not in cards[2]
    # The cards add no numbers the model could repeat as facts.
    assert not any(c.isdigit() for c in "".join(cards))


def test_item_prompt_has_what_candidates_and_enemy_ultimates_do(payload):
    snap = Snapshot.from_payload(payload)
    picks = [Pick(ITEMS["item_black_king_bar"], ""), Pick(ITEMS["item_manta"], "")]
    text = item_prompt(snap, picks, None, [HEROES.by_key("lion")], ITEMS)
    assert "- Lion: Finger of Death (ultimate)" in text
    assert (
        "- item_black_king_bar: Black King Bar, 4050 gold; for spell immunity against stuns, "
        "hexes and magic damage; Strength, Damage; active Avatar"
    ) in text


def test_items_say_what_players_buy_them_for():
    assert knowledge.item_line(ITEMS["item_silver_edge"]).startswith("for break: turns off")
    # Items without a written use still say what they do.
    assert knowledge.item_line(ITEMS["item_tango"]).startswith("use Devour")
    uses = " ".join(knowledge.ITEM_USES.values())
    assert not any(c.isdigit() for c in uses)
    # A death tip may name any hero its prompt names.
    assert not Grounding(HEROES).heroes(uses)
