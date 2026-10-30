"""A fixed test set of game moments, to see whether the coach's model got better.

Each case in evals/cases.json is one moment (a death, "what should I buy?",
the pre-game briefing) with what a good answer contains: a phrase a good tip
or briefing uses, or the items a good buy would be. Every case goes through
the same prompts and checks as a real game, and gets a point when its line
passes the coach's checks (so it would be spoken) and another when it is on
point. The set runs with and without the knowledge cards, so the gain shows:

    py -m coach.evals --model llama3.1:8b
    py -m coach.evals --model qwen3:14b --runs 3

The phrases are deliberately loose: the score is a guide for comparing models
and prompts, not a grade.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

from . import knowledge, llm, pregame
from .draft import Draft, analyse
from .game_questions import Notes
from .heroes import HeroIndex
from .item_advisor import ItemAdvisor, describe as item_prompt, ollama_asker as item_asker, schema
from .items import ItemInfo, load_items
from .rules import death_tip
from .situational import Pick
from .state import IN_PROGRESS, PRE_GAME, Item, Snapshot

CASES_FILE = Path(__file__).resolve().parent.parent / "evals" / "cases.json"
KINDS = ("tip", "item", "briefing")
NO_CARDS = {"heroes": {}, "items": {}}


@dataclass
class Result:
    case: str
    cards: bool
    reply: str | None  # what would be spoken; None when the checks dropped it
    on_point: bool

    @property
    def points(self) -> int:
        return (self.reply is not None) + self.on_point


def snapshot(case: dict) -> Snapshot:
    kills, deaths, assists = case.get("kda", (0, 0, 0))
    minute = case.get("minute", 0)
    return Snapshot(
        game_state=PRE_GAME if case["kind"] == "briefing" else IN_PROGRESS,
        clock_time=minute * 60,
        hero_name=f"npc_dota_hero_{case['hero']}",
        level=case.get("level", 1),
        gold=case.get("gold", 600),
        kills=kills,
        deaths=deaths,
        assists=assists,
        last_hits=case.get("last_hits", 0),
        gpm=case.get("gpm", 0),
        xpm=case.get("xpm", 0),
        alive=case["kind"] != "tip",
        respawn_seconds=case.get("respawn", 30) if case["kind"] == "tip" else 0,
        buyback_cost=case.get("buyback_cost", 200 + 15 * minute * 10),
        items=[Item(f"slot{i}", f"item_{key}", None, True, 0) for i, key in enumerate(case.get("items", []))],
    )


def notes(case: dict, heroes: HeroIndex) -> Notes | None:
    told = dict(case.get("told", {}))
    if not told:
        return None
    if "trouble" in told:
        told["trouble"] = heroes.by_key(told["trouble"])
    return Notes(**told)


def on_point(text: str | None, expect: list[str]) -> bool:
    lower = (text or "").lower()
    return any(phrase.lower() in lower for phrase in expect)


def run_case(case: dict, ask: llm.Ask, heroes: HeroIndex, items: dict[str, ItemInfo]) -> tuple[str | None, bool]:
    """What the coach would say for this case, and whether it is on point."""
    snap = snapshot(case)
    hero = heroes.by_key(snap.hero_name)
    enemies = [heroes.by_key(k) for k in case.get("enemies", [])]
    told = notes(case, heroes)
    position = case.get("position", 0)
    if case["kind"] == "tip":
        tip = death_tip.DeathTip(lambda line: None, None, items=items)
        prompt = death_tip.describe(snap, items, position, told)
        reply = tip.checked(ask(prompt), snap, prompt)
        tip.close()
        return reply, on_point(reply, case["expect"])
    if case["kind"] == "item":
        picks = [Pick(items[f"item_{key}"], "") for key in case["candidates"]]
        prompt = item_prompt(snap, picks, None, enemies, items, hero, position, told)
        advisor = ItemAdvisor(ask)
        parsed = advisor._pick(ask(prompt, schema(picks)), picks, enemies, told, hero)
        chosen = parsed.item.key.removeprefix("item_")
        reply = f"{parsed.item.name}, {parsed.reason}" if parsed.reason else None
        return reply, chosen in case["best"]
    allies = [heroes.by_key(k) for k in case.get("allies", [])]
    draft = Draft(allies, enemies, hero)
    coach = pregame.Pregame(lambda line: None, heroes, ask=ask)
    coach.position = position
    reply = coach._model_briefing(snap, draft, analyse(draft, None), [])
    coach.close()
    return reply, on_point(reply, case["expect"])


def run(
    cases: list[dict], asks: dict[str, llm.Ask], cards: bool, runs: int = 1
) -> list[Result]:
    heroes, items = HeroIndex(), load_items()
    results = []
    off = mock.patch.object(knowledge, "_load", lambda: NO_CARDS)
    with contextlib.nullcontext() if cards else off:
        for case in cases:
            for _ in range(runs):
                reply, good = run_case(case, asks[case["kind"]], heroes, items)
                results.append(Result(case["name"], cards, reply, good))
    return results


def load_cases(path: Path = CASES_FILE) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        cases = json.load(f)["cases"]
    for case in cases:
        if case["kind"] not in KINDS:
            raise ValueError(f"{case['name']}: kind must be one of {KINDS}")
    return cases


def ollama_asks(model: str, url: str, timeout: float) -> dict[str, llm.Ask]:
    """The same system prompts and settings a real game uses."""
    words = 70
    return {
        "tip": death_tip.ollama_asker(model, url, timeout),
        "item": item_asker(model, url, timeout),
        "briefing": llm.ollama_asker(
            model, url, timeout, pregame.SYSTEM_PROMPT.format(words=words),
            num_predict=words * 2, label="Briefing", temperature=0.2,
        ),
    }


def report(results: list[Result], print_: Callable[[str], None] = print) -> None:
    for cards in (True, False):
        mine = [r for r in results if r.cards == cards]
        if not mine:
            continue
        print_(f"\n== {'With' if cards else 'Without'} knowledge cards ==")
        for r in mine:
            mark = "+" if r.on_point else "-"
            print_(f"[{r.points}] {mark} {r.case}: {r.reply or '(dropped by the checks)'}")
        spoken = sum(r.reply is not None for r in mine)
        good = sum(r.on_point for r in mine)
        total = sum(r.points for r in mine)
        print_(f"Score {total}/{2 * len(mine)}: spoken {spoken}/{len(mine)}, on point {good}/{len(mine)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="py -m coach.evals", description=__doc__.splitlines()[0])
    parser.add_argument("--model", default="llama3.1:8b")
    parser.add_argument("--url", default="http://127.0.0.1:11434")
    parser.add_argument("--timeout", type=float, default=60, help="seconds per answer (generous: not a game)")
    parser.add_argument("--runs", type=int, default=1, help="answers per case, as models vary")
    parser.add_argument("--only", choices=KINDS, help="run one kind of case")
    parser.add_argument("--cards-only", action="store_true", help="skip the run without cards")
    args = parser.parse_args(argv)
    cases = [c for c in load_cases() if args.only in (None, c["kind"])]
    asks = ollama_asks(args.model, args.url, args.timeout)
    if asks["tip"]("Hero: test") is None:
        print(f"Ollama did not answer at {args.url} with {args.model}. Is it running, and is the model pulled?")
        return 1
    results = run(cases, asks, cards=True, runs=args.runs)
    if not args.cards_only:
        results += run(cases, asks, cards=False, runs=args.runs)
    print(f"Model {args.model}, {len(cases)} cases, {args.runs} run(s) each")
    report(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
