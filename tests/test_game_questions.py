import pytest

from coach.__main__ import first_pending
from coach.game_questions import GameQuestions, build, parse_result, parse_yes_no
from coach.heroes import HeroIndex
from coach.lineup import Question
from coach.state import MatchState

INDEX = HeroIndex()


class Game:
    """Feeds GSI updates for one match to the questions."""

    def __init__(self, payload, questions):
        self.payload, self.questions, self.state = payload, questions, MatchState()

    def at(self, clock, health=1380, alive=True, respawn=0, paused=False):
        hero, game = self.payload["hero"], self.payload["map"]
        game["clock_time"], game["paused"] = clock, paused
        hero["health"], hero["alive"], hero["respawn_seconds"] = health, alive, respawn
        self.state.update(self.payload)
        self.questions(self.state)
        return self.questions.pending()


@pytest.mark.parametrize(
    "text, expected",
    [("We won.", "won"), ("lost it", "lost"), ("it was even", "even"), ("not bad", "even"),
     ("pretty bad", "lost"), ("we're winning", "won"), ("pizza", None)],
)
def test_parse_result(text, expected):
    assert parse_result(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [("Yes.", True), ("yeah he is", True), ("No.", False), ("not really", False), ("hmm", None)],
)
def test_parse_yes_no(text, expected):
    assert parse_yes_no(text) == expected


def test_lane_question_after_ten_minutes_when_calm(payload):
    game = Game(payload, GameQuestions(INDEX))
    assert game.at(590) is None  # laning stage
    question = game.at(610)
    assert question.text == "How did your lane go: won, even or lost?"
    reply = question.answer("I lost my lane")
    assert "safe camps" in reply
    assert game.questions.notes.lane == "lost"
    assert game.at(611) is None  # asked once


def test_never_in_a_fight(payload):
    game = Game(payload, GameQuestions(INDEX))
    game.at(600)
    assert game.at(601, health=900) is None  # taking damage
    assert game.at(605, health=1380) is None  # healed, but hit 4 seconds ago
    assert game.at(612, health=1380) is not None  # quiet for 10 seconds
    assert game.at(613, health=400) is None  # low health


def test_asks_while_dead_with_time_to_wait(payload):
    game = Game(payload, GameQuestions(INDEX))
    assert game.at(700, health=0, alive=False, respawn=5) is None  # too short
    assert game.at(701, health=0, alive=False, respawn=25) is not None
    assert game.at(702, paused=True, health=0, alive=False, respawn=24) is None


def test_one_question_every_few_minutes_in_order(payload):
    enemies = [INDEX.find("pa"), INDEX.find("lion")]
    game = Game(payload, GameQuestions(INDEX, lambda: enemies, every=300))
    game.at(600).answer("even")
    assert game.at(899) is None  # the wait starts at the answer
    trouble = game.at(900)
    assert trouble.text == "Which enemy hero is giving you the most trouble?"
    assert trouble.answer("phantom assassin") == (
        "Got it, Phantom Assassin. Check where Phantom Assassin is on the map "
        "before you fight, and don't fight them alone."
    )
    assert game.questions.notes.trouble.name == "Phantom Assassin"
    carry = game.at(1200)
    assert carry.text == "Is their carry farming freely?"
    assert carry.answer("yeah") == (
        "Then group up with your team and go find their carry, or they will win the late game."
    )
    fights = game.at(1500)
    assert fights.text == "Is your team ahead or behind in fights?"
    assert "Roshan" in fights.answer("we're ahead")
    assert game.questions.notes.fights == "won"
    assert game.at(2400) is None  # all asked


def test_silence_drops_the_question_and_late_lane_is_skipped(payload):
    game = Game(payload, GameQuestions(INDEX, every=60))
    assert game.at(600).answer("") is None
    assert game.questions.notes.lane is None
    assert game.at(720).text.startswith("Which enemy")  # the lane isn't asked again
    late = Game(payload, GameQuestions(INDEX))
    assert late.at(1100).text.startswith("Which enemy")  # lane is old news by 18:00


def test_new_match_starts_over(payload):
    game = Game(payload, GameQuestions(INDEX))
    game.at(600).answer("won")
    payload["map"]["matchid"] = "8012345679"
    assert game.at(600).text.startswith("How did your lane go")
    assert game.questions.notes.lane is None


def test_settings():
    assert build({"game_questions": False}, INDEX) is None
    assert build({"question_every": 120}, INDEX).every == 120


def test_start_questions_go_first():
    class Asker:
        def __init__(self, question):
            self.question = question

        def pending(self):
            return self.question

    first, second = Question("first", lambda a: None), Question("second", lambda a: None)
    assert first_pending(None, None) is None
    assert first_pending(Asker(first), Asker(second))() is first
    assert first_pending(Asker(None), Asker(second))() is second


def test_trouble_hero_must_be_a_told_enemy(payload):
    enemies = [INDEX.find("pa"), INDEX.find("lion")]
    questions = GameQuestions(INDEX, lambda: enemies)
    assert questions._answer("trouble", "pudge") is None  # an ally, or misheard
    assert questions.notes.trouble is None
    questions = GameQuestions(INDEX)  # no lineup told: any hero
    questions._answer("trouble", "pudge")
    assert questions.notes.trouble.name == "Pudge"
