import json
from types import SimpleNamespace

import pytest

from coach import item_advisor
from coach.benchmarks import Verdict
from coach.game_questions import Notes
from coach.heroes import HeroIndex
from coach.item_advisor import Advice, ItemAdvisor, ItemWatch, candidates, describe, parse, schema, watch
from coach.situational import Pick
from coach.items import load_items
from coach.state import Item, Snapshot
from coach.voice import Answers

ITEMS = load_items()
HEROES = HeroIndex()
MANTA = ITEMS["item_manta"]
BEHIND = Verdict("behind", 0.2, "gold_per_min", 11)


def enemies(*keys):
    return [HEROES.by_key(k) for k in keys]


@pytest.fixture
def snap(payload):
    return Snapshot.from_payload(payload)  # Anti-Mage at 11:04 with Treads and Battle Fury


def short_list(snap, verdict=BEHIND, lineup=("lina", "lion")):
    return candidates(snap, verdict, enemies(*lineup), "core", ITEMS, MANTA)


class FakeModel:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def __call__(self, prompt, fmt=None):
        self.calls.append((prompt, fmt))
        return self.reply


def test_candidates_put_the_rule_pick_first_without_repeats(snap):
    keys = [p.item.key for p in short_list(snap)]
    # Lina and Lion call for a BKB, which is also the defensive pick when behind.
    assert keys == ["item_black_king_bar", "item_manta"]


def test_candidates_skip_owned_items(snap):
    keys = [p.item.key for p in short_list(snap, lineup=("phantom_assassin",))]
    assert keys == ["item_monkey_king_bar", "item_manta", "item_black_king_bar"]
    assert "item_bfury" not in keys


def test_prompt_has_own_data_lineup_notes_and_candidates(snap):
    picks = short_list(snap, lineup=("phantom_assassin",))
    notes = Notes(lane="lost", fights="lost")
    prompt = describe(snap, picks, BEHIND, enemies("phantom_assassin"), ITEMS,
                      HEROES.by_key("antimage"), 1, notes)
    assert "Hero: Anti-Mage" in prompt
    assert "Position: 1" in prompt
    assert "Game time: 11:04 (mid game)" in prompt
    assert "Enemy heroes: Phantom Assassin (melee" in prompt
    assert "their team is losing in fights" in prompt
    assert "- item_monkey_king_bar: Monkey King Bar" in prompt
    assert "behind" in prompt


def test_schema_only_allows_the_candidates(snap):
    picks = short_list(snap)
    assert schema(picks)["properties"]["item"]["enum"] == ["item_black_king_bar", "item_manta"]


@pytest.mark.parametrize(
    "reply, expected",
    [
        ('{"item": "item_manta", "why": "you farm fast"}', ("item_manta", "you farm fast")),
        ('Sure! {"item": "manta", "why": "x"}', ("item_manta", "x")),
        ('{"item": "item_rapier", "why": "big damage"}', None),
        ("Buy a Manta Style.", None),
        ('{"item": ', None),
        ("[1, 2]", None),
        (None, None),
    ],
)
def test_parse(snap, reply, expected):
    parsed = parse(reply, short_list(snap))
    assert (None if parsed is None else (parsed[0].item.key, parsed[1])) == expected


def test_reason_must_stick_to_the_facts():
    advisor = ItemAdvisor(None)
    lineup = enemies("lina", "lion")
    assert advisor.problem("Lina and Lion stun you a lot", lineup, None, None) is None
    assert advisor.problem("Pudge keeps hooking you", lineup, None, None)
    assert advisor.problem("you need 30 percent more damage", lineup, None, None)
    assert advisor.problem("word " * 20, lineup, None, None)
    assert advisor.problem("their team has a lot of magic", [], None, None)


def test_model_choice_is_spoken_with_its_reason(snap):
    model = FakeModel(json.dumps({"item": "item_manta", "why": "Lina and Lion can't stop your farm."}))
    pick = ItemAdvisor(model).choose(snap, BEHIND, enemies("lina", "lion"), "core", ITEMS, MANTA)
    assert pick.item.key == "item_manta"
    assert pick.reason == "Lina and Lion can't stop your farm"
    assert model.calls[0][1]["properties"]["item"]["enum"] == ["item_black_king_bar", "item_manta"]


def test_ungrounded_reason_falls_back_to_the_rule_reason(snap):
    model = FakeModel('{"item": "item_black_king_bar", "why": "Pudge has 3 hooks"}')
    pick = ItemAdvisor(model).choose(snap, BEHIND, enemies("lina", "lion"), "core", ITEMS, MANTA)
    assert pick.item.key == "item_black_king_bar"
    assert pick.reason == "Lina and Lion do a lot of magic damage"


@pytest.mark.parametrize("reply", [None, "garbage", '{"item": "item_rapier", "why": "x"}'])
def test_no_model_or_bad_reply_uses_the_rule_pick(snap, reply):
    pick = ItemAdvisor(FakeModel(reply)).choose(snap, BEHIND, enemies("lina", "lion"), "core", ITEMS, MANTA)
    assert pick.item.key == "item_black_king_bar"


def test_same_question_is_answered_from_the_cache(snap):
    model = FakeModel('{"item": "item_manta", "why": "farm"}')
    advisor = ItemAdvisor(model)
    for _ in range(3):
        advisor.choose(snap, BEHIND, enemies("lina", "lion"), "core", ITEMS, MANTA)
    assert len(model.calls) == 1
    snap.clock_time += 60
    advisor.choose(snap, BEHIND, enemies("lina", "lion"), "core", ITEMS, MANTA)
    assert len(model.calls) == 2


def test_cache_stays_small(snap):
    model = FakeModel('{"item": "item_manta", "why": "farm"}')
    advisor = ItemAdvisor(model)
    for minute in range(40):
        snap.clock_time = minute * 60
        advisor.choose(snap, BEHIND, enemies("lina", "lion"), "core", ITEMS, MANTA)
    assert len(advisor._cache) <= ItemAdvisor.CACHE


def test_one_candidate_needs_no_model(snap):
    model = FakeModel('{"item": "item_manta", "why": "farm"}')
    snap.items.append(Item("slot5", "item_black_king_bar", None, True, 0))
    pick = ItemAdvisor(model).choose(snap, None, [], "core", ITEMS, MANTA)
    assert pick.item.key == "item_manta"
    assert model.calls == []


def test_voice_answer_uses_the_advisor(snap):
    model = FakeModel('{"item": "item_manta", "why": "you out-farm them"}')
    builds = {"antimage": ["Power Treads", "Battle Fury", "Manta Style"]}
    lineup = lambda: enemies("lina", "lion")  # noqa: E731
    answers = Answers({}, builds, enemies=lineup, advice=Advice(ItemAdvisor(model), builds, enemies=lineup))
    snap.gold = 0
    answer = answers.answer("what should I buy?", snap)
    assert f"Get Manta Style next, {MANTA.cost} more gold: you out-farm them." in answer


@pytest.mark.parametrize("advisor", ["ollama", "claude", "rules"])
def test_build_each_advisor(advisor):
    assert isinstance(item_advisor.build({"advisor": advisor}), ItemAdvisor)


def test_build_rejects_unknown_advisor():
    with pytest.raises(ValueError):
        item_advisor.build({"advisor": "gpt"})


BKB = ITEMS["item_black_king_bar"]


def run_watch(item_watch, snap, seconds):
    """Calls check like the engine does, waiting for each background job."""
    said = []
    for now in seconds:
        snap.clock_time = now
        said += item_watch.check(SimpleNamespace(current=snap))
        if item_watch._job is not None:
            item_watch._job.result()
    return said


def test_watch_says_a_new_counter_once(snap):
    item_watch = ItemWatch(lambda s: (Pick(BKB, "Lina stuns you"), None, MANTA), every=10, cooldown=120)
    snap.gold = 0
    said = run_watch(item_watch, snap, [700, 710, 720, 730])
    assert said == [f"Get Black King Bar next, {BKB.cost} more gold: Lina stuns you."]


def test_watch_stays_quiet_about_the_next_build_item(snap):
    item_watch = ItemWatch(lambda s: (Pick(MANTA, ""), None, MANTA), every=10)
    assert run_watch(item_watch, snap, [700, 710, 720]) == []


def test_watch_waits_for_the_cooldown_between_changes(snap):
    picks = iter([Pick(BKB, "stuns")] * 2 + [Pick(ITEMS["item_monkey_king_bar"], "evasion")] * 20)
    item_watch = ItemWatch(lambda s: (next(picks), None, MANTA), every=10, cooldown=120)
    said = run_watch(item_watch, snap, range(700, 900, 10))
    assert len(said) == 2
    assert "Black King Bar" in said[0] and "Monkey King Bar" in said[1]


def test_watch_can_be_turned_off():
    advice = Advice(ItemAdvisor(None), {})
    assert watch({"announce": False}, advice) == []
    assert len(watch({}, advice)) == 1


def test_candidates_after_the_build_is_done_add_a_late_item(snap):
    keys = [p.item.key for p in candidates(snap, None, [], "core", ITEMS, None)]
    assert keys == ["item_black_king_bar"]


def test_no_wait_never_calls_the_model(snap):
    model = FakeModel('{"item": "item_manta", "why": "you farm fast"}')
    advisor = ItemAdvisor(model)
    pick = advisor.choose(snap, BEHIND, enemies("lina", "lion"), "core", ITEMS, MANTA, wait=False)
    assert pick.item.key == "item_black_king_bar"  # the rules' pick
    assert model.calls == []
    advisor.choose(snap, BEHIND, enemies("lina", "lion"), "core", ITEMS, MANTA)
    pick = advisor.choose(snap, BEHIND, enemies("lina", "lion"), "core", ITEMS, MANTA, wait=False)
    assert pick.item.key == "item_manta"  # the model's, once it is worked out
    assert len(model.calls) == 1


def test_typed_buy_answers_in_the_coach_window(tmp_path, payload, monkeypatch, capsys):
    import io

    from coach.__main__ import make_coach, read_typed_picks
    from coach.config import load
    from coach.speaker import Speaker

    coach = make_coach(load(app_dir=tmp_path), Speaker(), tips=False)
    monkeypatch.setattr("sys.stdin", io.StringIO("buy\n"))
    read_typed_picks(coach)
    assert capsys.readouterr().out.startswith("I can't see your hero yet.")

    coach.state.update(payload)
    monkeypatch.setattr("sys.stdin", io.StringIO("item\n"))
    read_typed_picks(coach)
    out = capsys.readouterr().out
    assert out.startswith(("Buy ", "Get ", "You're"))
    assert "Manta Style" in out or "Black King Bar" in out
