import json

from coach import evals


class Fake:
    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def __call__(self, prompt, fmt=None):
        self.prompts.append(prompt)
        return self.reply


def asks(tip="Use Counterspell when Lion jumps on you.", item='{"item": "black_king_bar", "why": "so Lion cannot hex you"}',
         briefing="Watch out for Black Hole and Chronosphere, and spread out in fights."):
    return {"tip": Fake(tip), "item": Fake(item), "briefing": Fake(briefing)}


def test_every_case_runs_through_the_real_prompts():
    cases = evals.load_cases()
    assert {c["kind"] for c in cases} == set(evals.KINDS)
    results = evals.run(cases, asks(), cards=True)
    assert len(results) == len(cases)


def test_points_for_spoken_and_on_point_lines():
    cases = [c for c in evals.load_cases() if c["name"].startswith(("Anti-Mage hexed", "Core against Lion"))]
    results = evals.run(cases, asks(), cards=True)
    assert [r.points for r in results] == [2, 2]
    assert results[1].reply == "Black King Bar, so Lion cannot hex you"


def test_a_line_the_checks_drop_scores_nothing():
    case = next(c for c in evals.load_cases() if c["name"].startswith("Anti-Mage hexed"))
    # Pudge isn't in this game, so the tip is never spoken.
    [result] = evals.run([case], asks(tip="Buy a Black King Bar against Pudge."), cards=True)
    assert result.reply is None and result.points == 0


def test_cards_can_be_left_out_for_comparison():
    case = next(c for c in evals.load_cases() if c["kind"] == "briefing")
    with_cards, without = asks(), asks()
    evals.run([case], with_cards, cards=True)
    evals.run([case], without, cards=False)
    assert "What the heroes do:" in with_cards["briefing"].prompts[0]
    assert "What the heroes do:" not in without["briefing"].prompts[0]
    # Leaving them out for one run doesn't lose them for the next.
    assert evals.knowledge.hero_cards([evals.HeroIndex().by_key("lion")])


def test_report_sums_each_run(capsys):
    results = [
        evals.Result("a", True, "Use Hex.", True),
        evals.Result("b", True, None, False),
        evals.Result("a", False, "Play safe.", False),
    ]
    evals.report(results)
    out = capsys.readouterr().out
    assert "Score 2/4: spoken 1/2, on point 1/2" in out
    assert "Score 1/2: spoken 1/1, on point 0/1" in out


def test_main_stops_when_ollama_is_not_running(capsys):
    assert evals.main(["--url", "http://127.0.0.1:9", "--timeout", "2"]) == 1
    assert "did not answer" in capsys.readouterr().out


def test_progress_is_reported_as_each_answer_comes_in():
    cases = evals.load_cases()[:2]
    seen = []
    evals.run(cases, asks(), cards=True, runs=2, progress=seen.append)
    assert [r.case for r in seen] == [cases[0]["name"]] * 2 + [cases[1]["name"]] * 2


def test_without_cards_leaves_out_the_item_uses_too():
    case = next(c for c in evals.load_cases() if c["name"] == "Core against evasion")
    with_cards, without = asks(), asks()
    evals.run([case], with_cards, cards=True)
    evals.run([case], without, cards=False)
    assert "pierces evasion" in with_cards["item"].prompts[0]
    assert "pierces evasion" not in without["item"].prompts[0]
