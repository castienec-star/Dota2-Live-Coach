"""Screen frames and a local vision model, for replay review only.

Frames are grabbed only when replay_view.ScreenGate says a replay is playing.
They stay in memory: nothing is saved to disk or sent anywhere except the
Ollama model running on this PC.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable

from . import llm

log = logging.getLogger(__name__)

# Reads game screens well; about 6 GB of graphics memory.
DEFAULT_MODEL = "qwen2.5vl:7b"
# For smaller graphics cards: about 4 GB.
LIGHT_MODEL = "gemma3:4b"
MODELS = {
    DEFAULT_MODEL: "Qwen2.5-VL 7B (best, about 6 GB)",
    LIGHT_MODEL: "Gemma 3 4B (lighter, about 4 GB)",
}
# Wide enough to read health bars and the minimap, small enough that a few
# frames fit in one ask (about 600 tokens each for Qwen2.5-VL).
MAX_WIDTH = 896
# Room for four frames, the numbers and the instructions.
CONTEXT = 8192

Frame = bytes  # a JPEG
Grab = Callable[[], "Frame | None"]
SeeAsk = Callable[[str, "list[Frame]"], "str | None"]


def grab_screen(max_width: int = MAX_WIDTH) -> Frame | None:
    """The main screen as a JPEG, or None where it can't be captured."""
    try:
        from PIL import ImageGrab
    except ImportError:
        log.warning("Screen capture needs Pillow: py -m pip install pillow")
        return None
    try:
        image = ImageGrab.grab()
    except Exception as exc:  # no display, or not Windows
        log.warning("Could not capture the screen (%s)", exc)
        return None
    if image.width > max_width:
        image = image.resize((max_width, round(image.height * max_width / image.width)))
    out = io.BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=80)
    return out.getvalue()


def ollama_vision(model: str, url: str, timeout: float, system: str, num_predict: int = 90) -> SeeAsk:
    """Ask a local Ollama vision model about a few frames (oldest first);
    None if it is off or slow."""
    warned = False

    def ask(prompt: str, frames: list[Frame]) -> str | None:
        nonlocal warned
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt, "images": [base64.b64encode(f).decode() for f in frames]},
            ],
            "stream": False,
            "keep_alive": llm.KEEP_ALIVE,
            "options": {"num_predict": num_predict, "temperature": 0.4, "num_ctx": CONTEXT},
        }
        request = urllib.request.Request(
            url.rstrip("/") + "/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:200]
            if "not found" in detail:
                log.warning("Vision model %s not found. Install it: ollama pull %s", model, model)
            else:
                log.warning("Vision model failed: %s %s", exc.code, detail)
            return None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if not warned:
                warned = True
                log.warning("Ollama not reachable at %s (%s)", url, exc)
            return None
        return llm.clean((data.get("message") or {}).get("content", ""))

    return ask


def installed(model: str, url: str, timeout: float = 3) -> bool | None:
    """True if Ollama has the model, False if not, None if Ollama isn't running."""
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/tags", timeout=timeout) as response:
            tags = json.load(response)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    names = {m.get("name", "") for m in tags.get("models", [])}
    return model in names or f"{model}:latest" in names
