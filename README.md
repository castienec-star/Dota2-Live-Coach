# Dota 2 Live Coach

A Windows app that listens to your own Dota 2 game and speaks short coaching
reminders aloud, then reviews the match afterwards.

## Fair-play rule

The coach only tells you things you could already see or work out yourself.

- Data comes only from Valve's official Game State Integration (your own hero
  and the game clock) and public post-game match data.
- Output is audio only. Nothing is drawn over the game.
- It never reads game memory, edits game files, sends input, or looks up
  other players' profiles.
- It never looks at your screen. What it can't get from GSI (your position,
  the other heroes in the match), it asks you out loud or lets you type.
- Voice questions (on by default, once installed): your microphone is only heard by speech
  models running on your PC. Nothing is recorded or sent anywhere.

## Setup (Windows)

Requires Python 3.12 or newer from [python.org](https://www.python.org/downloads/windows/),
which also installs the `py` launcher. Use `py` rather than `python`: on many
PCs `python` opens the Microsoft Store instead.

Install Git once (then open a new Command Prompt so it is found):

```
winget install --id Git.Git -e
```

Then, in Command Prompt. The `cd` matters: `py -m pip install` must run
inside the downloaded folder. `[voice]` adds the speech models the coach
uses to ask and answer questions out loud.

```
git clone https://github.com/castienec-star/Dota2-Live-Coach.git
cd Dota2-Live-Coach
py -m pip install -e ".[voice]"
py -m coach install
```

No Git? Click **Code > Download ZIP** on GitHub, unzip it, then `cd` into the
unzipped folder before running `py -m pip install -e ".[voice]"`.

`install` finds Dota 2 through Steam and writes
`gamestate_integration_coach.cfg` into
`dota 2 beta\game\dota\cfg\gamestate_integration\`. If it cannot find Dota,
pass the folder: `py -m coach install --dota-path "D:\SteamLibrary\steamapps\common\dota 2 beta"`.

Then in Steam, right-click Dota 2 > Properties > Launch Options and add
`-gamestateintegration`.

## Update

New features only reach you once you update. Close the coach window, then
double-click `update.bat` in the coach folder (or run it in Command Prompt).
It downloads the newest version and installs the voice packages. Then start
the coach again.

When the coach starts, its first line says which version it is, e.g.
`Dota 2 Live Coach, version from 2026-10-29 01:40 (b944970)`. If it also says
`Voice questions are OFF`, the voice packages are missing: run `update.bat`
again. If you copied `coach.toml` to `%APPDATA%\Dota2LiveCoach\` from an
older version, your copy overrides the new defaults: delete the lines you
didn't change on purpose (for example `enabled = false` under `[listen]`).

## Run

```
py -m coach
```

Start a match (a bot match works). The console logs your hero's state every
10 seconds, and each match is recorded to
`%APPDATA%\Dota2LiveCoach\recordings\` as a `.jsonl` file.

If Dota sends nothing for a minute after the coach starts, the coach says so
and prints what to check: whether the GSI config file is there and up to date
(if not, run `py -m coach install` again), the `-gamestateintegration` launch
option, restarting Dota after installing, and the port. When Dota connects
after that, it tells you.

## Voice reminders

Once the horn sounds, the coach speaks clock reminders through Windows'
built-in voice. Defaults follow patch 7.41:

| Reminder | Default timing |
| --- | --- |
| Power rune | 15 s before 6:00, then every 2 minutes |
| Gold (bounty) runes | 15 s before 4:00, then every 4 minutes |
| Wisdom shrines | 20 s before 7:00, then every 7 minutes |
| Water rune | 10 s before 2:00 and 4:00 (mid only, once your position is known) |
| Stack the camp | at :53 each minute until 11:53, only when your hero is near a neutral camp |

"Near a camp" uses your own hero's position and the fixed 7.41 camp spots
(see `THIRD_PARTY_NOTICES.md`). Game State Integration does not say whether a
camp is alive, already stacked or blocked, so the coach cannot check that.

### Your hero

| Reminder | When |
| --- | --- |
| You have gold for (item) | You can afford the next item on your build list |
| Buy a (cheap item) now, you'll get your (item) later | Before 25:00, you are still 600+ gold short of the next build item (boots included) and you can afford a Magic Wand or your hero's Bracer, Wraith Band or Null Talisman that you don't own. Each one at most once a match |
| You're ahead / about even / behind for (minutes) ... | At 15:00 and 25:00, your gold, experience and last hits per minute against public numbers for your hero, with what to do about it (see "How am I doing?" below). If you told the coach the enemy heroes and one calls for a counter, it names that item and why (see "What should I buy?"). Change the minutes in `[reminders.game_check]` |
| Low health, back off | Health drops under 25% (again after you heal over 40%) |
| Under buyback gold | After 30:00, your gold drops under the buyback cost |
| Skill point unused | 10 s after a level-up you haven't spent (up to level 16) |
| Use your wand | Hurt under 50% with a Magic Wand/Stick of 10+ charges |
| Place your observer ward | An observer ward has sat in your inventory for 60 s |

Item builds are per hero in the `[builds]` section of `coach.toml`, for
example `luna = ["Power Treads", "Manta Style", "Black King Bar"]`. The coach
comes with simple builds for heroes popular from Herald to Ancient (Axe,
Bristleback, Drow Ranger, Juggernaut, Legion Commander, Lion, Luna, Ogre Magi,
Phantom Assassin, Pudge, Slark, Sniper, Viper, Witch Doctor, Wraith King and
Zeus). Any other hero gets a support build in positions 4 and 5, otherwise a
core build (`default_support` and `default`); while your position isn't known,
it goes by the hero's usual role. Builds can also depend on your position:
`pudge_pos2 = [...]` is Pudge's build when you play mid, and `pos3 = [...]` is
for any hero without its own list when you play offlane. Put `pudge = []` in
your own `coach.toml` to turn the reminder off for one hero.

Any reminder can be limited to some positions, e.g. `positions = [4, 5]` under
`[reminders.stack]`. Out of the box only the water rune reminder is (mid only).
The position is the one you said or typed at the start of the game, or the one
set in `[pregame]`; until it is known, every reminder is said. Prices come from OpenDota's
item data; `coach/data/PATCH` names the patch the bundled data is current for
(7.41f).

### Death-timer tips

When you die with at least 10 seconds to wait, the coach speaks one short tip
for your next life, if it is ready before you respawn. The tip is based only on
your own hero's stats and items, plus what you answered to the coach's
questions this match (for example "find Pudge on the minimap before you
fight" after you said Pudge gives you trouble). The coach never looks up
anything about enemies.

Tips also look at your own last 15 seconds alive: a save or escape item that
was ready (Black King Bar, Shadow Blade, Blink Dagger, Force Staff, Glimmer
Cape...), an ultimate off cooldown, a wand with 10 or more charges, or a spell
you cast under 35% health just before dying. "You died with your Shadow Blade
ready. Press it as soon as the fight turns." beats a general tip, and the model
gets the same facts.

Choose where tips come from with `provider` in `[reminders.death_tip]`:

| Provider | Cost | Needs |
| --- | --- | --- |
| `ollama` (default) | Free | [Ollama](https://ollama.com) running on your PC with a model pulled |
| `claude` | About a cent per tip | A Claude API key in `ANTHROPIC_API_KEY` |
| `builtin` | Free | Nothing; written tips based on your stats |

If the model is not running or takes longer than `timeout` seconds, the coach
falls back to a built-in tip, so you always get one.

**Free local tips with Ollama (Windows):**

```
winget install --id Ollama.Ollama -e
ollama pull llama3.1:8b
```

Ollama then runs in the background (tray icon) and starts with Windows. The
8B model needs about 5 GB of GPU memory and only works for a moment at each
death. Check it with `ollama run llama3.1:8b "say hi"`. To use another model,
pull it and set `ollama_model`.

**Claude instead:** set `provider = "claude"` and your key, then open a new
Command Prompt:

```
setx ANTHROPIC_API_KEY "sk-ant-..."
```

### Pre-game briefing

In the countdown before the horn, the coach speaks a short briefing: what your
lineup is good and bad at, which enemy hero to watch, and when each team is
strongest. When those stretches begin in the game, it reminds you ("Your
team's strongest stretch starts now...").

It uses:

- **The draft and your position**, which you tell the coach. Once picks are
  done (strategy time, or right after the horn if you started the coach
  late), it asks out loud, with no wake word needed: "What position are you
  playing, one to five?", "Who's on your team?" and "Who are the enemy
  heroes?". Answer after the beep, all in one go ("Anti-Mage, Crystal Maiden,
  Lion, Pudge, Shadow Fiend") or a few at a time, or say "skip". Short names
  like "storm", "QoP" or "WR" work. It reads back what it understood
  ("Enemies: ... Right?"); fix a mistake with "no, Lina not Lion". The
  briefing waits for your answers.

  If the coach can't listen (no microphone, or the voice packages aren't
  installed), it asks the same questions in the coach window instead and
  tells you so out loud: type the answer and press Enter (Enter alone skips).
  Or type in the coach window at any time: `vs am cm lion pudge sf`
  for enemies, `with luna tide` for allies, `pos 4` for your position
  (`clear` starts over). To never be asked your position, set `position`
  under `[pregame]`, or per hero under `[pregame.positions]` (e.g.
  `pudge = 4`). To turn the questions off, set `start_questions = false`
  under `[listen]`. Your own hero is always known.
- **Short questions during the match** about what the game data can't show:
  "How did your lane go: won, even or lost?" around 10 minutes, then "Which
  enemy hero is giving you the most trouble?", "Is their carry farming
  freely?" and "Is your team ahead or behind in fights?". The coach only asks
  at a calm moment (while you wait to respawn, or when your hero is healthy
  and hasn't been hit for a while), never in a fight, at most one question
  every 5 minutes and each once a match. Answer in a word after the beep and
  it gives one line of advice ("Then group up with your team and go find
  their carry"); say nothing or "skip" and it lets it go. Your answers also
  steer "What should I buy?", the 15 and 25 minute check and death tips:
  the hero giving you trouble gets countered first, and losing fights or a
  free-farming enemy carry means a defensive item. Answers are forgotten
  after the match. Turn them off with `game_questions = false`, or
  space them out with `question_every`, under `[listen]`. See
  [docs/strategy/game-state-questions.md](docs/strategy/game-state-questions.md).
- **Public hero statistics** from [OpenDota](https://www.opendota.com): how
  each hero does against the others and by game length, like Dota Plus shows.
  They are saved on your PC and refreshed weekly.
- **Your own games**: after each match the coach learns from its recording
  (your deaths and when they happen, last hits at 10 minutes, item timings),
  plus your own public match history if "Expose Public Match Data" is on in
  Dota. This is how it learns your playstyle: the more you play, the more
  personal the briefing gets.
- **Ollama** turns those facts into the spoken briefing. Without it, a written
  briefing from the same facts is used. Small models like to make things up,
  so the coach checks what the model wrote before speaking it: a briefing
  that names a hero you didn't tell it about, uses a number that isn't in the
  facts, mentions a "jungler", or talks about teammates or enemies it knows
  nothing about is dropped (the coach window says why) and the written
  briefing is spoken instead. Until it knows at least some picks or has
  learned from your games, it doesn't ask the model at all. Death tips get the
  same hero check.

### Ask the coach out loud

Hands free, no window or key: say **"hey coach"**, wait for the beep, then
ask. For now the coach answers five questions from your own hero's data,
the game clock and the enemy heroes you told it:

- "How am I doing?" / "Am I ahead?": from 8 minutes on, whether you are
  ahead, even or behind for this point of the match, comparing your gold,
  experience and last hits per minute with public OpenDota numbers for your
  hero (supports only by experience), and what to do about it. Numbers for
  popular low-bracket heroes come with the coach; other heroes are read once
  from OpenDota if `opendota` is on in `[pregame]`. See
  [docs/strategy/ahead-or-behind.md](docs/strategy/ahead-or-behind.md).

- "What should I buy?": one item for right now, from how your game is going
  and the enemy heroes you named at the start of the game (or typed). A
  counter comes first, picked for your position: Monkey King Bar against
  Phantom Assassin, Dust or Sentries against invisible heroes, Black King
  Bar, Pipe or Glimmer Cape against a lot of magic damage, and so on; the
  hero you said gives you the most trouble is countered first. When you are
  behind, or told the coach your team is losing fights or their carry is
  farming freely, and nothing needs countering, a defensive item; otherwise
  the next item on your build. For example: "You're behind for 20 minutes.
  Get Black King Bar next, 1200 more gold: Lina and Lion do a lot of magic
  damage." See
  [docs/strategy/situational-items.md](docs/strategy/situational-items.md).
- "What's my next item?": the next item on your build and how much gold you
  still need.
- "Can I buy back?": the buyback cost against your gold, or its cooldown.
- "When is the next rune?": the next power rune, gold runes and wisdom
  shrines.

Anything else gets "I can't help with that yet". It is on by default and
needs two free speech models that run on your PC (downloaded once, about
200 MB). Install them once; until you do, the coach simply doesn't listen:

```
py -m pip install -e ".[voice]"
```

To turn it off, set `enabled = false` under `[listen]` in your `coach.toml`. A headset
helps so game sound and Discord don't wake the coach; it never listens while
it is talking itself. Change the wake word, the microphone, or use the
lighter `tiny.en` model there too.

Test the voice with `py -m coach say`. Pick another installed voice, change
the speed, or retime and turn off reminders in the `[voice]` and
`[reminders.*]` sections of `coach.toml`. Rune timings change between
patches, so check them after a big update.

Replay a recording without Dota:

```
py -m coach replay "%APPDATA%\Dota2LiveCoach\recordings\<file>.jsonl" --speed 1
```

`--speed 1` speaks the reminders in real time; without it the replay runs
instantly and prints them instead.

Settings live in `config/coach.toml`; copy it to
`%APPDATA%\Dota2LiveCoach\coach.toml` to override them.

## Development

```
py -m pip install -e ".[dev]"
py -m pytest
```

Where the project is heading: [VISION.md](VISION.md) (who it is for and the
path to a paid app) and [ROADMAP.md](ROADMAP.md) (what gets built next).
