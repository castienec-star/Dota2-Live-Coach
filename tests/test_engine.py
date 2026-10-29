from coach.rules import Engine
from coach.speaker import HIGH, NORMAL, URGENT
from coach.state import MatchState


class Says:
    def __init__(self, name, line):
        self.name = name
        self.line = line

    def check(self, state):
        return [self.line]

    def reset(self):
        pass


def run(rules, payload, **kwargs):
    said = []
    engine = Engine(rules, lambda *args: said.append(args), **kwargs)
    state = MatchState()
    state.update(payload)
    engine(state)
    return said


def test_only_the_most_important_lines_are_said(payload):
    rules = [
        Says("item_ready", "Buy Power Treads."),
        Says("power_rune", "Power rune in 15 seconds."),
        Says("skill_point", "Level up a spell."),
        Says("low_health", "Low health, back off."),
    ]
    assert run(rules, payload) == [("Low health, back off. Power rune in 15 seconds.",)]


def test_equal_lines_keep_the_rules_order(payload):
    rules = [Says("bounty_rune", "Gold runes."), Says("power_rune", "Power rune.")]
    assert run(rules, payload) == [("Gold runes. Power rune.",)]


def test_prioritized_passes_the_top_priority(payload):
    rules = [Says("item_ready", "Buy boots."), Says("buyback", "Save for buyback.")]
    assert run(rules, payload, prioritized=True) == [("Save for buyback. Buy boots.", URGENT)]
    assert run([Says("stack", "Stack.")], payload, prioritized=True) == [("Stack.", HIGH)]
    assert run([Says("ward", "Place a ward.")], payload, prioritized=True) == [("Place a ward.", NORMAL)]


def test_max_lines_is_configurable(payload):
    rules = [Says("power_rune", "One."), Says("stack", "Two."), Says("ward", "Three.")]
    assert run(rules, payload, max_lines=3) == [("One. Two. Three.",)]
