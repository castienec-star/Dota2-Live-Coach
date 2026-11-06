import json

from coach.app import Event
from coach.replay_api import ReplayApi


class FakeProcess:
    def __init__(self, args):
        self.args, self.running, self.queue = args, False, []

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def events(self):
        out, self.queue = self.queue, []
        return out


def make(tmp_path, have=True):
    procs, stopped = [], []

    def process(args):
        procs.append(FakeProcess(args))
        return procs[-1]

    api = ReplayApi(tmp_path, stop_live=lambda: stopped.append(1), process=process,
                    installed=lambda model, url: have)
    return api, procs, stopped


def test_start_saves_choices_and_stops_the_live_coach(tmp_path):
    api, procs, stopped = make(tmp_path)
    out = api.start({"mode": "continuous", "interval": "6", "model": "gemma3:4b", "hero": "juggernaut"})
    assert out["running"] and stopped == [1]
    assert procs[0].args == ("replay-review", "--mode", "continuous", "--vision-model", "gemma3:4b",
                             "--interval", "6.0", "--hero", "juggernaut")
    assert json.loads((tmp_path / "replay_review.json").read_text())["mode"] == "continuous"
    assert api.load()["settings"]["model"] == "gemma3:4b"
    assert not api.stop()["running"]


def test_bad_choices_fall_back(tmp_path):
    api, procs, _ = make(tmp_path)
    api.start({"mode": "always", "interval": "fast"})
    assert procs[0].args[:3] == ("replay-review", "--mode", "moments")
    assert "--interval" not in procs[0].args


def test_poll_reads_the_followed_hero_and_problems(tmp_path):
    api, procs, _ = make(tmp_path)
    api.start({})
    procs[0].queue = [
        Event("log", "Replay review: following your hero juggernaut", "20:00:01"),
        Event("log", "Replay review: can't tell which hero is yours yet. Pick your hero.", "20:00:02"),
        Event("said", "Back off now.", "20:00:03"),
    ]
    out = api.poll()
    assert out["following"] == "Juggernaut"
    assert [e["kind"] for e in out["events"]] == ["log", "problem", "said"]
    assert out["events"][1]["text"].startswith("can't tell")


def test_model_check(tmp_path):
    assert make(tmp_path)[0].check_model("qwen2.5vl:7b")["ok"]
    assert "ollama pull qwen2.5vl:7b" in make(tmp_path, have=False)[0].check_model("qwen2.5vl:7b")["text"]
    assert "isn't running" in make(tmp_path, have=None)[0].check_model("x")["text"]


def test_load_lists_heroes_and_models(tmp_path):
    data = make(tmp_path)[0].load()
    assert any(h["key"] == "juggernaut" for h in data["heroes"])
    assert data["models"][0]["id"] == "qwen2.5vl:7b"
