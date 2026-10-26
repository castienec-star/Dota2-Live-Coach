"""Command line entry point: py -m coach [run|install|replay|say]."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from aiohttp import web

from . import config as config_mod
from .gsi_server import Coach, make_app
from .install import find_dota, install
from .recorder import MatchRecorder
from .replay import replay
from .rules import Engine, hero, timers
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
) -> Coach:
    if summary_interval is None:
        summary_interval = cfg.summary_interval
    coach = Coach(cfg.token, recorder, summary_interval)
    rules = timers.build(cfg.reminders) + hero.build(cfg.reminders, cfg.builds)
    coach.listeners.append(Engine(rules, speaker.say))
    return coach


def cmd_run(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    recorder = MatchRecorder(cfg.record_dir) if cfg.record else None
    speaker = make_speaker(cfg)
    coach = make_coach(cfg, speaker, recorder)
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
    coach = make_coach(cfg, speaker, summary_interval=summary_interval)
    count = replay(coach, args.recording, args.speed)
    speaker.close(timeout=30)
    print(f"Replayed {count} updates")
    return 0


def cmd_say(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    speaker = make_speaker(cfg)
    speaker.say(args.text)
    speaker.close(timeout=30)
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
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    cfg = config_mod.load(args.config)
    commands = {"run": cmd_run, "install": cmd_install, "replay": cmd_replay, "say": cmd_say}
    return commands[args.command or "run"](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
