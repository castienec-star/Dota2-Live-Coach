import pytest

from coach.gsi_server import Coach
from coach.replay_review import DIED, PAUSED, ReplayReview, numbers, spread, stage
from coach.speaker import HIGH, NORMAL
from coach.state import Snapshot


def replay(clock=240, health=800, alive=True, paused=False, last_hits=18, state="DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"):
    return {
        "map": {"matchid": "1", "clock_time": clock, "paused": paused, "game_state": state},
        "player": {"team2": {"player0": {"accountid": "42", "team_name": "radiant", "gold": 900,
                                         "last_hits": last_hits}},
                   "team3": {"player5": {"accountid": "7", "team_name": "dire"}}},
        "hero": {"team2": {"player0": {"name": "npc_dota_hero_juggernaut", "health": health, "max_health": 1000,
                                       "alive": alive, "level": 5}},
                 "team3": {"player5": {"name": "npc_dota_hero_lion", "health": 500, "max_health": 600}}},
        "items": {"team2": {"player0": {"slot0": {"name": "item_magic_wand"}}}},
    }


class Rig:
    def __init__(self, mode="moments", replies=("You stayed too far up the lane at half health. Backing to the tower would have kept you alive.",)):
        self.now = 0.0
        self.said, self.asked, self.grabs = [], [], 0
        self.replies = list(replies)
        self.talking = False

        def ask(prompt, frames):
            self.asked.append((prompt, frames))
            return self.replies[min(len(self.asked), len(self.replies)) - 1]

        def grab():
            self.grabs += 1
            return f"frame{self.grabs}".encode()

        self.review = ReplayReview({42}, None, mode, ask, grab,
                                   lambda text, **kw: self.said.append((text, kw)),
                                   clock=lambda: self.now, run=lambda job: job(), busy=lambda: self.talking)
        self.coach = Coach("t")
        self.coach.replay = self.review
        self.coach.listeners.append(self.review)

    def send(self, payload, dt=1.0):
        self.now += dt
        return self.coach.handle(payload)

    def play(self, seconds, **kw):
        """The replay plays on: an update and a tick each second."""
        for _ in range(seconds):
            self.send(replay(clock=self.review.snap.clock_time + 1 if self.review.snap.clock_time else 240, **kw))
            self.review.tick()


def test_coach_sees_only_your_hero():
    rig = Rig()
    snap = rig.send(replay())
    assert snap.hero_name == "npc_dota_hero_juggernaut" and snap.gold == 900
    assert snap.team == "radiant"


def test_a_frame_every_second_and_a_few_go_to_the_model():
    rig = Rig()
    rig.play(12)
    assert rig.grabs == 12
    rig.send(replay(clock=253, health=0, alive=False), dt=0.1)
    prompt, frames = rig.asked[-1]
    assert len(frames) == 4 and frames[-1] == b"frame12"  # spread over the last 10 s
    assert "died at the end" in prompt and "laning stage" in prompt
    assert "juggernaut" in prompt and "lion" not in prompt
    assert rig.said[-1][1] == {"priority": HIGH, "max_delay": 30.0}


def test_paused_replay_takes_no_frames_but_is_talked_over():
    rig = Rig()
    rig.play(5)
    rig.send(replay(clock=245, paused=True))
    assert "paused" in rig.asked[-1][0]
    grabs = rig.grabs
    for _ in range(5):
        rig.now += 1
        rig.review.tick()
    assert rig.grabs == grabs


def test_fast_health_loss_is_a_moment():
    rig = Rig()
    rig.play(3)
    rig.send(replay(clock=243, health=300), dt=0.5)
    assert "lost a lot of health" in rig.asked[-1][0]


def test_continuous_looks_back_over_everything_since_last_time():
    rig = Rig(mode="continuous", replies=["You missed three last hits in a row there.",
                                          "Your wave pushed into their tower and you followed it."])
    rig.play(21)
    assert len(rig.asked) == 2  # every 10 s
    assert len(rig.asked[1][1]) == 4
    assert rig.said[0][1] == {"priority": NORMAL, "max_delay": 30.0}
    assert "Points you already made" in rig.asked[1][0]


def test_repeats_are_not_said_again():
    same = "You stayed in lane at half health with three enemies missing. Backing off would have saved you."
    rig = Rig(mode="continuous", replies=[same, same.replace("Backing off", "Going back")])
    rig.play(21)
    assert len(rig.asked) == 2 and len(rig.said) == 1


def test_no_new_look_while_the_coach_is_talking():
    rig = Rig(mode="continuous")
    rig.talking = True
    rig.play(25)
    assert rig.asked == []
    rig.talking = False
    rig.play(1)
    assert len(rig.asked) == 1


def test_skip_replies_are_not_said():
    rig = Rig(replies=["skip"])
    rig.play(2)
    assert rig.review.look(PAUSED)
    assert rig.said == []


def test_live_match_shuts_the_screen_and_isnt_coached():
    rig = Rig()
    rig.play(3)
    live = {"map": {"matchid": "2", "clock_time": 60}, "player": {"steamid": "76561197960265770", "gold": 600},
            "hero": {"name": "npc_dota_hero_axe"}}
    snap = rig.send(live)
    assert not rig.review.gate.open
    assert snap.hero_name == "npc_dota_hero_juggernaut"  # the live update was dropped
    grabs = rig.grabs
    assert not rig.review.look(DIED)
    rig.review.tick()
    assert rig.asked == [] and rig.grabs == grabs and not rig.review.frames


def test_unknown_hero_is_not_guessed():
    rig = Rig()
    rig.review.accounts = set()
    assert rig.send(replay()).hero_name is None
    rig.review.hero = "npc_dota_hero_lion"
    assert rig.send(replay()).hero_name == "npc_dota_hero_lion"


def test_rewinding_forgets_the_old_seconds():
    rig = Rig()
    rig.play(6)
    rig.send(replay(clock=100))
    assert not rig.review.frames


def test_numbers_and_stage():
    a = Snapshot(clock_time=230, hero_name="h", health=800, max_health=1000, last_hits=17, gold=500)
    b = Snapshot(clock_time=240, hero_name="h", health=300, max_health=1000, last_hits=17, gold=520, deaths=1,
                 alive=False)
    text = numbers([a, b])
    assert text.startswith("From 3:50 to 4:00: health 80% to 30%") and "last hits 17 to 17" in text and "died" in text
    assert "laning stage" in stage(240) and "mid game" in stage(900) and stage(None) == ""
    assert spread(list(range(10)), 4) == [0, 3, 6, 9] and spread([1, 2], 4) == [1, 2]


def test_bad_mode():
    with pytest.raises(ValueError):
        ReplayReview(set(), None, "sometimes", None, lambda: None, print)


def test_improvised_item_advice_and_fake_kills_are_dropped():
    rig = Rig(mode="continuous", replies=[
        "You could have used the wand to farm creeps, gaining gold and experience.",
        "Staying near your creeps would have helped you get those early kills.",
        "You let the wave push to their tower and lost three last hits.",
    ])
    rig.play(31)
    assert len(rig.asked) == 3
    assert [text for text, _ in rig.said] == ["You let the wave push to their tower and lost three last hits."]
    assert "Items: magic wand." in rig.asked[0][0]  # the coach still sees the items


def test_wand_for_a_fight_is_fine():
    rig = Rig(mode="continuous", replies=["You went into the lotus fight at low health and never broke your wand. "
                                          "Those charges would have kept you alive."])
    rig.play(11)
    assert len(rig.said) == 1


def test_unused_wand_at_death_may_be_mentioned():
    rig = Rig(replies=["You died with fifteen wand charges. Breaking the wand in that fight would have saved you."])
    wand = {"slot0": {"name": "item_magic_wand", "charges": 15, "can_cast": True, "cooldown": 0}}
    for _ in range(5):
        p = replay(clock=(rig.review.snap.clock_time or 239) + 1)
        p["items"]["team2"]["player0"] = wand
        rig.send(p)
        rig.review.tick()
    rig.send(replay(clock=245, health=0, alive=False), dt=0.1)
    assert "still had ready: magic wand (15 charges)" in rig.asked[-1][0]
    assert len(rig.said) == 1


def test_regular_looks_rotate_what_to_look_at():
    rig = Rig(mode="continuous", replies=["You missed two denies.", "You trade badly into their support.",
                                          "Your wave met under their tower."])
    rig.play(31)
    focuses = [p.split("This time, look most at: ")[1].split(".")[0] for p, _ in rig.asked]
    assert len(set(focuses)) == 3


def test_quiet_looks_leave_a_note(caplog):
    rig = Rig(mode="continuous", replies=["skip"])
    with caplog.at_level("INFO"):
        rig.play(11)
    assert "nothing clearly went wrong" in caplog.text
