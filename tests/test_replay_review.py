import pytest

from coach.gsi_server import Coach
from coach.replay_review import DIED, PAUSED, ReplayReview
from coach.speaker import HIGH, NORMAL


def replay(clock=860, health=800, alive=True, paused=False, state="DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"):
    return {
        "map": {"matchid": "1", "clock_time": clock, "paused": paused, "game_state": state},
        "player": {"team2": {"player0": {"accountid": "42", "team_name": "radiant", "gold": 900}},
                   "team3": {"player5": {"accountid": "7", "team_name": "dire"}}},
        "hero": {"team2": {"player0": {"name": "npc_dota_hero_juggernaut", "health": health, "max_health": 1000,
                                       "alive": alive, "level": 9}},
                 "team3": {"player5": {"name": "npc_dota_hero_lion", "health": 500, "max_health": 600}}},
        "items": {"team2": {"player0": {"slot0": {"name": "item_bfury"}}}},
    }


class Rig:
    def __init__(self, mode="moments", reply="Back off to your tower now."):
        self.now = 0.0
        self.said, self.asked, self.grabs = [], [], 0
        self.reply = reply

        def ask(prompt, frame):
            self.asked.append((prompt, frame))
            return self.reply

        def grab():
            self.grabs += 1
            return f"frame{self.grabs}".encode()

        self.review = ReplayReview({42}, None, mode, ask, grab,
                                   lambda text, **kw: self.said.append((text, kw)),
                                   clock=lambda: self.now, run=lambda job: job())
        self.coach = Coach("t")
        self.coach.replay = self.review
        self.coach.listeners.append(self.review)

    def send(self, payload, dt=1.0):
        self.now += dt
        return self.coach.handle(payload)


def test_coach_sees_only_your_hero():
    rig = Rig()
    snap = rig.send(replay())
    assert snap.hero_name == "npc_dota_hero_juggernaut" and snap.gold == 900
    assert snap.team == "radiant"


def test_death_is_judged_from_a_frame_before_it():
    rig = Rig()
    rig.send(replay())
    for _ in range(4):
        rig.now += 2
        rig.review.tick()
    kept = rig.review.frames[0][1]
    rig.send(replay(health=0, alive=False), dt=0.1)
    assert rig.asked[-1][1] == kept
    assert "about to die" in rig.asked[-1][0]
    assert "juggernaut" in rig.asked[-1][0] and "lion" not in rig.asked[-1][0]
    assert rig.said[-1] == ("Back off to your tower now.", {"priority": HIGH, "max_delay": 20})


def test_pause_and_fast_health_loss_are_moments():
    rig = Rig()
    rig.send(replay())
    rig.send(replay(paused=True))
    assert "paused" in rig.asked[-1][0]
    rig.now += 30
    rig.send(replay(health=800))
    rig.send(replay(health=300), dt=0.5)
    assert "lost a lot of health" in rig.asked[-1][0]
    assert len(rig.asked) == 2


def test_continuous_mode_looks_every_interval():
    rig = Rig(mode="continuous")
    rig.send(replay())
    for _ in range(20):
        rig.now += 1
        rig.review.tick()
    assert len(rig.asked) == 2  # every 8 s
    assert rig.said[0][1] == {"priority": NORMAL, "max_delay": 6}
    assert "Don't repeat" in rig.asked[1][0]


def test_skip_replies_are_not_said():
    rig = Rig(reply="skip")
    rig.send(replay())
    assert rig.review.look(PAUSED)
    assert rig.said == []


def test_live_match_shuts_the_screen_and_isnt_coached():
    rig = Rig()
    rig.send(replay())
    assert rig.review.gate.open
    live = {"map": {"matchid": "2", "clock_time": 60}, "player": {"steamid": "76561197960265770", "gold": 600},
            "hero": {"name": "npc_dota_hero_axe"}}
    snap = rig.send(live)
    assert not rig.review.gate.open
    assert snap.hero_name == "npc_dota_hero_juggernaut"  # the live update was dropped
    assert not rig.review.look(DIED)
    rig.review.tick()
    assert rig.asked == [] and rig.grabs == 0


def test_unknown_hero_is_not_guessed():
    rig = Rig()
    rig.review.accounts = set()
    snap = rig.send(replay())
    assert snap.hero_name is None
    rig.review.hero = "npc_dota_hero_lion"
    assert rig.send(replay()).hero_name == "npc_dota_hero_lion"


def test_bad_mode():
    with pytest.raises(ValueError):
        ReplayReview(set(), None, "sometimes", None, lambda: None, print)
