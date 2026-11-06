"""The app window: a web page (coach/ui/) in a native window, via pywebview.

    py -m coach app

pywebview uses Windows' own Edge WebView2, so nothing extra downloads and
nothing goes online: the page is local files, and it talks to Python only
through coach/app_api.py. Without pywebview, `py -m coach app` falls back to
the simple tkinter window (coach/app_window.py).
"""

from __future__ import annotations

from pathlib import Path

from .app_api import Api

UI = Path(__file__).resolve().parent / "ui"
TITLE = "Dota 2 Live Coach"


def open_window(app_dir: Path, debug: bool = False) -> None:
    import webview

    api = Api(app_dir)
    window = webview.create_window(
        TITLE,
        url=str(UI / "index.html"),
        js_api=api,
        width=1240,
        height=820,
        min_size=(980, 660),
        background_color="#070708",
    )
    window.events.closed += lambda: api.stop()
    webview.start(debug=debug)
