"""Talk to a local model through Ollama (free, runs on your own GPU)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Protocol

log = logging.getLogger(__name__)



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
            "keep_alive": "30m",
            "options": {"num_predict": num_predict, "temperature": temperature},
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
