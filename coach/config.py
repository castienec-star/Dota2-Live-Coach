"""Settings, loaded from config/coach.toml defaults plus an optional user file."""

from __future__ import annotations

import ipaddress
import logging as logging_mod
import os
import secrets
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

APP_DIR_NAME = "Dota2LiveCoach"
DEFAULTS_FILE = Path(__file__).resolve().parent.parent / "config" / "coach.toml"
# Sections whose tables the player names freely (hero builds).
FREE_SECTIONS = {"builds"}
# [coach] mode = "experienced" keeps only these unasked reminders: gold for
# the next item, stacks, the power rune and buyback, plus the post-game review
# (said after the match, never over it). Asked questions still get answers.
EXPERIENCED = {"item_ready", "stack", "power_rune", "buyback", "review"}
# ...and turns off the coach's own questions during the match.
EXPERIENCED_QUIET_LISTEN = ("game_questions", "enemy_items_check")
MODES = ("beginner", "experienced")

log = logging_mod.getLogger(__name__)


def user_dir() -> Path:
    """Per-user folder: %APPDATA%\\Dota2LiveCoach on Windows."""
    base = os.environ.get("APPDATA") or Path.home() / ".config"
    return Path(base) / APP_DIR_NAME


@dataclass(frozen=True)
class Config:
    host: str = "127.0.0.1"
    port: int = 4242
    token: str = ""
    record: bool = True
    record_dir: Path = Path()
    summary_interval: float = 10.0
    voice_backend: str = "sapi"
    voice_name: str = ""
    voice_rate: int = 0
    voice_max_delay: float = 4.0
    voice_max_lines: int = 2
    mode: str = "beginner"
    # Reminders the mode keeps quiet; asked questions still use their settings.
    quiet: frozenset[str] = frozenset()
    reminders: dict = field(default_factory=dict)
    builds: dict = field(default_factory=dict)
    pregame: dict = field(default_factory=dict)
    listen: dict = field(default_factory=dict)
    items: dict = field(default_factory=dict)
    app_dir: Path = Path()

    @property
    def unasked(self) -> dict:
        """[reminders.*] for what the coach says on its own, with the mode's
        quiet reminders turned off."""
        return {
            name: {**options, "enabled": False} if name in self.quiet else options
            for name, options in self.reminders.items()
        }

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"


def _merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_toml(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def apply_mode(mode: str, raw: dict, user: dict) -> tuple[dict, frozenset[str]]:
    """raw with the coach's own questions the mode leaves out turned off, and
    the reminders it quiets. Anything the player's own coach.toml turns on or
    off itself stays as set."""
    if mode not in MODES:
        raise ValueError(f"coach.mode must be one of {', '.join(MODES)}, got {mode!r}")
    if mode == "beginner":
        return raw, frozenset()
    own = user.get("reminders", {})
    quiet = frozenset(
        name
        for name in raw.get("reminders", {})
        if name not in EXPERIENCED and "enabled" not in own.get(name, {})
    )
    own_listen = user.get("listen", {})
    listen = dict(raw.get("listen", {}))
    for key in EXPERIENCED_QUIET_LISTEN:
        if key not in own_listen:
            listen[key] = False
    return {**raw, "listen": listen}, quiet


def stale(defaults: dict, user: dict) -> list[str]:
    """Sections in the user's coach.toml that the coach no longer knows, such
    as ones left over from an old version: "[pregame.capture]"."""
    found = []
    for name, value in user.items():
        if name not in defaults:
            found.append(f"[{name}]")
        elif isinstance(value, dict) and isinstance(defaults[name], dict) and name not in FREE_SECTIONS:
            found += [
                f"[{name}.{key}]"
                for key, sub in value.items()
                if isinstance(sub, dict) and key not in defaults[name]
            ]
    return found


def load_token(app_dir: Path) -> str:
    """Return the shared secret Dota sends with each update, creating it once."""
    token_file = app_dir / "gsi_token"
    if token_file.is_file():
        token = token_file.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_hex(16)
    app_dir.mkdir(parents=True, exist_ok=True)
    token_file.write_text(token, encoding="utf-8")
    return token


def load(user_file: Path | None = None, app_dir: Path | None = None) -> Config:
    app_dir = app_dir or user_dir()
    user_file = user_file or app_dir / "coach.toml"
    defaults, user = _read_toml(DEFAULTS_FILE), _read_toml(user_file)
    old = stale(defaults, user)
    if old:
        log.warning(
            "%s has settings this version doesn't use: %s. They are ignored; delete "
            "them, or compare the file with config/coach.toml to see what's new.",
            user_file,
            ", ".join(old),
        )
    raw = _merge(defaults, user)
    mode = str(raw.get("coach", {}).get("mode", "beginner")).strip().lower()
    raw, quiet = apply_mode(mode, raw, user)

    server = raw.get("server", {})
    recording = raw.get("recording", {})
    logging = raw.get("logging", {})
    voice = raw.get("voice", {})

    host = server.get("host", "127.0.0.1")
    if not ipaddress.ip_address(host).is_loopback:
        raise ValueError(f"server.host must be a loopback address, got {host!r}")

    record_dir = recording.get("directory") or app_dir / "recordings"
    return Config(
        host=host,
        port=int(server.get("port", 4242)),
        token=load_token(app_dir),
        record=bool(recording.get("enabled", True)),
        record_dir=Path(record_dir),
        summary_interval=float(logging.get("summary_interval", 10)),
        voice_backend=voice.get("backend", "sapi"),
        voice_name=voice.get("name", ""),
        voice_rate=int(voice.get("rate", 0)),
        voice_max_delay=float(voice.get("max_delay", 4)),
        voice_max_lines=int(voice.get("max_lines", 2)),
        mode=mode,
        quiet=quiet,
        reminders=raw.get("reminders", {}),
        builds=raw.get("builds", {}),
        pregame=raw.get("pregame", {}),
        listen=raw.get("listen", {}),
        items=raw.get("items", {}),
        app_dir=app_dir,
    )
