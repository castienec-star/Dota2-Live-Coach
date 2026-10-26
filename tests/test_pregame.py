import copy
import json

import numpy as np
import pytest
from PIL import Image

from coach import config as config_mod
from coach.capture import Layout, PortraitMatcher, read_top_bar
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


def noise(seed, size=(64, 36)):
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8))


def test_layout_slots_are_mirrored():
    slots = Layout().slots(1920, 1080)
    assert len(slots) == 10
    radiant, dire = slots[:5], slots[5:]
    for r, d in zip(radiant, reversed(dire)):
        assert 1920 - r[2] == pytest.approx(d[0], abs=1)
    assert all(a[2] <= b[0] for a, b in zip(slots, slots[1:]))


def test_read_top_bar_finds_heroes():
    refs = {hero_id: noise(hero_id, (256, 144)) for hero_id in range(1, 30)}
    matcher = PortraitMatcher(refs)
    layout = Layout()
    size = (1920, 1080)
    strip = Image.new("RGB", (1920, layout.strip_height(1080)))
    picks = [1, 2, 3, 4, 5, 6, 7, 8, 9, None]
    for hero_id, box in zip(picks, layout.slots(*size)):
        if hero_id is not None:
            portrait = refs[hero_id].resize((box[2] - box[0], box[3] - box[1]))
            strip.paste(portrait, box[:2])
    results = read_top_bar(strip, size, layout, matcher)
    assert [hero_id for hero_id, _ in results] == picks


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


def test_briefing_reads_the_top_bar_and_asks_the_model(payload):
    prompts, said = [], []
    windows = PowerWindows()
    reader = lambda: ids(*ALLIES) + ids(*ENEMIES)
    pregame = Pregame(
        said.append, INDEX, windows, FakeStats(), None,
        ask=lambda p: prompts.append(p) or "Fight early, they scale.", reader=reader,
        capture_delay=0, retry_delay=0,
    )
    start_pregame(pregame, payload)
    assert said == ["Fight early, they scale."]
    prompt = prompts[0]
    assert "Player's hero: Luna" in prompt
    assert "Enemies: Anti-Mage, Phantom Assassin, Shadow Fiend, Invoker, Pudge" in prompt
    assert "Your lineup is strongest from about 10 to 20 minutes." in prompt
    assert "Your public match history on Luna: 10 games, 60 percent won." in prompt
    assert windows._windows[0] == Window(10, 20, True)


def test_dire_player_gets_the_right_side(payload):
    prompts = []
    reader = lambda: ids(*ENEMIES) + ids(*ALLIES)
    pregame = Pregame(
        lambda line: None, INDEX, ask=lambda p: prompts.append(p) or "ok", reader=reader,
        capture_delay=0, retry_delay=0,
    )
    start_pregame(pregame, payload, team="dire")
    assert "Allies: Lion, Earthshaker, Crystal Maiden, Tidehunter" in prompts[0]


def test_typed_picks_win_over_the_screen(payload):
    prompts = []
    reader = lambda: [None] * 10
    pregame = Pregame(
        lambda line: None, INDEX, ask=lambda p: prompts.append(p) or "ok", reader=reader,
        capture_delay=0, retry_delay=0,
    )
    start_pregame(pregame, payload, typed=["vs am pudge"])
    assert "Enemies: Anti-Mage, Pudge" in prompts[0]


def test_typed_reply_names_unknown_words():
    pregame = Pregame(lambda line: None, INDEX)
    assert pregame.typed("vs am pudge xyz") == "Enemies: Anti-Mage, Pudge  (not recognised: xyz)"


def test_typed_help_and_clear():
    pregame = Pregame(lambda line: None, INDEX)
    assert pregame.typed("hello").startswith('Type "vs"')
    pregame.typed("with luna")
    assert pregame.typed("clear") == "Typed picks cleared."
    assert pregame.typed_allies == []


def test_builtin_briefing_when_no_model(payload):
    said = []
    pregame = Pregame(said.append, INDEX, ask=lambda p: None)
    start_pregame(pregame, payload, typed=["with " + " ".join(ALLIES), "vs " + " ".join(ENEMIES)])
    assert said and "Your team has lots of stuns and disables." in said[0]


def test_capture_failure_does_not_stop_the_briefing(payload):
    said = []

    def broken():
        raise OSError("no screen")

    pregame = Pregame(said.append, INDEX, reader=broken, capture_delay=0, retry_delay=0)
    start_pregame(pregame, payload)
    assert len(said) == 1


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


def test_defaults_keep_screen_capture_off(tmp_path):
    cfg = config_mod.load(app_dir=tmp_path)
    assert cfg.pregame["enabled"] is True
    assert cfg.pregame["capture"]["enabled"] is False
    pregame = build(cfg.pregame, lambda line: None, None, tmp_path, tmp_path)
    assert pregame.reader is None


def test_build_rejects_unknown_provider(tmp_path):
    with pytest.raises(ValueError):
        build({"provider": "gpt"}, lambda line: None, None, tmp_path, tmp_path)


def test_draft_test_command(tmp_path, monkeypatch, capsys):
    from coach import __main__ as cli
    from coach import capture

    refs = {hero_id: noise(hero_id, (256, 144)) for hero_id in (1, 2)}
    monkeypatch.setattr(capture, "load_references", lambda heroes, cache_dir: refs)
    layout = Layout()
    shot = Image.new("RGB", (1920, 1080))
    box = layout.slots(1920, 1080)[0]
    shot.paste(refs[2].resize((box[2] - box[0], box[3] - box[1])), box[:2])
    path = tmp_path / "shot.png"
    shot.save(path)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert cli.main(["draft-test", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Radiant 1: Axe" in out
    assert (tmp_path / "Dota2LiveCoach" / "draft-test.png").is_file()
