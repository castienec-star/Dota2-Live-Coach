"""Hands-free questions: say "hey coach", then ask, and the coach answers aloud.

Everything runs on this PC. The microphone is only heard by a small local
wake-word model until it catches the wake word; then a few seconds of speech
are turned into text by a local model and thrown away. Nothing is recorded or
sent anywhere. Answers come only from your own hero's GSI data, your build
list and the game clock, like every other reminder.

Needs the optional packages:  pip install -e ".[voice]"
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from collections.abc import Callable, Iterable, Iterator

from .heroes import HeroIndex
from .items import load_items
from .rules import timers
from .rules.hero import ItemReady, parse_builds
from .state import MatchState, Snapshot

log = logging.getLogger(__name__)

RATE = 16000  # samples per second, 16-bit mono: what both speech models expect
FRAME = 1280  # samples per microphone read (80 ms)

UNKNOWN = "I can't help with that yet. Ask me about your next item, buyback or runes."

# First match wins, so the narrower questions come first.
INTENTS: list[tuple[str, re.Pattern[str]]] = [
    ("buyback", re.compile(r"\bbuy ?backs?\b")),
    ("rune", re.compile(r"\b(runes?|shrines?|bounty|bounties|wisdom)\b")),
    ("next_item", re.compile(r"\b(items?|buy|build|purchase|get next|shop)\b")),
]


def intent(text: str) -> str:
    """Turn a transcribed question into one of the intents, or "unknown"."""
    folded = re.sub(r"[^a-z' ]+", " ", text.lower())
    return next((name for name, pattern in INTENTS if pattern.search(folded)), "unknown")


def _clock(seconds: int) -> str:
    minutes, secs = divmod(max(0, seconds), 60)
    return f"{minutes}:{secs:02d}"


def _next_time(reminder: timers.TimedReminder, now: int) -> int | None:
    """The first event time strictly after now, or None when they have stopped."""
    if now < reminder.first:
        return reminder.first
    if reminder.every <= 0:
        return None
    t = reminder.first + ((now - reminder.first) // reminder.every + 1) * reminder.every
    if reminder.until is not None and t > reminder.until:
        return None
    return t


class Answers:
    """Short spoken answers built from the latest snapshot."""

    RUNES = (("power_rune", "Power rune"), ("bounty_rune", "Gold runes"), ("wisdom_shrine", "Wisdom shrines"))

    def __init__(self, reminders: dict[str, dict], builds: dict[str, list[str]]) -> None:
        settings = {name: reminders.get(name, {}) for name, _ in self.RUNES}
        self.timers = {r.name: r for r in timers.build(settings) if r.name in dict(self.RUNES)}
        self.items = ItemReady(parse_builds(builds, load_items()), HeroIndex()) if builds else None

    def answer(self, text: str, snap: Snapshot) -> str:
        kind = intent(text)
        if kind == "unknown":
            return UNKNOWN
        if snap.hero_name is None:
            return "I can't see your hero yet. Ask me again once the game has started."
        return getattr(self, kind)(snap)

    def next_item(self, snap: Snapshot) -> str:
        target = self.items.next_item(snap) if self.items else None
        if target is None:
            return "Your build list is done. Buy what the game needs, like a Black King Bar or a defensive item."
        if snap.gold >= target.cost:
            return f"Buy {target.name} now, you have the gold."
        return f"Next is {target.name}. You need {target.cost - snap.gold} more gold."

    def buyback(self, snap: Snapshot) -> str:
        if snap.buyback_cost <= 0:
            return "Buyback isn't available yet."
        if snap.buyback_cooldown > 0:
            return f"Buyback is on cooldown for {snap.buyback_cooldown} seconds."
        if snap.gold < snap.buyback_cost:
            return f"You can't buy back. It costs {snap.buyback_cost} and you have {snap.gold}."
        return (
            f"You can buy back for {snap.buyback_cost}. "
            "Only do it to defend your base or join a big fight."
        )

    def rune(self, snap: Snapshot) -> str:
        now = snap.clock_time or 0
        parts = []
        for name, label in self.RUNES:
            reminder = self.timers.get(name)
            t = _next_time(reminder, now) if reminder else None
            if t is not None:
                parts.append(f"{label} at {_clock(t)}")
        if not parts:
            return "Rune reminders are turned off."
        return ", ".join(parts) + "."


class Endpointer:
    """Decides when a spoken question has ended, from microphone loudness.

    Gives up if nobody starts talking within wait seconds, and stops after
    silence seconds of quiet once they have, or after max_seconds in all.
    """

    def __init__(
        self,
        level: float = 500,
        wait: float = 3.0,
        silence: float = 0.8,
        max_seconds: float = 5.0,
    ) -> None:
        self.level = level
        self.wait = wait
        self.silence = silence
        self.max_seconds = max_seconds

    def collect(self, frames: Iterator[bytes]) -> bytes:
        """Read frames until the question ends; returns b"" if nobody spoke."""
        wait, silence, most = (frames_in(s) for s in (self.wait, self.silence, self.max_seconds))
        audio = bytearray()
        heard = False
        quiet = count = 0
        for frame in frames:
            count += 1
            if rms(frame) >= self.level:
                heard, quiet = True, 0
            elif heard:
                quiet += 1
            if heard:
                audio += frame
            if (heard and quiet >= silence) or count >= most:
                break
            if not heard and count >= wait:
                return b""
        return bytes(audio) if heard else b""


def frames_in(seconds: float) -> int:
    """How many microphone frames cover this many seconds (at least one)."""
    return max(1, math.ceil(seconds * RATE / FRAME - 1e-9))


def rms(frame: bytes) -> float:
    import numpy as np

    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0


class VoiceLoop:
    """Wake word, then one question, then one spoken answer, forever.

    The parts are passed in so the loop can be tested without a microphone:
    wake(frame) says whether the wake word just ended, transcribe(audio)
    returns text, busy() is true while the coach is talking (so it never wakes
    itself up), and chime() tells the player it is listening.
    """

    def __init__(
        self,
        wake: Callable[[bytes], bool],
        transcribe: Callable[[bytes], str],
        answer: Callable[[str], str],
        say: Callable[[str], None],
        busy: Callable[[], bool] = lambda: False,
        chime: Callable[[], None] = lambda: None,
        endpointer: Endpointer | None = None,
        cooldown: float = 3.0,
        wake_word: str = "",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.wake = wake
        self.transcribe = transcribe
        self.answer = answer
        self.say = say
        self.busy = busy
        self.chime = chime
        self.endpointer = endpointer or Endpointer()
        self.cooldown = cooldown
        self.wake_word = wake_word.lower()
        self.clock = clock
        self._ready_at = 0.0

    def run(self, frames: Iterable[bytes]) -> None:
        stream = iter(frames)
        for frame in stream:
            # Keep feeding the detector so it never hears a stale half-word,
            # but ignore it while the coach talks or just after a question.
            woke = self.wake(frame)
            if not woke or self.busy() or self.clock() < self._ready_at:
                continue
            self.chime()
            self.ask(self.endpointer.collect(stream))
            self._ready_at = self.clock() + self.cooldown

    def ask(self, audio: bytes) -> None:
        if not audio:
            return
        text = self.transcribe(audio)
        if self.wake_word:
            # Whisper writes "Hey, coach." as often as "hey coach".
            pattern = r"\W*".join(map(re.escape, self.wake_word.split()))
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)
        text = text.strip(" .,!?")
        if not text:
            return
        log.info("You asked: %s", text)
        self.say(self.answer(text))


class VoskWakeWord:
    """Spots the wake word with Vosk's small English model limited to that phrase."""

    def __init__(self, phrase: str, model_name: str = "vosk-model-small-en-us-0.15") -> None:
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-1)
        self.phrase = phrase.lower()
        # Downloaded once (about 40 MB) to the user's cache folder.
        grammar = json.dumps([self.phrase, "[unk]"])
        self.recognizer = KaldiRecognizer(Model(model_name=model_name), RATE, grammar)

    def __call__(self, frame: bytes) -> bool:
        if self.recognizer.AcceptWaveform(frame):
            text = json.loads(self.recognizer.Result()).get("text", "")
        else:
            text = json.loads(self.recognizer.PartialResult()).get("partial", "")
        if self.phrase in text:
            self.recognizer.Reset()
            return True
        return False


class WhisperTranscriber:
    """Speech to text with faster-whisper on the CPU, kept small so FPS doesn't drop."""

    def __init__(self, model: str = "base.en") -> None:
        from faster_whisper import WhisperModel

        # Downloaded once (about 150 MB for base.en).
        self.model = WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=2)

    def __call__(self, audio: bytes) -> str:
        import numpy as np

        samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = self.model.transcribe(samples, language="en", beam_size=1)
        return " ".join(s.text for s in segments)


def microphone(device: str | int | None = None) -> Iterator[bytes]:
    import sounddevice

    with sounddevice.RawInputStream(
        samplerate=RATE, blocksize=FRAME, dtype="int16", channels=1, device=device or None
    ) as stream:
        while True:
            data, _ = stream.read(FRAME)
            yield bytes(data)


def beep() -> None:
    try:
        import winsound

        winsound.Beep(880, 120)
    except Exception:  # not Windows, or no sound device
        pass


def start(
    settings: dict,
    state: MatchState,
    say: Callable[[str], None],
    busy: Callable[[], bool],
    reminders: dict[str, dict],
    builds: dict[str, list[str]],
) -> threading.Thread | None:
    """Start listening on a background thread, if [listen] is on and installed."""
    if not settings.get("enabled", False):
        return None
    wake_word = str(settings.get("wake_word", "hey coach"))
    try:
        wake = VoskWakeWord(wake_word)
        transcribe = WhisperTranscriber(str(settings.get("model", "base.en")))
    except ImportError:
        log.warning('Voice questions need extra packages:  pip install -e ".[voice]"')
        return None
    except Exception as exc:
        log.warning("Voice questions unavailable (%s)", exc)
        return None
    answers = Answers(reminders, builds)
    loop = VoiceLoop(
        wake,
        transcribe,
        lambda text: answers.answer(text, state.current),
        say,
        busy=busy,
        chime=beep,
        endpointer=Endpointer(
            level=float(settings.get("speech_level", 500)),
            max_seconds=float(settings.get("max_seconds", 5)),
        ),
        cooldown=float(settings.get("cooldown", 3)),
        wake_word=wake_word,
    )

    def run() -> None:
        try:
            loop.run(microphone(settings.get("device") or None))
        except Exception:
            log.exception("Voice questions stopped")

    thread = threading.Thread(target=run, name="voice", daemon=True)
    thread.start()
    log.info('Voice questions on: say "%s", then ask', wake_word)
    return thread
