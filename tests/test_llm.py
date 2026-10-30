import dataclasses
import itertools
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest

from coach import llm
from coach.__main__ import make_coach, ollama_models, with_tip_model
from coach.speaker import Speaker
from coach.state import Snapshot


@pytest.fixture
def fake_ollama():
    """A tiny local stand-in for Ollama, recording each path and body."""
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"done": true}')

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", received
    server.shutdown()


def test_unload_asks_ollama_to_drop_the_model(fake_ollama):
    url, received = fake_ollama
    assert llm.unload("llama3.2:3b", url)
    assert received == [("/api/generate", {"model": "llama3.2:3b", "keep_alive": 0})]


def test_unload_without_ollama_is_quiet():
    assert not llm.unload("llama3.1:8b", "http://127.0.0.1:9", timeout=2)


def test_models_in_use_skips_other_providers_and_turned_off_tables():
    tables = [
        {"provider": "ollama", "ollama_model": "llama3.1:8b"},
        {"provider": "ollama", "ollama_model": "llama3.1:8b"},
        {"provider": "claude", "ollama_model": "qwen2.5:3b"},
        {"provider": "ollama", "ollama_model": "phi3", "enabled": False},
        {"provider": "rules"},
    ]
    assert llm.models_in_use(tables) == {("llama3.1:8b", llm.DEFAULT_URL)}


def states(*game_states):
    """MatchState-like objects stepping through game_states."""
    snaps = [Snapshot(game_state=g) for g in game_states]
    return [SimpleNamespace(previous=a, current=b) for a, b in itertools.pairwise(snaps)]


def test_free_after_match_unloads_once_when_the_match_ends():
    freed = []
    done = threading.Event()

    def unload(model, url):
        freed.append(model)
        done.set()

    free = llm.FreeAfterMatch({("llama3.1:8b", llm.DEFAULT_URL)}, unload)
    for state in states("DOTA_GAMERULES_STATE_GAME_IN_PROGRESS", "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"):
        free(state)
    assert not done.wait(0.2)
    for state in states("DOTA_GAMERULES_STATE_GAME_IN_PROGRESS", llm.POST_GAME, llm.POST_GAME):
        free(state)
    assert done.wait(5)
    assert freed == ["llama3.1:8b"]


def config(tmp_path, **tables):
    from coach import config as config_mod

    cfg = config_mod.load(app_dir=tmp_path)
    return dataclasses.replace(cfg, **{name: {**getattr(cfg, name), **t} for name, t in tables.items()})


def test_item_advice_and_briefing_use_the_death_tip_model(tmp_path):
    tip = {"death_tip": {"provider": "ollama", "ollama_model": "llama3.2:3b"}}
    cfg = config(tmp_path, reminders=tip)
    assert with_tip_model(cfg, cfg.items)["ollama_model"] == "llama3.2:3b"
    assert with_tip_model(cfg, cfg.pregame)["ollama_model"] == "llama3.2:3b"
    assert ollama_models(cfg) == {("llama3.2:3b", llm.DEFAULT_URL)}
    # A model set in the table itself still wins.
    cfg = config(tmp_path, reminders=tip, items={"ollama_model": "qwen2.5:3b"})
    assert ollama_models(cfg) == {("llama3.2:3b", llm.DEFAULT_URL), ("qwen2.5:3b", llm.DEFAULT_URL)}
    cfg = config(tmp_path, reminders=tip, items={"ollama_model": "qwen2.5:3b", "advisor": "rules"})
    assert ollama_models(cfg) == {("llama3.2:3b", llm.DEFAULT_URL)}


def test_coach_frees_its_models_after_the_match(tmp_path):
    cfg = config(tmp_path, pregame={"opendota": False, "learn": False})
    coach = make_coach(cfg, Speaker(), tips=True)
    free = [listener for listener in coach.listeners if isinstance(listener, llm.FreeAfterMatch)]
    assert [f.models for f in free] == [{(llm.DEFAULT_MODEL, llm.DEFAULT_URL)}]
    coach.pregame.close()

    cfg = config(tmp_path, pregame={"opendota": False, "learn": False}, items={"free_after_match": False})
    coach = make_coach(cfg, Speaker(), tips=True)
    assert not any(isinstance(listener, llm.FreeAfterMatch) for listener in coach.listeners)
    coach.pregame.close()
