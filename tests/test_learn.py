from coach import learn
from coach.hero_stats import HeroStat

NAMES = {"skeleton_king": "Wraith King", "dragon_knight": "Dragon Knight", "witch_doctor": "Witch Doctor",
         "crystal_maiden": "Crystal Maiden", "lich": "Lich", "juggernaut": "Juggernaut"}


def stat(win_rate: float, picks: int = 10_000) -> HeroStat:
    return HeroStat(picks, round(picks * win_rate), 1, 100, 0.1)


# Archon (bracket 4) only: other brackets must never be used.
STATS = {
    4: {
        "skeleton_king": stat(0.56),
        "dragon_knight": stat(0.53),
        "juggernaut": stat(0.49),  # loses at this medal: left out
        "witch_doctor": stat(0.52),
        "crystal_maiden": stat(0.51),
        "lich": stat(0.55),
        "pudge": stat(0.60),  # not in the pool of easy heroes
    },
    5: {"juggernaut": stat(0.70)},
}


def test_two_cores_and_a_support_from_the_players_own_medal():
    line = learn.suggest("what hero should I learn", "archon", STATS, NAMES)
    assert line == (
        "In Archon games this patch: Wraith King wins 56%: his ultimate gives you a second life. "
        "Dragon Knight wins 53%: tanky and simple. Lich wins 55%: safe spells from far away. "
        "Pick one and play it for your next ten games."
    )


def test_the_question_names_the_role():
    line = learn.suggest("what support should I learn", "archon", STATS, NAMES)
    assert [n for n in ("Lich", "Witch Doctor", "Crystal Maiden") if n in line] == ["Lich", "Witch Doctor", "Crystal Maiden"]
    assert line.index("Lich") < line.index("Witch Doctor") < line.index("Crystal Maiden")
    assert "Wraith King" not in line


def test_the_position_this_game_names_the_role():
    line = learn.suggest("what hero should I learn", "archon", STATS, NAMES, position=1)
    assert "Wraith King" in line and "Dragon Knight" in line
    assert "Lich" not in line and "Juggernaut" not in line  # Juggernaut loses in Archon


def test_unknown_medal_names_safe_heroes_and_asks_for_it():
    line = learn.suggest("what hero should I learn", None, STATS, NAMES)
    assert line.startswith("Good heroes to learn. Wraith King:")
    assert "%" not in line  # no numbers from a medal that isn't the player's
    assert "say my rank is" in line


def test_a_medal_without_numbers_says_so():
    line = learn.suggest("what hero should I learn", "immortal", STATS, NAMES)
    assert "%" not in line
    assert "I don't have this patch's numbers for Immortal games." in line


def test_role_words():
    assert learn.role_in("I play pos 5") == learn.SUPPORT
    assert learn.role_in("best carry to learn") == learn.CORE
    assert learn.role_in("what hero should I learn") is None


def test_every_pool_hero_exists():
    from coach.heroes import load_heroes

    keys = {h.key for h in load_heroes().values()}
    assert set(learn.POOL) <= keys
