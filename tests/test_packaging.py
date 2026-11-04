import importlib.util
import os
import sys
from pathlib import Path

import pytest

from coach import __main__ as cli
from coach import benchmarks, config, heroes, items, knowledge, popularity
from coach.rules import timers

ROOT = Path(__file__).resolve().parent.parent


def load_build_exe():
    spec = importlib.util.spec_from_file_location("build_exe", ROOT / "packaging" / "build_exe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_exe = load_build_exe()


@pytest.mark.parametrize(
    "path",
    [
        config.DEFAULTS_FILE,
        timers.CAMPS_FILE,
        heroes.HEROES_FILE,
        items.ITEMS_FILE,
        knowledge.KNOWLEDGE_FILE,
        benchmarks.BENCHMARKS_FILE,
        popularity.POPULARITY_FILE,
        popularity.PATCH_FILE,
    ],
)
def test_every_data_file_the_coach_reads_is_bundled(path):
    # The app finds these next to its code, so each must land in the bundle
    # at the same path relative to the bundle root as to the repo root.
    relative = path.relative_to(ROOT).as_posix()
    bundled = set()
    for src, target in build_exe.DATA:
        if (ROOT / src).is_dir() and relative.startswith(src + "/"):
            bundled.add(f"{target}/{relative[len(src) + 1:]}")
        elif relative == src:
            bundled.add(f"{target}/{Path(src).name}")
    assert bundled == {relative}


def test_pyinstaller_args_add_data_build_file_and_packages(tmp_path):
    build_file = tmp_path / "BUILD"
    args = build_exe.pyinstaller_args(build_file, tmp_path / "work", tmp_path / "dist", ["vosk"])
    data = [args[i + 1] for i, a in enumerate(args) if a == "--add-data"]
    assert f"{build_file}{os.pathsep}." in data
    assert f"{ROOT / 'config/coach.toml'}{os.pathsep}config" in data
    assert f"{ROOT / 'coach/data'}{os.pathsep}coach/data" in data
    assert args[args.index("--collect-all") + 1] == "vosk"
    assert "--onedir" in args and args[args.index("--name") + 1] == "DotaCoach"


def test_setup_bat_runs_install():
    bat = build_exe.SETUP_BAT.format(name="DotaCoach")
    assert '"%~dp0DotaCoach.exe" install' in bat
    assert "-gamestateintegration" in bat


def test_app_version_comes_from_the_build_file(tmp_path, monkeypatch):
    (tmp_path / cli.BUILD_FILE).write_text("2026-11-03 04:00 (abc1234)\n", encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert cli.version() == "2026-11-03 04:00 (abc1234)"


def test_app_without_build_file_says_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert cli.version().startswith("unknown")


def test_version_flag_prints_and_exits(capsys):
    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out.startswith("Dota 2 Live Coach, version from ")
