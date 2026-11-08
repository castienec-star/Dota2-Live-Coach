# Support basics for Herald to Ancient

Positions 4 and 5 are half of every team, and the coach's last-hit and
build lines mostly skip them. This note lists the support habits that win
low-bracket games and which ones the coach can back with the player's own
GSI data (clock, own hero position, own items, gold, health) and the
position the player told it. It can never see enemy wards, enemy heroes or
whether a camp is free.

## The habits

| Habit | Detail | Source |
|---|---|---|
| Keep wards up | Keep at least one, better two, observer wards on the map at all times; first ones at the river runes, later Roshan. Move them around so they last. | [DotaFire, "A full support guide"](https://www.dotafire.com/dota-2/guide/a-full-support-guide-beginner-to-intermediate-2094) (2014, still the standard advice) |
| Don't sit on wards | A ward in the bag sees nothing. The coach already says "Place your observer ward." after a minute (`WardReminder`). | same |
| Buy the stock | The shop restocks smoke about every 7 minutes, observers about every 2 minutes 15, sentries about every 70 seconds, up to 3, 4 and 10. A team that first buys smoke at 30:00 has wasted four. | [ONE Esports, "How to be a good support"](https://www.oneesports.gg/dota2/how-to-be-a-good-support-player-in-dota-2/) (2023; numbers may have moved since) |
| Dust and sentries against invisible heroes | Riki, Bounty Hunter, Clinkz, Weaver and the like: carry one. | DotaFire; `situational-items.md` already names them |
| Pull at :15 or :45 | Hit a neutral in the small camp near your lane at about :15 or :45 and walk back to the lane, so your creeps follow it. Pull when the lane has pushed past the middle, not while it sits at your tower. | DotaFire |
| Stack at :53 | Hit the camp at :50 to :53 and walk away so a second set spawns for your core. The coach already says it near a camp. | DotaFire; README "Stack the camp" |
| Block the enemy's camp | A hero, a creep or a sentry inside the spawn box at the minute stops the camp from spawning. | ONE Esports |
| Don't take your core's farm | Help your carry last hit and give them sure kills; take the last hit only when they can't. | DotaFire |
| Stay behind and with the team | Supports die first when focused; stay behind your cores, never walk the map alone, and come to every big fight. | DotaFire |
| Buy for the team | Wards, dust, a Glimmer Cape or Force Staff before damage items. | DotaFire; `fundamentals.md` |
| Take the lotus and runes | Lotus pools and bounty runes every 3 minutes, power runes from 6:00. In 7.41 the lotus pools moved closer to the offlane tier 1 towers. | [Sportskeeda, "5 support tips"](https://sportskeeda.com/esports/5-support-tips-tricks-dota-2-beginners); 7.41 notes in `objectives.md` |

## What the coach can say, and the signal

| Line | Who | GSI signal |
|---|---|---|
| "Pull the small camp now, then walk back to lane." | position 5 (or 4) only, laning phase | clock at about :13 and the hero within about 1000 of their own side's easy camp, like the stack reminder's camp check |
| "You have no ward: buy one and keep one up near the river." | positions 4 and 5 | no observer ward in the own inventory for a few minutes after 1:30 |
| "Carry a smoke for your team." | positions 4 and 5, from 10:00 | no `item_smoke_of_deceit` in the inventory at a 7-minute mark |
| "Stay with your team; you are the first one they hit." | supports | a death after 10:00 (the death tips already say a version of it) |

The pull line needs care: GSI does not say where the lane is, so the coach
cannot know whether the lane has pushed. Say it at most a few times early on,
in beginner mode only, and never twice in a row when the player did not move
toward the camp. The ward line must not fire when the player just placed
both wards: wait until the inventory has been empty of wards for a while.

## Why this matters for a paying player

Low-bracket supports often buy their own items first and no wards, so
both teams play blind and the side with any vision wins the fights. A
support player hears almost nothing from the coach today besides runes and
stacks; these lines give a pos 5 something every few minutes that actually
changes the game.
