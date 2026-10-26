"""Writes the GSI config file that tells Dota 2 where to send game state.

This is Valve's supported way for an app to subscribe to game events. It only
adds a file to Dota's gamestate_integration folder; it does not modify the game.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from .config import Config

CFG_NAME = "gamestate_integration_coach.cfg"
GSI_SUBDIR = Path("game") / "dota" / "cfg" / "gamestate_integration"
DOTA_DIR = Path("steamapps") / "common" / "dota 2 beta"

CFG_TEMPLATE = """\
"Dota 2 Live Coach"
{{
	"uri"		"{url}"
	"timeout"	"5.0"
	"buffer"	"0.1"
	"throttle"	"0.1"
	"heartbeat"	"30.0"
	"data"
	{{
		"auth"		"1"
		"provider"	"1"
		"map"		"1"
		"player"	"1"
		"hero"		"1"
		"abilities"	"1"
		"items"		"1"
	}}
	"auth"
	{{
		"token"		"{token}"
	}}
}}
"""


def render_cfg(config: Config) -> str:
    return CFG_TEMPLATE.format(url=config.url, token=config.token)


def steam_path_from_registry() -> Path | None:
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            value, _ = winreg.QueryValueEx(key, "SteamPath")
    except OSError:
        return None
    return Path(value)


def library_folders(steam_path: Path) -> list[Path]:
    """Steam library roots listed in libraryfolders.vdf, main install first."""
    folders = [steam_path]
    vdf = steam_path / "steamapps" / "libraryfolders.vdf"
    if vdf.is_file():
        text = vdf.read_text(encoding="utf-8", errors="replace")
        for raw in re.findall(r'"path"\s+"([^"]+)"', text):
            path = Path(raw.replace("\\\\", "\\"))
            if path not in folders:
                folders.append(path)
    return folders


def find_dota(steam_path: Path | None = None) -> Path | None:
    steam_path = steam_path or steam_path_from_registry()
    if steam_path is None:
        return None
    for library in library_folders(steam_path):
        candidate = library / DOTA_DIR
        if (candidate / "game" / "dota").is_dir():
            return candidate
    return None


def install(config: Config, dota_path: Path) -> Path:
    target_dir = dota_path / GSI_SUBDIR
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / CFG_NAME
    target.write_text(render_cfg(config), encoding="utf-8")
    return target
