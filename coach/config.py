"""Settings, loaded from config/coach.toml defaults plus an optional user file."""

from __future__ import annotations

import ipaddress
import os
import secrets
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

APP_DIR_NAME = "Dota2LiveCoach"
DEFAULTS_FILE = Path(__file__).resolve().parent.parent / "config" / "coach.toml"


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
    reminders: dict = field(default_factory=dict)
    builds: dict = field(default_factory=dict)
    pregame: dict = field(default_factory=dict)
    listen: dict = field(default_factory=dict)
    app_dir: Path = Path()

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
    raw = _merge(_read_toml(DEFAULTS_FILE), _read_toml(user_file))

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
        reminders=raw.get("reminders", {}),
        builds=raw.get("builds", {}),
        pregame=raw.get("pregame", {}),
        listen=raw.get("listen", {}),
        app_dir=app_dir,
    )
