"""Talk to a local model through Ollama (free, runs on your own GPU)."""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Protocol

log = logging.getLogger(__name__)

DEFAULT_MODEL = "llama3.1:8b"
DEFAULT_URL = "http://127.0.0.1:11434"
# Room for the knowledge cards: a briefing with ten heroes' cards is about
# 1600 tokens, and older Ollama versions cut prompts at 2048 from the start,
# losing the instructions. Every caller asks with the same size, so the
# model stays loaded once instead of reloading for each size.
CONTEXT = 4096
POST_GAME = "DOTA_GAMERULES_STATE_POST_GAME"
# Loading the model while the player drafts makes the briefing and the first
# tip arrive on time.
WARM_STATES = {"DOTA_GAMERULES_STATE_HERO_SELECTION", "DOTA_GAMERULES_STATE_STRATEGY_TIME"}
# How long Ollama keeps a model loaded after each ask. The coach frees it
# itself when the match ends.
KEEP_ALIVE = "30m"


class Ask(Protocol):
    """Asks a model; None when it is off, slow or failed. fmt is a JSON schema
    the reply must follow, where the model supports it."""

    def __call__(self, prompt: str, fmt: dict | None = None) -> str | None: ...


def ollama_asker(
    model: str,
    url: str,
    timeout: float,
    system: str,
    num_predict: int = 80,
    label: str = "Ollama",
    temperature: float = 0.7,
) -> Ask:
    """Ask a local Ollama model; returns None if Ollama is not running or is slow.
    The returned ask takes an optional JSON schema as fmt, which Ollama makes
    the reply follow."""
    warned = False

    def ask(prompt: str, fmt: dict | None = None) -> str | None:
        nonlocal warned
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            # Keep the model loaded between calls so answers come back fast.
            "keep_alive": KEEP_ALIVE,
            "options": {"num_predict": num_predict, "temperature": temperature, "num_ctx": CONTEXT},
        }
        if fmt is not None:
            body["format"] = fmt
        request = urllib.request.Request(
            url.rstrip("/") + "/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:200]
            log.warning("%s failed: %s %s", label, exc.code, detail)
            return None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if not warned:
                warned = True
                log.warning("Ollama not reachable at %s (%s); using built-in lines", url, exc)
            return None
        return clean((data.get("message") or {}).get("content", ""))

    return ask


def clean(text: str) -> str | None:
    """A model's reply as a line to speak: no wrapping quotes or stray whitespace."""
    text = " ".join(text.split())
    while len(text) > 1 and text[0] in "\"'“”‘’" and text[-1] in "\"'“”‘’":
        text = text[1:-1].strip()
    return text.strip("\"“”") or None


def unload(model: str, url: str, timeout: float = 5) -> bool:
    """Ask Ollama to drop a model from GPU memory now (keep_alive 0) instead of
    holding it for keep_alive minutes. False if Ollama isn't running."""
    if not _generate({"model": model, "keep_alive": 0}, url, timeout):
        return False
    log.info("Freed GPU memory: unloaded %s from Ollama", model)
    return True


def load(model: str, url: str, timeout: float = 60) -> bool:
    """Ask Ollama to load a model now (a request with no prompt), so the first
    real question doesn't wait for it. False if Ollama isn't running."""
    body = {"model": model, "keep_alive": KEEP_ALIVE, "options": {"num_ctx": CONTEXT}}
    return _generate(body, url, timeout)


def _generate(body: dict, url: str, timeout: float) -> bool:
    request = urllib.request.Request(
        url.rstrip("/") + "/api/generate", json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.debug("Ollama request for %s failed (%s)", body.get("model"), exc)
        return False
    return True


def models_in_use(tables: list[dict]) -> set[tuple[str, str]]:
    """The (model, url) pairs the coach asks Ollama for, from config tables
    with a "provider" (death tips, briefing, item advice)."""
    used = set()
    for options in tables:
        if options.get("enabled", True) and options.get("provider", "ollama") == "ollama":
            used.add((options.get("ollama_model", DEFAULT_MODEL), options.get("ollama_url", DEFAULT_URL)))
    return used


class ModelMemory:
    """Loads the coach's Ollama models while you draft, and unloads them when
    the match is over, so the GPU memory goes back to Dota and the rest of the
    PC between games.

    Over means the game reached post-game, Dota stopped reporting a match
    (you abandoned or went back to the menu), or Dota went quiet for
    "quiet" seconds (closed or crashed; idle() notices that). Each call to
    Ollama runs in the background, never holding up the game state."""

    def __init__(
        self,
        models: set[tuple[str, str]],
        quiet: float = 180,
        clock: Callable[[], float] = time.monotonic,
        unload: Callable[[str, str, float], bool] = unload,
        load: Callable[[str, str], bool] = load,
    ) -> None:
        self.models = models
        self.quiet = quiet
        self.clock = clock
        self.unload = unload
        self.load = load
        self._loaded = False
        self._heard = clock()

    def __call__(self, state) -> None:
        self._heard = self.clock()
        now, before = state.current.game_state, state.previous.game_state
        if now == before:
            return
        if now is not None and now != POST_GAME:
            if now in WARM_STATES and not self._loaded:
                self._background(self.warm)
            self._loaded = True  # or will be, at the coach's first ask
        elif self._loaded:
            self._loaded = False
            self._background(self.free)

    def idle(self) -> None:
        """Called every so often: frees the models once Dota has been quiet."""
        if self._loaded and self.clock() - self._heard >= self.quiet:
            self._loaded = False
            self._background(self.free)

    def warm(self) -> None:
        for model, url in sorted(self.models):
            self.load(model, url)

    def free(self, timeout: float = 5) -> None:
        """timeout: seconds per model; short when the coach is closing."""
        for model, url in sorted(self.models):
            self.unload(model, url, timeout)

    @staticmethod
    def _background(job: Callable[[], None]) -> None:
        threading.Thread(target=job, daemon=True).start()
