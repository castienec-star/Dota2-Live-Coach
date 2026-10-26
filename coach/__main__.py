"""Command line entry point: python -m coach [run|install|replay]."""

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


def cmd_run(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    recorder = MatchRecorder(cfg.record_dir) if cfg.record else None
    coach = Coach(cfg.token, recorder, cfg.summary_interval)
    logging.info("Listening for Dota 2 on %s", cfg.url)
    try:
        web.run_app(make_app(coach), host=cfg.host, port=cfg.port, print=None, access_log=None)
    finally:
        if recorder is not None:
            recorder.close()
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
    coach = Coach(cfg.token, summary_interval=0)
    count = replay(coach, args.recording, args.speed)
    print(f"Replayed {count} updates")
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
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    cfg = config_mod.load(args.config)
    commands = {"run": cmd_run, "install": cmd_install, "replay": cmd_replay}
    return commands[args.command or "run"](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
