"""Entry point of the Windows app (DotaCoach.exe), built by build_exe.py.

Runs the same command line as `py -m coach`. Double-clicking the app starts
the coach; `DotaCoach.exe install` (or "Set up Dota 2.bat") writes the GSI file.
"""

from __future__ import annotations

import sys

from coach.__main__ import main


def run() -> int:
    try:
        code = main()
    except KeyboardInterrupt:
        code = 0
    except SystemExit as exc:  # argparse errors and --help
        code = exc.code if isinstance(exc.code, int) else 1
    except Exception:
        import traceback

        traceback.print_exc()
        code = 1
    # A double-clicked console window closes at once, taking the error with it.
    if code and sys.stdin is not None and sys.stdin.isatty():
        try:
            input("\nThe coach stopped. Press Enter to close this window.")
        except (EOFError, KeyboardInterrupt):
            pass
    return code


if __name__ == "__main__":
    sys.exit(run())
