"""Speaks coaching lines one at a time on a background thread.

Lines that wait too long in the queue are dropped: a rune call that arrives
late is worse than none. Waiting lines are spoken most important first, so a
low health warning never waits behind a briefing or a tip.
"""

from __future__ import annotations

import heapq
import itertools
import logging
import threading
import time
from collections.abc import Callable
from typing import Protocol

log = logging.getLogger(__name__)

# How important a line is. Higher is spoken first when several are waiting.
LOW = 0  # the pre-game briefing
NORMAL = 1  # item, skill point and ward reminders, the game check
HIGH = 2  # rune and stack calls, answers to the player, death tips
URGENT = 3  # low health, buyback, use your wand


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
        # (-priority, order, queued at, max delay, text); None closes.
        self._queue: list[tuple[int, int, float, float, str]] = []
        self._order = itertools.count()
        self._ready = threading.Condition()
        self._closed = False
        self._factory = backend_factory
        self._speaking = threading.Event()
        # Told each line as it is spoken (True) or skipped as late (False).
        self.on_line: Callable[[str, bool], None] | None = None
        # The speech engine must be created on the thread that uses it.
        self._thread = threading.Thread(target=self._run, name="speaker", daemon=True)
        self._thread.start()

    def say(self, text: str, priority: int = NORMAL, max_delay: float | None = None) -> None:
        """Queue a line. max_delay (default: the speaker's) is how long it may
        wait before it is too late to say."""
        delay = self.max_delay if max_delay is None else max_delay
        with self._ready:
            heapq.heappush(self._queue, (-priority, next(self._order), time.monotonic(), delay, text))
            self._ready.notify()

    @property
    def busy(self) -> bool:
        """True while a line is being spoken or waits to be."""
        with self._ready:
            return self._speaking.is_set() or bool(self._queue)

    def close(self, timeout: float = 5.0) -> None:
        with self._ready:
            self._closed = True
            self._ready.notify()
        self._thread.join(timeout)

    def _next(self) -> tuple[float, float, str] | None:
        """The most important waiting line; None once closed and empty."""
        with self._ready:
            while not self._queue and not self._closed:
                self._ready.wait()
            if not self._queue:
                return None
            _, _, queued_at, delay, text = heapq.heappop(self._queue)
            # Set while holding the lock so busy never reads empty in between.
            self._speaking.set()
            return queued_at, delay, text

    def _tell(self, text: str, spoken: bool) -> None:
        if self.on_line is not None:
            try:
                self.on_line(text, spoken)
            except Exception:
                log.exception("Could not note the line %r", text)

    def _run(self) -> None:
        backend = self._factory()
        while (item := self._next()) is not None:
            queued_at, delay, text = item
            try:
                if time.monotonic() - queued_at > delay:
                    log.info("Skipped late line: %s", text)
                    self._tell(text, False)
                    continue
                self._tell(text, True)
                backend.speak(text)
            except Exception:
                log.exception("Could not speak %r", text)
            finally:
                self._speaking.clear()
