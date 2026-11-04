"""First-run setup in plain words: done for the player when the coach starts.

New players lose the coach at setup: they skip `py -m coach install`, forget
the launch option, or never find out the voice is silent. So `py -m coach`
checks the same things on every start:

- Dota's GSI config file is missing or out of date: write it (the same file
  `py -m coach install` writes; Valve's supported way to get game state).
- Steam's own settings file (localconfig.vdf, read only) shows Dota 2 without
  the `-gamestateintegration` launch option: say how to add it.
- The config file was just written: say one line out loud as a voice test and
  print what to check if nothing was heard.

Nothing here reads or changes the game, its memory or the screen. The launch
option check only reads Steam's settings text file; when it can't tell, the
coach gives the plain instruction instead of guessing.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .health import cfg_problem
from .install import find_dota, install, steam_path_from_registry

log = logging.getLogger(__name__)

DOTA_APP_ID = "570"
LAUNCH_OPTION = "-gamestateintegration"
LAUNCH_STEPS = "In Steam, right-click Dota 2 > Properties > Launch Options and add  -gamestateintegration"

VOICE_TEST = (
    "Hi, I'm your Dota coach. Dota is set up. "
    "If you hear me, the voice works."
)


def parse_vdf(text: str) -> dict:
    """Valve's KeyValues text ("key" "value" and "key" { ... }) as nested dicts.

    Keys are lower-cased: Steam writes "apps" and "Apps" in different versions.
    """
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    root: dict = {}
    stack = [root]
    key = None
    for quoted, brace in tokens:
        if brace == "{":
            child: dict = {}
            if key is not None:
                stack[-1][key.lower()] = child
            stack.append(child)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif key is None:
            key = quoted
        else:
            stack[-1][key.lower()] = quoted
            key = None
    return root


def launch_options(steam_path: Path) -> list[str] | None:
    """Dota 2's launch options for each Steam account on this PC, or None
    when Steam's settings can't be read (then we can't tell)."""
    found = []
    for vdf in sorted((steam_path / "userdata").glob("*/config/localconfig.vdf")):
        try:
            data = parse_vdf(vdf.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        steam = data.get("userlocalconfigstore", {}).get("software", {}).get("valve", {}).get("steam", {})
        app = steam.get("apps", {}).get(DOTA_APP_ID)
        if isinstance(app, dict):
            found.append(app.get("launchoptions", ""))
    return found or None


def has_launch_option(steam_path: Path | None) -> bool | None:
    """True when Dota 2 has -gamestateintegration for any Steam account here,
    False when Steam's settings show it missing, None when we can't tell."""
    if steam_path is None:
        return None
    options = launch_options(steam_path)
    if options is None:
        return None
    return any(LAUNCH_OPTION in o.lower().split() for o in options)


@dataclass
class Setup:
    """What the start-up check found and did."""

    dota: Path | None = None
    wrote: Path | None = None  # the GSI config file, when it was (re)written
    launch_option: bool | None = None
    steps: list[str] = field(default_factory=list)  # what the player still has to do

    @property
    def ready(self) -> bool:
        return self.dota is not None and not self.steps


def check(
    config: Config,
    steam: Callable[[], Path | None] = steam_path_from_registry,
    dota: Callable[[Path | None], Path | None] = find_dota,
) -> Setup:
    """Writes the GSI config file if it is missing or out of date and lists
    what the player still has to do. Never touches anything else."""
    steam_path = steam()
    setup = Setup(dota=dota(steam_path))
    if setup.dota is None:
        setup.steps.append(
            "Could not find Dota 2 through Steam. If you haven't yet, run  py -m coach install --dota-path "
            '"D:\\SteamLibrary\\steamapps\\common\\dota 2 beta"  with your own Dota folder.'
        )
        return setup
    if cfg_problem(config, setup.dota) is not None:
        try:
            setup.wrote = install(config, setup.dota)
        except OSError as exc:
            setup.steps.append(f"Could not write Dota's config file ({exc}). Run  py -m coach install  as administrator.")
            return setup
    setup.launch_option = has_launch_option(steam_path)
    if setup.launch_option is False:
        setup.steps.append(
            LAUNCH_STEPS + ", then restart Dota 2. (Steam saves this when it closes: "
            "ignore this if you just added it.)"
        )
    elif setup.wrote is not None:
        if setup.launch_option is None:
            setup.steps.append(LAUNCH_STEPS + " (skip this if it is already there).")
        setup.steps.append("If Dota 2 is open, restart it so it reads the new file.")
    return setup


def spoken(setup: Setup) -> str | None:
    """One line to say at start, or None when nothing was set up just now.

    A missing launch option is only printed on later starts: Steam saves its
    settings file when it closes, so it can be out of date. Not finding Dota
    is only printed too: players with Dota outside Steam's libraries ran
    `install --dota-path` already. The health check speaks up anyway if Dota
    stays silent for a minute."""
    if setup.wrote is None:
        return None
    if setup.launch_option is True:
        return VOICE_TEST + " If Dota is open, restart it."
    return VOICE_TEST + " The coach window shows what is left to do."


def run(config: Config, say: Callable[[str], None], out: Callable[[str], None] = print, **kwargs) -> Setup:
    """The start-up check: fix what the coach can, print and say the rest."""
    try:
        setup = check(config, **kwargs)
    except Exception:  # a failed check must never stop the coach
        log.exception("The setup check failed; the coach runs anyway")
        return Setup()
    if setup.wrote is not None:
        out(f"Set up Dota 2 for the coach: wrote {setup.wrote}")
    if setup.steps:
        out("To finish setting up:")
        for number, step in enumerate(setup.steps, 1):
            out(f"  {number}. {step}")
    if setup.wrote is not None:
        out("You should hear the coach say hello now. If you hear nothing, check the")
        out("Windows sound output, then test with  py -m coach say")
    line = spoken(setup)
    if line:
        say(line)
    return setup
