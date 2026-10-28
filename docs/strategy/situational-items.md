# Situational items

Backs the "What should I buy?" voice answer (`coach/situational.py`, issue #9
step 3). The enemy lineup is only what the player told the coach at the
start of the game (or typed); the coach never looks it up, and never uses
enemy items, positions or net worth.

## Why it matters at low MMR

Herald to Ancient players mostly buy the same build every game. The items
that swing low-bracket games are the reactive ones: a Black King Bar against
a lineup of nukers and stunners, Dust or Sentries against an invisible hero
that keeps killing them, Monkey King Bar against Phantom Assassin. One
well-timed counter is worth more than the next greedy item.

## How the item is picked

1. **A counter to the enemy lineup**, checked in this order. The first one
   that has an item for the player's role and that they don't own yet wins.

   | Enemy heroes that... | Core (pos 1-2) | Offlane (pos 3) | Support (pos 4-5) | Needs |
   |---|---|---|---|---|
   | can turn invisible (Riki, Clinkz, Bounty Hunter, Weaver, Nyx, Mirana, Treant, Sand King) | Dust of Appearance | Dust of Appearance | Sentry Ward | 1 hero |
   | dodge attacks (Phantom Assassin, Windranger, Brewmaster) | Monkey King Bar | - | - | 1 hero |
   | make illusions (Phantom Lancer, Naga Siren, Chaos Knight, Terrorblade, Meepo) | Maelstrom | Maelstrom | - | 1 hero |
   | heal a lot (Huskar, Alchemist, Necrophos, Abaddon, Lifestealer, Oracle, Omniknight, Witch Doctor, Dazzle, Timbersaw) | Eye of Skadi | Spirit Vessel | Spirit Vessel | 1 hero |
   | do a lot of magic damage (Lina, Lion, Zeus, Leshrac, Skywrath, QoP, ...) | Black King Bar | Pipe of Insight | Glimmer Cape | 2 heroes |
   | have a lot of stuns (Lion, Shadow Shaman, Earthshaker, Tidehunter, ...) | Black King Bar | Black King Bar | Force Staff | 2 heroes |
   | hit hard with attacks (PA, Sven, Troll, Ursa, Slark, Juggernaut, ...) | - | Blade Mail | Ghost Scepter | 2 heroes |

   Magic damage, stuns and right-click need two heroes because almost every
   lineup has one; the specific counters need only one hero. Owning an
   upgrade counts (Mjollnir or Gleipnir covers Maelstrom, Hurricane Pike
   covers Force Staff, Ethereal Blade covers Ghost Scepter).
2. **Behind and nothing to counter**: a defensive item. Cores Black King Bar
   (offlaners then Blade Mail), supports Glimmer Cape then Force Staff. Same
   advice as the "you're behind" verdict in
   [ahead-or-behind.md](ahead-or-behind.md).
3. **Otherwise** (ahead or even): the next item on the player's build. Being
   ahead is the time to finish the farming or fighting item, not to buy
   another defensive one.

The verdict (ahead, even or behind) comes first in the spoken answer when it
is known (from 8:00, for heroes with benchmark numbers).

## Sources

- Item effects, patch 7.41: Liquipedia item pages, e.g.
  [Monkey King Bar](https://liquipedia.net/dota2/Monkey_King_Bar) (Pierce:
  80% chance for attacks to pierce evasion),
  [Black King Bar](https://liquipedia.net/dota2/Black_King_Bar) (spell
  immunity), [Pipe of Insight](https://liquipedia.net/dota2/Pipe_of_Insight)
  (team magic barrier), [Spirit Vessel](https://liquipedia.net/dota2/Spirit_Vessel)
  (reduces healing and regeneration),
  [Dust of Appearance](https://liquipedia.net/dota2/Dust_of_Appearance) and
  [Sentry Ward](https://liquipedia.net/dota2/Sentry_Ward) (reveal invisible
  units), [Maelstrom](https://liquipedia.net/dota2/Maelstrom) (chain
  lightning that clears illusions).
- Hero lists: each hero's own abilities (invisibility, evasion, illusions,
  heals, nukes, stuns) on Liquipedia, and OpenDota's hero roles (Nuker,
  Disabler, Carry) from the bundled `coach/data/heroes.json`.

## Known limits

- A short, hand-made list. Heroes not on it never trigger a counter; edit
  `THREATS` in `coach/situational.py` to add one.
- It doesn't know what the enemy has bought, so it can't say "they have
  Butterfly, buy MKB". That would need enemy items, which GSI doesn't give a
  player and the fair-play rule forbids looking up.
- The unasked 15:00 and 25:00 check still gives the general advice; naming
  the counter there too is a next step.
