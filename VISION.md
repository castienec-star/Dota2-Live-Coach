# Vision

Dota 2 Live Coach is a voice coach for new and lower-bracket players. It sits
in your ear during a match, reminds you of the habits that win games below
Divine, and helps you learn from each match afterwards. The goal is to sell it
as a small monthly subscription.

## Who it is for

Players from **Herald to Ancient**: people in their first few hundred games,
returning players, and players stuck in a bracket who know the heroes but not
the habits.

What holds these players back is rarely mechanics or draft theory. It is the
basics, repeated every game:

- **Dying too much.** Deaths are the biggest gap between brackets. Low
  players fight at low health, walk into fog alone and buy back for nothing.
- **Farming badly.** Missing last hits, standing in lane with full gold and no
  plan, never stacking or farming the jungle between waves.
- **Forgetting the clock.** Runes, wisdom shrines, stacks, day and night,
  Roshan, the neutral item tiers. Higher players track these without thinking.
- **Item builds that don't fit.** Buying what feels good, late core items, no
  Black King Bar against disables, no detection, no wards bought or placed.
- **No plan for the game.** Not knowing when their lineup is strong, so they
  fight when they should farm and farm when they should push.
- **Too much information.** Guides and videos are long. In the game there is
  no time to read anything.

## What it does for them

Short spoken lines at the right moment, based only on what the player could
see themselves:

- Clock reminders: runes, shrines, stacks (only when near a camp).
- Their own hero: gold for the next item, low health, unspent skill point,
  use the wand, place the ward, buyback gold.
- A pre-game briefing from the draft: what the lineup is good at, the enemy
  to watch, when each team is strongest, and reminders when those stretches
  start.
- A tip while waiting to respawn.
- Learning from the player's own recordings, so advice becomes personal.

Planned (see ROADMAP.md): a post-game review with three things to fix next
game, fundamentals coaching such as last-hit pace and "don't fight at low
health", sensible default builds for the heroes low-bracket players pick most,
and an easy installer with a settings window.

## Why pay for it, when free tools exist

| Tool | What it does | Where we differ |
| --- | --- | --- |
| **Dota Plus** (Valve, about $4/month) | Hero guides, item and skill suggestions shown in game, hero leveling, post-game stats | Visual and passive: the player has to look and read. We speak, at the moment it matters, and focus on habits, not cosmetics or leveling. |
| **Overlay apps** (e.g. Overwolf-based) | Draft stats and item suggestions drawn over the game | Drawn over the game, and in 2022 Valve cracked down on overlay apps that showed players extra information about others. We are audio only and use only Valve's own Game State Integration, so there is nothing to ban. |
| **Stats sites** (OpenDota, STRATZ, Dotabuff) | Detailed numbers after the game | Great for analysts, overwhelming for a Herald. We turn a match into three plain things to fix. |
| **Guides and videos** | Deep knowledge | Long, and no use mid-game. We bring the key line into the game. |

The pitch: **"A coach in your ear that teaches the habits that win low-MMR
games, and that can never get you banned."** Trust is the product. The
fair-play rule in the README is not a limitation to work around; it is the
main selling point, and every feature has to keep it.

## Path to sellable

Rough order. Items marked (decision) need Castien before anyone builds them.

1. **Coaching worth paying for.** Post-game review, fundamentals reminders,
   good default builds for popular low-bracket heroes, accurate patch data.
   Players must notice the difference in their first three games.
2. **Easy install.** Today it needs Python, Git and the command line, which
   most target players will not do. Next: a one-file Windows installer (for
   example PyInstaller plus an Inno Setup installer) that also writes the GSI
   config and explains the launch option.
3. **Onboarding.** A first-run walkthrough that checks Dota is found, GSI is
   working ("start a bot match and you should hear me") and the voice is
   audible.
4. **Settings window.** Turn reminders on and off, pick the voice and volume,
   choose "beginner" or "experienced" mode, without editing `coach.toml`.
5. **Code signing** so Windows SmartScreen does not scare buyers away
   (decision: costs money every year).
6. **Accounts, licensing and subscription** (decision). Options range from a
   licence key sold through a store such as Lemon Squeezy, Paddle or Gumroad
   (they handle sales tax), to a full account system. A licence key checked
   offline with a grace period is the smallest step that works.
7. **Auto-update** so patch data and builds stay current without a reinstall
   (decision: needs somewhere to host updates).
8. **A landing page, a free trial and a refund policy** (decision).

## Data sources and terms that matter for selling

- **Valve Game State Integration** is Valve's official, supported way for
  third-party tools to read the player's own game state. Valve's rules for
  third-party tools still apply: anything that gives information the player
  could not see, or automates play, risks bans. We stay well inside them.
- **Valve's art and names.** Hero portraits, names and icons are Valve's
  intellectual property. Using them in a paid app should be checked against
  Valve's Dota 2 content terms before launch (the optional draft reader
  downloads Valve's official hero pictures at run time). Do not put Valve art
  in marketing material without checking.
- **The draft reader** captures the screen, which Valve has not approved. It
  must stay opt-in and clearly labelled "at your own risk", or be removed
  from the paid product. Typed picks always work without it.
- **OpenDota API.** The free tier needs no key but is limited (50,000 calls a
  month at the time of their 2018 announcement, plus a per-minute limit) and
  is meant for fair use. With many paying users each calling it from their
  own PC this is per user, so it probably holds, but we should cache well
  (we already refresh weekly) and confirm OpenDota's terms allow use inside a
  commercial product, or buy their premium tier (decision). Data from
  `dotaconstants` is MIT licensed (see THIRD_PARTY_NOTICES.md).
- **Claude API** death tips use the player's own API key today. A paid
  product cannot ship with our key inside it. Either keep it "bring your own
  key", default to the free local and built-in tips, or run a small server
  (decision).
- **Ollama and the local model** are free, but the model has its own licence
  (Llama 3.1 has a community licence with an acceptable-use policy) and needs
  a 5 GB download and a decent GPU. Built-in tips must stay good enough on
  their own for players without one.

## Open questions for Castien

1. **Price and trial.** Around $3 to $5 a month (Dota Plus is about $4)?
   Is there a free tier (for example clock reminders free, coaching paid)?
2. **Where to sell.** Own site with a payment provider, or a store such as
   Steam (likely hard for a tool), itch.io or Microsoft Store?
3. **Draft reader.** Keep it in the paid product as opt-in, or drop screen
   reading entirely so the "can't get you banned" promise is absolute?
4. **AI tips.** Built-in and Ollama only, or also offer Claude tips through a
   server we pay for (needs accounts and costs per tip)?
5. **Languages.** English first? Russian, Spanish and Portuguese speaking
   players are a large share of low brackets.
6. **Brand name.** "Dota 2" is Valve's trademark; a sold product probably
   needs its own name ("... for Dota 2").
