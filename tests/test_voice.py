import numpy as np
import pytest

from coach.state import Snapshot
from coach.voice import FRAME, UNKNOWN, Answers, Endpointer, VoiceLoop, intent, start

BUILDS = {"antimage": ["Power Treads", "Battle Fury", "Manta Style"]}


@pytest.mark.parametrize(
    "text, expected",
    [
        ("What's my next item?", "next_item"),
        ("What should I buy?", "what_to_buy"),
        ("What's next on my build?", "next_item"),
        ("Should I buy back?", "buyback"),
        ("can I buyback", "buyback"),
        ("When is the next rune?", "rune"),
        ("When do the wisdom shrines spawn?", "rune"),
        ("Tell me a joke.", "unknown"),
    ],
)
def test_intent(text, expected):
    assert intent(text) == expected


@pytest.fixture
def snap(payload):
    return Snapshot.from_payload(payload)  # Anti-Mage at 11:04 with Treads and Battle Fury


def test_next_item_says_how_much_gold_is_missing(snap):
    answers = Answers({}, BUILDS)
    snap.gold = 1640
    manta = answers.items.next_item(snap)
    assert answers.answer("what's my next item", snap) == (
        f"Next is Manta Style. You need {manta.cost - 1640} more gold."
    )


def test_next_item_when_affordable(snap):
    snap.gold = 10000
    assert Answers({}, BUILDS).answer("next item", snap) == "Buy Manta Style now, you have the gold."


def test_next_item_after_the_build_is_done(snap):
    answers = Answers({}, {"antimage": ["Power Treads"]})
    assert answers.answer("next item?", snap).startswith("Your build list is done.")


def test_buyback_answers(snap):
    answers = Answers({}, BUILDS)
    snap.buyback_cost, snap.buyback_cooldown, snap.gold = 1500, 0, 1000
    assert answers.answer("can I buy back", snap) == "You can't buy back. It costs 1500 and you have 1000."
    snap.gold = 2000
    assert answers.answer("can I buy back", snap).startswith("You can buy back for 1500.")
    snap.buyback_cooldown = 120
    assert answers.answer("can I buy back", snap) == "Buyback is on cooldown for 120 seconds."


def test_rune_times_follow_the_clock(snap):
    answers = Answers({}, BUILDS)
    assert answers.answer("next rune?", snap) == (
        "Power rune at 12:00, Gold runes at 12:00, Wisdom shrines at 14:00."
    )
    snap.clock_time = -30
    assert answers.answer("next rune?", snap).startswith("Power rune at 6:00, Gold runes at 4:00")


def test_rune_settings_from_config(snap):
    answers = Answers({"power_rune": {"enabled": False}, "wisdom_shrine": {"enabled": False}}, BUILDS)
    assert answers.answer("rune", snap) == "Gold runes at 12:00."


def test_unknown_and_no_hero(snap):
    answers = Answers({}, BUILDS)
    assert answers.answer("who wins", snap) == UNKNOWN
    assert answers.answer("next item", Snapshot()).startswith("I can't see your hero yet.")


def frame(level):
    return np.full(FRAME, level, dtype=np.int16).tobytes()


def test_endpointer_stops_after_silence():
    frames = iter([frame(0)] * 3 + [frame(2000)] * 5 + [frame(0)] * 20 + [frame(2000)])
    audio = Endpointer(level=500, silence=0.8).collect(frames)
    # Five loud frames plus the 10 quiet ones (0.8 s) that ended the question.
    assert len(audio) == 15 * FRAME * 2
    assert next(frames) == frame(0)  # stopped before reading everything


def test_endpointer_gives_up_when_nobody_talks():
    assert Endpointer(wait=1.0).collect(iter([frame(0)] * 100)) == b""


def test_endpointer_caps_long_questions():
    audio = Endpointer(max_seconds=1.0).collect(iter([frame(2000)] * 100))
    assert len(audio) == 13 * FRAME * 2  # 13 frames of 80 ms reach 1 s


def run_loop(frames, busy=lambda: False, transcript="hey coach what's my next item"):
    heard, said, chimes = [], [], []
    loop = VoiceLoop(
        wake=lambda f: f == b"WAKE",
        transcribe=lambda audio: transcript,
        answer=lambda text: heard.append(text) or "answer",
        say=said.append,
        busy=busy,
        chime=lambda: chimes.append(1),
        endpointer=Endpointer(level=500, silence=0.16),
        cooldown=0,
        wake_word="hey coach",
    )
    loop.run(frames)
    return heard, said, chimes


def test_loop_answers_after_the_wake_word():
    heard, said, chimes = run_loop([frame(0), b"WAKE", frame(2000), frame(0), frame(0)])
    assert heard == ["what's my next item"]
    assert said == ["answer"]
    assert chimes == [1]


def test_loop_ignores_the_wake_word_while_the_coach_talks():
    heard, said, _ = run_loop([b"WAKE", frame(2000), frame(0), frame(0)], busy=lambda: True)
    assert heard == said == []


def test_loop_stays_quiet_when_nothing_was_said():
    heard, said, chimes = run_loop([b"WAKE"] + [frame(0)] * 50)
    assert chimes == [1]
    assert heard == said == []


def test_loop_ignores_an_empty_transcript():
    heard, said, _ = run_loop([b"WAKE", frame(2000), frame(0), frame(0)], transcript=" Hey, coach. ")
    assert heard == said == []


def test_start_does_nothing_when_turned_off():
    assert start({"enabled": False}, None, print, lambda: False, {}, {}) is None


def test_loop_asks_pending_questions_without_the_wake_word():
    from coach.lineup import Question

    answers, said, chimes = [], [], []
    questions = [Question("Who are the enemy heroes?", lambda text: answers.append(text) or "Got it.")]
    loop = VoiceLoop(
        wake=lambda f: False,
        transcribe=lambda audio: "Pudge and Sniper.",
        answer=lambda text: "answer",
        say=said.append,
        chime=lambda: chimes.append(1),
        cooldown=0,
        wake_word="hey coach",
        pending=lambda: questions.pop() if questions else None,
    )
    loop.run([frame(0), frame(2000)] + [frame(0)] * 20)
    assert said == ["Who are the enemy heroes?", "Got it."]
    assert answers == ["Pudge and Sniper"]
    assert chimes == [1]


def test_loop_passes_silence_to_a_question():
    from coach.lineup import Question

    answers = []
    questions = [Question("Position?", lambda text: answers.append(text))]
    loop = VoiceLoop(
        wake=lambda f: False,
        transcribe=lambda audio: "never called",
        answer=lambda text: "answer",
        say=lambda line: None,
        pending=lambda: questions.pop() if questions else None,
    )
    loop.run([frame(0)] * 200)
    assert answers == [""]
