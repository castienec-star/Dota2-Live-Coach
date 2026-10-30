import copy

import pytest

from coach import chat as chat_mod
from coach.chat import OFF, OLLAMA_OFF, UNSURE, Chat, _cut, stale
from coach.game_questions import Notes
from coach.heroes import HeroIndex
from coach.item_advisor import Advice, ItemAdvisor
from coach.state import Snapshot
from coach.voice import UNKNOWN, Answers, VoiceLoop

HEROES = HeroIndex()
BUILDS = {"antimage": ["Power Treads", "Battle Fury", "Manta Style"]}


def heroes(*keys):
    return [HEROES.by_key(k) for k in keys]


@pytest.fixture
def snap(payload):
    return Snapshot.from_payload(payload)  # Anti-Mage at 11:04 with Treads and Battle Fury


class FakeModel:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, prompt, fmt=None):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else None


def test_prompt_has_own_data_build_lineup_notes_and_question(snap):
    model = FakeModel("Stay behind your creeps.")
    advice = Advice(ItemAdvisor(None), BUILDS, enemies=lambda: heroes("lina", "lion"))
    chat = Chat(
        model,
        advice,
        position=lambda s: 1,
        allies=lambda: heroes("antimage", "crystal_maiden"),
        enemies=lambda: heroes("lina", "lion"),
        notes=lambda: Notes(lane="lost"),
        enemy_items=lambda: ["Lion has Glimmer Cape"],
    )
    assert chat("how do I play against Lina?", snap) == "Stay behind your creeps."
    prompt = model.prompts[0]
    assert "Your hero: Anti-Mage, level" in prompt
    assert "Position: 1" in prompt
    assert "Game time: 11:04 (mid game)" in prompt
    assert "Power Treads" in prompt and "Battle Fury" in prompt
    assert "Next item on the build: Manta Style" in prompt
    assert "The coach suggests buying: Black King Bar" in prompt
    assert "Teammates: Crystal Maiden" in prompt
    assert "Enemies: Lina, Lion" in prompt
    assert "their lane was lost; Lion has Glimmer Cape" in prompt
    assert prompt.endswith("The player asks: how do I play against Lina?")


def test_unknown_lineup_is_said_and_before_the_game(snap):
    model = FakeModel("Pick a hero you know well.")
    chat = Chat(model)
    assert chat("what hero should I pick", Snapshot()) == "Pick a hero you know well."
    prompt = model.prompts[0]
    assert "hasn't started" in prompt
    assert "Teammates: not known" in prompt and "Enemies: not known" in prompt


def test_follow_ups_see_earlier_questions_this_match_only(snap):
    model = FakeModel("Get Manta Style.", "Then Black King Bar.", "Farm the jungle.")
    chat = Chat(model)
    chat("what after Battle Fury?", snap)
    chat("and after that?", snap)
    assert "- Player: what after Battle Fury?\n- You: Get Manta Style." in model.prompts[1]
    other = copy.deepcopy(snap)
    other.match_id = "999"
    chat("where should I farm?", other)
    assert "Earlier this match" not in model.prompts[2]


def test_history_keeps_the_last_few(snap):
    model = FakeModel(*[f"Answer {n}." for n in range(5)])
    chat = Chat(model)
    for n in range(5):
        chat(f"question {n}", snap)
    assert [q for q, _ in chat.history] == ["question 2", "question 3", "question 4"]


def test_reply_naming_a_hero_nobody_told_is_dropped(snap):
    chat = Chat(FakeModel("Watch out for Pudge hooks."), enemies=lambda: heroes("lina"))
    assert chat("what should I watch for?", snap) == UNSURE
    assert chat.history == []


def test_reply_after_a_fight_started_is_not_said(snap):
    snap.health = snap.max_health = 1000
    hurt = copy.deepcopy(snap)
    hurt.health = hurt.max_health // 4
    chat = Chat(FakeModel("Farm the jungle."), current=lambda: hurt)
    assert chat("where should I farm?", snap) == ""


def test_stale():
    calm = Snapshot(hero_name="npc_dota_hero_antimage", health=900, max_health=1000)
    assert not stale(calm, calm)
    assert stale(calm, Snapshot(hero_name="npc_dota_hero_antimage", alive=False))
    assert stale(calm, Snapshot(hero_name="npc_dota_hero_antimage", health=500, max_health=1000))
    assert not stale(Snapshot(), calm)


def test_long_replies_are_cut_to_two_sentences():
    assert _cut("One. Two! Three? Four.") == "One. Two!"
    long = " ".join(["word"] * 80)
    assert len(_cut(long).split()) == chat_mod.MAX_WORDS


def test_answers_send_unknown_questions_to_the_chat(snap):
    model = FakeModel("Push the tower with your team.")
    answers = Answers({}, BUILDS, chat=Chat(model))
    assert answers.answer("should we push or farm", snap) == "Push the tower with your team."
    # Built-in questions never wait for the model.
    assert answers.answer("next item", snap).startswith("Next is Manta Style")
    assert len(model.prompts) == 1


def test_answers_fall_back_when_the_model_is_off(snap):
    assert Answers({}, BUILDS, chat=Chat(FakeModel(), off=OLLAMA_OFF)).answer("tell me a joke", snap) == OLLAMA_OFF
    assert Answers({}, BUILDS, chat=Chat(None)).answer("tell me a joke", snap) == OFF
    assert Answers({}, BUILDS).answer("tell me a joke", snap) == UNKNOWN


def test_voice_loop_says_nothing_for_a_dropped_reply():
    said = []
    loop = VoiceLoop(lambda f: False, lambda a: "where to farm", lambda t: "", said.append)
    loop.ask(b"audio")
    assert said == []


def test_build_follows_the_death_tip_provider():
    assert chat_mod.build({"chat": False}, {}) is None
    built = chat_mod.build({}, {"provider": "ollama", "ollama_url": "http://127.0.0.1:9"})
    assert built.ask is not None and built.off == OLLAMA_OFF
    assert chat_mod.build({}, {"provider": "builtin"}).ask is None
    # Off death tips don't turn the chat off.
    assert chat_mod.build({}, {"enabled": False}).ask is not None


def test_ollama_chat_through_the_fake_server(snap, fake_chat_ollama):
    url, received = fake_chat_ollama
    built = chat_mod.build({"chat_timeout": 5}, {"ollama_url": url, "ollama_model": "llama3.2:3b"})
    assert built("how do I last hit better?", snap) == "Hit the creep when its health is low."
    body = received[0]
    assert body["model"] == "llama3.2:3b"
    assert body["messages"][0]["content"] == chat_mod.SYSTEM_PROMPT
    assert "The player asks: how do I last hit better?" in body["messages"][1]["content"]


@pytest.fixture
def fake_chat_ollama():
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = json.dumps({"message": {"content": "Hit the creep when its health is low."}})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", received
    server.shutdown()


def test_typed_questions_go_to_the_chat(tmp_path, payload, monkeypatch, capsys):
    import io

    from coach.__main__ import make_coach, read_typed_picks
    from coach.config import load
    from coach.speaker import Speaker

    coach = make_coach(load(app_dir=tmp_path), Speaker(), tips=False)
    coach.state.update(payload)
    model = FakeModel("Fight near your towers.")
    coach.chat = Chat(model)
    monkeypatch.setattr("sys.stdin", io.StringIO("should we fight now?\nbuy\n\n"))
    read_typed_picks(coach)
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "Fight near your towers."
    assert "Manta Style" in out[1] or "Black King Bar" in out[1]  # buy is still built in
    assert len(out) == 2 and len(model.prompts) == 1  # an empty line asks nothing

    coach.chat = Chat(None)
    monkeypatch.setattr("sys.stdin", io.StringIO("tell me a joke\n"))
    read_typed_picks(coach)
    assert capsys.readouterr().out.strip() == OFF
