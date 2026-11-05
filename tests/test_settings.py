import json
import tomllib

import pytest

from coach import config, settings
from coach.heroes import load_heroes
from coach.items import load_items

DEFAULTS = config._read_toml(config.DEFAULTS_FILE)


def choose(user, **changes):
    kwargs = {
        "mode": "beginner",
        "voice_name": "",
        "voice_rate": DEFAULTS["voice"]["rate"],
        "reminders": settings.checks(DEFAULTS, user, changes.get("mode", "beginner")),
        "builds": {},
    }
    kwargs.update(changes)
    return settings.updated(DEFAULTS, user, **kwargs)


def test_every_reminder_is_listed_with_a_plain_name():
    names = settings.reminder_names(DEFAULTS)
    assert set(names) == set(DEFAULTS["reminders"])
    assert all(n in settings.REMINDERS for n in names)


def test_nothing_changed_writes_nothing():
    assert choose({}) == {}


def test_turning_a_reminder_off_and_back_on():
    user = choose({}, reminders={**settings.checks(DEFAULTS, {}, "beginner"), "night": False})
    assert user == {"reminders": {"night": {"enabled": False}}}
    on_again = choose(user, reminders={**settings.checks(DEFAULTS, user, "beginner"), "night": True})
    assert on_again == {}


def test_other_settings_in_the_players_file_are_kept():
    user = {"server": {"port": 5000}, "reminders": {"stack": {"radius": 800}}}
    assert choose(user, voice_rate=3) == {**user, "voice": {"rate": 3}}


def test_experienced_mode_writes_only_what_differs_from_the_mode():
    checks = settings.checks(DEFAULTS, {}, "experienced")
    assert checks["item_ready"] and checks["stack"]
    assert not checks["night"] and not checks["death_tip"]
    user = choose({}, mode="experienced", reminders={**checks, "low_health": True})
    assert user == {"coach": {"mode": "experienced"}, "reminders": {"low_health": {"enabled": True}}}
    # The coach reads it back the same way.
    cfg_raw, quiet = config.apply_mode("experienced", config._merge(DEFAULTS, user), user)
    assert "low_health" not in quiet and "night" in quiet


def test_switching_mode_keeps_the_players_own_changes():
    beginner = settings.checks(DEFAULTS, {}, "beginner")
    beginner["stack"] = False  # the player's own choice
    after = settings.remode(beginner, "beginner", "experienced", DEFAULTS)
    assert after["night"] is False  # follows the mode
    assert after["stack"] is False  # stays as the player set it
    assert after["item_ready"] is True


def test_builds_are_spelled_as_the_coach_knows_them():
    items = load_items()
    names, unknown = settings.parse_build("phase boots\nBlink Dagger, item_black_king_bar\nWiggle stick", items)
    assert names == ["Phase Boots", "Blink Dagger", "Black King Bar"]
    assert unknown == ["Wiggle stick"]


def test_build_choice_empty_box():
    items = load_items()
    # Pudge has a bundled build: empty turns the item reminder off.
    assert settings.build_choice("pudge", "", DEFAULTS, items) == ([], [])
    # A hero with no bundled build: empty keeps the fallback. Picked from the
    # hero list so new bundled builds don't break this test.
    unbuilt = next(h.key for h in load_heroes().values() if h.key not in DEFAULTS["builds"])
    assert settings.build_choice(unbuilt, "  ", DEFAULTS, items) == (None, [])


def test_build_override_and_back_to_default():
    pudge = settings.build_for("pudge", DEFAULTS, {})
    assert pudge[0] == "Tranquil Boots"
    user = choose({}, builds={"pudge": ["Phase Boots", "Blink Dagger"]})
    assert user == {"builds": {"pudge": ["Phase Boots", "Blink Dagger"]}}
    assert settings.build_for("pudge", DEFAULTS, user) == ["Phase Boots", "Blink Dagger"]
    assert choose(user, builds={"pudge": None}) == {}
    assert choose(user, builds={"pudge": pudge}) == {}


def test_bad_mode_is_refused():
    with pytest.raises(ValueError):
        choose({}, mode="pro")


def test_saved_file_loads_back(tmp_path):
    user = {
        "server": {"port": 5000},
        "voice": {"name": 'Microsoft "Zira" Desktop', "rate": -2},
        "reminders": {"night": {"enabled": False}, "stack": {"radius": 800, "enabled": True}},
        "builds": {"pudge": ["Phase Boots", "Aghanim's Scepter"], "shadow_shaman_pos4": []},
        "player": {"rank": "Legend 3"},
        "listen": {"chat_timeout": 6.5},
    }
    path = tmp_path / "coach.toml"
    assert settings.save(path, user) is None
    assert tomllib.loads(path.read_text(encoding="utf-8")) == user
    assert path.read_text(encoding="utf-8").startswith("# Your Dota 2 Live Coach settings")
    cfg = config.load(app_dir=tmp_path)
    assert cfg.port == 5000 and cfg.voice_rate == -2
    assert cfg.reminders["night"]["enabled"] is False
    assert cfg.builds["pudge"] == ["Phase Boots", "Aghanim's Scepter"]


def test_saving_over_a_file_keeps_a_backup(tmp_path):
    path = tmp_path / "coach.toml"
    path.write_text("# my notes\n[server]\nport = 5000\n", encoding="utf-8")
    backup = settings.save(path, {"server": {"port": 5001}})
    assert backup.read_text(encoding="utf-8").startswith("# my notes")
    assert tomllib.loads(path.read_text(encoding="utf-8")) == {"server": {"port": 5001}}


def test_last_hero_from_the_newest_recording(tmp_path):
    heroes = load_heroes()
    assert settings.last_hero(tmp_path, heroes) is None
    lines = [
        {"t": 1, "payload": {"hero": {"name": "npc_dota_hero_pudge"}}},
        {"t": 2, "said": "Power rune in 15 seconds.", "clock": 345},
        "not json",
    ]
    (tmp_path / "20261104-200000-match-1.jsonl").write_text(
        "\n".join(x if isinstance(x, str) else json.dumps(x) for x in lines), encoding="utf-8"
    )
    assert settings.last_hero(tmp_path, heroes).name == "Pudge"


def test_settings_window_opens_and_saves(tmp_path):
    tk = pytest.importorskip("tkinter")
    from coach.settings_window import SettingsWindow

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    try:
        heroes = load_heroes()
        pudge = next(h for h in heroes.values() if h.key == "pudge")
        path = tmp_path / "coach.toml"
        window = SettingsWindow(root, path, DEFAULTS, {}, heroes, load_items(), ["Zira"], pudge)
        assert window.build_text.get("1.0", "end").startswith("Tranquil Boots")
        window.checks["night"].set(False)
        window.mode.set("experienced")
        window._mode_changed()
        assert window.checks["death_tip"].get() is False
        window.build_text.delete("1.0", "end")
        window.build_text.insert("1.0", "Phase Boots\nBlink Dagger")
        assert window.save()
        saved = tomllib.loads(path.read_text(encoding="utf-8"))
        assert saved["coach"] == {"mode": "experienced"}
        assert saved["builds"] == {"pudge": ["Phase Boots", "Blink Dagger"]}
        assert "reminders" not in saved  # night is off in experienced mode anyway

        window.build_text.insert("end", "\nWiggle stick")
        assert not window.save()
        assert "Wiggle stick" in window.status.cget("text")
    finally:
        root.destroy()
