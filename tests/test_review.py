import copy

import pytest

from coach import __main__ as main_mod
from coach.items import load_items
from coach.profile import MatchSummary
from coach.review import POST_GAME, Last, break_line, stop_line, day_summary, losing_streak, saved_results, saved_reviews, Review, last_hit_target, points, progress, spoken, text
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


def feed(review, payload, clocks, deaths=(), won=None):
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
    if won is not None:
        p["map"]["win_team"] = "radiant" if won else "dire"
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


@pytest.mark.parametrize(
    "point, before, now, expected",
    [
        ("last_hits", dict(last_hits_10=18), dict(last_hits_10=30),
         "You fixed last game's point: 30 last hits at 10 minutes, up from 18. Well done."),
        ("last_hits", dict(last_hits_10=12), dict(last_hits_10=20),
         "Better than last game: 20 last hits at 10 minutes, up from 12. Keep working on it."),
        ("last_hits", dict(last_hits_10=20), dict(last_hits_10=15),
         "Last game's point is still the one to work on: 15 last hits at 10 minutes, after 20 last game."),
        ("deaths", dict(deaths=9, death_times=[100, 300]), dict(deaths=2, death_times=[700, 1500]),
         "You fixed last game's point: 2 deaths this game, after 9 last game. Well done."),
        ("item", dict(item_times={"item_bfury": 1700}), dict(item_times={"item_bfury": 1100}),
         "You fixed last game's point: your first big item came at 18 minutes, after 28 last game. Well done."),
    ],
)
def test_progress_against_last_game(point, before, now, expected):
    last = Last(match(**before), False, point)
    assert progress(last, match(**now), False, ITEMS) == expected


def test_no_progress_line_without_a_point_or_after_a_role_change():
    assert progress(Last(match(), False, None), match(last_hits_10=10), False, ITEMS) is None
    assert progress(Last(match(last_hits_10=10), False, "last_hits"), match(), True, ITEMS) is None


def test_next_review_opens_with_last_games_point(tmp_path, payload):
    said = []
    review = Review(said.append, tmp_path, position=lambda snap: 1)
    feed(review, payload, range(0, 1801, 30), deaths=(100, 300))
    assert review.last.point == "deaths"
    assert (tmp_path / "last.json").exists()
    # A new coach start reads it back.
    review = Review(said.append, tmp_path, position=lambda snap: 1)
    assert review.previous_last_hits() == 20
    feed(review, payload, range(0, 1801, 30), deaths=(1700,))
    assert said[-1].startswith(
        "Match review. You fixed last game's point: 1 death this game, after 2 last game. Well done."
    )
    assert len(review.saved.read_text(encoding="utf-8").splitlines()) <= 2 + 3


def test_bad_last_file_is_ignored(tmp_path):
    (tmp_path / "last.json").write_text("{not json", encoding="utf-8")
    assert Review(lambda line: None, tmp_path).last is None
    assert Review(lambda line: None, None).previous_last_hits() is None


HOUR = 3600
NOON = 1_800_000_000.0  # any fixed moment


def write_review(folder, at, result, hero="luna"):
    folder.mkdir(parents=True, exist_ok=True)
    import time

    name = f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(at))}-{hero}.txt"
    m = match(hero=hero, won={"won": True, "lost": False}.get(result))
    (folder / name).write_text(text(m, ["One."]), encoding="utf-8")


def test_saved_results_read_back_the_text_files(tmp_path):
    write_review(tmp_path, NOON - 2 * HOUR, "won")
    write_review(tmp_path, NOON - HOUR, "lost", hero="lion")
    write_review(tmp_path, NOON, "unknown")
    (tmp_path / "notes.txt").write_text("not a review", encoding="utf-8")
    results = saved_results(tmp_path)
    assert [won for _, won in results] == [True, False, None]
    assert results[0][0] == pytest.approx(NOON - 2 * HOUR)


@pytest.mark.parametrize(
    "results, expected",
    [
        ([(NOON - 2 * HOUR, False), (NOON - HOUR, False), (NOON, False)], 3),
        ([(NOON - HOUR, True), (NOON - 0.5 * HOUR, False), (NOON, False)], 2),
        # A long gap is a break the player already took.
        ([(NOON - 5 * HOUR, False), (NOON - HOUR, False), (NOON, False)], 2),
        ([(NOON - HOUR, False), (NOON, None)], 0),
        ([(NOON - 3 * HOUR, False)], 0),
        ([], 0),
    ],
)
def test_losing_streak_counts_this_sitting_only(results, expected):
    assert losing_streak(results, NOON) == expected


def test_break_line():
    assert break_line(3).startswith("That's three losses in a row. Take a ten-minute break")


def lose(tmp_path, payload, at, said, **kw):
    review = Review(said.append, tmp_path, position=lambda snap: 1, clock=lambda: at, **kw)
    feed(review, payload, range(0, 1801, 30), deaths=(1700,), won=False)
    return review


def test_third_loss_in_a_row_suggests_a_break_once_a_day(tmp_path, payload):
    said = []
    lose(tmp_path, payload, NOON - HOUR, said)
    lose(tmp_path, payload, NOON - 0.5 * HOUR, said)
    assert not any("break" in line for line in said)
    lose(tmp_path, payload, NOON, said)
    assert said[-1].startswith("Match review. ")
    assert said[-1].endswith(break_line(3))
    assert len(said) == 3  # one spoken line per review, never a second one that could be dropped
    lose(tmp_path, payload, NOON + 0.5 * HOUR, said)
    assert "break" not in said[-1]  # already said today


def test_break_after_zero_turns_it_off(tmp_path, payload):
    said = []
    for at in (NOON - HOUR, NOON - 0.5 * HOUR, NOON):
        lose(tmp_path, payload, at, said, break_after=0)
    assert not any("break" in line for line in said)


def test_a_win_breaks_the_streak(tmp_path, payload):
    said = []
    lose(tmp_path, payload, NOON - HOUR, said)
    review = Review(said.append, tmp_path, position=lambda snap: 1, clock=lambda: NOON - 0.5 * HOUR)
    feed(review, payload, range(0, 1801, 30), deaths=(1700,), won=True)
    lose(tmp_path, payload, NOON, said)
    assert not any("break" in line for line in said)


# Local noon, so "today" is the same day in any time zone the tests run in.
LOCAL_NOON = __import__("time").mktime((2027, 1, 15, 12, 0, 0, 0, 0, -1))


def write_points(folder, at, won, lines, hero="luna"):
    import time

    folder.mkdir(parents=True, exist_ok=True)
    name = f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(at))}-{hero}.txt"
    (folder / name).write_text(text(match(hero=hero, won=won), lines), encoding="utf-8")


def test_every_point_kind_is_found_back_in_its_saved_file(tmp_path):
    early_deaths = match(deaths=5, death_times=[200, 500, 900, 1400, 1700], last_hits_10=18, item_times={"item_bfury": 1500})
    no_item_support = match(hero="lion", deaths=7, death_times=[700, 900, 1100, 1300, 1500, 2100, 2400], item_times={}, duration=2400)
    write_points(tmp_path, LOCAL_NOON - HOUR, False, points(early_deaths, False, ITEMS))
    write_points(tmp_path, LOCAL_NOON, True, points(no_item_support, True, ITEMS), hero="lion")
    kinds = [k for _, _, k in saved_reviews(tmp_path)]
    assert kinds == [["deaths", "last_hits", "item"], ["deaths", "item"]]


def test_day_summary_with_no_games(tmp_path):
    assert day_summary(tmp_path / "reviews", LOCAL_NOON).startswith("No games today yet.")
    assert "reviews are off" in day_summary(None, LOCAL_NOON)


def test_day_summary_counts_today_only_and_names_the_common_point(tmp_path):
    died = ["You died 2 times before 10 minutes. In lane, stand behind your creeps."]
    write_points(tmp_path, LOCAL_NOON - 30 * HOUR, False, died)  # yesterday
    write_points(tmp_path, LOCAL_NOON - 3 * HOUR, False, died)
    write_points(tmp_path, LOCAL_NOON - 2 * HOUR, True, ["You had 20 last hits at 10 minutes; aim for 35."])
    write_points(tmp_path, LOCAL_NOON - HOUR, True, died + ["Your first big item, Manta Style, came at 24 minutes."])
    said = day_summary(tmp_path, LOCAL_NOON)
    assert said.startswith("Today: three games, two wins and one loss.")
    assert "Deaths came up most, in 2 of 3 reviews. Next game, walk back to your tower" in said
    assert said.endswith("You won the last one, a good game to stop on if you're tired.")


def test_day_summary_after_losses_in_a_row(tmp_path):
    write_points(tmp_path, LOCAL_NOON - HOUR, False, ["A steady game with nothing big to fix."])
    write_points(tmp_path, LOCAL_NOON - 0.5 * HOUR, None, ["A steady game with nothing big to fix."])
    write_points(tmp_path, LOCAL_NOON - 0.25 * HOUR, False, ["A steady game with nothing big to fix."])
    write_points(tmp_path, LOCAL_NOON, False, ["A steady game with nothing big to fix."])
    said = day_summary(tmp_path, LOCAL_NOON)
    assert said.startswith("Today: four games, no wins, three losses and one I couldn't see the end of.")
    assert "No point came up twice" in said
    assert said.endswith("That's two losses in a row: a short break helps before the next one.")


def test_one_game_today(tmp_path):
    write_points(tmp_path, LOCAL_NOON, True, ["A steady game with nothing big to fix."])
    assert day_summary(tmp_path, LOCAL_NOON) == (
        "Today: one game, one win and no losses. You won the last one, a good game to stop on if you're tired."
    )


def play(tmp_path, payload, at, said, won, **kw):
    review = Review(said.append, tmp_path, position=lambda snap: 1, clock=lambda: at, **kw)
    feed(review, payload, range(0, 1801, 30), deaths=(1700,), won=won)


def test_stop_line():
    assert stop_line(3) == "Three games today and you won this one: a good game to stop on if you're tired."


def test_win_after_two_games_today_is_a_good_game_to_stop_on_once_a_day(tmp_path, payload):
    said = []
    play(tmp_path, payload, LOCAL_NOON - 30 * HOUR, said, True)  # yesterday doesn't count
    play(tmp_path, payload, LOCAL_NOON - 2 * HOUR, said, False)
    play(tmp_path, payload, LOCAL_NOON - HOUR, said, True)
    assert not any("stop on" in line for line in said)
    play(tmp_path, payload, LOCAL_NOON, said, True)
    assert said[-1].startswith("Match review. ")
    assert said[-1].endswith(stop_line(3))
    assert len(said) == 4  # one spoken line per review
    play(tmp_path, payload, LOCAL_NOON + HOUR, said, True)
    assert "stop on" not in said[-1]  # already said today


def test_no_stop_line_after_a_loss_or_when_turned_off(tmp_path, payload):
    said = []
    for at in (LOCAL_NOON - 2 * HOUR, LOCAL_NOON - HOUR):
        play(tmp_path, payload, at, said, True, stop_after=0)
    play(tmp_path, payload, LOCAL_NOON - 0.5 * HOUR, said, False)
    play(tmp_path, payload, LOCAL_NOON, said, True, stop_after=0)
    assert not any("stop on" in line for line in said)


def write_game(folder, at, deaths, last_hits_10=None, support=False, hero="luna"):
    import time

    folder.mkdir(parents=True, exist_ok=True)
    name = f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(at))}-{hero}.txt"
    m = match(hero=hero, deaths=deaths, last_hits_10=last_hits_10)
    (folder / name).write_text(text(m, ["A steady game."], support=support), encoding="utf-8")


def test_saved_games_read_back_the_numbers_and_the_support_mark(tmp_path):
    from coach.review import saved_games

    write_game(tmp_path, LOCAL_NOON - HOUR, 9, 18)
    write_game(tmp_path, LOCAL_NOON, 3, 12, support=True, hero="lion")
    (tmp_path / "notes.txt").write_text("not a review", encoding="utf-8")
    games = saved_games(tmp_path)
    assert [(g.deaths, g.last_hits_10, g.support) for g in games] == [(9, 18, False), (3, 12, True)]


def test_trend_needs_a_few_games(tmp_path):
    from coach.review import trend_summary

    assert "reviews are off" in trend_summary(None, LOCAL_NOON)
    write_game(tmp_path, LOCAL_NOON, 5, 30)
    assert trend_summary(tmp_path, LOCAL_NOON) == (
        "I need at least 4 games in my match reviews to see a trend, and I have 1. "
        "Ask me again after a few more games."
    )


def test_trend_compares_the_last_five_games_with_the_five_before(tmp_path):
    from coach.review import trend_summary

    for i, (deaths, lh) in enumerate([(12, 40)] + [(9, 18)] * 5 + [(5, 26)] * 5):
        write_game(tmp_path, LOCAL_NOON - (11 - i) * HOUR, deaths, lh)
    write_game(tmp_path, LOCAL_NOON - 5.5 * HOUR, 4, 5, support=True, hero="lion")  # support last hits don't count
    said = trend_summary(tmp_path, LOCAL_NOON)
    assert said.startswith("In your last 5 games you died 5 times a game, down from ")
    assert "Last hits at 10 minutes: 26, up from 18." in said
    assert said.endswith("You're getting better. Keep doing what changed.")


def test_trend_with_more_deaths_gives_the_deaths_tip(tmp_path):
    from coach.review import trend_summary

    for i, deaths in enumerate([4, 5, 9, 10]):
        write_game(tmp_path, LOCAL_NOON - (4 - i) * HOUR, deaths)
    said = trend_summary(tmp_path, LOCAL_NOON)
    assert said.startswith("In your last 2 games you died 10 times a game, up from 4.")
    assert "Last hits" not in said
    assert "Next game, walk back to your tower" in said


def test_trend_steady(tmp_path):
    from coach.review import trend_summary

    for i in range(6):
        write_game(tmp_path, LOCAL_NOON - (6 - i) * HOUR, 6, 30)
    said = trend_summary(tmp_path, LOCAL_NOON)
    assert "about the same as before" in said
    assert said.endswith("Pick one thing to work on: ask me what to focus on during the game.")


def test_trend_in_spanish():
    from coach.i18n import Catalog, SPEECH_ES

    said = Catalog(SPEECH_ES).translate(
        "In your last 5 games you died 5 times a game, down from 9. Last hits at 10 minutes: 26, up from 18. "
        "You're getting better. Keep doing what changed."
    )
    assert said == (
        "En tus últimas 5 partidas moriste 5 veces por partida, menos que las 9 de antes. "
        "Last hits en el minuto 10: 26, más que los 18 de antes. Estás mejorando. Sigue haciendo lo que cambiaste."
    )
