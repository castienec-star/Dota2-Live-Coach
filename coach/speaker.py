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
    """Windows' built-in text-to-speech (SAPI), called directly through COM."""

    def __init__(self, voice: str = "", rate: int = 0) -> None:
        import comtypes
        import comtypes.client

        # COM must be set up on the thread that speaks; Speaker builds the
        # backend on its own thread for this reason.
        comtypes.CoInitialize()
        self.voice = comtypes.client.CreateObject("SAPI.SpVoice")
        self.voice.Rate = max(-10, min(10, rate))
        if voice:
            tokens = self.voice.GetVoices()
            names = [tokens.Item(i).GetDescription() for i in range(tokens.Count)]
            match = next((i for i, n in enumerate(names) if voice.lower() in n.lower()), None)
            if match is None:
                log.warning("No installed voice matches %r; voices: %s", voice, ", ".join(names))
            else:
                self.voice.Voice = tokens.Item(match)

    def speak(self, text: str) -> None:
        log.info("Coach: %s", text)
        # Blocks until the line has been spoken, so lines never overlap.
        self.voice.Speak(text)


def make_backend(name: str, voice: str = "", rate: int = 0) -> Backend:
    if name == "sapi":
        try:
            return SapiBackend(voice, rate)
        except Exception as exc:  # not Windows, or no speech engine
            log.warning("Voice unavailable (%s); printing lines instead", exc)
    return PrintBackend()


class Speaker:
    def __init__(self, backend_factory=PrintBackend, max_delay: float = 4.0) -> None:
        self.max_delay = max_delay
        self._queue: queue.Queue[tuple[float, str] | None] = queue.Queue()
        self._factory = backend_factory
        self._speaking = threading.Event()
        # The speech engine must be created on the thread that uses it.
        self._thread = threading.Thread(target=self._run, name="speaker", daemon=True)
        self._thread.start()

    def say(self, text: str) -> None:
        self._queue.put((time.monotonic(), text))

    @property
    def busy(self) -> bool:
        """True while a line is being spoken or waits to be."""
        return self._speaking.is_set() or not self._queue.empty()

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
            self._speaking.set()
            try:
                backend.speak(text)
            except Exception:
                log.exception("Could not speak %r", text)
            finally:
                self._speaking.clear()
