import pytest

from coach.grounding import Grounding, numbers
from coach.heroes import HeroIndex

INDEX = HeroIndex()
GROUNDING = Grounding(INDEX)
LUNA = INDEX.find("luna")

# What the model said before the horn in a real match with no Phantom Assassin.
INVENTED = (
    "Alright, listen up. Our main strength is our team's roaming capabilities, so we "
    "can take advantage of that. We need to watch out for their Phantom Assassin, "
    "she's been taking out our carry. Wait for our jungler to come out and help you, "
    "and then we can make a push around 20-25 minutes."
)


def test_invented_hero_is_caught():
    problem = GROUNDING.problem(INVENTED, "Player's hero: Luna", [LUNA])
    assert problem is not None and "Phantom Assassin" in problem


def test_jungler_and_unknown_teams_are_caught():
    assert "jungler" in GROUNDING.problem("Wait for our jungler.", "", [LUNA])
    assert GROUNDING.problem("Our team is strong.", "", [LUNA], allies_known=False)
    stay = "Stay with your team until your Black King Bar is ready."
    assert GROUNDING.problem(stay, "", [LUNA], allies_known=False) is None
    assert GROUNDING.problem("Watch their carry.", "", [LUNA], enemies_known=False)
    assert GROUNDING.problem("Watch their carry.", "", [LUNA]) is None


def test_numbers_must_come_from_the_facts():
    facts = "Your lineup is strongest from about 15 to 25 minutes."
    assert GROUNDING.problem("Fight from 15 to twenty five minutes.", facts, []) is None
    assert "20" in GROUNDING.problem("Push around 20-25 minutes.", facts, [])
    assert GROUNDING.problem("Push at 20 minutes.", facts, [], check_numbers=False) is None


@pytest.mark.parametrize(
    "text, ok",
    [
        ("Kill the Anti-Mage early.", True),
        ("Kill the anti mage early.", True),
        ("Kill the AM early.", True),
        ("Watch the PA.", False),
        ("Buy a TP and a tiny ward.", True),
        ("Stop Tiny from getting a blink.", False),
    ],
)
def test_hero_names_short_names_and_common_words(text, ok):
    allowed = [LUNA, INDEX.find("am")]
    assert (GROUNDING.problem(text, "", allowed) is None) == ok


def test_numbers():
    assert numbers("at 10, twenty five and thirty minutes, 1v1") == {10, 25, 30}


def test_a_line_that_drifts_into_another_language_is_dropped():
    g = Grounding(HeroIndex())
    assert g.problem("Use Force Staff组合使用力杖", "", []) == 'is not all in English ("组")'
    assert g.problem("Don\u2019t fight alone \u2014 use your Blink. Café.", "", []) is None
