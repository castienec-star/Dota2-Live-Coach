"""Entry point of the app window ("Dota 2 Live Coach.exe"), built by build_exe.py.

A windowed build (no console) that imports only the window (pywebview and
coach/ui), so it stays small. The coach itself still runs as DotaCoach.exe next to it, started and
stopped from the window (coach/app.py).
"""

from __future__ import annotations

import sys

from coach.app_web import open_window
from coach.config import user_dir


def run() -> int:
    open_window(user_dir())
    return 0


if __name__ == "__main__":
    sys.exit(run())
