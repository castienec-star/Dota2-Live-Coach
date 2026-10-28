# Notes for agents working on this repo

- Refresh hero, item, camp, rune and build data only when Dota's live patch
  (OpenDota `/api/constants/patch` or dota2.com/patches) is newer than
  `coach/data/PATCH`, then update that file in the same PR. Never add data
  refreshes to ROADMAP.md.
- Keep the README's fair-play rule: Valve Game State Integration and public
  post-game data only, audio only, no memory or screen reading (except the
  opt-in top-bar draft reader).
