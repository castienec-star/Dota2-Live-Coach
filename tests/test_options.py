import pytest

from coach import config, options
from coach.app import Event
from coach.app_api import Api

DEFAULTS = config._read_toml(config.DEFAULTS_FILE)


def test_every_field_and_reminder_exists_in_the_defaults():
    for f in options.all_fields():
        assert options._get(DEFAULTS, f.path) is not None, f.path
    names = {r.name for r in options.all_reminders()}
    assert names == set(DEFAULTS["reminders"])


def test_unchanged_values_save_nothing():
    sent = options.values(DEFAULTS, {})
    assert options.saved(DEFAULTS, {}, sent) == ({}, [])


def test_a_timing_and_a_reminder_change_are_saved_and_shown_back():
    sent = options.values(DEFAULTS, {})
    sent["fields"]["reminders.stack.until"] = "9:53"
    sent["fields"]["reminders.game_check.minutes"] = "20, 12,30"
    sent["fields"]["reminders.power_rune.lead"] = "20"
    sent["reminders"]["night"] = False
    user, errors = options.saved(DEFAULTS, {}, sent)
    assert errors == []
    assert user["reminders"]["stack"] == {"until": 593}
    assert user["reminders"]["game_check"] == {"minutes": [12, 20, 30]}
    assert user["reminders"]["power_rune"] == {"lead": 20}
    assert user["reminders"]["night"] == {"enabled": False}
    shown = options.values(DEFAULTS, user)
    assert shown["fields"]["reminders.stack.until"] == "9:53"
    assert shown["fields"]["reminders.game_check.minutes"] == "12, 20, 30"
    assert shown["reminders"]["night"] is False


def test_back_to_the_default_removes_the_players_line():
    user = {"reminders": {"power_rune": {"lead": 20}}, "voice": {"rate": 3}}
    sent = options.values(DEFAULTS, user)
    sent["fields"]["reminders.power_rune.lead"] = "15"
    assert options.saved(DEFAULTS, user, sent) == ({"voice": {"rate": 3}}, [])


def test_other_settings_in_the_players_file_are_kept():
    user = {"builds": {"luna": ["Power Treads"]}, "server": {"port": 5000}}
    assert options.saved(DEFAULTS, user, options.values(DEFAULTS, user)) == (user, [])


@pytest.mark.parametrize("path, raw", [
    ("reminders.stack.until", "11:75"),
    ("reminders.stack.until", "soon"),
    ("reminders.low_health.below", "150"),
    ("reminders.game_check.minutes", "15, x"),
    ("voice.rate", "11"),
    ("pregame.position", "7"),
])
def test_bad_values_are_refused_with_a_reason_and_nothing_changes(path, raw):
    sent = options.values(DEFAULTS, {})
    sent["fields"][path] = raw
    user, errors = options.saved(DEFAULTS, {}, sent)
    assert user == {} and len(errors) == 1


def test_position_and_rank_choices():
    sent = options.values(DEFAULTS, {})
    sent["fields"]["pregame.position"] = "2"
    sent["fields"]["player.rank"] = "Archon"
    user, _ = options.saved(DEFAULTS, {}, sent)
    assert user["pregame"] == {"position": 2} and user["player"] == {"rank": "Archon"}


def test_experienced_mode_quiets_reminders_and_questions_like_the_coach_does():
    sent = options.values(DEFAULTS, {})
    sent["reminders"]["night"] = False  # the player's own choice stays
    after = options.remode(sent, "beginner", "experienced", DEFAULTS)
    on = {name for name, v in after["reminders"].items() if v}
    assert on == config.EXPERIENCED
    assert after["fields"]["listen.game_questions"] is False
    user, _ = options.saved(DEFAULTS, {}, after)
    assert user == {"coach": {"mode": "experienced"}}
    back = options.remode(after, "experienced", "beginner", DEFAULTS)
    assert back["reminders"]["wand"] is True


def test_turning_on_a_reminder_in_experienced_mode_is_saved():
    sent = options.values(DEFAULTS, {"coach": {"mode": "experienced"}})
    assert sent["reminders"]["night"] is False
    sent["reminders"]["night"] = True
    user, _ = options.saved(DEFAULTS, {"coach": {"mode": "experienced"}}, sent)
    assert user["reminders"] == {"night": {"enabled": True}}


def test_schema_is_plain_data_with_every_reminder():
    schema = options.schema()
    names = [r["name"] for g in schema["reminders"] for r in g["reminders"]]
    assert sorted(names) == sorted(DEFAULTS["reminders"])
    assert {g["id"] for g in schema["general"]} == {"language", "voice", "listen", "game"}


class FakeCoach:
    def __init__(self):
        self.running, self.calls = False, []

    def start(self):
        self.running = True
        self.calls.append("start")

    def stop(self):
        self.running = False
        self.calls.append("stop")

    def events(self):
        return [Event("said", "Power rune in 15 seconds.", "18:00:00")] if self.running else []


def test_api_saves_and_restarts_a_running_coach(tmp_path):
    coach = FakeCoach()
    api = Api(tmp_path, coach=coach, voices=[])
    data = api.load_settings()
    assert data["values"] == data["defaults"]
    out = api.start()
    assert out["status"]["running"] and out["events"][0]["text"] == "Power rune in 15 seconds."
    sent = data["values"]
    sent["fields"]["reminders.power_rune.lead"] = "25"
    saved = api.save_settings(sent)
    assert saved["ok"] and saved["restarted"] and coach.calls == ["start", "stop", "start"]
    assert "lead = 25" in (tmp_path / "coach.toml").read_text(encoding="utf-8")
    assert api.load_settings()["values"]["fields"]["reminders.power_rune.lead"] == "25"


def test_api_refuses_bad_values_without_writing(tmp_path):
    api = Api(tmp_path, coach=FakeCoach(), voices=[])
    sent = api.load_settings()["values"]
    sent["fields"]["reminders.stack.until"] = "late"
    out = api.save_settings(sent)
    assert not out["ok"] and out["errors"] and not (tmp_path / "coach.toml").exists()


def test_a_high_mmr_switches_beginner_to_experienced_once(tmp_path):
    coach = FakeCoach()
    api = Api(tmp_path, coach=coach, voices=[])
    out = api.add_mmr("5800")
    assert out["ok"] and out["mode_switched"] and out["values"]["mode"] == "experienced"
    assert 'mode = "experienced"' in (tmp_path / "coach.toml").read_text(encoding="utf-8")
    # the player goes back to beginner by hand: the app doesn't switch it again
    sent = api.load_settings()["values"]
    back = api.switch_mode(sent, "beginner")
    assert api.save_settings(back)["ok"]
    assert not api.add_mmr("5900")["mode_switched"]
    data = api.load_settings()
    assert data["values"]["mode"] == "beginner" and data["notice"] == ""


def test_a_low_mmr_keeps_beginner_mode(tmp_path):
    api = Api(tmp_path, coach=FakeCoach(), voices=[])
    out = api.add_mmr("2400")
    assert out["ok"] and not out["mode_switched"]
    assert api.load_settings()["values"]["mode"] == "beginner"


def test_opening_the_app_applies_an_mmr_entered_before(tmp_path):
    from coach import progress

    progress.MmrHistory(tmp_path).add("5800")
    data = Api(tmp_path, coach=FakeCoach(), voices=[]).load_settings()
    assert data["values"]["mode"] == "experienced" and data["notice"]
