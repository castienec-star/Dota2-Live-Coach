import dataclasses
import itertools
import json
import threading
import time
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


def test_load_asks_ollama_to_load_the_model_without_a_prompt(fake_ollama):
    url, received = fake_ollama
    assert llm.load("llama3.2:3b", url)
    assert received == [("/api/generate", {"model": "llama3.2:3b", "keep_alive": llm.KEEP_ALIVE})]


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


DRAFT = "DOTA_GAMERULES_STATE_HERO_SELECTION"
PLAYING = "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"


class Ollama:
    """Records load and unload calls; wait() waits for the background ones."""

    def __init__(self):
        self.calls = []
        self.event = threading.Event()

    def load(self, model, url):
        self.calls.append(("load", model))
        self.event.set()

    def unload(self, model, url, timeout):
        self.calls.append(("unload", model))
        self.event.set()

    def wait(self, calls):
        while len(self.calls) < calls:
            assert self.event.wait(5)
            self.event.clear()
        time.sleep(0.1)  # and no more
        return self.calls


def memory(ollama, clock=lambda: 0.0):
    return llm.ModelMemory({("llama3.1:8b", llm.DEFAULT_URL)}, 180, clock, ollama.unload, ollama.load)


def test_model_memory_loads_while_drafting_and_frees_after_the_match():
    ollama = Ollama()
    models = memory(ollama)
    for state in states(None, DRAFT, DRAFT, PLAYING, PLAYING):
        models(state)
    assert ollama.wait(1) == [("load", "llama3.1:8b")]
    for state in states(PLAYING, llm.POST_GAME, llm.POST_GAME, None):
        models(state)
    assert ollama.wait(2) == [("load", "llama3.1:8b"), ("unload", "llama3.1:8b")]


def test_model_memory_frees_when_the_match_is_left_or_dota_goes_quiet():
    ollama = Ollama()
    models = memory(ollama)
    # Started mid-match (no draft seen), then back to the menu: no post-game.
    for state in states(None, PLAYING, None):
        models(state)
    assert ollama.wait(1) == [("unload", "llama3.1:8b")]

    now = [0.0]
    ollama = Ollama()
    models = memory(ollama, lambda: now[0])
    for state in states(None, PLAYING):
        models(state)
    now[0] = 179
    models.idle()
    assert ollama.wait(0) == []
    now[0] = 180  # no update for three minutes: Dota closed or crashed
    models.idle()
    models.idle()
    assert ollama.wait(1) == [("unload", "llama3.1:8b")]


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
    free = [listener for listener in coach.listeners if isinstance(listener, llm.ModelMemory)]
    assert [f.models for f in free] == [{(llm.DEFAULT_MODEL, llm.DEFAULT_URL)}]
    coach.pregame.close()

    cfg = config(tmp_path, pregame={"opendota": False, "learn": False}, items={"free_after_match": False})
    coach = make_coach(cfg, Speaker(), tips=True)
    assert not any(isinstance(listener, llm.ModelMemory) for listener in coach.listeners)
    coach.pregame.close()
