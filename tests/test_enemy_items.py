import pytest

from coach.enemy_items import EnemyItems, ItemMatcher
from coach.heroes import HeroIndex
from coach.state import MatchState
from coach.voice import Answers


@pytest.fixture(scope="module")
def index():
    return HeroIndex()


@pytest.fixture(scope="module")
def matcher():
    return ItemMatcher()


def record(index, matcher, *enemies):
    lineup = [index.by_key(k) for k in enemies]
    return EnemyItems(index, lambda: lineup, matcher)


@pytest.mark.parametrize(
    "text, said",
    [
        ("Lion has Glimmer and Force Staff", "Got it, Lion has Glimmer Cape and Force Staff."),
        ("enemy Sven bought BKB", "Got it, Sven has Black King Bar."),
        ("Phantom Assassin got a black king bar and a desolator", "Got it, Phantom Assassin has Black King Bar and Desolator."),
        ("lion has force, not glimmer", "Got it, Lion has Force Staff."),
        ("Anti-Mage is building a Manta", "Got it, Anti-Mage has Manta Style."),
    ],
)
def test_reports_are_read_back(index, matcher, text, said):
    items = EnemyItems(index, matcher=matcher)
    assert items.is_report(text)
    assert items.report(text) == said


@pytest.mark.parametrize(
    "text",
    [
        "what should I buy",
        "should I buy BKB against Lina",
        "do I have a black king bar",
        "does Lion have Glimmer",
        "their carry has butterfly",  # no hero named
        "Lina has nothing",
        "how am I doing",
    ],
)
def test_questions_are_not_reports(index, matcher, text):
    items = EnemyItems(index, matcher=matcher)
    assert not items.is_report(text)
    assert items.report(text) is None
    assert items.told() == {}


def test_latest_report_replaces_and_forget_clears(index, matcher):
    items = record(index, matcher, "lion", "sven")
    items.report("Lion has Glimmer")
    items.report("Sven has BKB")
    items.report("Lion has Force Staff and Glimmer")
    assert items.facts() == ["Lion has Force Staff and Glimmer Cape", "Sven has Black King Bar"]
    assert items.report("forget the enemy items") == "Okay, I forgot the enemy items."
    assert items.told() == {}


def test_only_told_enemies_when_the_lineup_is_known(index, matcher):
    items = record(index, matcher, "lion", "sven")
    assert items.report("Pudge has Blink Dagger") is None  # not an enemy this match
    assert items.report("Lion has Blink Dagger") == "Got it, Lion has Blink Dagger."


def test_new_match_starts_empty(index, matcher, payload):
    items = record(index, matcher, "lion")
    state = MatchState()
    state.update(payload)
    items(state)
    items.report("Lion has Glimmer")
    payload["map"]["matchid"] = "999"
    state.update(payload)
    items(state)
    assert items.told() == {}


def test_voice_answers_record_a_report(index, matcher, payload):
    from coach.state import Snapshot

    items = record(index, matcher, "lion")
    answers = Answers({}, {}, enemy_items=items)
    snap = Snapshot.from_payload(payload)
    assert answers.answer("Lion has Glimmer Cape", snap) == "Got it, Lion has Glimmer Cape."
    assert items.facts() == ["Lion has Glimmer Cape"]
    assert answers.answer("can I buy back", snap).startswith(("You can", "Buyback"))


def test_every_nickname_is_a_real_item(matcher):
    from coach.enemy_items import NICKNAMES

    assert set(NICKNAMES.values()) <= set(matcher.items)


def test_told_items_reach_what_to_buy(tmp_path, payload):
    from coach import config
    from coach.__main__ import make_coach, notes_of, what_to_buy
    from coach.speaker import Speaker

    cfg = config.load(app_dir=tmp_path)
    coach = make_coach(cfg, Speaker(), tips=False)
    coach.handle(payload)  # Anti-Mage, a core
    assert notes_of(coach)() is None  # nothing told yet, no questions
    coach.enemy_items.report("Lion has Glimmer and Force Staff")
    assert "Lion has Glimmer Cape and Force Staff" in notes_of(coach)().told()
    assert "Nullifier" in what_to_buy(coach)


@pytest.mark.parametrize(
    "text, said",
    [
        ("Lion has glimmer and Sven has BKB", "Got it, Lion has Glimmer Cape and Sven has Black King Bar."),
        ("lion glimmer and force", "Got it, Lion has Glimmer Cape and Force Staff."),
        ("nothing new", None),
        ("skip", None),
    ],
)
def test_answer_to_the_check_question(index, matcher, text, said):
    assert EnemyItems(index, matcher=matcher).answer(text) == said
