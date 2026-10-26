"""Speaks coaching lines one at a time on a background thread.

Lines that wait too long in the queue are dropped: a rune call that arrives
late is worse than none.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Protocol

log = logging.getLogger(__name__)


class Backend(Protocol):
    def speak(self, text: str) -> None: ...


class PrintBackend:
    """Logs lines instead of speaking them (tests, or voice turned off)."""

    def speak(self, text: str) -> None:
        log.info("Coach: %s", text)


class SapiBackend:
    """Windows' built-in text-to-speech, through pyttsx3."""

    def __init__(self, voice: str = "", rate: int = 180) -> None:
        import pyttsx3

        self.engine = pyttsx3.init()
        self.engine.setProperty("rate", rate)
        if voice:
            match = next(
                (v for v in self.engine.getProperty("voices") if voice.lower() in v.name.lower()),
                None,
            )
            if match is None:
                log.warning("No installed voice matches %r; using the default", voice)
            else:
                self.engine.setProperty("voice", match.id)

    def speak(self, text: str) -> None:
        log.info("Coach: %s", text)
        self.engine.say(text)
        self.engine.runAndWait()


def make_backend(name: str, voice: str = "", rate: int = 180) -> Backend:
    if name == "sapi":
        try:
            return SapiBackend(voice, rate)
        except Exception as exc:  # pyttsx3 missing, or no speech engine
            log.warning("Voice unavailable (%s); printing lines instead", exc)
    return PrintBackend()


class Speaker:
    def __init__(self, backend_factory=PrintBackend, max_delay: float = 4.0) -> None:
        self.max_delay = max_delay
        self._queue: queue.Queue[tuple[float, str] | None] = queue.Queue()
        self._factory = backend_factory
        # The speech engine must be created on the thread that uses it.
        self._thread = threading.Thread(target=self._run, name="speaker", daemon=True)
        self._thread.start()

    def say(self, text: str) -> None:
        self._queue.put((time.monotonic(), text))

    def close(self, timeout: float = 5.0) -> None:
        self._queue.put(None)
        self._thread.join(timeout)

    def _run(self) -> None:
        backend = self._factory()
        while (item := self._queue.get()) is not None:
            queued_at, text = item
            if time.monotonic() - queued_at > self.max_delay:
                log.info("Skipped late line: %s", text)
                continue
            try:
                backend.speak(text)
            except Exception:
                log.exception("Could not speak %r", text)
