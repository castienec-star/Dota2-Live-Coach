"""Writes every GSI update of a match to a .jsonl file so it can be replayed."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any


class MatchRecorder:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path: Path | None = None
        self._file: IO[str] | None = None

    def start(self, match_id: str) -> Path:
        self.close()
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.path = self.directory / f"{stamp}-match-{match_id}.jsonl"
        self._file = self.path.open("a", encoding="utf-8")
        return self.path

    def write(self, payload: dict[str, Any]) -> None:
        if self._file is None:
            return
        # The auth token is a local secret; recordings may be shared.
        clean = {k: v for k, v in payload.items() if k != "auth"}
        self._file.write(json.dumps({"t": time.time(), "payload": clean}) + "\n")
        self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


def read_recording(path: Path) -> Iterator[tuple[float, dict[str, Any]]]:
    """Yield (timestamp, payload) pairs from a recording, in order."""
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                entry = json.loads(line)
                yield entry["t"], entry["payload"]
