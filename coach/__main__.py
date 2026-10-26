"""Command line entry point: py -m coach [run|install|replay|say|draft-test]."""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from pathlib import Path

from aiohttp import web

from . import config as config_mod
from . import pregame as pregame_mod
from .gsi_server import Coach, make_app
from .install import find_dota, install
from .recorder import MatchRecorder
from .replay import replay
from .rules import Engine, death_tip, hero, timers, windows
from .speaker import Speaker, make_backend


def make_speaker(cfg: config_mod.Config) -> Speaker:
    return Speaker(
        lambda: make_backend(cfg.voice_backend, cfg.voice_name, cfg.voice_rate),
        cfg.voice_max_delay,
    )


def make_coach(
    cfg: config_mod.Config,
    speaker: Speaker,
    recorder: MatchRecorder | None = None,
    summary_interval: float | None = None,
    tips: bool = True,
    capture: bool = False,
) -> Coach:
    """tips turns on the features that call a model; capture lets the pre-game
    briefing read the top bar, when coach.toml also turns that on."""
    if summary_interval is None:
        summary_interval = cfg.summary_interval
    coach = Coach(cfg.token, recorder, summary_interval)
    power_windows = windows.build(cfg.reminders)
    rules = (
        timers.build(cfg.reminders)
        + hero.build(cfg.reminders, cfg.builds)
        + power_windows
        + (death_tip.build(cfg.reminders, speaker.say) if tips else [])
    )
    coach.listeners.append(Engine(rules, speaker.say))
    if tips:
        coach.pregame = pregame_mod.build(
            cfg.pregame,
            speaker.say,
            power_windows[0] if power_windows else None,
            cfg.app_dir,
            cfg.record_dir,
            capture=capture,
        )
        if coach.pregame is not None:
            coach.listeners.append(coach.pregame)
    return coach


def read_typed_picks(coach: Coach) -> None:
    """Lets you type the draft in the coach window: "vs am cm lion pudge sf"."""
    for line in sys.stdin:
        reply = coach.pregame.typed(line)
        if reply:
            print(reply, flush=True)


def cmd_run(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    recorder = MatchRecorder(cfg.record_dir) if cfg.record else None
    speaker = make_speaker(cfg)
    coach = make_coach(cfg, speaker, recorder, capture=True)
    if coach.pregame is not None and sys.stdin is not None and sys.stdin.isatty():
        threading.Thread(target=read_typed_picks, args=(coach,), daemon=True).start()
        logging.info('Type the enemy picks any time, e.g.  vs am cm lion pudge sf')
    logging.info("Listening for Dota 2 on %s", cfg.url)
    try:
        web.run_app(make_app(coach), host=cfg.host, port=cfg.port, print=None, access_log=None)
    finally:
        if recorder is not None:
            recorder.close()
        speaker.close()
    return 0


def cmd_install(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    dota = args.dota_path or find_dota()
    if dota is None:
        logging.error("Could not find Dota 2. Pass its folder with --dota-path.")
        return 1
    target = install(cfg, dota)
    print(f"Wrote {target}")
    print("Last step: in Steam, right-click Dota 2 > Properties > Launch Options,")
    print("and add:  -gamestateintegration")
    return 0


def cmd_replay(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    # A fast replay would skip every spoken line as late, so it prints them
    # instead, and leaves out the state summaries.
    if args.speed > 0:
        speaker, summary_interval = make_speaker(cfg), None
    else:
        speaker, summary_interval = Speaker(), float("inf")
    # A fast replay skips model calls (tips, briefing): they would arrive too late.
    coach = make_coach(cfg, speaker, summary_interval=summary_interval, tips=args.speed > 0)
    count = replay(coach, args.recording, args.speed)
    speaker.close(timeout=30)
    print(f"Replayed {count} updates")
    return 0


def cmd_say(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    speaker = make_speaker(cfg)
    speaker.say(args.text)
    speaker.close(timeout=30)
    return 0


def cmd_draft_test(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    """Read the heroes from a saved screenshot, to check the top bar settings."""
    from PIL import ImageDraw

    from .capture import (
        Layout,
        PortraitMatcher,
        load_references,
        load_screenshot,
        load_taught,
        read_top_bar,
        teach,
    )
    from .heroes import HeroIndex

    index = HeroIndex()
    heroes = index.heroes
    settings = cfg.pregame.get("capture", {})
    layout = Layout.from_settings(settings)
    image, size = load_screenshot(args.screenshot)
    cache_dir = cfg.app_dir / "hero_images"
    slots = layout.slots(*size)
    for lesson in args.teach:
        slot, _, name = lesson.partition("=")
        slot = slot.strip().lower()
        hero = index.find(name)
        if len(slot) != 2 or slot[0] not in "rd" or slot[1] not in "12345" or hero is None:
            print(f'Could not use --teach {lesson!r}; write it like  d2="vengeful spirit"')
            return 1
        box = slots[(0 if slot[0] == "r" else 5) + int(slot[1]) - 1]
        path = teach(hero, image.crop(box), cache_dir)
        print(f"Learned {hero.name} from slot {slot} ({path.name})")
    print("Loading hero pictures (downloaded once)...")
    matcher = PortraitMatcher(load_references(heroes, cache_dir), load_taught(heroes, cache_dir))
    min_score = float(settings.get("min_score", 0.5))
    results = read_top_bar(image, size, layout, matcher, min_score)
    marked = image.copy()
    draw = ImageDraw.Draw(marked)
    for i, ((hero_id, score), box) in enumerate(zip(results, slots)):
        team = "Radiant" if i < 5 else "Dire"
        name = heroes[hero_id].name if hero_id in heroes else "?"
        others = ", ".join(
            f"{heroes[h].name} {s:.2f}" for h, s in matcher.candidates(image.crop(box))[1:]
        )
        print(f"{team} {i % 5 + 1}: {name:<20} match {score:.2f}   next: {others}")
        draw.rectangle(box, outline=(255, 0, 255), width=2)
    strip = marked.crop((0, 0, size[0], min(size[1], layout.strip_height(size[1]) * 3)))
    out = cfg.app_dir / "draft-test.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    strip.save(out)
    print(f"Saved the portrait boxes to {out}")
    if any(hero_id is None for hero_id, _ in results):
        print('Wrong or "?" hero? Teach it, e.g.  --teach d2="vengeful spirit"  (r1-r5, d1-d5)')
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="coach", description="Dota 2 Live Coach")
    parser.add_argument("--config", type=Path, help="path to a coach.toml")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="listen for game state (default)")
    p_install = sub.add_parser("install", help="write Dota 2's GSI config file")
    p_install.add_argument("--dota-path", type=Path, help='the "dota 2 beta" folder')
    p_replay = sub.add_parser("replay", help="replay a recorded match")
    p_replay.add_argument("recording", type=Path)
    p_replay.add_argument("--speed", type=float, default=0.0, help="1.0 = real time")
    p_say = sub.add_parser("say", help="test the voice")
    p_say.add_argument("text", nargs="?", default="Power rune in 15 seconds.")
    p_draft = sub.add_parser("draft-test", help="read the top bar heroes from a screenshot")
    p_draft.add_argument("screenshot", type=Path)
    p_draft.add_argument(
        "--teach",
        action="append",
        default=[],
        metavar="SLOT=HERO",
        help='learn a portrait from the screenshot, e.g. d2="vengeful spirit"',
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    cfg = config_mod.load(args.config)
    commands = {
        "run": cmd_run,
        "install": cmd_install,
        "replay": cmd_replay,
        "say": cmd_say,
        "draft-test": cmd_draft_test,
    }
    return commands[args.command or "run"](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
