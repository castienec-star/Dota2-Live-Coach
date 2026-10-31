# Post-game review: what to tell a low-bracket player after the match

Used by `coach/review.py` (ROADMAP item 3). The review says at most three
points, most important first, each with one habit to try next game. One
clear habit per game sticks; a list of ten mistakes does not.

## Order of the points

1. **Deaths.** Dying is the most common way games are thrown below Divine,
   and each death gives the enemy gold and experience and costs your own
   farm time. One death point only, the most specific that fits:
   - two or more deaths **before 10:00** means the laning stage is the
     problem: stand behind your creeps, go back to the tower when low;
   - **three deaths within six minutes** (the same streak as the live death-tip line) is the tilt spiral (walking back
     into the same fight): farm near your towers for a minute instead;
   - **seven or more** deaths in a game, spread out: think about the
     enemies you can't see before walking forward, and keep a Town Portal.
2. **Last hits at 10:00, cores only.** Target 35: 3.5 last hits per minute
   from when the creeps meet at about 0:30, the same pace the "how am I
   doing?" answer uses before 8 minutes (see `ahead-or-behind.md`). Under 80%
   of it (under 28) is a point. Low-bracket cores often sit near half the
   target, and it's the biggest farm gap there. Supports are not judged on
   last hits.
3. **First big item.** The first item over 1800 gold (the same line the
   pre-game profile uses for item timings). Rule of thumb: a core's first big
   item by about 20 minutes, a support's (Glimmer Cape, Force Staff) by 25.
   Later than that, or none at all in a long game, is a point. This is a
   rough single number; the next step is comparing with the hero's public
   popular-item timings (OpenDota `itemPopularity`, already bundled for the
   item advisor).

When there is less than three to fix, the review praises what went well
(few deaths in a long game, last hits on target): beginners quit coaching
tools that only criticise.

## Comparing with last game

Castien asked on 2026-10-31 for the review to open by saying whether the
player fixed last game's point. The first point of each review (deaths,
last hits or first big item) is kept in `reviews/last.json`, and the next
review opens with one line:

- the same check no longer finds that point: "You fixed last game's point:
  30 last hits at 10 minutes, up from 18. Well done.";
- still a point but better (fewer deaths, more last hits, an earlier item):
  "Better than last game: ... Keep working on it.";
- otherwise: "Last game's point is still the one to work on: ...".

The line takes one of the three spoken points. It is skipped when the role
changed (core and support targets differ) or last game had nothing to fix.
The live 10:00 last-hit line (`last-hitting.md`) uses the same file, but only
mentions last game when the player beat it: a bad lane shouldn't sound like a
step back.

## Fair play

Only the player's own GSI data (deaths with the game clock, last hits,
own items). Nothing about other players.
