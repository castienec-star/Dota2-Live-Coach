import pytest

from coach.heroes import HeroIndex
from coach.lineup import Interview, TypedQuestions, parse_heroes, parse_position
from coach.pregame import Pregame
from coach.state import PRE_GAME, MatchState

INDEX = HeroIndex()
STRATEGY = "DOTA_GAMERULES_STATE_STRATEGY_TIME"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Four.", 4),
        ("pos 4", 4),
        ("Position two", 2),
        ("I'm playing for", 4),
        ("mid", 2),
        ("Soft support.", 4),
        ("support", 5),
        ("offlane", 3),
        ("carry", 1),
        ("pizza", None),
    ],
)
def test_parse_position(text, expected):
    assert parse_position(text) == expected


def names(heroes):
    return [h.name for h in heroes]


def test_parse_spoken_heroes():
    text = "They have Anti-Mage, Crystal Maiden and Lion, Pudge and Shadow Fiend."
    assert names(parse_heroes(INDEX, text)) == [
        "Anti-Mage", "Crystal Maiden", "Lion", "Pudge", "Shadow Fiend",
    ]


def test_parse_nicknames_and_mishearings():
    # "we" would match Weaver on its own; "sniber" is a mishearing of Sniper.
    assert names(parse_heroes(INDEX, "We've got storm, QoP and sniber")) == [
        "Storm Spirit", "Queen of Pain", "Sniper",
    ]


class Sink:
    """Stands in for the briefing: remembers what the player said."""

    def __init__(self):
        self.position, self.allies, self.enemies = 0, [], []

    def heard(self, position=None, allies=None, enemies=None):
        if position is not None:
            self.position = position
        if allies is not None:
            self.allies = allies
        if enemies is not None:
            self.enemies = enemies


def start(payload, interview, game_state=STRATEGY, clock=-60):
    state = MatchState()
    payload["hero"]["name"] = "npc_dota_hero_luna"
    payload["map"]["game_state"] = "DOTA_GAMERULES_STATE_HERO_SELECTION"
    state.update(payload)
    interview(state)
    payload["map"]["game_state"] = game_state
    payload["map"]["clock_time"] = clock
    state.update(payload)
    interview(state)
    return state


def converse(interview, answers):
    """Answers each question in turn; returns everything the coach said."""
    said = []
    for answer in answers:
        question = interview.pending()
        assert question is not None, f"no question left for {answer!r}"
        said.append(question.text)
        reply = question.answer(answer)
        if reply:
            said.append(reply)
    assert interview.pending() is None
    return said


def test_asks_position_team_and_enemies(payload):
    sink = Sink()
    interview = Interview(INDEX, sink)
    assert interview.pending() is None  # nothing during the draft
    start(payload, interview)
    assert interview.busy
    said = converse(interview, [
        "four",
        "lion, tide, earthshaker and crystal maiden",
        "yes",
        "anti-mage, phantom assassin, shadow fiend, invoker, pudge",
        "",  # silence accepts the read-back
    ])
    assert said == [
        "What position are you playing, one to five?",
        "Position 4, soft support.",
        "Who's on your team?",
        "Your team: Lion, Tidehunter, Earthshaker, Crystal Maiden. Right?",
        "Who are the enemy heroes?",
        "Enemies: Anti-Mage, Phantom Assassin, Shadow Fiend, Invoker, Pudge. Right?",
    ]
    assert sink.position == 4
    assert names(sink.allies) == ["Lion", "Tidehunter", "Earthshaker", "Crystal Maiden"]
    assert names(sink.enemies)[0] == "Anti-Mage"
    assert not interview.busy


def test_correct_a_misheard_hero(payload):
    sink = Sink()
    interview = Interview(INDEX, sink, position=1)
    start(payload, interview)
    said = converse(interview, [
        "skip",  # teammates
        "am cm lion pudge sf",
        "no, lina not lion",
        "right",
    ])
    assert said[-1] == "Enemies: Anti-Mage, Crystal Maiden, Lina, Pudge, Shadow Fiend. Right?"
    assert names(sink.enemies) == ["Anti-Mage", "Crystal Maiden", "Lina", "Pudge", "Shadow Fiend"]
    assert sink.allies == []
    assert sink.position == 1  # from coach.toml, not asked


def test_hero_by_hero(payload):
    sink = Sink()
    interview = Interview(INDEX, sink, position=2)
    start(payload, interview)
    said = converse(interview, ["skip", "pudge", "and sniper", "no"])
    assert "Enemies: Pudge. Anyone else?" in said
    assert "Enemies: Pudge, Sniper. Anyone else?" in said
    assert names(sink.enemies) == ["Pudge", "Sniper"]


def test_no_to_a_full_list_starts_over(payload):
    sink = Sink()
    interview = Interview(INDEX, sink, position=2)
    start(payload, interview)
    said = converse(interview, [
        "skip", "am cm lion pudge sf", "no", "axe zeus lion pudge sniper", "yes",
    ])
    assert "Okay, say them again." in said
    assert names(sink.enemies) == ["Axe", "Zeus", "Lion", "Pudge", "Sniper"]


def test_known_answers_are_not_asked(payload):
    sink = Sink()
    sink.enemies = [INDEX.find("am")]  # typed in the coach window
    interview = Interview(INDEX, sink, hero_positions={"luna": 1})
    start(payload, interview)
    assert converse(interview, ["skip"]) == ["Who's on your team?"]
    assert sink.position == 1


def test_silence_skips_and_own_hero_is_left_out(payload):
    sink = Sink()
    interview = Interview(INDEX, sink)
    start(payload, interview)
    converse(interview, ["", "luna, lion", "yes", ""])
    assert sink.position == 0
    assert names(sink.allies) == ["Lion"]  # Luna is the player's own hero


def test_asks_once_a_match_and_late_starts(payload):
    interview = Interview(INDEX, Sink(), position=1)
    state = start(payload, interview, game_state="DOTA_GAMERULES_STATE_GAME_IN_PROGRESS", clock=20)
    assert interview.pending().text == "Who's on your team?"
    converse(interview, ["skip", "skip"])
    interview(state)
    assert interview.pending() is None
    late = Interview(INDEX, Sink(), position=1)
    start(payload, late, game_state="DOTA_GAMERULES_STATE_GAME_IN_PROGRESS", clock=300)
    assert late.pending() is None


def test_answers_reach_the_briefing(payload):
    prompts = []
    pregame = Pregame(lambda line: None, INDEX, ask=lambda p: prompts.append(p) or "ok")
    interview = Interview(INDEX, pregame)
    pregame.waiting = lambda: interview.busy
    state = MatchState()
    payload["hero"]["name"] = "npc_dota_hero_luna"
    payload["map"]["game_state"] = PRE_GAME
    state.update(payload)
    interview(state)
    pregame(state)
    converse(interview, ["5", "skip", "pudge sniper", "no"])
    pregame.close()
    assert len(prompts) == 1
    assert "Player's position: 5 (hard support)" in prompts[0]
    assert "Enemies: Pudge, Sniper" in prompts[0]


def test_typed_answers_when_the_coach_cant_hear(payload):
    sink, said, shown = Sink(), [], []
    interview = Interview(INDEX, sink)
    questions = TypedQuestions(interview, said.append, shown.append)
    state = start(payload, interview)
    questions(state)
    questions(state)  # shown once, however many updates come
    assert shown == [
        "Coach asks: What position are you playing, one to five?  (type the answer and press Enter; Enter alone skips)"
    ]
    assert said == ["Type your position, your team and the enemy heroes in the coach window."]
    assert questions.answer("4")
    assert questions.answer("lion tide es cm")
    assert questions.answer("")
    assert questions.answer("am pa sf invoker pudge")
    assert questions.answer("")
    assert not questions.answer("vs pudge")  # nothing left to answer
    assert sink.position == 4
    assert names(sink.enemies)[1] == "Phantom Assassin"
    assert "Position 4, soft support." in shown
    assert shown[-1].startswith("Coach asks: Enemies: Anti-Mage")
    assert len(said) == 1
