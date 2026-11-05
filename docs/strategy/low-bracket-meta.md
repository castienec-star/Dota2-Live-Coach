# Low-bracket hero meta (patch 7.41f)

Which heroes Herald to Ancient players pick most, and which win, in the live
patch. Backs the choice of bundled builds (`[builds]` in `config/coach.toml`,
ROADMAP item 1) and the hero-specific advice in `fundamentals.md`.

Following Castien's rule, each medal is read on its own: a Legend player is
compared only with Legend games, never with a mix of brackets.

## Source and limits

- OpenDota's public `/api/heroStats` (`N_pick`, `N_win` for brackets 1 to 6,
  Herald to Ancient), read on 2026-11-01 while the live patch was 7.41f
  (OpenDota's `/api/constants/patch` lists 7.41 as the newest patch). These
  are OpenDota's recent public matches, not all matches.
- **Only heroes with ids 1 to 54 (Anti-Mage to Lifestealer)** were readable
  from the cloud run: the fetch tool cut the response there. Popular heroes
  with higher ids (Ogre Magi, Slark, Legion Commander, Bristleback, Spirit
  Breaker, Bounty Hunter, Mars, Tusk and others) are missing. The full table
  comes from `py -m coach refresh-hero-stats` (PR #70), run at home.
- Each bracket has 100,000 or more games for the popular heroes, so a gap of
  2 points is real, but win rate also reflects who picks the hero (Pudge and
  Sniper are first-time picks), not only how strong it is.

## Most picked, with win rate, per bracket

Heroes with ids 1 to 54 only (see above).

| Bracket | Most picked (win %) |
|---|---|
| Herald | Sniper 51.6, Pudge 52.5, Lion 49.8, Phantom Assassin 52.2, Juggernaut 51.7, Drow Ranger 48.1, Shadow Shaman 52.4, Lina 45.6 |
| Guardian | Pudge 52.6, Sniper 50.9, Lion 49.0, Phantom Assassin 52.1, Shadow Shaman 51.9, Juggernaut 51.9, Witch Doctor 53.0, Crystal Maiden 53.4 |
| Crusader | Pudge 52.5, Lion 49.1, Sniper 50.4, Witch Doctor 52.5, Juggernaut 52.2, Phantom Assassin 51.6, Shadow Shaman 51.6, Axe 51.5 |
| Archon | Pudge 51.5, Lion 48.7, Sniper 49.9, Witch Doctor 52.5, Juggernaut 52.7, Axe 50.8, Anti-Mage 51.6, Shadow Shaman 51.9 |
| Legend | Pudge 50.8, Lion 48.9, Sniper 49.1, Juggernaut 53.1, Witch Doctor 52.2, Axe 50.0, Windranger 48.0, Anti-Mage 51.3 |
| Ancient | Pudge 50.4, Lion 48.7, Juggernaut 53.3, Windranger 48.4, Earthshaker 51.1, Dragon Knight 52.6, Axe 49.3, Anti-Mage 51.1 |

## Win rate by bracket for the heroes that matter

| Hero | Herald | Guardian | Crusader | Archon | Legend | Ancient |
|---|---|---|---|---|---|---|
| Wraith King | 56.7 | 56.2 | 56.2 | 55.6 | 55.1 | 54.0 |
| Phantom Lancer | 52.7 | 53.2 | 53.1 | 52.7 | 53.4 | 53.6 |
| Dragon Knight | 52.9 | 53.3 | 53.0 | 53.2 | 52.6 | 52.6 |
| Witch Doctor | 53.6 | 53.0 | 52.5 | 52.5 | 52.2 | 51.7 |
| Crystal Maiden | 53.5 | 53.4 | 52.6 | 51.8 | 51.2 | 50.8 |
| Juggernaut | 51.7 | 51.9 | 52.2 | 52.7 | 53.1 | 53.3 |
| Pudge | 52.5 | 52.6 | 52.5 | 51.5 | 50.8 | 50.4 |
| Phantom Assassin | 52.2 | 52.1 | 51.6 | 51.4 | 50.7 | 50.0 |
| Axe | 52.1 | 52.2 | 51.5 | 50.8 | 50.0 | 49.3 |
| Luna | 51.8 | 50.6 | 51.3 | 51.0 | 50.4 | 50.4 |
| Sniper | 51.6 | 50.9 | 50.4 | 49.9 | 49.1 | 48.2 |
| Zeus | 49.2 | 50.4 | 50.4 | 50.4 | 50.3 | 50.0 |
| Lion | 49.8 | 49.0 | 49.1 | 48.7 | 48.9 | 48.7 |
| Viper | 48.1 | 47.6 | 48.3 | 48.0 | 48.5 | 49.4 |
| Drow Ranger | 48.1 | 47.2 | 47.0 | 46.9 | 46.1 | 45.4 |
| Lina | 45.6 | 45.8 | 46.6 | 47.0 | 47.2 | 47.5 |
| Shadow Fiend | 44.3 | 45.1 | 44.9 | 43.5 | 42.8 | 41.3 |
| Nature's Prophet | 46.5 | 44.9 | 43.3 | 42.6 | 42.6 | 43.3 |

## What a beginner should be told

- **Forgiving heroes win at every medal.** Wraith King (a free second life),
  Dragon Knight (tanky, simple), Witch Doctor and Crystal Maiden (simple
  supports) win 51.8% or more from Herald to Archon. If a new player asks what
  to learn, these are the safe answers for their medal.
- **Fragile ranged cores lose most from mistakes.** Drow Ranger, Lina and
  Shadow Fiend are picked a lot and sit at 41 to 48%: they die when they
  stand in front. Their death tips should be about position ("stand behind
  your team, attack from max range"), not items. Sniper wins in Herald
  (51.6%) and falls each medal to 48.2% in Ancient, as opponents learn to
  jump on him.
- **Juggernaut rewards learning.** His win rate rises with medal (51.7% to
  53.3%): a good hero to stay on while climbing.
- **Nature's Prophet loses everywhere (43 to 46%).** Low-bracket players
  farm with him and never join fights. One line at the 15 and 25 minute check
  ("group up with your team now") fits him better than a farm tip.
- **Bundled builds now cover the top 25 picks** (ids 1 to 54): Shadow
  Shaman, Windranger, Anti-Mage, Earthshaker, Necrophos, Crystal Maiden,
  Lina, Dragon Knight, Lifestealer, Phantom Lancer, Tidehunter, Lich and
  Sven got hand-written builds in `config/coach.toml` (ROADMAP item 15).

## Next most-picked heroes (ROADMAP item 20)

Herald-to-Ancient picks summed from the bundled-data snapshot of
OpenDota's `/api/heroStats` taken on 2026-11-04 (PR #82,
`coach/data/hero_stats.json`, all 127 heroes). Among the top 50, these had
no hand-written build and now have one in `config/coach.toml`, chosen from
what players buy on them this patch (`coach/data/item_popularity.json`):

| Rank | Hero | Herald-Ancient win % | Build idea for a beginner |
|---|---|---|---|
| 4 | Rubick | 49.4 | Blink and Force Staff to land and survive spells |
| 8 | Invoker | 50.7 | Kaya, then Black King Bar before the Scepter |
| 19 | Techies | 51.0 | Support saves (Force, Glimmer, Solar Crest) |
| 27 | Skywrath Mage | 49.9 | Rod of Atos to hold a target, Force and Glimmer to live |
| 29 | Outworld Destroyer | 53.1 | Witch Blade, Hurricane Pike to keep distance |
| 31 | Undying | 50.0 | Shard first, then saves |
| 33 | Hoodwink | 47.1 | Force Staff and Shard before Blink |
| 34 | Magnus | 49.1 | Blink, then Black King Bar so the Reverse Polarity lands |
| 36 | Silencer | 50.6 | Support saves, then Scepter |
| 40 | Spectre | 53.0 | Radiance and Manta, Black King Bar before late items |
| 41 | Vengeful Spirit | 52.4 | Support by default; a pos 1 build when you say you're carry |
| 42 | Nature's Prophet | 43.1 | Maelstrom and a Pike, but the real fix is joining fights |

Hoodwink (47.1%) and Nature's Prophet (43.1%) lose a lot at these medals;
their builds favour escape items because both die alone on the map.

