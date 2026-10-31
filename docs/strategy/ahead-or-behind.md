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
  supports' curves, and the first rough answer in a match adds "That's a
  rough comparison with cores in general." A rough answer beats "I don't
  know" for a beginner, as long as it says it's rough once.
- **Before 8 minutes:** a core hears last hits against 3.5 per minute from
  when the creeps meet at about 0:30 (35 at 10:00, ROADMAP item 4), rounded
  to 5: "12 last hits at 5 minutes, aim for about 15." Low-bracket cores often sit near half of that, and
  last hitting is the biggest farm gap there. Supports hear only deaths
  and a habit (keep the core safe, stack a camp). Everyone hears deaths so
  far, since not dying is the first habit to build.
- The 15/25 minute check now speaks for every hero, rough or not.

## Compared with your own rank

Castien asked (2026-10-31) that the coach know your MMR, so the comparison
is fair: a Herald on 350 GPM is doing fine, a Legend on 350 GPM isn't. And
then that only your own medal's numbers are used: a Legend 3 is compared
only with Legend players.

- **Your medal** (`coach/rank.py`): what you said ("my rank is Archon",
  "my MMR is 2500", or the one-time question at the start of a game; kept
  in `rank.json`), else `[player] rank` in `coach.toml`, else the medal on
  your own public OpenDota profile (`/players/{your account}`, the same
  own-profile rule as the briefing's match history). MMR becomes a medal at
  about 770 MMR a medal (five stars of about 154).
- **What each medal reaches** (`coach/data/brackets.json`, written by
  `py -m coach refresh-brackets`): about 250 recent ranked matches per
  medal (Herald to Ancient each, Divine and Immortal together), only on
  the live patch, not Turbo, 15 minutes or longer, nobody abandoned. From OpenDota's public match data:
  `/publicMatches?min_rank=&max_rank=` lists matches by average rank tier,
  `/matches/{id}` gives each player's GPM, XPM and last hits. On each team
  the three with most last hits count as cores, the other two as
  supports, and each hero with 30 or more games in that medal gets its
  own numbers. Saved at the same percentiles as `benchmarks.json`.
- **How it is used:** only your medal's numbers. Your hero's own Legend
  curve when there is one, else Legend cores or supports in general (the
  first such answer in a match says it's a rough comparison with Legend
  cores in general). The all-bracket `benchmarks.json` isn't used once
  your medal is known. Against your own medal "behind" is under 25% and
  "ahead" is 70% and up, centred on your medal's median.
- **Last-hit targets** (before 8 minutes and the 5:00/10:00 line): the
  whole-match last hits a minute of your medal's middle core, lowered by
  the same early ramp as the verdict (0.73 at 10:00), from when the creeps
  meet. A middle core overall (about 5.5 a minute) gives the old 15 and 35;
  a Herald core on 3.5 a minute gets 10 and 25.
- Without the file, or for a medal it doesn't cover, everything works as
  before, against all players, and the coach says so when you tell it your
  rank.
- `rank.describe("archon")` gives one sentence of a medal's typical numbers
  for the local model's facts.

## Known limits

- Net worth is not compared: GSI gives gold but not net worth, and the
  benchmarks have no net worth curve.
- Benchmarks mix every position a hero is played in (Pudge mid and Pudge
  support share one curve). With ~2,500 players a medal, only popular
  heroes reach 30 games; the rest use the medal's cores or supports.
- Only the 16 heroes with a build have their own bundled numbers. Next:
  bundle OpenDota's public benchmarks for every hero (issue #28 point 1),
  refreshed with patch data.
- Rough numbers are only core or support. A pos 1 carry farms more than a
  pos 3 offlaner, so next: average by the known position (1, 2 or 3).
