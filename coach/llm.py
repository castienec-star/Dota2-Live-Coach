"""Talk to a local model through Ollama (free, runs on your own GPU)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable

log = logging.getLogger(__name__)

Ask = Callable[[str], "str | None"]


def ollama_asker(
    model: str,
    url: str,
    timeout: float,
    system: str,
    num_predict: int = 80,
    label: str = "Ollama",
    temperature: float = 0.7,
) -> Ask:
    """Ask a local Ollama model; returns None if Ollama is not running or is slow."""
    warned = False

    def ask(prompt: str) -> str | None:
        nonlocal warned
        body = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            # Keep the model loaded between calls so answers come back fast.
            "keep_alive": "30m",
            "options": {"num_predict": num_predict, "temperature": temperature},
        }).encode()
        request = urllib.request.Request(
            url.rstrip("/") + "/api/chat", body, {"Content-Type": "application/json"}
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
        text = (data.get("message") or {}).get("content", "").strip()
        return text or None

    return ask
