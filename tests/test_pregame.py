import copy
import json

import pytest

from coach import config as config_mod
from coach.draft import Window
from coach.heroes import HeroIndex
from coach.pregame import Pregame, build, builtin_briefing
from coach.profile import Profile, summarize
from coach.items import load_items
from coach.rules import Engine
from coach.rules.windows import PowerWindows
from coach.state import PRE_GAME, MatchState

INDEX = HeroIndex()
IN_PROGRESS = "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"


def write_recording(path, payload, hero="npc_dota_hero_luna", won=True, deaths=(300, 900)):
    """A short fake match: 20 minutes, with deaths and a Manta Style at 17:00."""
    lines = []
    p = copy.deepcopy(payload)
    p["hero"]["name"] = hero
    p["items"] = {}
    for clock in range(0, 1201, 30):
        p["map"]["clock_time"] = clock
        p["map"]["game_state"] = IN_PROGRESS
        p["player"]["deaths"] = sum(1 for t in deaths if t <= clock)
        p["player"]["last_hits"] = clock // 10
        if clock >= 1020:
            p["items"] = {"slot0": {"name": "item_manta", "purchaser": 0}}
        lines.append({"t": 1000 + clock, "payload": copy.deepcopy(p)})
    p["map"]["game_state"] = "DOTA_GAMERULES_STATE_POST_GAME"
    p["map"]["win_team"] = "radiant" if won else "dire"
    lines.append({"t": 3000, "payload": copy.deepcopy(p)})
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")


def test_summarize_recording(tmp_path, payload):
    rec = tmp_path / "a.jsonl"
    write_recording(rec, payload)
    m = summarize(rec, load_items())
    assert m.hero == "luna"
    assert m.won is True  # the sample player is on Radiant
    assert m.death_times == [300, 900]
    assert m.last_hits_10 == 60
    assert m.item_times == {"item_manta": 1020}


def test_short_recording_is_skipped(tmp_path, payload):
    rec = tmp_path / "a.jsonl"
    payload["map"]["clock_time"] = 100
    rec.write_text(json.dumps({"t": 1, "payload": payload}), encoding="utf-8")
    assert summarize(rec, load_items()) is None


def test_profile_learns_from_recordings(tmp_path, payload):
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    for i in range(3):
        write_recording(recordings / f"m{i}.jsonl", payload, won=i != 0, deaths=(100, 200, 900))
    profile = Profile(recordings, tmp_path / "profile.json")
    profile.update()
    lines = profile.describe("npc_dota_hero_luna")
    text = " ".join(lines)
    assert "you won 2 of 3" in text
    assert "before 10 minutes" in text
    assert "Manta Style at 17 minutes" in text
    # Saved summaries are reused instead of reading the recordings again.
    again = Profile(recordings, tmp_path / "profile.json")
    assert len(again.update()) == 3


def test_profile_empty_without_recordings(tmp_path):
    profile = Profile(tmp_path / "none", tmp_path / "profile.json")
    profile.update()
    assert profile.describe("luna") == []


def tick(state, engine, payload, clock):
    payload["map"]["clock_time"] = clock
    state.update(payload)
    engine(state)


def test_power_window_reminders(payload):
    rule = PowerWindows(lead=10)
    said = []
    engine = Engine([rule], said.append)
    state = MatchState()
    tick(state, engine, payload, 870)  # a new match resets the windows
    rule.set([Window(15, 25, True), Window(35, 45, False)])
    for clock in range(880, 892):
        tick(state, engine, payload, clock)
    for clock in range(2085, 2095):
        tick(state, engine, payload, clock)
    assert said == [
        "Your team's strongest stretch starts now, until about 25 minutes. Group up and look for fights.",
        "The enemy lineup is strongest from now until about 45 minutes. Play safe and only fight with an advantage.",
    ]


ALLIES = ("luna", "lion", "es", "cm", "tide")
ENEMIES = ("am", "pa", "sf", "invoker", "pudge")


class FakeStats:
    def matchups(self, hero_id):
        return {}

    def durations(self, hero_id):
        ours = hero_id in {INDEX.find(n).id for n in ALLIES}
        rates = (0.6, 0.6, 0.5) if ours else (0.4, 0.4, 0.5)
        return {10 + 5 * i: (1000, round(r * 1000)) for i, r in enumerate(rates)}

    def player_heroes(self, account):
        return {INDEX.find("luna").id: (10, 6)}


def start_pregame(pregame, payload, team="radiant", typed=()):
    """Hero selection, then the countdown; typed lines are entered during the draft."""
    state = MatchState()
    payload["player"]["team_name"] = team
    payload["hero"]["name"] = "npc_dota_hero_luna"
    payload["map"]["game_state"] = "DOTA_GAMERULES_STATE_HERO_SELECTION"
    payload["map"]["clock_time"] = -100
    state.update(payload)
    pregame(state)
    for line in typed:
        pregame.typed(line)
    payload["map"]["game_state"] = PRE_GAME
    state.update(payload)
    pregame(state)
    pregame.close()
    return state


def ids(*names):
    return [INDEX.find(n).id for n in names]


def test_briefing_uses_the_picks_and_asks_the_model(payload):
    prompts, said = [], []
    windows = PowerWindows()
    pregame = Pregame(
        said.append, INDEX, windows, FakeStats(), None,
        ask=lambda p: prompts.append(p) or "Fight early, they scale.",
    )
    start_pregame(pregame, payload, typed=["with " + " ".join(ALLIES), "vs " + " ".join(ENEMIES), "pos 1"])
    assert said == ["Fight early, they scale."]
    prompt = prompts[0]
    assert "Player's hero: Luna" in prompt
    assert "Player's position: 1 (safe lane carry)" in prompt
    assert "Allies: Lion, Earthshaker, Crystal Maiden, Tidehunter" in prompt
    assert "Enemies: Anti-Mage, Phantom Assassin, Shadow Fiend, Invoker, Pudge" in prompt
    assert "Your lineup is strongest from about 10 to 20 minutes." in prompt
    assert "Your public match history on Luna: 10 games, 60 percent won." in prompt
    assert windows._windows[0] == Window(10, 20, True)


def test_briefing_waits_for_the_start_questions(payload):
    prompts = []
    waiting = [True]
    pregame = Pregame(
        lambda line: None, INDEX, ask=lambda p: prompts.append(p) or "ok",
        waiting=lambda: waiting[0], wait_limit=5,
    )
    state = MatchState()
    payload["hero"]["name"] = "npc_dota_hero_luna"
    payload["map"]["game_state"] = PRE_GAME
    state.update(payload)
    pregame(state)
    pregame.heard(enemies=[INDEX.find("am")], position=5)  # answered while it waits
    waiting[0] = False
    pregame.close()
    assert len(prompts) == 1
    assert "Enemies: Anti-Mage" in prompts[0]
    assert "Player's position: 5 (hard support)" in prompts[0]


def test_picks_after_the_briefing_get_a_fresh_one(payload):
    prompts = []
    pregame = Pregame(lambda line: None, INDEX, ask=lambda p: prompts.append(p) or "ok")
    state = MatchState()
    payload["map"]["game_state"] = PRE_GAME
    state.update(payload)
    pregame(state)
    pregame.heard(enemies=[INDEX.find("pudge")])
    pregame.close()
    assert len(prompts) == 2
    assert "Enemies: Pudge" in prompts[1]


def test_typed_reply_names_unknown_words():
    pregame = Pregame(lambda line: None, INDEX)
    assert pregame.typed("vs am pudge xyz") == "Enemies: Anti-Mage, Pudge  (not recognised: xyz)"


def test_typed_help_and_clear():
    pregame = Pregame(lambda line: None, INDEX)
    assert pregame.typed("hello").startswith('Type "vs"')
    pregame.typed("with luna")
    assert pregame.typed("clear") == "Typed picks cleared."
    assert pregame.allies == []


def test_typed_position():
    pregame = Pregame(lambda line: None, INDEX)
    assert pregame.typed("pos 4") == "Position 4: soft support"
    assert pregame.position == 4
    assert pregame.typed("pos 9").startswith("Type your position")


def test_builtin_briefing_when_no_model(payload):
    said = []
    pregame = Pregame(said.append, INDEX, ask=lambda p: None)
    start_pregame(pregame, payload, typed=["with " + " ".join(ALLIES), "vs " + " ".join(ENEMIES)])
    assert said and "Your team has lots of stuns and disables." in said[0]


def test_briefing_only_once_per_match(payload):
    said = []
    pregame = Pregame(said.append, INDEX)
    state = MatchState()
    payload["map"]["game_state"] = PRE_GAME
    for clock in (-90, -89, -88):
        payload["map"]["clock_time"] = clock
        state.update(payload)
        pregame(state)
    pregame.close()
    assert len(said) == 1


def test_builtin_briefing_has_a_default():
    from coach.draft import Analysis

    assert builtin_briefing(Analysis(), []) == "Good luck. Play safe in lane and watch the minimap."


def test_defaults_ask_instead_of_reading_the_screen(tmp_path):
    cfg = config_mod.load(app_dir=tmp_path)
    assert cfg.pregame["enabled"] is True
    assert "capture" not in cfg.pregame
    assert cfg.pregame["position"] == 0
    assert cfg.listen["start_questions"] is True
    assert build(cfg.pregame, lambda line: None, None, tmp_path, tmp_path) is not None


def test_build_rejects_unknown_provider(tmp_path):
    with pytest.raises(ValueError):
        build({"provider": "gpt"}, lambda line: None, None, tmp_path, tmp_path)
