# Notes for agents working on this repo

- Refresh hero, item, camp, rune and build data only when Dota's live patch
  (OpenDota `/api/constants/patch` or dota2.com/patches) is newer than
  `coach/data/PATCH`, then update that file in the same PR (and rebuild
  `coach/data/knowledge.json` with `py -m coach.knowledge`). Never add data
  refreshes to ROADMAP.md.
- Keep the README's fair-play rule: Valve Game State Integration and public
  post-game data only, audio only, no memory or screen reading, ever. What
  GSI doesn't give (position, the other heroes), the coach asks the player.

## How to keep working (Castien, 2026-10-29)

- Keep developing without waiting for Castien. Work order: open issues
  labelled `agent` (an issue marked PRIORITY first), then the top unchecked
  ROADMAP.md item. Castien reviews and merges when available.
- **At most 8 open PRs since Castien's last review or merge.** Before opening
  a PR, count the open PRs created after Castien's most recent merge or
  review; at 8, stop opening PRs and wait (fixing your open PRs is fine).
- Before starting an item, check open PRs and branches so two sessions don't
  build the same thing. If an open PR touches the same files, build on its
  branch or wait for it.
- Keep your own PRs mergeable: merge `main` into the branch when it
  conflicts (never force-push), and answer every review comment with a fix
  or a reason.
- Speak through `Speaker.say(text, priority, max_delay)` priorities
  (`coach/speaker.py`) rather than adding new ways to queue lines.
- Run the tests with `python -m pytest -q` before every push.
