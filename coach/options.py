"""Every option the app window lets a player change, in plain words.

The window (coach/ui/) draws a toggle for each reminder and a field for each
of its timings from OPTIONS; `values()` fills them from the defaults and the
player's coach.toml, and `saved()` turns what the window sends back into the
player's coach.toml, keeping only what differs from the defaults (the same
rule as coach/settings.py, so new defaults in a later version still reach
them). Nothing here needs a window, so it is all testable.

A field's `kind` says how it is shown and checked:
  toggle   on/off
  seconds  a number of seconds          (lead = 15)
  clock    a game time as m:ss          (stack until = 713 -> "11:53")
  minute   one game minute              (roshan minute = 20)
  minutes  a list of minutes, "15, 25"  (game_check minutes)
  percent  0 to 100
  count    a whole number
  choice   one of `choices`
  text     free text
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import config as config_mod
from . import i18n
from .settings import _prune, mode_default


@dataclass(frozen=True)
class Field:
    path: str  # "reminders.power_rune.lead"
    label: str
    kind: str
    help: str = ""
    low: int = 0
    high: int = 7200
    choices: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Reminder:
    name: str  # the [reminders.<name>] table
    label: str
    help: str
    fields: tuple[Field, ...] = ()


@dataclass(frozen=True)
class Group:
    id: str
    title: str
    help: str
    reminders: tuple[Reminder, ...] = ()
    fields: tuple[Field, ...] = ()


def _r(name: str, *fields: tuple) -> tuple[Field, ...]:
    return tuple(Field(f"reminders.{name}.{key}", *rest) for key, *rest in fields)


LEAD = ("lead", "Say it this early", "seconds", "Seconds before it happens.", 0, 60)

REMINDER_GROUPS = (
    Group("map", "Map and clock", "Runes, camps and the game clock.", (
        Reminder("power_rune", "Power rune", "Before each power rune spawns in the river.", _r(
            "power_rune", LEAD,
            ("thin_after", "Every other rune after", "clock", "Late game, only every other rune is called. 0:00 calls them all."),
        )),
        Reminder("bounty_rune", "Bounty runes", "Before the gold runes spawn.", _r(
            "bounty_rune", LEAD,
            ("thin_after", "Every other rune after", "clock", "0:00 calls them all."),
        )),
        Reminder("wisdom_shrine", "Wisdom shrines", "Before the experience shrines activate.", _r(
            "wisdom_shrine", ("lead", "Say it this early", "seconds", "", 0, 60),
        )),
        Reminder("water_rune", "Water runes", "At 2:00 and 4:00, for mid players only.", _r(
            "water_rune", ("lead", "Say it this early", "seconds", "", 0, 60),
        )),
        Reminder("stack", "Stack the camp", "At :53 each minute, only when you're near a neutral camp.", _r(
            "stack", ("until", "Stop reminding after", "clock", "Game time of the last stack reminder."),
        )),
        Reminder("neutral_items", "Neutral item tiers", "When each tier of neutral items opens."),
        Reminder("night", "Night is starting", "When night falls and vision gets shorter.", _r(
            "night", ("nights", "For the first", "count", "Number of nights.", 1, 20),
        )),
        Reminder("roshan", "Think Roshan", "Once, a reminder that Roshan is worth taking after a won fight.", _r(
            "roshan", ("minute", "At minute", "minute", "", 5, 90),
        )),
    )),
    Group("hero", "Your hero", "Gold, health and items: only from your own hero.", (
        Reminder("item_ready", "Gold for your next item", "When you can afford the next item on your build."),
        Reminder("worth_buying", "A cheap item while you save", "Magic Wand or a stats item while a big item is far away.", _r(
            "worth_buying",
            ("far", "When the next item is still", "count", "Gold short of your next build item.", 100, 5000),
            ("until_minute", "Until minute", "minute", "", 5, 60),
        )),
        Reminder("low_health", "Low health: back off", "Once when your health drops low, and \"go heal\" if it stays low.", _r(
            "low_health",
            ("below", "Back off under", "percent", "Health percent.", 5, 80),
            ("linger_below", "Go heal under", "percent", "Health percent.", 5, 90),
            ("linger", "...for this long", "seconds", "Seconds without taking damage.", 3, 60),
        )),
        Reminder("wand", "Use your Magic Wand", "When you're hurt and your wand has charges.", _r(
            "wand",
            ("below", "Health under", "percent", "", 5, 90),
            ("min_charges", "With at least", "count", "Wand charges.", 1, 20),
        )),
        Reminder("buyback", "Buyback gold", "When your gold drops under the buyback cost.", _r(
            "buyback", ("from_minute", "From minute", "minute", "", 0, 90),
        )),
        Reminder("skill_point", "Unspent skill point", "When you've levelled up and not spent the point.", _r(
            "skill_point",
            ("delay", "Wait before reminding", "seconds", "", 0, 120),
            ("max_level", "Up to level", "count", "", 1, 30),
        )),
        Reminder("ward", "Place your ward", "When an observer ward stays in your inventory.", _r(
            "ward", ("hold_seconds", "After carrying it", "seconds", "", 10, 600),
        )),
        Reminder("aegis", "You have the Aegis: push", "When you pick up the Aegis, and a minute before it runs out.", _r(
            "aegis", ("warn_after", "Runs-out warning after", "seconds", "0 turns it off.", 0, 300),
        )),
    )),
    Group("coaching", "Coaching", "Tips and check-ins that help you improve.", (
        Reminder("death_tip", "A tip after you die", "One short tip while you wait to respawn.", _r(
            "death_tip",
            ("min_respawn", "Only when the respawn is at least", "seconds", "", 0, 120),
            ("streak", "Calm-down line after", "count", "Deaths close together. 0 turns it off.", 0, 10),
        )),
        Reminder("last_hits", "Last-hit check", "Your last hits against a target for your rank (cores only).", _r(
            "last_hits", ("minutes", "At minutes", "minutes", "For example 5, 10."),
        )),
        Reminder("focus_check", "Focus after laning", "The one thing to work on once the laning phase ends.", _r(
            "focus_check", ("at", "At", "clock", "Game time."),
        )),
        Reminder("game_check", "Ahead or behind?", "How your gold and experience compare, with what to do and what to buy.", _r(
            "game_check", ("minutes", "At minutes", "minutes", "For example 15, 25."),
        )),
        Reminder("power_window", "When your team is strongest", "When the stretches from the pre-game briefing start.", _r(
            "power_window", ("lead", "Say it this early", "seconds", "", 0, 60),
        )),
        Reminder("review", "Review after the match", "Three things to work on, also saved as a text file.", _r(
            "review", ("break_after_losses", "Suggest a break after", "count", "Losses in a row. 0 turns it off.", 0, 10),
        )),
    )),
)

GENERAL = (
    Group("language", "Language", "What the coach speaks and the app shows.", fields=(
        Field("coach.language", "Coach language", "choice",
              "Spoken lines, answers and this window. Spanish needs a Spanish Windows voice "
              "(Settings > Time & language > Speech).", choices=i18n.LANGUAGES),
    )),
    Group("voice", "Voice", "How the coach sounds.", fields=(
        Field("voice.name", "Voice", "voice", "An installed Windows voice."),
        Field("voice.rate", "Speed", "count", "From -10 (slow) to 10 (fast).", -10, 10),
        Field("voice.max_lines", "At most this many lines at once", "count",
              "When several reminders are due together, the most important are said.", 1, 5),
        Field("voice.max_delay", "Skip a reminder that is late by", "seconds", "", 1, 30),
    )),
    Group("listen", "Questions", "Talk to the coach. Your microphone is only heard on this PC.", fields=(
        Field("listen.enabled", "Voice questions (\"hey coach ...\")", "toggle"),
        Field("listen.wake_word", "Wake word", "text"),
        Field("listen.start_questions", "Ask my position and the heroes before the horn", "toggle"),
        Field("listen.game_questions", "Ask short questions at calm moments", "toggle"),
        Field("listen.enemy_items_check", "Ask me to check the enemy items", "toggle"),
        Field("listen.chat", "Answer any other question with the AI model", "toggle"),
    )),
    Group("game", "Before the game", "The briefing and what the coach knows about you.", fields=(
        Field("pregame.enabled", "Spoken briefing before the horn", "toggle"),
        Field("pregame.words", "Longest briefing", "count", "Words.", 20, 200),
        Field("pregame.position", "My position", "choice", "Or let the coach ask each game.", choices=(
            ("0", "Ask each game"), ("1", "1 - Safe lane"), ("2", "2 - Mid"), ("3", "3 - Offlane"),
            ("4", "4 - Soft support"), ("5", "5 - Hard support"))),
        Field("player.rank", "My rank", "choice", "Targets compare you with players of your medal.", choices=(
            ("", "Ask me / from OpenDota"), ("Herald", "Herald"), ("Guardian", "Guardian"), ("Crusader", "Crusader"),
            ("Archon", "Archon"), ("Legend", "Legend"), ("Ancient", "Ancient"), ("Divine", "Divine"),
            ("Immortal", "Immortal"))),
        Field("items.announce", "Say item advice unasked when it changes", "toggle"),
    )),
)


def all_fields() -> list[Field]:
    out = []
    for group in REMINDER_GROUPS + GENERAL:
        out += list(group.fields)
        for reminder in group.reminders:
            out += list(reminder.fields)
    return out


def all_reminders() -> list[Reminder]:
    return [r for g in REMINDER_GROUPS for r in g.reminders]


def _get(table: dict, path: str, fallback=None):
    for part in path.split("."):
        if not isinstance(table, dict) or part not in table:
            return fallback
        table = table[part]
    return table


def _put(table: dict, path: str, value) -> None:
    *parents, last = path.split(".")
    for part in parents:
        table = table.setdefault(part, {})
    table[last] = value


def _drop(table: dict, path: str) -> None:
    *parents, last = path.split(".")
    for part in parents:
        table = table.get(part)
        if not isinstance(table, dict):
            return
    table.pop(last, None)


def show(f: Field, value) -> str | bool:
    """A stored value as the window shows it."""
    if f.kind == "toggle":
        return bool(value)
    if f.kind == "clock":
        value = int(value or 0)
        return f"{value // 60}:{value % 60:02d}"
    if f.kind == "minutes":
        return ", ".join(str(v) for v in value or [])
    return "" if value is None else str(value)


def parse(f: Field, raw) -> tuple[object, str]:
    """What the window sent, as the value to store, or ("", error)."""
    if f.kind == "toggle":
        return bool(raw), ""
    text = str(raw).strip()
    if f.kind in ("text", "voice"):
        return text, ""
    if f.kind == "choice":
        keys = [k for k, _ in f.choices]
        if text not in keys:
            return "", f"{f.label}: pick one of the list"
        return (int(text) if f.path == "pregame.position" else text), ""
    if f.kind == "clock":
        found = re.fullmatch(r"(\d{1,3})(?::(\d{1,2}))?", text)
        if not found or int(found.group(2) or 0) > 59:
            return "", f"{f.label}: write a game time like 11:53"
        return int(found.group(1)) * 60 + int(found.group(2) or 0), ""
    if f.kind == "minutes":
        parts = [p for p in re.split(r"[,\s]+", text) if p]
        if not all(p.isdigit() for p in parts):
            return "", f"{f.label}: write minutes like 15, 25"
        values = sorted({int(p) for p in parts})
        if any(v < 1 or v > 120 for v in values):
            return "", f"{f.label}: minutes from 1 to 120"
        return values, ""
    if not re.fullmatch(r"-?\d+", text):
        return "", f"{f.label}: write a whole number"
    value = int(text)
    high = 100 if f.kind == "percent" else f.high
    if not f.low <= value <= high:
        return "", f"{f.label}: from {f.low} to {high}"
    return value, ""


def mode_of(defaults: dict, user: dict) -> str:
    return str(_get(user, "coach.mode", _get(defaults, "coach.mode", "beginner"))).lower()


def reminder_on(name: str, defaults: dict, user: dict, mode: str) -> bool:
    own = _get(user, f"reminders.{name}.enabled")
    return bool(own) if own is not None else mode_default(name, mode, defaults)


def listen_default(path: str, defaults: dict, mode: str):
    """A [listen] switch as the mode sets it when the player didn't (config.apply_mode)."""
    key = path.split(".", 1)[1]
    if mode == "experienced" and key in config_mod.EXPERIENCED_QUIET_LISTEN:
        return False
    return _get(defaults, path)


def default_of(f: Field, defaults: dict, mode: str):
    if f.path.startswith("listen."):
        return listen_default(f.path, defaults, mode)
    fallback = "" if f.kind in ("text", "voice", "choice") else (False if f.kind == "toggle" else 0)
    return _get(defaults, f.path, fallback)


def values(defaults: dict, user: dict) -> dict:
    """Everything the window shows: the mode, each reminder on or off, and each field."""
    mode = mode_of(defaults, user)
    return {
        "mode": mode,
        "reminders": {r.name: reminder_on(r.name, defaults, user, mode) for r in all_reminders()},
        "fields": {f.path: show(f, _get(user, f.path, default_of(f, defaults, mode))) for f in all_fields()},
    }


def saved(defaults: dict, user: dict, sent: dict) -> tuple[dict, list[str]]:
    """The player's new coach.toml from what the window sent, and any errors
    (nothing is changed when there are errors)."""
    mode = str(sent.get("mode", mode_of(defaults, user)))
    if mode not in config_mod.MODES:
        return user, [f"Unknown mode {mode!r}"]
    new = json.loads(json.dumps(user))
    errors = []
    if mode == _get(defaults, "coach.mode", "beginner"):
        _drop(new, "coach.mode")
    else:
        _put(new, "coach.mode", mode)
    for name, on in (sent.get("reminders") or {}).items():
        if name not in {r.name for r in all_reminders()}:
            continue
        if bool(on) == mode_default(name, mode, defaults):
            _drop(new, f"reminders.{name}.enabled")
        else:
            _put(new, f"reminders.{name}.enabled", bool(on))
    by_path = {f.path: f for f in all_fields()}
    for path, raw in (sent.get("fields") or {}).items():
        f = by_path.get(path)
        if f is None:
            continue
        value, error = parse(f, raw)
        if error:
            errors.append(error)
            continue
        if value == default_of(f, defaults, mode):
            _drop(new, path)
        else:
            _put(new, path, value)
    if errors:
        return user, errors
    return _prune(new), []


def schema(lang: str = "en") -> dict:
    """OPTIONS as plain data for the window, in the app's language."""

    def t(text: str) -> str:
        return i18n.ui(text, lang)

    def fields(fs):
        return [{"path": f.path, "label": t(f.label), "kind": f.kind, "help": t(f.help), "low": f.low,
                 "high": 100 if f.kind == "percent" else f.high,
                 # Language names stay in their own language.
                 "choices": [[k, v if f.path == "coach.language" else t(v)] for k, v in f.choices]}
                for f in fs]

    return {
        "reminders": [
            {"id": g.id, "title": t(g.title), "help": t(g.help), "reminders": [
                {"name": r.name, "label": t(r.label), "help": t(r.help), "fields": fields(r.fields),
                 "experienced": r.name in config_mod.EXPERIENCED}
                for r in g.reminders]}
            for g in REMINDER_GROUPS
        ],
        "general": [{"id": g.id, "title": t(g.title), "help": t(g.help), "fields": fields(g.fields)}
                    for g in GENERAL],
    }


def language_of(defaults: dict, user: dict) -> str:
    """The app's language: the player's coach.toml, else the defaults."""
    return i18n.normalize(_get(user, "coach.language", _get(defaults, "coach.language", "en")))


def remode(sent: dict, old: str, new: str, defaults: dict) -> dict:
    """The window's values after switching mode: what still matched the old
    mode follows the new one; what the player changed stays (settings.remode)."""
    out = {**sent, "mode": new}
    out["reminders"] = {
        name: mode_default(name, new, defaults) if bool(on) == mode_default(name, old, defaults) else bool(on)
        for name, on in (sent.get("reminders") or {}).items()
    }
    fields = dict(sent.get("fields") or {})
    for path in list(fields):
        if path.startswith("listen.") and path.split(".", 1)[1] in config_mod.EXPERIENCED_QUIET_LISTEN:
            if bool(fields[path]) == bool(listen_default(path, defaults, old)):
                fields[path] = bool(listen_default(path, defaults, new))
    out["fields"] = fields
    return out
