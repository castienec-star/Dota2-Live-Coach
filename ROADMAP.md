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
3. [ ] **Post-game review: three things to fix.** After the match, speak
   (and save as a text file) three short points from the player's own
   recording: deaths and when, last hits at 10 minutes against a target for
   their role, slow big-item timings. *Why:* this is the "learn something
   every game" moment that justifies a subscription.
4. [ ] **Last-hit pace check.** At 5 and 10 minutes, compare the player's
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
7. [ ] **Neutral item tier reminders.** Tell the player when each tier of
   neutral items starts dropping and remind them to pick one up from the
   stash. Timings from the live patch. *Why:* new players forget neutral
   items entirely.
8. [ ] **Day/night and Roshan basics.** Say when night starts (vision is
   shorter) for the first few cycles, and give one reminder at a sensible
   minute that Roshan is worth taking after a won fight. Uses only the game
   clock and `daytime`. *Why:* objective play is what turns won fights into
   won games at low MMR.
9. [ ] **Beginner and experienced modes.** One switch in `coach.toml` that
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
12. [ ] **Strategy notes in `docs/strategy/`.** Short, sourced notes on low-
    bracket fundamentals and the heroes from item 1, used to make the
    coach's tips and builds accurate. *Why:* the coach is only as good as its
    advice.
13. [ ] **Better built-in death tips.** Use the strategy notes to make the
    no-AI tips specific to role and game stage (laning, mid game, late), so
    players without a GPU still get good advice. *Why:* many low-bracket
    players have modest PCs and no API key.
14. [ ] **Windows installer prototype.** Build a single `.exe` with
    PyInstaller and a GitHub Actions job that produces it as an artifact, so
    nobody needs Python or Git. No signing or auto-update yet. *Why:* the
    current command-line setup loses most buyers before their first game.
15. [ ] **First-run setup in plain words.** `py -m coach` (and the future
    installer) runs install automatically when the GSI config is missing,
    tests the voice, and tells the player exactly what to do next.
    *Why:* onboarding decides whether a trial turns into a subscription.
16. [ ] **Simple settings window.** A small local window (tkinter, no
    server) to toggle reminders, pick the voice and mode, and edit the build
    for the current hero. *Why:* paying users expect not to edit TOML.

## Ideas to look at later

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

- Skill build reminders per hero (for example "max your first spell"),
  from public data.
- Spoken item timing goals per hero ("aim for Battle Fury by 15 minutes").
- A weekly progress summary from the player's own recordings (deaths per
  game falling, last hits rising).
- Translations of the spoken lines.
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

## Needs Castien's decision

These are not built until Castien decides. Recommendations in italics.

- **Price, free tier and trial.** *Recommend about $4/month with a 14-day
  trial, or clock reminders free and coaching paid.*
- **Licensing and payments.** *Recommend a licence key sold through a
  merchant-of-record store (Lemon Squeezy or Paddle handle tax), checked
  offline with a grace period; no accounts at first.*
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
