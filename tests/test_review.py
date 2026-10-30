import copy

from coach import __main__ as main_mod
from coach.items import load_items
from coach.profile import MatchSummary
from coach.review import POST_GAME, Review, last_hit_target, points, spoken, text
from coach.state import MatchState

from test_pregame import IN_PROGRESS, write_recording

ITEMS = load_items()


def match(**kw):
    base = dict(
        hero="luna", duration=1800, won=True, kills=5, deaths=4, assists=6,
        last_hits_10=40, death_times=[700, 1300, 1500, 1700], item_times={"item_manta": 1000},
    )
    return MatchSummary(**{**base, **kw})


def test_target_is_35_at_ten():
    assert last_hit_target() == 35


def test_early_deaths_low_last_hits_and_late_item():
    m = match(deaths=5, death_times=[200, 500, 900, 1400, 1700], last_hits_10=18, item_times={"item_bfury": 1500})
    lines = points(m, False, ITEMS)
    assert len(lines) == 3
    assert "died 2 times before 10 minutes" in lines[0]
    assert "18 last hits at 10 minutes; aim for 35" in lines[1]
    assert "Battle Fury, came at 25 minutes" in lines[2]


def test_death_streak():
    m = match(deaths=4, death_times=[900, 1000, 1150, 1700])
    assert "died 3 times between 15 and 20 minutes" in points(m, False, ITEMS)[0]


def test_good_game_gets_praise_not_invented_problems():
    m = match(deaths=2, death_times=[700, 1500])
    lines = points(m, False, ITEMS)
    assert lines == [
        "Only 2 deaths in 30 minutes: staying alive like that wins games, keep it up.",
        "40 last hits at 10 minutes is right on target.",
    ]


def test_support_skips_last_hits_and_gets_support_items():
    m = match(hero="lion", deaths=2, death_times=[700, 1500], last_hits_10=3, item_times={})
    lines = points(m, True, ITEMS)
    assert not any("last hits" in line for line in lines)
    assert "Glimmer Cape or Force Staff" in lines[0]


def test_never_empty():
    m = match(duration=900, deaths=3, death_times=[700, 800, 900], last_hits_10=None, item_times={})
    assert len(points(m, False, ITEMS)) == 1


def test_text_file_layout():
    m = match()
    out = text(m, ["One.", "Two."])
    assert out.startswith("Luna, 30 minutes, won. 5 kills, 4 deaths, 6 assists, 40 last hits at 10:00")
    assert "1. One.\n2. Two.\n" in out


def feed(review, payload, clocks, deaths=()):
    state = MatchState()
    p = copy.deepcopy(payload)
    p["items"] = {}
    for clock in clocks:
        p["map"]["clock_time"] = clock
        p["map"]["game_state"] = IN_PROGRESS
        p["player"]["deaths"] = sum(1 for t in deaths if t <= clock)
        p["player"]["last_hits"] = clock // 30
        state.update(copy.deepcopy(p))
        review(state)
    p["map"]["game_state"] = POST_GAME
    state.update(copy.deepcopy(p))
    review(state)
    state.update(copy.deepcopy(p))
    review(state)


def test_review_spoken_once_at_post_game_and_saved(tmp_path, payload):
    said = []
    review = Review(said.append, tmp_path / "reviews", position=lambda snap: 1)
    feed(review, payload, range(0, 1801, 30), deaths=(100, 300))
    assert len(said) == 1
    assert said[0].startswith("Match review. You died 2 times before 10 minutes.")
    assert "20 last hits at 10 minutes" in said[0]
    assert review.saved is not None and review.saved.parent == tmp_path / "reviews"
    assert "1. You died 2 times" in review.saved.read_text(encoding="utf-8")


def test_short_game_gets_no_review(tmp_path, payload):
    said = []
    review = Review(said.append, tmp_path, position=lambda snap: 1)
    feed(review, payload, range(0, 200, 30))
    assert said == []


def test_review_command_prints_points(tmp_path, payload, capsys):
    rec = tmp_path / "a.jsonl"
    write_recording(rec, payload, deaths=(100, 200, 900))
    assert main_mod.main(["--config", str(tmp_path / "none.toml"), "review", str(rec)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Luna, 20 minutes, won.")
    assert "1. You died 2 times before 10 minutes" in out


def test_spoken():
    assert spoken(["A.", "B."]) == "Match review. A. B."
