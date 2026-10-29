"""Command line entry point: py -m coach [run|install|replay|say]."""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from aiohttp import web

from . import config as config_mod
from . import game_questions
from . import health as health_mod
from . import pregame as pregame_mod
from . import voice
from .benchmarks import Benchmarks
from .gsi_server import Coach, make_app
from .heroes import HeroIndex, load_heroes
from .install import find_dota, install
from .lineup import Interview, Question, configured_position
from .opendota import OpenDota
from .recorder import MatchRecorder
from .replay import replay
from .rules import (
    Engine,
    PositionOf,
    death_tip,
    for_positions,
    game_check,
    hero,
    split_positions,
    timers,
    windows,
)
from .speaker import Speaker, make_backend
from .state import Snapshot


def make_speaker(cfg: config_mod.Config) -> Speaker:
    return Speaker(
        lambda: make_backend(cfg.voice_backend, cfg.voice_name, cfg.voice_rate),
        cfg.voice_max_delay,
    )


def position_of(cfg: config_mod.Config, coach: Coach) -> PositionOf:
    """The position the player told the coach this match, else the one set
    in coach.toml, else 0 (not known)."""

    def position(snap: Snapshot) -> int:
        told = coach.pregame.position if coach.pregame is not None else 0
        return told or configured_position(cfg.pregame, snap.hero_name)

    return position


def make_benchmarks(cfg: config_mod.Config) -> Benchmarks:
    """Bundled hero benchmarks, plus OpenDota for other heroes if it is on."""
    if not cfg.pregame.get("opendota", True):
        return Benchmarks()
    stats = OpenDota(cfg.app_dir / "opendota")
    hero_ids = {h.key: h.id for h in load_heroes().values()}
    return Benchmarks(fetch=stats.benchmarks, hero_ids=hero_ids)


def make_coach(
    cfg: config_mod.Config,
    speaker: Speaker,
    recorder: MatchRecorder | None = None,
    summary_interval: float | None = None,
    tips: bool = True,
    benchmarks: Benchmarks | None = None,
) -> Coach:
    """tips turns on the features that call a model."""
    if summary_interval is None:
        summary_interval = cfg.summary_interval
    coach = Coach(cfg.token, recorder, summary_interval)
    position = position_of(cfg, coach)
    reminders, positions = split_positions(cfg.reminders)
    power_windows = windows.build(reminders)
    rules = (
        timers.build(reminders)
        + hero.build(reminders, cfg.builds, position)
        + power_windows
        + game_check.build(
            reminders,
            benchmarks or (make_benchmarks(cfg) if tips else Benchmarks()),
            position,
            # The enemy heroes the player told the coach; pregame is made below.
            lambda: coach.pregame.enemies if coach.pregame is not None else [],
        )
        + (death_tip.build(reminders, speaker.say, position) if tips else [])
    )
    coach.listeners.append(Engine(for_positions(rules, positions, position), speaker.say))
    if tips:
        coach.pregame = pregame_mod.build(
            cfg.pregame,
            speaker.say,
            power_windows[0] if power_windows else None,
            cfg.app_dir,
            cfg.record_dir,
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


def make_interview(cfg: config_mod.Config, coach: Coach) -> Interview | None:
    """The start-of-game questions (position, teammates, enemies), if turned on."""
    if coach.pregame is None or not cfg.listen.get("start_questions", True):
        return None
    positions = cfg.pregame.get("positions", {})
    return Interview(
        coach.pregame.index,
        coach.pregame,
        position=int(cfg.pregame.get("position", 0)),
        hero_positions={k: int(v) for k, v in positions.items()},
    )


def make_game_questions(cfg: config_mod.Config, coach: Coach) -> game_questions.GameQuestions | None:
    """The in-match questions (lane, trouble hero, enemy carry, fights), if turned on."""
    if coach.pregame is None:
        return game_questions.build(cfg.listen, HeroIndex())
    return game_questions.build(cfg.listen, coach.pregame.index, lambda: coach.pregame.enemies)


def first_pending(*askers) -> Callable[[], Question | None] | None:
    """The voice loop asks the first waiting question: start-of-game ones first."""
    askers = tuple(a for a in askers if a is not None)
    if not askers:
        return None
    return lambda: next((q for q in (a.pending() for a in askers) if q is not None), None)


def version() -> str:
    """The date and commit of this copy, so you can tell an update arrived."""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cd (%h)", "--date=format:%Y-%m-%d %H:%M"],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown (not a git download)"
    return out.stdout.strip() or "unknown (not a git download)"


def cmd_run(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    logging.info("Dota 2 Live Coach, version from %s", version())
    recorder = MatchRecorder(cfg.record_dir) if cfg.record else None
    speaker = make_speaker(cfg)
    benchmarks = make_benchmarks(cfg)
    coach = make_coach(cfg, speaker, recorder, benchmarks=benchmarks)
    if coach.pregame is not None and sys.stdin is not None and sys.stdin.isatty():
        threading.Thread(target=read_typed_picks, args=(coach,), daemon=True).start()
        logging.info('Type the enemy picks any time, e.g.  vs am cm lion pudge sf')
    interview = make_interview(cfg, coach)
    questions = make_game_questions(cfg, coach)
    listening = voice.start(
        cfg.listen,
        coach.state,
        speaker.say,
        lambda: speaker.busy,
        split_positions(cfg.reminders)[0],
        cfg.builds,
        pending=first_pending(interview, questions),
        position=position_of(cfg, coach),
        benchmarks=benchmarks,
        enemies=lambda: coach.pregame.enemies if coach.pregame is not None else [],
    )
    if interview is not None and listening is not None:
        # Only ask when the coach can hear the answers. It goes before the
        # briefing so the briefing knows to wait for the answers.
        coach.listeners.insert(coach.listeners.index(coach.pregame), interview)
        coach.pregame.waiting = lambda: interview.busy
    if questions is not None and listening is not None:
        coach.listeners.append(questions)
    logging.info("Listening for Dota 2 on %s", cfg.url)
    app = make_app(coach)
    coach.health = health_mod.Health(cfg)
    health_mod.watch(app, coach.health, speaker.say)
    try:
        web.run_app(app, host=cfg.host, port=cfg.port, print=None, access_log=None)
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
    commands = {
        "run": cmd_run,
        "install": cmd_install,
        "replay": cmd_replay,
        "say": cmd_say,
    }
    return commands[args.command or "run"](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
