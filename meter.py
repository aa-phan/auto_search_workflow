"""Process-wide request and timing counters for run diagnostics (no I/O, no dependencies).

The pipeline reads a snapshot at the start of a run and again at the end; the difference is stored in the
Runs tab so the limits of the deployment (Google Sheets quota, provider rate limits, run time) can be audited
from measured values at the end of the pilot instead of guessed."""

from __future__ import annotations

import threading


class Meter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, float] = {}

    def add(self, name: str, amount: float = 1) -> None:
        with self._lock:
            self._counts[name] = self._counts.get(name, 0) + amount

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return dict(self._counts)

    def since(self, before: dict[str, float]) -> dict[str, float]:
        now = self.snapshot()
        return {k: now[k] - before.get(k, 0) for k in now if now[k] - before.get(k, 0)}


METER = Meter()
