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
- It does not look at your screen, with one exception you have to turn on
  yourself: reading the draft from the top bar (see below).
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

Then, in Command Prompt. The `cd` matters: `py -m pip install -e .` must run
inside the downloaded folder.

```
git clone https://github.com/castienec-star/Dota2-Live-Coach.git
cd Dota2-Live-Coach
py -m pip install -e .
py -m coach install
```

No Git? Click **Code > Download ZIP** on GitHub, unzip it, then `cd` into the
unzipped folder before running `py -m pip install -e .`.

`install` finds Dota 2 through Steam and writes
`gamestate_integration_coach.cfg` into
`dota 2 beta\game\dota\cfg\gamestate_integration\`. If it cannot find Dota,
pass the folder: `py -m coach install --dota-path "D:\SteamLibrary\steamapps\common\dota 2 beta"`.

Then in Steam, right-click Dota 2 > Properties > Launch Options and add
`-gamestateintegration`.

## Run

```
py -m coach
```

Start a match (a bot match works). The console logs your hero's state every
10 seconds, and each match is recorded to
`%APPDATA%\Dota2LiveCoach\recordings\` as a `.jsonl` file.

## Voice reminders

Once the horn sounds, the coach speaks clock reminders through Windows'
built-in voice. Defaults follow patch 7.41:

| Reminder | Default timing |
| --- | --- |
| Power rune | 15 s before 6:00, then every 2 minutes |
| Gold (bounty) runes | 15 s before 4:00, then every 4 minutes |
| Wisdom shrines | 20 s before 7:00, then every 7 minutes |
| Water rune | 10 s before 2:00 and 4:00 |
| Stack the camp | at :53 each minute until 11:53, only when your hero is near a neutral camp |

"Near a camp" uses your own hero's position and the fixed 7.41 camp spots
(see `THIRD_PARTY_NOTICES.md`). Game State Integration does not say whether a
camp is alive, already stacked or blocked, so the coach cannot check that.

### Your hero

| Reminder | When |
| --- | --- |
| You have gold for (item) | You can afford the next item on your build list |
| Buy a (cheap item) now, you'll get your (item) later | Before 25:00, the next build item is 1500+ gold away and you can afford a Magic Wand or your hero's Bracer, Wraith Band or Null Talisman that you don't own. Each one at most once a match |
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
Zeus). Any other hero gets a support build if it is a support, otherwise a core
build (`default_support` and `default`). Put `pudge = []` in your own
`coach.toml` to turn the reminder off for one hero. Prices come from OpenDota's
item data; `coach/data/PATCH` names the patch the bundled data is current for
(7.41f).

### Death-timer tips

When you die with at least 10 seconds to wait, the coach speaks one short tip
for your next life, if it is ready before you respawn. The tip is based only on
your own hero's stats and items, nothing about enemies.

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

- **The draft**: the heroes you can see. Type them in the coach window at any
  time during the draft, e.g. `vs am cm lion pudge sf` for enemies and
  `with luna tide` for allies (`clear` starts over). Short names like `am`,
  `cm` and `qop` work. Your own hero is always known.
- **Public hero statistics** from [OpenDota](https://www.opendota.com): how
  each hero does against the others and by game length, like Dota Plus shows.
  They are saved on your PC and refreshed weekly.
- **Your own games**: after each match the coach learns from its recording
  (your deaths and when they happen, last hits at 10 minutes, item timings),
  plus your own public match history if "Expose Public Match Data" is on in
  Dota. This is how it learns your playstyle: the more you play, the more
  personal the briefing gets.
- **Ollama** turns those facts into the spoken briefing. Without it, a written
  briefing from the same facts is used.

**Reading the draft from the screen (optional, off by default).** Set
`enabled = true` under `[pregame.capture]` in your `coach.toml`. The coach
then takes one picture of a thin strip at the very top of your main monitor
just before the horn (once more if heroes are missing), matches the ten hero
portraits against Valve's official hero pictures, and throws the picture
away. Dota must run in borderless window mode. This never touches the game
itself, but Valve has not approved screen-reading tools, so use it at your
own risk. Typed picks always win over what the screen showed.

To check that the portraits line up on your screen, take a screenshot in a
game (F12 in Steam saves one) and run:

```
py -m coach draft-test "C:\path\to\screenshot.png"
```

It prints the ten heroes it reads and saves the boxes it looked in to
`%APPDATA%\Dota2LiveCoach\draft-test.png`. Adjust `top`, `height`, `width`,
`step` and `gap` in `[pregame.capture]` until the boxes sit on the portraits.

If a hero comes out wrong or as `?` (new hero art or a persona can look
different from Valve's picture), teach it from the same screenshot. Slots are
`r1`-`r5` for Radiant and `d1`-`d5` for Dire, left to right:

```
py -m coach draft-test "C:\path\to\screenshot.png" --teach d2="vengeful spirit"
```

The coach keeps that portrait and recognises the hero from then on.

### Ask the coach out loud

Hands free, no window or key: say **"hey coach"**, wait for the beep, then
ask. For now the coach answers three questions from your own hero's data and
the game clock:

- "What's my next item?" / "What should I buy?": the next item on your build
  and how much gold you still need.
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
