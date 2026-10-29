"""The in-match answers (issue #11 step 4) in buy advice, the game check and death tips."""

import pytest

from coach.__main__ import make_coach, notes_of
from coach.benchmarks import Benchmarks, Verdict
from coach.config import load
from coach.game_questions import Notes
from coach.heroes import HeroIndex
from coach.items import load_items
from coach.rules.death_tip import BuiltinTips, describe
from coach.rules.game_check import GameCheck
from coach.situational import against, recommend, struggling
from coach.speaker import Speaker
from coach.state import MatchState, Snapshot
from coach.voice import Answers

ITEMS = load_items()
HEROES = HeroIndex()
MANTA = ITEMS["item_manta"]


def hero(key):
    return HEROES.by_key(key)


def verdict(kind):
    return Verdict(kind, 0.5, "gold_per_min", 11) if kind else None


@pytest.fixture
def snap(payload):
    return Snapshot.from_payload(payload)  # Anti-Mage at 11:04 with Treads and Battle Fury


@pytest.mark.parametrize(
    "kind, notes, expected",
    [
        ("behind", None, ""),
        (None, None, None),
        (None, Notes(fights="lost"), "your team is losing fights"),
        ("even", Notes(carry_free=True), "their carry is farming freely"),
        (None, Notes(lane="lost"), "your lane was hard"),
        ("even", Notes(lane="lost"), None),  # the numbers say it is even now
        ("ahead", Notes(fights="lost", carry_free=True), None),
        (None, Notes(lane="won", fights="won", carry_free=False), None),
    ],
)
def test_struggling(kind, notes, expected):
    assert struggling(verdict(kind), notes) == expected


def test_the_trouble_hero_needs_only_one_and_comes_first(snap):
    lineup = [hero("lina"), hero("phantom_assassin")]
    # Alone, one nuker isn't worth a Black King Bar and Phantom Assassin wins.
    assert against(lineup, "core", snap, ITEMS).item.name == "Monkey King Bar"
    pick = against(lineup, "core", snap, ITEMS, trouble=hero("lina"))
    assert (pick.item.name, pick.reason) == ("Black King Bar", "Lina does a lot of magic damage")


def test_a_trouble_hero_without_a_counter_falls_back_to_the_lineup(snap):
    pick = against([hero("riki")], "core", snap, ITEMS, trouble=hero("antimage"))
    assert pick.reason == "Riki can turn invisible"


def test_losing_fights_buys_to_stay_alive(snap):
    pick = recommend(snap, verdict("even"), [], "support", ITEMS, MANTA, Notes(fights="lost"))
    assert (pick.item.name, pick.reason) == ("Glimmer Cape", "your team is losing fights")
    pick = recommend(snap, verdict("ahead"), [], "support", ITEMS, MANTA, Notes(fights="lost"))
    assert pick.item is MANTA


def test_voice_answer_uses_the_notes(snap):
    snap.gold = 500
    notes = Notes(lane="lost", trouble=hero("lion"))
    answers = Answers({}, {}, benchmarks=Benchmarks(), notes=lambda: notes)
    assert answers.answer("what should I buy", snap) == (
        "Get Black King Bar next, 3550 more gold: Lion does a lot of magic damage."
    )
    notes.trouble = None
    assert answers.answer("what should I buy", snap) == (
        "Get Black King Bar next, 3550 more gold: your lane was hard."
    )


def jugg(gpm):
    return Snapshot(
        clock_time=1500, hero_name="npc_dota_hero_juggernaut", gpm=gpm, xpm=gpm + 50, last_hits=gpm // 4
    )


def run_check(rule, snap):
    state = MatchState()
    state.current = snap
    return rule.check(state)


def test_game_check_adds_a_defensive_item_when_even_but_losing_fights():
    rule = GameCheck(Benchmarks(), minutes=[25], notes=lambda: Notes(fights="lost"))
    (line,) = run_check(rule, jugg(500))
    assert line.startswith("You're about even for 25 minutes.")
    assert line.endswith("Get Black King Bar next, 4050 more gold: your team is losing fights.")


def test_game_check_names_the_trouble_hero():
    rule = GameCheck(Benchmarks(), minutes=[25], notes=lambda: Notes(trouble=hero("riki")))
    (line,) = run_check(rule, jugg(400))
    assert line.endswith("Riki can turn invisible.")


def test_game_check_without_notes_is_unchanged():
    rule = GameCheck(Benchmarks(), minutes=[25], notes=lambda: Notes())
    (line,) = run_check(rule, jugg(500))
    assert line == "You're about even for 25 minutes. Keep farming and fight together with your team."


def test_builtin_tips_name_the_trouble_hero_every_other_death(snap):
    notes = Notes(trouble=hero("pudge"))
    tips = BuiltinTips(lambda: notes)
    snap.clock_time = 300
    first = tips(snap)
    assert first == "Next life, find Pudge on the minimap before you fight, and don't meet Pudge alone."
    assert tips(snap) != first
    assert tips(snap) == first


def test_builtin_tip_for_losing_fights(snap):
    snap.clock_time, snap.deaths = 300, 1
    snap.items = [i for i in snap.items if i.name != "item_tpscroll"]
    tips = BuiltinTips(lambda: Notes(fights="lost"))
    assert "losing fights" in tips(snap)


def test_prompt_has_what_the_player_told(snap):
    notes = Notes(lane="lost", trouble=hero("pudge"), carry_free=True, fights="even")
    text = describe(snap, ITEMS, notes=notes)
    assert text.endswith(
        "The player told you: their lane was lost; Pudge gives them the most trouble; "
        "the enemy carry is farming freely; their team is about even in fights"
    )
    assert "told" not in describe(snap, ITEMS, notes=Notes())


def test_coach_reads_the_notes_once_questions_are_on(tmp_path):
    coach = make_coach(load(app_dir=tmp_path), Speaker(), tips=False)
    notes = notes_of(coach)
    assert notes() is None

    class Questions:
        notes = Notes(lane="won")

    coach.questions = Questions()
    assert notes().lane == "won"


def test_model_tip_may_name_the_trouble_hero(payload):
    # The grounding check must not drop a tip about the hero the player named.
    from coach.rules import Engine
    from coach.rules.death_tip import DeathTip
    from coach.state import MatchState

    notes = Notes(trouble=HEROES.by_key("npc_dota_hero_pudge"))
    tip = "Find Pudge on the minimap before you walk into the trees."
    said = []
    rule = DeathTip(said.append, lambda prompt: tip, fallback=lambda snap: "Built-in tip.", notes=lambda: notes)
    state, engine = MatchState(), Engine([rule], lambda line: None)
    payload["hero"]["alive"] = True
    state.update(payload)
    engine(state)
    payload["hero"]["alive"] = False
    payload["hero"]["respawn_seconds"] = 25
    payload["map"]["clock_time"] += 1
    state.update(payload)
    engine(state)
    rule.close()
    assert said == [tip]
