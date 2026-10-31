# Last hitting

Backs the unasked last-hit check at 5:00 and 10:00
(`coach/rules/last_hits.py`, ROADMAP item 4), the "how am I doing?" answer
before 8 minutes and the post-game review's last-hit point.

## Why it matters at low MMR

Last hits are most of a core's early gold, and the gap between a Herald and a
Divine core is far bigger in last hits than in kills. GSI gives the player's
own `player.last_hits` directly, so this is the cheapest coaching win there
is.

## The target

- **3.5 last hits a minute from when the creeps meet (about 0:30)**, rounded
  to 5: 15 at 5:00, 35 at 10:00. The same numbers as the post-game review
  (`docs/strategy/post-game-review.md`) and the early "how am I doing?"
  answer (`docs/strategy/ahead-or-behind.md`).
- **Scaled to your rank** once the coach knows it (2026-10-31): 3.5 times how
  the middle core of your medal last-hits against the middle core overall,
  from `coach/data/brackets.json` (see "Compared with your own rank" in
  `docs/strategy/ahead-or-behind.md`). The post-game review still uses the
  flat 35 for now.
- A lane wave is four creeps every 30 seconds early on (three melee, one
  ranged), about 8 a minute, so 3.5 is a bit under half the lane: reachable
  for a beginner who is contested, and well under what good cores get.
- It is deliberately flat, not per hero. OpenDota's public benchmarks
  (`coach/data/benchmarks.json`) are whole-match averages (Juggernaut's
  median is about 9 a minute over a full game), far above what the first
  ten minutes allow, so they would discourage a beginner in lane.

## What the coach says

- On target: "17 last hits at 5 minutes, great farming. Keep it up."
- At least 70% of the target: "11 last hits at 5 minutes, close to the 15 to
  aim for. Keep at it."
- Further behind, one thing to work on:
  - 5:00, still in lane: hit a creep when its health drops under one of your
    attacks, and don't chase kills in lane.
  - 10:00, lanes opening up: take the nearest jungle camp between waves
    instead of walking around.
- Supports (position 4 or 5, or a support hero while the position isn't
  known) hear nothing: their job is to keep the core's lane safe.

Encouraging wording on purpose: one line at 5 and 10 minutes, never a
string of "you're behind", so players keep the reminder on.
