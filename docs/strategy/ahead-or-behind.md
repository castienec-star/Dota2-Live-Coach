# Ahead, even or behind

Backs the "How am I doing?" voice answer and the unasked check at 15:00 and
25:00 (`coach/benchmarks.py`, `coach/rules/game_check.py`, issue #9 step 2).
Castien asked for the unasked check on 2026-10-28.

## Where the numbers come from

- OpenDota's public hero benchmarks
  (`https://api.opendota.com/api/benchmarks?hero_id=N`): for each hero, the
  gold per minute, experience per minute and last hits per minute that 10%,
  20% ... 99% of recent public matches reached. These are aggregate numbers,
  not anyone's profile, so they fit the fair-play rule.
- A snapshot for the 16 heroes with a bundled build is in
  `coach/data/benchmarks.json` (fetched 2026-10-28, patch 7.41). Refresh it
  with the other patch data, only when a new patch is live (see CLAUDE.md).
  Other heroes are read from OpenDota once and cached for 30 days, if
  `[pregame] opendota` is on.
- The player's side is GSI only: `player.gpm`, `player.xpm` and
  `player.last_hits` over the game clock.

## How the verdict is chosen

1. **Too early before 8:00.** Laning numbers swing on one kill or one lost
   wave.
2. **Scale for the time of the match.** Benchmarks are whole-match averages,
   and per-minute numbers grow through a match (more waves, bigger camps,
   farming items). So early numbers are scaled up: divided by 0.6 at the horn,
   0.8 at 15:00, nothing from 30:00. This ramp is an approximation picked so a
   steady low-bracket carry (about 450 GPM and 75 last hits at 15:00 on
   Juggernaut) lands "even"; tune it with real recordings.
3. **Share of public matches beaten**, per number, by interpolating the
   percentile curve, then averaged.
   - Cores (positions 1 to 3, or a hero without the Support role while the
     position isn't known): gold, experience and last hits.
   - Supports (positions 4 and 5): experience only. A pos 5 is not "behind"
     for having no farm; experience shows whether they are in fights and
     levelling.
4. **Bands.** Under 15% of public matches is "behind", 55% and up is
   "ahead", anything between is "even". Public matches are mostly played
   below Divine, so this "even" band sits around where a Herald-to-Ancient
   player actually is, rather than the median of all games.

## What the coach says

- **Behind, core:** the weakest number, then farm the safe side near towers,
  skip risky fights, buy a Black King Bar or defensive item. Low-bracket
  comebacks come from not feeding and from late-game items, not from forcing
  fights while behind.
- **Behind, support:** stay near the cores, get experience from fights, buy
  Glimmer Cape or Force Staff to stay alive.
- **Even:** keep farming, fight together.
- **Ahead:** group and take a tower, or Roshan after a won fight. Low-bracket
  teams often win a fight and go back to farming; turning fights into
  buildings is how a lead wins the game.

## Every hero, every minute (issue #28)

- **No numbers for the hero** (not bundled, OpenDota off or unreachable): the
  verdict uses the average of the bundled cores' curves, or the bundled
  supports' curves, and the coach adds "That's a rough comparison with cores
  in general." A rough answer beats "I don't know" for a beginner, as long as
  it says it's rough.
- **Before 8 minutes:** a core hears last hits against 3.5 per minute
  (35 at 10:00, ROADMAP item 4), rounded to 5: "12 last hits at 5 minutes,
  aim for about 20." Low-bracket cores often sit near half of that, and
  last hitting is the biggest farm gap there. Supports hear only deaths
  and a habit (keep the core safe, stack a camp). Everyone hears deaths so
  far, since not dying is the first habit to build.
- The 15/25 minute check now speaks for every hero, rough or not.

## Known limits

- Net worth is not compared: GSI gives gold but not net worth, and the
  benchmarks have no net worth curve.
- Benchmarks mix every bracket and every position a hero is played in (Pudge
  mid and Pudge support share one curve).
- Only the 16 heroes with a build have their own bundled numbers. Next:
  bundle OpenDota's public benchmarks for every hero (issue #28 point 1),
  refreshed with patch data.
