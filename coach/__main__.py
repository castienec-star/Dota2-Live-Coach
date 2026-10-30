"""Command line entry point: py -m coach [run|install|replay|refresh-items|refresh-benchmarks|review|say]."""

from __future__ import annotations

import argparse
import dataclasses
import functools
import logging
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from aiohttp import web

from . import config as config_mod
from . import chat as chat_mod
from . import enemy_items, game_questions, item_advisor, situational
from . import health as health_mod
from . import llm
from . import pregame as pregame_mod
from . import review as review_mod
from . import voice
from .benchmarks import Benchmarks, status
from .gsi_server import Coach, make_app
from .heroes import HeroIndex, load_heroes
from .install import find_dota, install
from .items import load_items
from .lineup import Interview, Question, TypedQuestions, configured_position
from .opendota import OpenDota
from .profile import summarize
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
from .speaker import HIGH, LOW, Speaker, make_backend
from .state import Snapshot


def notes_of(coach: Coach) -> Callable[[], game_questions.Notes | None]:
    """What the player told the coach so far: the answers to the in-match
    questions and the enemy items they reported."""

    def notes() -> game_questions.Notes | None:
        answered = coach.questions.notes if coach.questions is not None else None
        told = coach.enemy_items.told() if coach.enemy_items is not None else {}
        if not told:
            return answered
        return dataclasses.replace(answered or game_questions.Notes(), enemy_items=told)

    return notes


def make_speaker(cfg: config_mod.Config) -> Speaker:
    return Speaker(
        lambda: make_backend(cfg.voice_backend, cfg.voice_name, cfg.voice_rate),
        cfg.voice_max_delay,
    )


def reply_say(speaker: Speaker) -> Callable[[str], None]:
    """For answers and questions to the player: they are waiting for them,
    so they go first and may wait longer than a rune call."""
    return functools.partial(speaker.say, priority=HIGH, max_delay=15)


def position_of(cfg: config_mod.Config, coach: Coach) -> PositionOf:
    """The position the player told the coach this match, else the one set
    in coach.toml, else 0 (not known)."""

    def position(snap: Snapshot) -> int:
        told = coach.pregame.position if coach.pregame is not None else 0
        return told or configured_position(cfg.pregame, snap.hero_name)

    return position


def with_tip_model(cfg: config_mod.Config, table: dict) -> dict:
    """A config table whose Ollama model and address default to the death
    tips' ones, so the coach keeps one model in GPU memory, not two or three."""
    tip = cfg.reminders.get("death_tip", {})
    return {
        "ollama_model": tip.get("ollama_model", llm.DEFAULT_MODEL),
        "ollama_url": tip.get("ollama_url", llm.DEFAULT_URL),
        **table,
    }


def ollama_models(cfg: config_mod.Config) -> set[tuple[str, str]]:
    """Every (model, address) the death tips, briefing, item advice and chat ask."""
    items = with_tip_model(cfg, cfg.items)
    tip = cfg.reminders.get("death_tip", {})
    return llm.models_in_use(
        [
            tip,
            {**tip, "enabled": bool(cfg.listen.get("chat", True))},
            with_tip_model(cfg, cfg.pregame),
            {**items, "provider": items.get("advisor", "ollama")},
        ]
    )


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
    if benchmarks is None:
        benchmarks = make_benchmarks(cfg) if tips else Benchmarks()
    # The enemy heroes the player told the coach; pregame is made below.
    enemies = lambda: coach.pregame.enemies if coach.pregame is not None else []  # noqa: E731
    # "What should I buy?": the model picks only when tips are on.
    coach.advice = item_advisor.Advice(
        item_advisor.build(with_tip_model(cfg, cfg.items)) if tips else item_advisor.ItemAdvisor(None),
        cfg.builds,
        position,
        benchmarks,
        enemies,
        notes_of(coach),
    )
    coach.enemy_items = enemy_items.EnemyItems(enemies=enemies)
    coach.listeners.append(coach.enemy_items)
    # A death tip has its own deadline too: the respawn.
    tip_say = functools.partial(speaker.say, priority=HIGH, max_delay=10)
    reminders, positions = split_positions(cfg.reminders)
    power_windows = windows.build(reminders)
    rules = (
        timers.build(reminders)
        + hero.build(reminders, cfg.builds, position, enemies)
        + power_windows
        + game_check.build(
            reminders,
            benchmarks,
            position,
            enemies,
            notes_of(coach),
            # Never waits for the model: its pick if ready, else the rules'.
            lambda snap: coach.advice(snap, wait=False)[0],
        )
        + (death_tip.build(reminders, tip_say, position, notes_of(coach)) if tips else [])
    )
    coach.listeners.append(Engine(for_positions(rules, positions, position), speaker.say, cfg.voice_max_lines, prioritized=True))
    if reminders.get("review", {}).get("enabled", True):
        # Nothing else is said after the game, so it may wait for a busy speaker.
        review_say = functools.partial(speaker.say, priority=LOW, max_delay=60)
        # A fast replay (no tips) only prints it.
        folder = cfg.app_dir / "reviews" if tips else None
        coach.listeners.append(review_mod.Review(review_say, folder, position))
    if tips:
        coach.pregame = pregame_mod.build(
            with_tip_model(cfg, cfg.pregame),
            # Long, and only useful before the game: any reminder goes first.
            functools.partial(speaker.say, priority=LOW, max_delay=20),
            power_windows[0] if power_windows else None,
            cfg.app_dir,
            cfg.record_dir,
        )
        if coach.pregame is not None:
            coach.listeners.append(coach.pregame)
        models = ollama_models(cfg)
        if len({model for model, _ in models}) > 1:
            logging.warning(
                "The coach asks Ollama for %s; each one takes GPU memory. Use one "
                "ollama_model everywhere in coach.toml to save memory for Dota.",
                " and ".join(sorted({model for model, _ in models})),
            )
        if models and cfg.items.get("free_after_match", True):
            coach.listeners.append(llm.ModelMemory(models))
    return coach


# Typed in the coach window for "what should I buy?", e.g. without a microphone.
BUY_COMMANDS = ("buy", "item", "items")


def what_to_buy(coach: Coach) -> str:
    """The same answer as asking "what should I buy?"."""
    snap = coach.state.current
    if snap.hero_name is None:
        return "I can't see your hero yet. Ask me again once the game has started."
    pick, verdict, _ = coach.advice(snap)
    return situational.spoken(pick, verdict, snap)


# Typed picks and position, read by the pre-game briefing.
PICK_COMMANDS = ("vs", "with", "pos", "clear")

# Typed for "how am I doing?".
HOW_COMMANDS = ("how", "status")


def how_am_i_doing(coach: Coach) -> str:
    """The same answer as asking "how am I doing?"."""
    snap = coach.state.current
    if snap.hero_name is None:
        return "I can't see your hero yet. Ask me again once the game has started."
    advice = coach.advice
    position = advice.position(snap) if advice.position else 0
    return status(advice.benchmarks, snap, advice.heroes.by_key(snap.hero_name), position)


def read_typed_picks(coach: Coach, questions: TypedQuestions | None = None) -> None:
    """Lets you type the draft in the coach window: "vs am cm lion pudge sf",
    "buy" for what to buy now, "how" for how you are doing, the answer to
    a start-of-game question shown there, or any other question for the model."""
    for line in sys.stdin:
        if not line.strip():
            continue
        command = line.strip().split(maxsplit=1)[0].lower()
        if command in BUY_COMMANDS and coach.advice is not None:
            print(what_to_buy(coach), flush=True)
            continue
        if command in HOW_COMMANDS and coach.advice is not None:
            print(how_am_i_doing(coach), flush=True)
            continue
        if command not in PICK_COMMANDS and questions and questions.answer(line):
            continue
        # What an enemy has: "lion has glimmer and force".
        if coach.enemy_items is not None and coach.enemy_items.is_report(line):
            print(coach.enemy_items.report(line), flush=True)
            continue
        # "how do I play against pudge?": the same free chat as out loud.
        if command not in PICK_COMMANDS and coach.chat is not None:
            reply = coach.chat(line.strip(), coach.state.current)
            print(coach.chat.off if reply is None else reply or "Ask me again once the fight is over.", flush=True)
            continue
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
    if recorder is not None:
        speaker.on_line = lambda text, spoken: recorder.said(text, coach.state.current.clock_time, spoken)
    typing = coach.pregame is not None and sys.stdin is not None and sys.stdin.isatty()
    interview = make_interview(cfg, coach)
    questions = make_game_questions(cfg, coach)
    enemies = lambda: coach.pregame.enemies if coach.pregame is not None else []  # noqa: E731
    advice = coach.advice
    allies = lambda: coach.pregame.allies if coach.pregame is not None else []  # noqa: E731
    # Questions the built-in answers don't cover go to the death tips' model.
    chat = chat_mod.build(
        cfg.listen,
        cfg.reminders.get("death_tip", {}),
        advice,
        position_of(cfg, coach),
        allies,
        enemies,
        notes_of(coach),
        lambda: coach.state.current,
        coach.enemy_items.facts if coach.enemy_items is not None else None,
    )
    coach.chat = chat
    # Keeps "what should I buy?" ready, and says when the pick changes.
    coach.listeners.append(Engine(item_advisor.watch(cfg.items, advice), speaker.say, prioritized=True))
    listening = voice.start(
        cfg.listen,
        coach.state,
        reply_say(speaker),
        lambda: speaker.busy,
        split_positions(cfg.reminders)[0],
        cfg.builds,
        pending=first_pending(interview, questions),
        position=position_of(cfg, coach),
        benchmarks=benchmarks,
        enemies=enemies,
        notes=notes_of(coach),
        advice=advice,
        enemy_items=coach.enemy_items,
        chat=chat,
    )
    typed = None
    if interview is not None and listening is None and typing:
        # The coach can't hear you: ask the same questions in this window.
        typed = TypedQuestions(interview, speaker.say, lambda text: print(text, flush=True))
        logging.info("Voice is off, so the start-of-game questions will be asked here")
    if interview is not None and (listening is not None or typed is not None):
        # They go before the briefing so the briefing knows to wait for the answers.
        at = coach.listeners.index(coach.pregame)
        coach.listeners[at:at] = [interview] + ([typed] if typed else [])
        coach.pregame.waiting = lambda: interview.busy
    elif interview is not None:
        logging.warning("Nobody will be asked the picks: voice is off and there is no coach window to type in")
    if questions is not None and listening is not None:
        coach.listeners.append(questions)
        coach.questions = questions
    if typing:
        threading.Thread(target=read_typed_picks, args=(coach, typed), daemon=True).start()
        logging.info('Type the enemy picks any time, e.g.  vs am cm lion pudge sf')
        logging.info('Type "buy" any time to hear what to buy now, or "how" for how you are doing')
        if chat is not None:
            logging.info("Or type any other question for the coach, e.g.  how do I play against pudge")
    if listening is None:
        logging.info("Voice is off: item advice still comes unasked, at 15 and 25 minutes and when the pick changes")
    logging.info("Listening for Dota 2 on %s", cfg.url)
    app = make_app(coach)
    coach.health = health_mod.Health(cfg)
    health_mod.watch(app, coach.health, speaker.say)
    for listener in coach.listeners:
        if isinstance(listener, llm.ModelMemory):
            # Dota closed or crashed mid-match sends no post-game: free on silence.
            health_mod.repeat(app, 30, listener.idle)
    try:
        web.run_app(app, host=cfg.host, port=cfg.port, print=None, access_log=None)
    finally:
        if recorder is not None:
            recorder.close()
        speaker.close()
        for listener in coach.listeners:
            if isinstance(listener, llm.ModelMemory):
                # Closing the coach gives the GPU memory back too; quickly, as
                # Ollama drops the model on its own timer anyway.
                listener.free(timeout=1.5)
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


def cmd_refresh_items(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    """Saves what real players build on each hero, from OpenDota's public stats."""
    from . import popularity

    stats = OpenDota(cfg.app_dir / "opendota", timeout=20)
    out = args.out or popularity.POPULARITY_FILE

    def get(path: str):
        # One failed hero shouldn't make the rest skip the network.
        stats._offline_until = 0.0
        return stats.get(path, max_age=86400)

    heroes = load_heroes()
    print(f"Reading item popularity for {len(heroes)} heroes from OpenDota (about 3 minutes)...")
    try:
        found = popularity.fetch(get, heroes, progress=lambda text: print(text, flush=True))
    except RuntimeError as exc:
        logging.error("%s. Check your internet connection and try again.", exc)
        return 1
    if len(found) < len(heroes) // 2:
        logging.error("Only %d of %d heroes came back; nothing saved. Try again later.", len(found), len(heroes))
        return 1
    popularity.save(found, out)
    print(f"Saved {len(found)} heroes to {out}")
    return 0


def cmd_refresh_benchmarks(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    """Saves the public GPM, experience and last-hit numbers for every hero,
    so "how am I doing?" never needs the network in a match."""
    from . import benchmarks

    stats = OpenDota(cfg.app_dir / "opendota", timeout=20)
    out = args.out or benchmarks.BENCHMARKS_FILE

    def get(path: str):
        # One failed hero shouldn't make the rest skip the network.
        stats._offline_until = 0.0
        return stats.get(path, max_age=86400)

    heroes = load_heroes()
    print(f"Reading benchmarks for {len(heroes)} heroes from OpenDota (about 3 minutes)...")
    found = benchmarks.fetch_all(get, heroes, progress=lambda text: print(text, flush=True))
    if len(found) < len(heroes) // 2:
        logging.error("Only %d of %d heroes came back; nothing saved. Try again later.", len(found), len(heroes))
        return 1
    saved = benchmarks.save(found, {h.key: h.id for h in heroes.values()}, out)
    print(f"Saved {saved} heroes to {out}")
    return 0


def cmd_review(cfg: config_mod.Config, args: argparse.Namespace) -> int:
    """Prints the post-game review of a recorded match."""
    items = load_items()
    summary = summarize(args.recording, items)
    if summary is None:
        logging.error("%s holds no finished game of at least 5 minutes.", args.recording)
        return 1
    heroes = HeroIndex()
    position = configured_position(cfg.pregame, summary.hero)
    support = review_mod.is_support(heroes.by_key(summary.hero), position)
    print(review_mod.text(summary, review_mod.points(summary, support, items), heroes), end="")
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
    p_refresh = sub.add_parser("refresh-items", help="save popular items per hero from OpenDota")
    p_refresh.add_argument("--out", type=Path, default=None, help="where to save (default: the bundled data file)")
    p_bench = sub.add_parser("refresh-benchmarks", help="save public GPM and last-hit numbers per hero from OpenDota")
    p_bench.add_argument("--out", type=Path, default=None, help="where to save (default: the bundled data file)")
    p_review = sub.add_parser("review", help="print the post-game review of a recorded match")
    p_review.add_argument("recording", type=Path)
    p_say = sub.add_parser("say", help="test the voice")
    p_say.add_argument("text", nargs="?", default="Power rune in 15 seconds.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    cfg = config_mod.load(args.config)
    commands = {
        "run": cmd_run,
        "install": cmd_install,
        "replay": cmd_replay,
        "refresh-items": cmd_refresh_items,
        "refresh-benchmarks": cmd_refresh_benchmarks,
        "review": cmd_review,
        "say": cmd_say,
    }
    return commands[args.command or "run"](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
