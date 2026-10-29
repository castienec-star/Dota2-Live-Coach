"""Writes every GSI update of a match to a .jsonl file so it can be replayed.

What the coach said (or skipped as too late) goes in the same file, with the
game clock, so a review can tell what the player actually heard.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any


class MatchRecorder:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path: Path | None = None
        self._file: IO[str] | None = None
        # Updates come from the server, spoken lines from the speaker thread.
        self._lock = threading.Lock()

    def start(self, match_id: str) -> Path:
        self.close()
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.path = self.directory / f"{stamp}-match-{match_id}.jsonl"
        self._file = self.path.open("a", encoding="utf-8")
        return self.path

    def write(self, payload: dict[str, Any]) -> None:
        # The auth token is a local secret; recordings may be shared.
        clean = {k: v for k, v in payload.items() if k != "auth"}
        self._entry({"t": time.time(), "payload": clean})

    def said(self, text: str, clock: int | None, spoken: bool = True) -> None:
        """A line the coach spoke, or skipped because it waited too long."""
        self._entry({"t": time.time(), "said" if spoken else "skipped": text, "clock": clock})

    def _entry(self, entry: dict[str, Any]) -> None:
        with self._lock:
            if self._file is None:
                return
            self._file.write(json.dumps(entry) + "\n")
            self._file.flush()

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None


def read_recording(path: Path) -> Iterator[tuple[float, dict[str, Any]]]:
    """Yield (timestamp, payload) pairs from a recording, in order."""
    for entry in _entries(path):
        if "payload" in entry:
            yield entry["t"], entry["payload"]


def read_lines(path: Path) -> Iterator[tuple[int | None, str, bool]]:
    """Yield (game clock, text, spoken) for each line the coach said or skipped."""
    for entry in _entries(path):
        if "said" in entry:
            yield entry.get("clock"), entry["said"], True
        elif "skipped" in entry:
            yield entry.get("clock"), entry["skipped"], False


def _entries(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)
