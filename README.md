# Dota 2 Live Coach

A Windows app that listens to your own Dota 2 game and speaks short coaching
reminders aloud, then reviews the match afterwards.

## Fair-play rule

The coach only tells you things you could already see or work out yourself.

- Data comes only from Valve's official Game State Integration (your own hero
  and the game clock) and public post-game match data.
- Output is audio only. Nothing is drawn over the game.
- It never captures the screen, reads game memory, edits game files, sends
  input, or looks up opponents.

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
| Low health, back off | Health drops under 25% (again after you heal over 40%) |
| Under buyback gold | After 30:00, your gold drops under the buyback cost |
| Skill point unused | 10 s after a level-up you haven't spent (up to level 16) |
| Use your wand | Hurt under 50% with a Magic Wand/Stick of 10+ charges |
| Place your observer ward | An observer ward has sat in your inventory for 60 s |

Item builds are per hero in the `[builds]` section of `coach.toml`, for
example `luna = ["Power Treads", "Manta Style", "Black King Bar"]`. Prices come
from a 7.41 snapshot of OpenDota's item data.

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
