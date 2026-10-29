# Questions during the match

Backs `coach/game_questions.py` (issue #11 step 3). GSI in player mode only
describes the player's own hero, so the coach cannot know how the lane went,
which enemy is the problem, whether the enemy carry is farming or who wins
fights. It asks the player instead: that is the player telling the coach
what they saw on their own screen, so it keeps the fair-play rule. The coach
never looks anything up about other players.

## When it asks

| Question | From | Until | Answers |
|---|---|---|---|
| How did your lane go: won, even or lost? | 10:00 | 18:00 | won / even / lost |
| Which enemy hero is giving you the most trouble? | 12:00 | end | a hero name |
| Is their carry farming freely? | 15:00 | end | yes / no |
| Is your team ahead or behind in fights? | 20:00 | end | ahead / even / behind |

- 10:00 is when the laning stage is usually over; after 18:00 "how did your
  lane go" is old news, so it is dropped.
- Only at calm moments: dead with at least 10 seconds to wait, or alive with
  at least 80% health and no damage taken for 10 game seconds. Taking
  damage is the best "in a fight" signal GSI gives about your own hero.
- At most one question every 5 game minutes (`question_every`), each once a
  match, answered or not. Silence or "skip" drops it without a reply. Start-
  of-game questions always go first.

## What the coach says back

One line of fundamentals, the same advice as the "how am I doing?" verdict
in [ahead-or-behind.md](ahead-or-behind.md):

- **Lost lane**: farm safe camps near your towers and catch up. Low-bracket
  games are long, and a lost lane is rarely a lost game; dying again while
  trying to win it back is what loses it.
- **Won lane**: use the lead on a tower or another lane instead of farming
  the same wave.
- **Trouble hero**: check where that hero is on the minimap before fighting,
  and don't fight them alone. Map awareness is the habit this builds.
- **Enemy carry farming freely**: group up and go find them. An unbothered
  carry is how lower-bracket games are thrown late.
- **Losing fights**: stay together, avoid open fights, farm until the big
  item is done (a Black King Bar or defensive item, see
  [situational-items.md](situational-items.md)).
- **Winning fights**: take a tower or Roshan after each won fight instead of
  going back to farm. Turning fights into objectives is the most common
  missing step at low MMR.

## Next (issue #11 step 4)

The answers are kept for the match (`GameQuestions.notes`) but not yet used
elsewhere. Next: a lost lane or a free-farming enemy carry should tilt "what
should I buy?" and the 15/25 minute check toward defensive items, and the
trouble hero should be named in death tips and counter picks.
