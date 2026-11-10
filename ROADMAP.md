# Roadmap

The autonomous developer takes the top unchecked item each run (one pull
request per item) and ticks it off in the same PR. Reorder, add or delete
items freely: this list is how Castien steers the work. See VISION.md for why.

Every item must keep the README's fair-play rule: Valve Game State
Integration and public post-game data only, audio only, no memory or screen
reading at all. What GSI doesn't give, the coach asks the player.

Patch data (heroes, items, camps, runes, builds) is not a roadmap item: it is
refreshed only when Dota's live patch is newer than `coach/data/PATCH` (see
CLAUDE.md).

## Next up

1. [x] **Default builds for popular low-bracket heroes.** Only Luna has a build
   today. Add simple, forgiving builds for the heroes most picked from Herald
   to Ancient (for example Pudge, Sniper, Drow Ranger, Phantom Assassin,
   Wraith King, Juggernaut, Lion, Witch Doctor, Ogre Magi, Zeus, Bristleback,
   Legion Commander, Axe, Viper, Slark), checked against OpenDota's public
   per-bracket item data, plus a role-based `default` list. *Why:* most
   players will never edit `coach.toml`; the item reminder is useless
   without a build.
2. [x] **"Worth buying now" while saving.** When the next build item is far
   off and gold sits unspent, suggest one cheap item that helps any hero
   ("Buy a Magic Wand now, you'll get your Black King Bar later"), at most
   once per item a match. *Why:* low-bracket players carry unspent gold for
   minutes and lose it when they die (issue #12).
3. [x] **Post-game review: three things to fix.** After the match, speak
   (and save as a text file) three short points from the player's own
   recording: deaths and when, last hits at 10 minutes against a target for
   their role, slow big-item timings. *Why:* this is the "learn something
   every game" moment that justifies a subscription.
4. [x] **Last-hit pace check.** At 5 and 10 minutes, compare the player's
   last hits with a simple target (for example 35 at 10:00 for a core) and
   give one encouraging line. Supports skip it. *Why:* last hitting is the
   biggest farm gap in low brackets and GSI gives last hits directly.
5. [x] **"Don't fight, heal" after a near-death.** When health stays under
   the low-health line for a while without healing, suggest going back or
   using regen (salve, tango, fountain), naming regen the player owns.
   *Why:* dying is the number one habit to fix below Divine.
6. [x] **Death streak tip.** After two or three deaths close together, one
   calm line: farm safely, stay near towers, buy a Black King Bar or
   defensive item if it is on the build. *Why:* tilt and feeding are classic
   low-bracket losses; one sentence can stop the spiral.
7. [x] **Neutral item tier reminders.** Tell the player when each tier of
   neutral items starts dropping and remind them to pick one up from the
   stash. Timings from the live patch. *Why:* new players forget neutral
   items entirely.
8. [x] **Day/night and Roshan basics.** Say when night starts (vision is
   shorter) for the first few cycles, and give one reminder at a sensible
   minute that Roshan is worth taking after a won fight. Uses only the game
   clock and `daytime`. *Why:* objective play is what turns won fights into
   won games at low MMR.
9. [x] **Beginner and experienced modes.** One switch in `coach.toml` that
   sets how talkative the coach is. Beginner: all reminders, longer lines.
   Experienced: only gold, stacks, power rune and buyback. *Why:* the same
   app must suit a Herald and an Ancient without editing ten settings.
10. [x] **Don't talk over itself.** Give reminders a priority (low health
    beats runes) and drop low-priority lines when several land at once.
    *Why:* a coach that chatters gets turned off.
11. [x] **GSI health check on start.** If no GSI update arrives within a
    minute of starting, say and print what to check (launch option, config
    file path, firewall), then detect when Dota connects. *Why:* "it does
    nothing" is the top support problem for a paid app.
12. [x] **Strategy notes in `docs/strategy/`.** Short, sourced notes on low-
    bracket fundamentals and the heroes from item 1, used to make the
    coach's tips and builds accurate. *Why:* the coach is only as good as its
    advice. Done: `fundamentals.md` (what to say by stage and role, with the
    GSI signal) and `low-bracket-meta.md` (per-medal win rates, 7.41f).
13. [x] **Better built-in death tips.** Use the strategy notes to make the
    no-AI tips specific to role and game stage (laning, mid game, late), so
    players without a GPU still get good advice. *Why:* many low-bracket
    players have modest PCs and no API key. The tables in
    `docs/strategy/fundamentals.md` list the lines and their GSI signals,
    including position tips for fragile ranged cores (Drow Ranger, Lina,
    Shadow Fiend lose 41 to 48% at every medal, `low-bracket-meta.md`).
    Done in `coach/rules/death_tip.py` (`STAGE_TIPS`, `hero_tip`).
14. [x] **"What should I focus on now?"** A voice question, answered while
    alive with the same stage and role lines as the built-in death tips
    (`STAGE_TIPS`, `hero_tip` in `coach/rules/death_tip.py`), plus the
    stat-based ones (low last hits, no Town Portal). *Why:* Castien asked
    for it (2026-11-04); a beginner gets one clear priority without having
    to die first.
    Done: `BuiltinTips.focus` (low health first, lines worded for now, not
    "next life"), voice intent `focus` and typed `focus`, and said once
    unasked at 10:30 (`coach/rules/focus_check.py`, Castien OK'd 2026-11-04).
15. [x] **Builds for the next most-picked heroes.** Shadow Shaman,
    Windranger, Anti-Mage, Earthshaker, Necrophos, Crystal Maiden, Lina,
    Dragon Knight, Lifestealer, Phantom Lancer, Tidehunter, Lich and Sven are
    in the top 25 picks from Herald to Ancient (`low-bracket-meta.md`) but
    fall back to the role default. *Why:* a top-25 hero getting a generic
    "Power Treads, Black King Bar, Satanic" build looks broken to a buyer.
    Done: hand-written builds in `config/coach.toml`. Most of these heroes
    already got OpenDota's popular items, but those lists had gaps a beginner
    notices (Necrophos without boots, Lifestealer told to buy a bare Sange,
    Earthshaker on the generic support list). Owning Harpoon now counts as
    the build's Echo Sabre.
16. [x] **Suggest a break after a losing streak.** When the player's last
    three reviews in `reviews/` are losses, say one calm line at the next
    game start ("three losses in a row; a ten-minute break helps more than
    another queue"), at most once a day, switchable off. *Why:* tilt queuing
    is a classic low-bracket MMR drain, and climbing players name breaks
    between games as a top habit (`fundamentals.md`). Uses only the coach's
    own files.
    Done: said at the end of the third loss's review (`coach/review.py`),
    not at the next game start: once a match is found, a break means
    abandoning it. Losses are read back from the saved review files; games
    more than 90 minutes apart are separate sittings. `break_after_losses`
    under `[reminders.review]`.
17. [x] **Windows installer prototype.** Build a single `.exe` with
    PyInstaller and a GitHub Actions job that produces it as an artifact, so
    nobody needs Python or Git. No signing or auto-update yet. *Why:* the
    current command-line setup loses most buyers before their first game.
    Done: `packaging/build_exe.py` and the "windows app" workflow build a
    `DotaCoach` folder (a folder, not one `.exe`, so it starts fast with the
    speech packages) with "Set up Dota 2.bat".
18. [x] **First-run setup in plain words.** `py -m coach` (and the future
    installer) runs install automatically when the GSI config is missing,
    tests the voice, and tells the player exactly what to do next.
    *Why:* onboarding decides whether a trial turns into a subscription.
19. [x] **Simple settings window.** A small local window (tkinter, no
    server) to toggle reminders, pick the voice and mode, and edit the build
    for the current hero. *Why:* paying users expect not to edit TOML.
    Done: `py -m coach settings` ("Coach settings.bat" in the app),
    `coach/settings.py` and `coach/settings_window.py`. It opens on the hero
    of the last recording and saves only what differs from the defaults.

20. [x] **Hand-written builds for the next most-picked heroes.** Take the
    most-picked heroes from Herald to Ancient that still use OpenDota's
    popular-items fallback (pick counts in `coach/data/hero_stats.json`
    once it is bundled, otherwise `low-bracket-meta.md`) and write a
    forgiving build for each, about a dozen per PR. *Why:* the fallback
    lists can skip boots (Necrophos started with Radiance) or name bare
    components; Castien chose hand-written builds over patching the
    fallback (2026-11-04).
    Done for the 12 most-picked heroes still on the fallback (Rubick,
    Invoker, Techies, Skywrath Mage, Outworld Destroyer, Undying, Hoodwink,
    Magnus, Silencer, Spectre, Vengeful Spirit with a pos 1 version, Nature's
    Prophet), ranked by Herald-to-Ancient picks in the week-old
    `hero_stats.json` from PR #82. A test now checks every bundled build
    starts with boots. Next batch: item 21.
21. [x] **Builds for the batch after that.** The 12 most-picked heroes from
    Herald to Ancient still on the fallback after item 20. *Why:* same as
    item 20; these heroes are each in 3 to 4% of low-bracket matches.
    Done: Shadow Fiend, Queen of Pain, Jakiro, Faceless Void, Snapfire,
    Venomancer, Ancient Apparition, Dawnbreaker, Disruptor, Ursa, Dark
    Willow and Slardar, ranked by Herald-to-Ancient picks in
    `hero_stats.json` (PR #82). Shadow Fiend and Queen of Pain, who lose
    more than they win at these medals, get Dragon Lance or a Black King Bar
    before more damage. Next batch: Razor, Riki, Grimstroke, Night Stalker
    and the heroes after them: item 22.
22. [x] **Builds for the third batch.** The next 12 most-picked heroes from
    Herald to Ancient still on the fallback. *Why:* same as item 20.
    Done: Razor, Riki, Grimstroke, Night Stalker, Warlock, Timbersaw,
    Weaver, Dazzle, Winter Wyvern, Tinker, Storm Spirit and Ember Spirit,
    ranked by Herald-to-Ancient picks in `hero_stats.json` (PR #82) and
    checked against `item_popularity.json`. The five that lose more than
    they win at these medals (Timbersaw, Weaver, Tinker, Storm Spirit, Ember
    Spirit, 44 to 49%) get Dragon Lance, Blink Dagger or a Black King Bar
    before late damage. Next batch: Centaur Warrunner, Templar Assassin,
    Arc Warden, Monkey King and the heroes after them.

## Ideas to look at later

- Done: "How did I do today?" (voice, or typed `today`): today's record
  from the saved reviews, the point that came up most with one thing to try
  next game, and a good-game-to-stop-on or short-break line
  (`review.day_summary`, backed by `docs/strategy/fundamentals.md`, "Don't
  chain-queue after losses"). Also done: the review of a win that makes
  three or more games today ends with "a good game to stop on if you're
  tired", once a day (`stop_after_games`). Next: when the player keeps
  playing after that line and loses two in a row, the break line could
  remind them they were ahead for the day.
- App follow-ups to item 17: publish the app folder as a zip on a GitHub
  Release when a version is tagged (artifact downloads need a GitHub login
  and expire after 30 days); say `DotaCoach.exe install` instead of
  `py -m coach install` in the coach's own hints when it runs as the app;
  check the app with Windows Defender and SmartScreen on a clean PC, since
  an unsigned app gets a warning (signing is a cost: see Castien's section).
- Voice questions (issue #9): the ahead/behind verdict ("how am I doing?")
  is done in the `agent/ahead-or-behind` PR, and "what should I buy?" with
  counters from the known enemy lineup in the `agent/situational-items` PR.
  The unasked 15:00 and 25:00 check names the counter too. Next, optional
  LLM phrasing (step 4). The coach also says the verdict
  unasked at 15 and 25 minutes. Next, tune the time ramp in
  `docs/strategy/ahead-or-behind.md` from real recordings. More
  questions that fit the current answers: "when should I stack?", "how many
  last hits should I have?" (once item 4 has targets).
- Pick the "worth buying now" item from the known enemy lineup (the
  start-of-game answers or typed picks, issue #16): Magic Wand against spell spammers, Infused Raindrops against
  magic nukers, Wind Lace or boots when the build has none yet.

- Last-hit pace, next steps (item 4 is done in `coach/rules/last_hits.py`):
  count denies too ("and 6 denies, nice") once the coach knows the lane
  matchup. Comparing with last game is done (the 10:00 line and the review's
  opening line); next, a trend over the last five games ("your last hits
  at 10 minutes went from 15 to 28 this week").
- Skill build reminders per hero (for example "max your first spell"),
  from public data.
- Spoken item timing goals per hero ("aim for Battle Fury by 15 minutes").
- A weekly progress summary from the player's own recordings (deaths per
  game falling, last hits rising). The post-game review (item 3) already
  writes one text file per match in `reviews/`; the summary can compare them.
- Post-game review, next steps: name the hero the player died to most when
  they told the coach (in-match answers), compare item timings with the
  hero's public popular-item timings instead of one 20-minute rule. Saying
  whether the player fixed last game's first point is done
  (`reviews/last.json`, Castien asked for it on 2026-10-31). Also save (not speak) the review when the player abandons and GSI goes
  silent before post-game, using the health watch.
- Neutral items, next steps (item 7 is done in `coach/rules/timers.py`):
  once the coach knows the player has no neutral item a few minutes after a
  tier opens (GSI's `neutral0` slot is empty), one nudge to go craft it; and
  in Turbo, halve the tier times automatically from GSI's game mode.
- First-run setup, next steps (item 18 is done in `coach/first_run.py`):
  the packaged app (item 17) runs it too, but its printed steps still say
  `py -m coach install`: say `DotaCoach.exe install` there. Once the
  settings window (item 19) exists, show the numbered steps there with a
  "test the voice again" button.
- Built-in death tips, next steps (item 13 is done): when the player told
  the coach their lane was lost, a laning-phase line about playing for
  experience under their tower (the "what should I focus on now?" answer is item
  14).
- Modes, next steps (item 9 is done: `[coach] mode` in `coach.toml`): a
  longer, explaining first-time version of each line in beginner mode
  ("Power rune in 15 seconds. Mid should check it: it can win the lane"),
  said the first one or two times a match only; and a voice switch ("hey
  coach, quiet mode") once the settings window (item 19) exists.
- Translations of the spoken lines.
- "What hero should I learn?": answer with two or three forgiving heroes
  for the player's role that win at their own medal (Wraith King, Dragon
  Knight, Witch Doctor, Crystal Maiden in 7.41f, `low-bracket-meta.md`),
  from `coach/data/hero_stats.json` once PR #70's refresh has run.
- Done: hero-aware 15:00 and 25:00 check. Nature's Prophet (43 to 46% at
  every medal), and Anti-Mage from 25:00, hear "group up with your team and
  join the next fight" instead of a farm line when even or behind, in the
  check and in "how am I doing?" (`LONE_FARMERS` in `coach/benchmarks.py`).
  Next: other heroes whose win rate falls when they farm alone, picked from
  the per-medal numbers in `coach/data/brackets.json`; and for a core who
  told the coach "we're losing fights", say to fight together near a tower
  rather than farm.
- Upgrade-aware builds: know that Dragon Lance went into Hurricane Pike (from
  dotaconstants' item components) so builds can list both steps.
- Questions during the match (issue #11 step 3): done in the
  `agent/game-questions` PR (lane, trouble hero, enemy carry, fights, at calm
  moments). Next, step 4: feed the answers into "what should I buy?", the
  15/25 minute check and death tips. Later maybe "Is Roshan down?" once a
  Roshan reminder exists (item 8).
- Per-position builds and reminders (issue #11): done in the
  `agent/position-builds` PR (`hero_posN` / `posN` builds, a `positions` list
  on any reminder). Next: support-only lines the coach can back with GSI,
  e.g. "buy a sentry" when a pos 4/5 holds no wards at a rune or shrine
  time, and core-only last-hit pace (item 4) once the position is known.
- Bundled per-position builds for heroes often played in two roles at low
  MMR (Pudge mid or support, Zeus mid or support), checked against public
  per-bracket item data.
- Learn the player's usual position per hero from their answers, so after a
  few games the coach only confirms it ("Pudge, position 4 again?").
- Check the default builds against OpenDota's public per-bracket item data
  (Herald to Ancient) once the coach's build tooling can reach it.

- Settings window, next steps (item 19 is done): the voice-question
  switches (`[listen]`: hey coach, start questions, questions during the
  match), the player's rank and usual position, and per-position builds
  (`hero_pos4`); a "Settings" line in the coach's own console and the
  first-run steps; and opening it without the console window in the app
  (a second, windowed exe).

## Needs Castien's decision

These are not built until Castien decides. Recommendations in italics.

- **Price and payments: decided** (Castien, 2026-11-06). $2.50 a month or
  $25 a year, sold through Lemon Squeezy's hosted store (no website yet),
  with a Lemon Squeezy licence key unlocking the app. Plan and setup steps:
  `docs/product/paid-app.md`. Still open: a free trial or free tier.
- **Code signing certificate** (yearly cost) so Windows does not warn on
  install. *Recommend before any public sale.*
- **Auto-update and hosting** for patch data and builds. *Recommend GitHub
  Releases first: free, no server.*
- **OpenDota for a commercial product.** Confirm the API terms and whether to
  buy the premium tier. *Recommend asking OpenDota before launch.*
- **Claude tips in the paid product.** Our own key would need a server and
  accounts. *Recommend keeping Claude as "bring your own key" and making
  built-in tips strong.*
- **Telemetry or crash reports.** None today. *Recommend opt-in crash reports
  only, if ever.*
- **Product name and Valve content.** "Dota 2" and hero art are Valve's.
  *Recommend a name like "<name> for Dota 2" and checking Valve's terms.*

## Not building (fair-play rule)

- Anything about enemy positions, cooldowns, items or profiles that the
  player cannot see. GSI does not give it and looking it up would break the
  rule.
- Overlays or anything drawn over the game.
- Reading the minimap or any part of the screen. The top-bar draft reader
  was removed (Castien, 2026-10-28, issue #11): the coach asks instead.
- Sending keys or clicks to the game.
