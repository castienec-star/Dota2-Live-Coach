# Low-bracket fundamentals, by game stage and role

What a Herald to Ancient player should hear, when, and which GSI signal lets
the coach say it. Backs ROADMAP item 13 (built-in death tips by role and
stage) and is the checklist new reminders are measured against. Everything
here uses only the player's own GSI data (clock, gold, items, health, last
hits, deaths, buyback) and what the player told the coach (position, enemy
lineup). The coach never knows where enemies are, so it never says "they are
missing"; it says "look at the minimap".

## Habits for every game

- **One role, a few heroes.** Climbing players pick one role and four or
  five heroes for it, so every game teaches the same lessons (esports.gg,
  "A 7k player's top 10 tips to gain MMR"). The coach's builds and
  last-hit targets are per hero and role for the same reason.
- **One thing to fix per game.** Pick one weakness and work on it across
  games (same source). The post-game review's first point and "did you fix
  it?" line (`post-game-review.md`) is exactly this.
- **Don't chain-queue after losses.** Take a few minutes between games and a
  longer break after several losses (same source). Tilted players feed.
  The coach can see a losing streak in its own `reviews/` files.
- **Mute and focus on yourself.** Blaming teammates teaches nothing (same
  source). The coach's tone stays calm and about the player's own play.

## Laning, 0:00 to 10:00

| What to say | Who | GSI signal |
|---|---|---|
| Last hit when the creep's health drops under one hit; don't chase kills | cores | `last_hits` at 5:00 and 10:00 (`last-hitting.md`) |
| Carry a Town Portal scroll | everyone | no `item_tpscroll` in the TP slot |
| Go back or use regen at low health instead of staying for one more creep | everyone | health under the low line (ROADMAP item 5) |
| Take the gold runes and the 6:00 power rune | supports and mid | clock (README rune timings) |
| Stack the nearest camp at :53 | supports | clock and hero near a camp |
| A death before 10:00 is usually from walking past the river without vision | everyone | death with clock under 10:00 |

## Mid game, 10:00 to 25:00

| What to say | Who | GSI signal |
|---|---|---|
| Farm the jungle camp between waves, don't walk around | cores | `last_hits` under the 10:00 pace |
| Farm on your side of the map; the far lanes are where you get caught alone | cores | death between 10:00 and 25:00 |
| After a won fight, take a tower or Roshan instead of farming | everyone | clock 20:00 (`[reminders.roshan]`) |
| Buy a Black King Bar or a save item before the next greedy item when disabled a lot | cores and supports | situational pick (`situational-items.md`) |
| Stay with your team when you are a support; buy wards and a Glimmer or Force Staff | supports | position 4 or 5 |
| Fragile ranged cores (Drow Ranger, Sniper, Lina, Shadow Fiend): stand behind your team and attack from max range | those heroes | hero name and a death |
| Heroes who farm alone too long (Nature's Prophet, Anti-Mage): join the next fight | those heroes | 15:00 and 25:00 check |

The last two rows come from `low-bracket-meta.md`: those heroes lose most at
low MMR because of position and fight-joining mistakes, not items.

## Late game, 25:00 and after

| What to say | Who | GSI signal |
|---|---|---|
| Keep gold for buyback before you fight | cores | `buyback_cost` and gold (death tip) |
| Never farm a side lane alone; one death now can lose the game | everyone | death after 25:00 |
| Go high ground only with your whole team, ideally with Aegis | everyone | clock and Aegis in inventory |
| Defend your base together; don't trade a Barracks for a far-lane farm | everyone | death after 25:00 |

## How the built-in death tips use this note

`STAGE_TIPS` in `coach/rules/death_tip.py` holds three lines for each stage
and role (supports are positions 4 and 5, or a support hero while the
position is unknown; the offlane gets the core lines), taken from the tables
above. `hero_tip` adds the position line for fragile ranged cores and the
join-fights line for lone farmers after the laning phase. The stat-based tips
(low last hits, buyback, dying often, no Town Portal) still come first, and
supports never hear the last-hit or buyback ones. No line repeats twice in a
row.
