import json
from datetime import date

from coach import hero_stats
from coach.chat import Chat
from coach.hero_stats import HeroStat, check_patch, describe, fetch, load, save
from coach.heroes import HeroIndex
from coach.state import Snapshot

HEROES = HeroIndex()
PATCHES = [{"name": "7.40", "date": "2025-12-16T00:50:40Z"}, {"name": "7.41", "date": "2026-03-24T00:50:59Z"}]


def row(hero_id, picks, wins):
    data = {"id": hero_id, "localized_name": "x"}
    for b in range(1, 9):
        data[f"{b}_pick"], data[f"{b}_win"] = picks, wins
    return data


def test_patch_check_takes_a_lettered_update_and_refuses_a_new_patch():
    today = date(2026, 10, 31)
    assert check_patch(PATCHES, "7.41f", today) is None
    assert check_patch(PATCHES, "7.41", today) is None
    assert "7.42 is out" in check_patch(PATCHES + [{"name": "7.42", "date": "2026-10-01T00:00:00Z"}], "7.41f", today)
    assert "7.41 is out" in check_patch(PATCHES, "7.4", today)
    assert "mix two patches" in check_patch(PATCHES, "7.41", date(2026, 3, 27))
    assert check_patch(None, "7.41f") == "OpenDota did not send the patch list"


def test_fetch_save_and_load_only_herald_to_ancient(tmp_path):
    heroes = HEROES.heroes
    found = fetch(lambda path: [row(1, 1000, 520), row(14, 2000, 960), row(99999, 5, 5)], heroes)
    assert set(found) == {"antimage", "pudge"}
    assert found["antimage"]["picks"] == [1000] * 8
    path = tmp_path / "hero_stats.json"
    save(found, path, "7.41f")
    assert json.loads(path.read_text())["patch"] == "7.41f"
    stats = load(path, "7.41f")
    # Six brackets, Divine and Immortal left out.
    assert stats["antimage"].picks == 6000 and stats["antimage"].wins == 3120
    assert stats["antimage"].rank == 1 and stats["pudge"].rank == 2 and stats["pudge"].of == 2
    assert round(stats["pudge"].pick_share, 2) == round(12000 / 1800, 2)


def test_file_from_another_patch_or_broken_is_ignored(tmp_path):
    path = tmp_path / "hero_stats.json"
    save(fetch(lambda path: [row(1, 1000, 520)], HEROES.heroes), path, "7.41e")
    assert load(path, "7.41f") == {}
    path.write_text("not json")
    assert load(path, "7.41f") == {}
    assert load(tmp_path / "missing.json") == {}


def test_too_few_games_is_left_out(tmp_path):
    path = tmp_path / "hero_stats.json"
    save(fetch(lambda path: [row(1, 100, 50), row(14, 2000, 960)], HEROES.heroes), path, "7.41f")
    assert set(load(path, "7.41f")) == {"pudge"}


def test_describe_names_each_known_hero_once():
    stats = {"pudge": HeroStat(12000, 5772, 98, 127, 0.21)}
    pudge, lina = HEROES.by_key("pudge"), HEROES.by_key("lina")
    lines = describe(stats, [pudge, None, lina, pudge], "7.41f")
    assert lines[0].startswith("Patch 7.41f win rates in Herald to Ancient public games this week")
    assert lines[1:] == ["- Pudge: wins 48.1% (98th of 127), in 21% of matches"]
    assert describe(stats, [lina]) == []
    assert [hero_stats.ordinal(n) for n in (1, 2, 3, 11, 12, 13, 21, 22, 101)] == [
        "1st", "2nd", "3rd", "11th", "12th", "13th", "21st", "22nd", "101st",
    ]


def test_chat_prompt_has_win_rates_of_match_heroes(payload):
    prompts = []
    stats = {
        "antimage": HeroStat(10000, 5200, 20, 127, 0.1),
        "pudge": HeroStat(12000, 5772, 98, 127, 0.21),
        "lina": HeroStat(9000, 4500, 60, 127, 0.09),
    }
    chat = Chat(
        lambda prompt, fmt=None: prompts.append(prompt) or "Pudge is a little weak this patch.",
        enemies=lambda: [HEROES.by_key("pudge")],
        items={},
        stats=stats,
    )
    assert chat("is pudge strong right now?", Snapshot.from_payload(payload))
    prompt = prompts[0]
    assert "- Anti-Mage: wins 52.0% (20th of 127)" in prompt
    assert "- Pudge: wins 48.1% (98th of 127)" in prompt
    assert "Lina" not in prompt  # not in this match


def test_chat_without_stats_says_nothing_about_them(payload):
    prompts = []
    chat = Chat(lambda prompt, fmt=None: prompts.append(prompt) or "ok", items={}, stats={})
    chat("anything?", Snapshot.from_payload(payload))
    assert "win rates" not in prompts[0]


def test_refresh_command_saves_this_patch(tmp_path, monkeypatch):
    from coach.__main__ import main
    from coach.heroes import load_heroes

    rows = [row(h.id, 1000, 500) for h in load_heroes().values()]
    answers = {"/constants/patch": PATCHES, "/heroStats": rows}
    monkeypatch.setattr("coach.config.user_dir", lambda: tmp_path)
    monkeypatch.setattr("coach.opendota.OpenDota.get", lambda self, path, max_age=None: answers.get(path))
    out = tmp_path / "stats.json"
    assert main(["--config", str(tmp_path / "none.toml"), "refresh-hero-stats", "--out", str(out)]) == 0
    assert len(load(out)) == len(rows)


def test_refresh_command_refuses_a_newer_patch_or_no_network(tmp_path, monkeypatch):
    from coach.__main__ import main

    newer = PATCHES + [{"name": "9.99", "date": "2026-01-01T00:00:00Z"}]
    answers = {"/constants/patch": newer, "/heroStats": [row(1, 1000, 500)]}
    monkeypatch.setattr("coach.config.user_dir", lambda: tmp_path)
    monkeypatch.setattr("coach.opendota.OpenDota.get", lambda self, path, max_age=None: answers.get(path))
    out = tmp_path / "stats.json"
    assert main(["--config", str(tmp_path / "none.toml"), "refresh-hero-stats", "--out", str(out)]) == 1
    monkeypatch.setattr("coach.opendota.OpenDota.get", lambda self, path, max_age=None: None)
    assert main(["--config", str(tmp_path / "none.toml"), "refresh-hero-stats", "--out", str(out)]) == 1
    assert not out.exists()
