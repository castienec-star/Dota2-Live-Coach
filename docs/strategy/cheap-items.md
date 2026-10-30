# Cheap items against the enemy lineup

Backs the "worth buying now" reminder (`WorthBuying` and `CHEAP_COUNTERS` in
`coach/rules/hero.py`, issue #16). The enemy lineup is only what the player
told the coach (start-of-game questions or typed picks); the coach never
looks it up.

## Why it matters at low MMR

Herald to Ancient players buy the same starting items every game and carry
unspent gold for minutes. A 225 to 460 gold item bought for the right lane
opponent often decides the lane: a Magic Wand full of charges against a
spell spammer, or Raindrops that soak a nuker's burst. It costs little, so
it never delays the big item (the reminder only fires while the next build
item is still 600+ gold away).

## The table

| Enemy heroes that... | Item | Why |
|---|---|---|
| do a lot of magic damage early: Lina, Lion, Zeus, Leshrac, Skywrath Mage, Queen of Pain, Tinker, Shadow Fiend | Infused Raindrops (225) | Blocks 120 magic damage from each instance of 75 or more, 6 charges, plus mana regen. Sold from 3:00, so it is not suggested earlier. |
| cast a lot of spells: Bristleback, Skywrath Mage, Batrider, Zeus, Timbersaw, Leshrac, Venomancer, Storm Spirit, Queen of Pain, Tinker | Magic Wand (460) | One charge per visible enemy spell within 1200 range, up to 20; each charge heals 15 health and 15 mana, used all at once. Spammers fill it in a few minutes. |

One enemy hero is enough, because both items are cheap and each is
suggested at most once a match. The counter is checked before the usual
Magic Wand and Bracer / Wraith Band / Null Talisman, and the line names the
heroes: "Buy Infused Raindrops now: Lina and Lion do a lot of magic damage."
Without a told lineup, or with no hero from the table, the reminder is the
same as before.

Not added (yet): Wind Lace or Boots against chasing heroes, Orb of Venom,
and Blight Stone. They depend much more on the player's hero and role than
on the enemy, so they fit the build lists better than this table.

## Sources

- Infused Raindrops: https://liquipedia.net/dota2/Infused_Raindrops
  (cost, 120 block over a 75 threshold, 6 charges, from 3:00), checked
  2026-10-30 against patch 7.41.
- Magic Wand: https://liquipedia.net/dota2/Magic_Wand (460 gold since 7.40,
  1200 radius, 20 charges, 15 health and mana per charge), checked
  2026-10-30.
- Heroes in the magic damage row are the same nukers as the "magic damage"
  threat in [situational-items.md](situational-items.md); the spell spam
  row is the issue #16 list plus heroes whose main damage is low-cooldown
  spells.
