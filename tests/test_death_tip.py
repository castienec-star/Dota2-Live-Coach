import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from coach.items import load_items
from coach.rules import Engine
from coach.rules.death_tip import BuiltinTips, DeathTip, build, describe, ollama_asker
from coach.state import MatchState, Snapshot


def die(payload, state, engine, respawn=25):
    payload["hero"]["alive"] = True
    state.update(payload)
    engine(state)
    payload["hero"]["alive"] = False
    payload["hero"]["respawn_seconds"] = respawn
    payload["map"]["clock_time"] += 1
    state.update(payload)
    engine(state)


def make(ask, **kwargs):
    said = []
    kwargs.setdefault("fallback", lambda snap: "Built-in tip.")
    rule = DeathTip(said.append, ask, **kwargs)
    return rule, said


def test_tip_spoken_once_per_death(payload):
    prompts = []
    rule, said = make(lambda p: prompts.append(p) or "Farm the safe lane jungle.")
    state = MatchState()
    engine = Engine([rule], lambda line: None)
    die(payload, state, engine)
    # More updates while dead must not ask again.
    state.update(payload)
    engine(state)
    rule.close()
    assert said == ["Farm the safe lane jungle."]
    assert len(prompts) == 1


def test_no_tip_after_respawn(payload):
    release = threading.Event()

    def slow(prompt):
        release.wait(5)
        return "Too late."

    rule, said = make(slow)
    state = MatchState()
    engine = Engine([rule], lambda line: None)
    die(payload, state, engine)
    payload["hero"]["alive"] = True
    state.update(payload)
    release.set()
    rule.close()
    assert said == []


def test_short_death_timer_skipped(payload):
    rule, said = make(lambda p: "Tip.")
    state = MatchState()
    die(payload, state, Engine([rule], lambda line: None), respawn=5)
    rule.close()
    assert said == []


def test_failed_request_falls_back_to_builtin_tip(payload):
    rule, said = make(lambda p: None)
    state = MatchState()
    die(payload, state, Engine([rule], lambda line: None))
    rule.close()
    assert said == ["Built-in tip."]


def test_builtin_provider_needs_no_model(payload):
    rule, said = make(None)
    state = MatchState()
    die(payload, state, Engine([rule], lambda line: None))
    rule.close()
    assert said == ["Built-in tip."]


def test_builtin_tips_use_own_stats(payload):
    tips = BuiltinTips()
    snap = Snapshot.from_payload(payload)
    snap.clock_time, snap.gold, snap.buyback_cost = 1900, 100, 2000
    assert "buyback" in tips(snap)
    snap.clock_time, snap.last_hits = 900, 10
    assert "last hits" in tips(snap)


@pytest.fixture
def fake_ollama():
    """A tiny local stand-in for Ollama's /api/chat."""
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = json.dumps({"message": {"role": "assistant", "content": " Buy a BKB next. "}})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", received
    server.shutdown()


def test_ollama_asker(fake_ollama):
    url, received = fake_ollama
    ask = ollama_asker("llama3.1:8b", url, timeout=5)
    assert ask("Hero: luna") == "Buy a BKB next."
    assert received[0]["model"] == "llama3.1:8b"
    assert received[0]["stream"] is False
    assert received[0]["messages"][1]["content"] == "Hero: luna"


def test_ollama_not_running_returns_none():
    ask = ollama_asker("llama3.1:8b", "http://127.0.0.1:9", timeout=2)
    assert ask("Hero: luna") is None


def test_prompt_has_only_own_hero_data(payload):
    text = describe(Snapshot.from_payload(payload), load_items())
    assert "Hero: antimage, level 11" in text
    assert "Battle Fury" in text and "Magic Wand" in text
    assert "Gold: 1640; buyback costs 865 (affordable)" in text
    # GSI in player mode has no enemy data, and the prompt adds none.
    assert "enemy" not in text.lower()


def test_build_can_be_switched_off():
    assert build({"death_tip": {"enabled": False}}, print) == []
    rules = build({"death_tip": {"min_respawn": 20}}, print)
    assert rules[0].min_respawn == 20
    rules[0].close()


@pytest.mark.parametrize("provider", ["ollama", "claude", "builtin"])
def test_build_each_provider(provider):
    rules = build({"death_tip": {"provider": provider}}, print)
    assert (rules[0].ask is None) == (provider == "builtin")
    rules[0].close()


def test_build_rejects_unknown_provider():
    with pytest.raises(ValueError):
        build({"death_tip": {"provider": "gpt"}}, print)
