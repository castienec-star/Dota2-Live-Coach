"""Builds the Windows app: a DotaCoach folder with DotaCoach.exe, no Python
or Git needed on the player's PC.

    py -m pip install -e ".[voice,build]"
    py packaging/build_exe.py

The result is dist/DotaCoach/. Zip that folder to share it. GitHub Actions
(.github/workflows/build-exe.yml) builds the same folder on every change to
main and keeps it as a download on the run's page.

A folder rather than a single .exe: a one-file build unpacks itself (a few
hundred MB with the speech packages) to a temp folder on every start, which
is slow and trips virus scanners more often. Not signed and no auto-update
yet (ROADMAP item 14).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "DotaCoach"
# The windowed app players double-click: start/stop, status, what was said.
APP_NAME = "Dota 2 Live Coach"
APP_CONTENTS = "_app"

# Files the coach reads next to its own code (Path(__file__) lookups), as
# (source relative to ROOT, folder inside the bundle).
DATA = [
    ("coach/data", "coach/data"),
    ("config/coach.toml", "config"),
]

# Packages with DLLs or model files that PyInstaller can't find by imports
# alone. Skipped when not installed (a build without the voice extras).
COLLECT = ["faster_whisper", "ctranslate2", "vosk"]

SETUP_BAT = """\
@echo off
rem Tells Dota 2 to send game state to the coach. Run once, then restart Dota.
"%~dp0{name}.exe" install %*
echo.
echo Next: in Steam, right-click Dota 2 ^> Properties ^> Launch Options and add
echo   -gamestateintegration
echo Then start the coach by double-clicking {name}.exe.
pause
"""

SETTINGS_BAT = """\
@echo off
rem Opens the coach's settings window (mode, voice, reminders, builds).
start "" "%~dp0{name}.exe" settings
"""

START_HERE = """\
Dota 2 Live Coach
=================

1. Double-click "Set up Dota 2.bat" once. It finds Dota 2 through Steam and
   adds the Game State Integration file (Valve's supported way for apps to
   follow a match). It doesn't change the game.
2. In Steam, right-click Dota 2 > Properties > Launch Options and add
   -gamestateintegration
3. Double-click "{app}.exe" before a match and press Start. (Or
   double-click {name}.exe for the same coach in a console window.)

The coach only speaks. It never reads your screen or the game's memory.
Settings: double-click "Coach settings.bat" (mode, voice, reminders, item
builds). Everything else: copy _internal\\config\\coach.toml to
%APPDATA%\\Dota2LiveCoach\\ and change your copy. On the first start the coach downloads its speech models
(about 200 MB) once.

Version: {version}
"""


def installed(package: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(package) is not None


def pyinstaller_args(build_file: Path, work: Path, dist: Path, collect: list[str]) -> list[str]:
    """The PyInstaller command line for the app folder."""
    args = [
        str(ROOT / "packaging" / "launcher.py"),
        "--name", NAME,
        "--onedir",
        "--console",
        "--noconfirm",
        "--clean",
        "--paths", str(ROOT),
        "--workpath", str(work),
        "--distpath", str(dist),
        "--specpath", str(work),
        "--add-data", f"{build_file}{os.pathsep}.",
    ]
    for source, target in DATA:
        args += ["--add-data", f"{ROOT / source}{os.pathsep}{target}"]
    for package in collect:
        args += ["--collect-all", package]
    return args


def app_args(work: Path, dist: Path) -> list[str]:
    """The PyInstaller command line for the windowed app.

    It imports only the window (pywebview), so its own folder (APP_CONTENTS,
    next to _internal) stays small; the coach runs as NAME.exe beside it.
    """
    return [
        str(ROOT / "packaging" / "app_launcher.py"),
        "--name", APP_NAME,
        "--onedir",
        "--windowed",
        "--contents-directory", APP_CONTENTS,
        "--noconfirm",
        "--paths", str(ROOT),
        "--workpath", str(work / "app"),
        "--distpath", str(dist / "app"),
        "--specpath", str(work / "app"),
        # The page, and the defaults the settings pages compare with.
        "--add-data", f"{ROOT / 'coach/ui'}{os.pathsep}coach/ui",
        "--add-data", f"{ROOT / 'config/coach.toml'}{os.pathsep}config",
        "--collect-all", "webview",
    ]


def main() -> int:
    import PyInstaller.__main__

    from coach.__main__ import BUILD_FILE, version

    work = ROOT / "build" / "pyinstaller"
    dist = ROOT / "dist"
    work.mkdir(parents=True, exist_ok=True)
    stamp = version()
    build_file = work / BUILD_FILE
    build_file.write_text(stamp + "\n", encoding="utf-8")

    collect = [p for p in COLLECT if installed(p)]
    missing = sorted(set(COLLECT) - set(collect))
    if missing:
        print(f"Building without {', '.join(missing)}: voice questions will be off in this app.")
    PyInstaller.__main__.run(pyinstaller_args(build_file, work, dist, collect))

    app = dist / NAME
    PyInstaller.__main__.run(app_args(work, dist))
    window = dist / "app" / APP_NAME
    shutil.copy(window / f"{APP_NAME}.exe", app / f"{APP_NAME}.exe")
    shutil.copytree(window / APP_CONTENTS, app / APP_CONTENTS, dirs_exist_ok=True)
    (app / "Set up Dota 2.bat").write_text(SETUP_BAT.format(name=NAME), encoding="utf-8")
    (app / "Coach settings.bat").write_text(SETTINGS_BAT.format(name=NAME), encoding="utf-8")
    (app / "START HERE.txt").write_text(START_HERE.format(name=NAME, app=APP_NAME, version=stamp), encoding="utf-8")
    shutil.copy(ROOT / "THIRD_PARTY_NOTICES.md", app / "THIRD_PARTY_NOTICES.md")
    print(f"Built {app} (version from {stamp})")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main())
