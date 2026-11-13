"""What the settings window changes in the player's own coach.toml.

The window (coach/settings_window.py) only shows and edits; everything here
works without tkinter so it can be tested. The player's file keeps only what
differs from config/coach.toml: setting something back to the default removes
it, so a later version's new defaults still reach them.
"""

from __future__ import annotations

import json
import re
import shutil
from collections import deque
from pathlib import Path

from . import config as config_mod
from .heroes import HeroInfo
from .items import ItemInfo, lookup

# Plain names for the reminders in [reminders.*], in the order the window
# lists them. A reminder missing here still shows, under its section name.
REMINDERS = {
    "item_ready": "Gold for your next item",
    "worth_buying": "A cheap item while you save",
    "low_health": "Low health: back off, go heal",
    "wand": "Use your Magic Wand",
    "buyback": "Not enough gold to buy back",
    "skill_point": "Unspent skill point",
    "ward": "Place the ward you carry",
    "aegis": "You have the Aegis: push",
    "death_tip": "A tip after you die",
    "power_rune": "Power rune",
    "bounty_rune": "Bounty (gold) runes",
    "water_rune": "Water runes (mid only)",
    "wisdom_shrine": "Wisdom shrine",
    "stack": "Stack the camp",
    "neutral_items": "Neutral item tiers",
    "night": "Night is starting",
    "roshan": "Take Roshan after a won fight",
    "last_hits": "Last-hit check at 5 and 10 minutes",
    "focus_check": "What to focus on after laning",
    "game_check": "Ahead or behind at 15 and 25 minutes",
    "power_window": "When your team is strongest",
    "review": "Review after the match",
}
# The builds every hero without its own list falls back to.
ROLE_BUILDS = {"default": "Any core (default)", "default_support": "Any support (default)"}

HEADER = (
    "# Your Dota 2 Live Coach settings, saved by the settings window\n"
    "# (py -m coach settings). Only what differs from the defaults is here;\n"
    "# see config/coach.toml for every setting and what it does.\n"
)


def label(name: str) -> str:
    return REMINDERS.get(name) or name.replace("_", " ").capitalize()


def reminder_names(defaults: dict) -> list[str]:
    """Every reminder in the defaults, in the window's order."""
    found = list(defaults.get("reminders", {}))
    return [n for n in REMINDERS if n in found] + [n for n in found if n not in REMINDERS]


def mode_default(name: str, mode: str, defaults: dict) -> bool:
    """Whether a reminder is on in this mode when the player's file doesn't
    turn it on or off itself (config.apply_mode's rule)."""
    on = bool(defaults.get("reminders", {}).get(name, {}).get("enabled", True))
    return on and (mode == "beginner" or name in config_mod.EXPERIENCED)


def checks(defaults: dict, user: dict, mode: str) -> dict[str, bool]:
    """On or off for each reminder, as the coach would run it in this mode."""
    own = user.get("reminders", {})
    return {
        name: bool(own[name]["enabled"]) if "enabled" in own.get(name, {}) else mode_default(name, mode, defaults)
        for name in reminder_names(defaults)
    }


def remode(current: dict[str, bool], old: str, new: str, defaults: dict) -> dict[str, bool]:
    """The checkboxes after switching mode: reminders still as the old mode
    had them follow the new mode; ones the player changed stay as they are."""
    return {
        name: mode_default(name, new, defaults) if on == mode_default(name, old, defaults) else on
        for name, on in current.items()
    }


def build_for(key: str, defaults: dict, user: dict) -> list[str]:
    """The hero's own build list, or [] when it has none (it then uses the
    role default, or OpenDota's popular items)."""
    own = user.get("builds", {})
    if key in own:
        return list(own[key])
    return list(defaults.get("builds", {}).get(key, []))


def parse_build(text: str, items: dict[str, ItemInfo]) -> tuple[list[str], list[str]]:
    """Item names, one per line or comma separated, spelled as the coach
    knows them, plus the lines it doesn't recognise."""
    names, unknown = [], []
    for part in re.split(r"[\n,]", text):
        part = part.strip()
        if not part:
            continue
        item = lookup(items, part)
        if item is None:
            unknown.append(part)
        else:
            names.append(item.name)
    return names, unknown


def build_choice(
    key: str, text: str, defaults: dict, items: dict[str, ItemInfo]
) -> tuple[list[str] | None, list[str]]:
    """What the build box's text means for updated(): a list to save, or None
    for the default. An empty box turns item reminders off for a hero with a
    bundled build; for one without, it just keeps the fallback."""
    names, unknown = parse_build(text, items)
    if not names and not unknown and key not in defaults.get("builds", {}):
        return None, []
    return names, unknown


def _set(table: dict, key: str, value, default) -> None:
    if value == default:
        table.pop(key, None)
    else:
        table[key] = value


def updated(
    defaults: dict,
    user: dict,
    *,
    mode: str,
    voice_name: str,
    voice_rate: int,
    reminders: dict[str, bool],
    builds: dict[str, list[str] | None],
) -> dict:
    """The player's coach.toml contents with the window's choices. builds maps
    a build key to its new list, or None to go back to the default."""
    if mode not in config_mod.MODES:
        raise ValueError(f"mode must be one of {', '.join(config_mod.MODES)}, got {mode!r}")
    new = json.loads(json.dumps(user))  # a deep copy; TOML values are JSON-safe
    coach = new.setdefault("coach", {})
    _set(coach, "mode", mode, defaults.get("coach", {}).get("mode", "beginner"))
    voice = new.setdefault("voice", {})
    _set(voice, "name", voice_name.strip(), defaults.get("voice", {}).get("name", ""))
    _set(voice, "rate", max(-10, min(10, int(voice_rate))), defaults.get("voice", {}).get("rate", 0))

    own = new.setdefault("reminders", {})
    for name, on in reminders.items():
        table = own.setdefault(name, {})
        _set(table, "enabled", bool(on), mode_default(name, mode, defaults))

    own_builds = new.setdefault("builds", {})
    for key, items in builds.items():
        default = defaults.get("builds", {}).get(key)
        if items is None or items == default:
            own_builds.pop(key, None)
        else:
            own_builds[key] = list(items)
    return _prune(new)


def _prune(table: dict) -> dict:
    """Drops tables left empty, so the file holds only real choices."""
    out = {}
    for key, value in table.items():
        if isinstance(value, dict):
            value = _prune(value)
            if not value:
                continue
        out[key] = value
    return out


_BARE = re.compile(r"^[A-Za-z0-9_-]+$")


def _key(key: str) -> str:
    return key if _BARE.match(key) else json.dumps(key)


def _value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        # JSON's escapes (\", \\, \n, \uXXXX) are valid in TOML basic strings.
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    raise TypeError(f"can't write {type(value).__name__} to coach.toml")


def dumps(data: dict) -> str:
    """TOML for nested tables of strings, numbers, booleans and lists (all a
    coach.toml holds). Comments in the old file are not kept."""
    lines: list[str] = []
    todo: deque[tuple[tuple[str, ...], dict]] = deque([((), data)])
    while todo:
        path, table = todo.popleft()
        plain = [(k, v) for k, v in table.items() if not isinstance(v, dict)]
        if path and plain:
            lines += ["", "[" + ".".join(_key(p) for p in path) + "]"]
        lines += [f"{_key(k)} = {_value(v)}" for k, v in plain]
        todo.extendleft(reversed([(path + (k,), v) for k, v in table.items() if isinstance(v, dict)]))
    return "\n".join(lines).lstrip("\n") + "\n"


def save(path: Path, data: dict) -> Path | None:
    """Writes the player's coach.toml. An existing file is first copied to
    coach.toml.bak (its comments are not kept); that copy's path is returned."""
    backup = None
    if path.is_file():
        backup = path.with_name(path.name + ".bak")
        shutil.copyfile(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + "\n" + dumps(data), encoding="utf-8")
    return backup


def last_hero(record_dir: Path, heroes: dict[int, HeroInfo]) -> HeroInfo | None:
    """The hero in the newest recording, so the window opens on the build the
    player last played. Reads only the end of the file."""
    try:
        files = sorted(record_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return None
    by_key = {h.key: h for h in heroes.values()}
    for path in reversed(files[-3:]):
        try:
            with path.open("rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 256_000))
                tail = f.read().decode("utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line in reversed(tail):
            try:
                name = json.loads(line)["payload"]["hero"]["name"]
            except (ValueError, KeyError, TypeError):
                continue
            hero = by_key.get(str(name).removeprefix("npc_dota_hero_"))
            if hero:
                return hero
    return None
