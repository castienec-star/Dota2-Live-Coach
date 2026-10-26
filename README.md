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
built-in voice:

| Reminder | Default timing |
| --- | --- |
| Power rune | 15 s before 6:00, then every 2 minutes |
| Bounty runes | 15 s before 3:00, then every 3 minutes |
| Wisdom runes | 20 s before 7:00, then every 7 minutes |
| Water rune | 10 s before 2:00 and 4:00 |
| Stack the camp | at :53 each minute, until 11:53 |

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
