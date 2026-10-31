# Neutral item tiers

Backs the neutral item reminder (`NeutralTierReminder` in
`coach/rules/timers.py`, ROADMAP item 7). Uses only the game clock.

## How neutral items work now

Neutral items are no longer dropped or bought. Cleared jungle camps drop
Madstone (2 to the hero who kills a regular camp and 1 to a random ally;
large camps give 3 and 2). When you have enough Madstone for the next tier,
a sound plays and the Madstone counter in the HUD flashes; clicking it shows
four artifacts (an active or passive item) and four enchantments (passive
stats) to pick from. A new tier replaces the old item, and tiers are crafted
in order.

How much Madstone you can hold is capped by game time, which is what makes
each tier "open":

| Tier | Opens (normal) | Turbo |
|---|---|---|
| 1 | 5:00 | 2:30 |
| 2 | 15:00 | 7:30 |
| 3 | 25:00 | 12:30 |
| 4 | 35:00 | 17:30 |
| 5 | 60:00 | 30:00 |

Source: [Liquipedia, Neutral Item](https://liquipedia.net/dota2/Neutral_Item)
(checked 2026-10-31 for patch 7.41). Liquipedia's own page disagrees on the
tier 1 cost (5 or 6 Madstone), so the coach never names a cost.

## What a beginner should hear

- New players miss the system entirely: the counter is small and the sound
  is easy to lose in a fight. So at 5:00 the coach explains it once in one
  sentence: clear camps for Madstone, click the flashing counter, pick one.
- At later tiers a reminder to upgrade is enough; the same counter is used.
- Supports get Madstone too (the ally share), so the reminder is for every
  position.
- GSI does not give the Madstone count, so the coach can't say "you have
  enough now". It only says when a tier opens.
