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
   - **three deaths within five minutes** is the tilt spiral (walking back
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

## Fair play

Only the player's own GSI data (deaths with the game clock, last hits,
own items). Nothing about other players.
