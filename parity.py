"""Storage parity (DECISIONS D-57, P3-05 and P3-07): does the compact storage say what the Events rows say?

Pure and read-only: no I/O, no clock, no Sheets. It imports `compact` and `ledger` only (never state, pipeline or hunter), so
the pipeline can run it inside a poll and the command line can run it on a fresh load. During dual writing `Events` holds
every row and stays authoritative: a difference found here marks the run degraded and restarts the three-day clock, but
nothing in this module can change detection, evaluation or alerts.

`check_dual(events, ledger, now=...)` compares the full Events rows (`events`) with a compact view of the same rows (`ledger`:
the simulated compact Events rows plus the Identity set and Tally rows that were actually stored). Three layers:

1. The seen set: every keyable identity-class Events key is in Identity and every Identity key has such an Events row (both
   directions); kind letters, `Count`, cell size, the completion marker, duplicate IDs and the stem round trip are right.
2. The Tally recount: per (Run_ID, Run_At, dimension) Tally equals the count recomputed from the Events rows.
3. The state counts: jobs awaiting evaluation or alert, error attempts and abandoned stages, computed from `replay` of all
   Events rows and again from `replay` of the compact view.

Layer 4 (the reported figures) arrives with plan 03-03. A Diff names a job key, a run id with its time, a dimension key or a
counter name, and its detail holds numbers only: never a title, URL, location or any tracker text (the repository is public).
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

import compact
import ledger as lg


@dataclass(frozen=True)
class Diff:
    layer: int  # 1 seen set, 2 Tally recount, 3 state counts; 0 for a check that could not run
    kind: str
    ref: str  # a job key, `<run_id>@<run_at>` (optionally followed by a dimension key), a stem and chunk, or a counter name
    detail: str = ""  # numbers only
    declared: bool = False  # listed but not counted: stays in Events forever, so nothing is lost

    def text(self) -> str:
        return f"{self.kind} {self.ref}" + (f" ({self.detail})" if self.detail else "")


@dataclass
class ParityReport:
    diffs: list[Diff] = field(default_factory=list)
    compared: dict[str, int] = field(default_factory=dict)  # what was compared: seen keys, Identity entries, Tally groups, state counters
    seconds: float = 0.0

    @property
    def counted(self) -> int:
        return sum(1 for d in self.diffs if not d.declared)

    @property
    def declared(self) -> int:
        return sum(1 for d in self.diffs if d.declared)

    def kinds(self) -> dict[str, int]:
        """Counted differences per kind, largest first."""
        counts = Counter(d.kind for d in self.diffs if not d.declared)
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    def named(self, limit: int) -> list[str]:
        """The first `limit` counted differences as text (what the `storage` key stores)."""
        return [d.text() for d in self.diffs if not d.declared][:limit]


def _group(run_id: str, run_at: str) -> str:
    return f"{run_id}@{run_at}"


def _seen_set(events: list[lg.Event], ledger: compact.Ledger, compared: dict[str, int]) -> list[Diff]:
    """Layer 1."""
    out: list[Diff] = []
    ident = ledger.identity
    seen_rows = Counter(ev.key for ev in events if ev.event == lg.SEEN)
    keyable: dict[str, tuple[str, str, lg.Event]] = {}  # key -> (stem, entry, first-seen event)
    for key, ev in sorted(compact.first_seen_identity(events).items()):
        keyed = compact.identity_entry(ev)
        if keyed is None:
            out.append(Diff(1, "unkeyable", key, declared=True))
        else:
            keyable[key] = (keyed[0], keyed[1], ev)
    out += [Diff(1, "duplicate_seen", key, f"{n} rows", declared=True) for key, n in sorted(seen_rows.items()) if n > 1]
    stored = ident.keys()
    out += [Diff(1, "identity_missing", key) for key in sorted(keyable.keys() - stored)]
    out += [Diff(1, "identity_extra", key) for key in sorted(stored - keyable.keys())]
    for key in sorted(keyable.keys() & stored):
        stem, entry, ev = keyable[key]
        if ident.kind(key) != compact.KIND_OF[ev.disposition]:
            out.append(Diff(1, "identity_kind", key))
        if f"{stem}|{compact.decode_entry(entry)[1]}" != key:
            out.append(Diff(1, "stem", key))
    entries = 0
    for row in ident.all_rows():
        found = row.entries()
        entries += len(found)
        if row.count != len(found):
            out.append(Diff(1, "identity_count", f"{row.stem}#{row.chunk}", f"{row.count} vs {len(found)}"))
        if len(row.ids) > compact.IDENTITY_CELL_CHARS:
            out.append(Diff(1, "identity_cell", f"{row.stem}#{row.chunk}", f"{len(row.ids)} characters"))
    for stem in ident.stems():
        if not ident.baselined_at(stem):
            out.append(Diff(1, "identity_marker", stem))
        ids = Counter(compact.decode_entry(e)[1] for row in ident.rows(stem) for e in row.entries())
        out += [Diff(1, "identity_duplicate", f"{stem}|{pid}", f"{n} entries") for pid, n in sorted(ids.items()) if n > 1]
    compared["seen_keys"] = len(seen_rows)
    compared["identity_entries"] = entries
    return out


def _tally(events: list[lg.Event], ledger: compact.Ledger, compared: dict[str, int]) -> list[Diff]:
    """Layer 2."""
    out: list[Diff] = []
    want = compact.tally_recount(events)
    have = ledger.tally_totals()
    recorded: Counter[tuple[str, str]] = Counter()
    for row in ledger.tally:
        recorded[(row.run_id, row.run_at)] += row.total
    out += [Diff(2, "tally_missing", _group(*g), f"{sum(want[g].values())} observations") for g in sorted(want.keys() - have.keys())]
    out += [Diff(2, "tally_orphan", _group(*g), f"{recorded[g]} counted") for g in sorted(have.keys() - want.keys()) if recorded[g] > 0 or sum(have[g].values()) > 0]
    for g in sorted(want.keys() & have.keys()):
        for dim in sorted(set(want[g]) | set(have[g])):
            if want[g].get(dim, 0) != have[g].get(dim, 0):
                out.append(Diff(2, "tally_count", f"{_group(*g)} {dim}", f"{have[g].get(dim, 0)} vs {want[g].get(dim, 0)}"))
    for g in sorted(have.keys() & want.keys()):
        if recorded[g] != sum(have[g].values()):
            out.append(Diff(2, "tally_count", f"{_group(*g)} total", f"{recorded[g]} vs {sum(have[g].values())}"))
    compared["tally_groups"] = len(want.keys() | have.keys())
    return out


def _state_counters(events: list[lg.Event], now: datetime) -> Counter[str]:
    counters: Counter[str] = Counter({"awaiting_evaluation": 0, "awaiting_alert": 0})
    for st in lg.replay(events).values():
        counters["awaiting_evaluation"] += lg.needs_evaluation(st)
        counters["awaiting_alert"] += lg.needs_alert(st, now)
        for stage, attempts in st.errors.items():
            counters[f"error_attempts:{stage}"] += attempts
        for stage in st.abandoned:
            counters[f"abandoned:{stage}"] += 1
    return counters


def _state_counts(events: list[lg.Event], ledger: compact.Ledger, now: datetime, compared: dict[str, int]) -> list[Diff]:
    """Layer 3."""
    old = _state_counters(events, now)
    new = _state_counters(ledger.events, now)
    names = sorted(old.keys() | new.keys())
    compared["state_counters"] = len(names)
    return [Diff(3, "state_counts", name, f"{new.get(name, 0)} vs {old.get(name, 0)}") for name in names if old.get(name, 0) != new.get(name, 0)]


def check_dual(events: list[lg.Event], ledger: compact.Ledger, *, now: datetime) -> ParityReport:
    """Compare the full Events rows with the compact view `ledger` (see the module docstring). Every difference is returned;
    `counted` and `declared` tell them apart. `now` is the run's own clock (the state counts ask whether an alert is due)."""
    t0 = time.monotonic()
    compared: dict[str, int] = {}
    diffs = _seen_set(events, ledger, compared) + _tally(events, ledger, compared) + _state_counts(events, ledger, now, compared)
    return ParityReport(diffs, compared, round(time.monotonic() - t0, 2))
