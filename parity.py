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

4. The reported figures (plan 03-03): the Dashboard summary, the pilot reconciliation over a 7-day and an all-time window and the
   storage logical counts, each computed from all Events rows and again from the compact view (kept rows, Identity and Tally),
   with identical arguments. A tracker row that matches only an identity-only job is removed from both sides and declared
   (`tracker_identity_job`), because the compact side no longer holds that job (D-57, Pitfall 9).

A Diff names a job key, a run id with its time, a dimension key, a counter name or the dotted path of a figure, and its detail holds
numbers only: never a title, URL, location or any tracker text (the repository is public).
"""

from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, Iterable

import compact
import ledger as lg
import reporting as rp
import storage_report
from boards import parse_job_url


@dataclass(frozen=True)
class Diff:
    layer: int  # 1 seen set, 2 Tally recount, 3 state counts, 4 figures; 0 for a check that could not run
    kind: str
    ref: str  # a job key, `<run_id>@<run_at>` (optionally followed by a dimension key), a stem and chunk, a counter name or a figure's dotted path
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


PRESENTATION_KEYS = (("storage",),)  # summary sections that only present the storage state (plan 03-04); never compared
ROW_COUNT_FIGURES = frozenset({"source_freshness.ledger_events_read", "source_freshness.latest_ledger_event", "exclusions.events_from_rehearsal_runs"})
ALL_TIME_START = datetime(2020, 1, 1, tzinfo=timezone.utc)  # the all-time reconciliation window starts before any ledger row
RECONCILE_WINDOWS = (("7d", timedelta(days=7)), ("all", None))
_PATH_SEGMENT = re.compile(r"[^A-Za-z0-9_.:|@-]")


def _segment(key: Any) -> str:
    """One path segment of a figure: the dictionary key or list index, restricted to harmless characters and cut short, so a path
    can never carry free text into the storage key, the notes or the log."""
    return _PATH_SEGMENT.sub("?", str(key))[:40]


def _number(value: Any) -> str:
    """A figure as it may appear in a difference: a number, `none`, or the word `text` (a string is never copied)."""
    if value is None:
        return "none"
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, (int, float)):
        return f"{value:g}"
    return "text"


def _leaves(old: Any, new: Any, path: tuple[str, ...], out: list[tuple[tuple[str, ...], Any, Any]], skip: Iterable[tuple[str, ...]]) -> int:
    """Walk two figure trees together; append (path, old, new) for every leaf (or list length) that differs. Returns the number of
    leaves compared."""
    if path in skip:
        return 0
    if isinstance(old, dict) and isinstance(new, dict):
        return sum(_leaves(old.get(k), new.get(k), (*path, _segment(k)), out, skip) for k in sorted(old.keys() | new.keys(), key=str))
    if isinstance(old, (list, tuple)) and isinstance(new, (list, tuple)):
        compared = 1
        if len(old) != len(new):
            out.append(((*path, "length"), len(old), len(new)))
        for i, (a, b) in enumerate(zip(old, new)):
            compared += _leaves(a, b, (*path, str(i)), out, skip)
        return compared
    if old != new:
        out.append((path, old, new))
    return 1


def compare_figures(old: dict[str, Any], new: dict[str, Any], *, prefix: str = "", skip: Iterable[tuple[str, ...]] = PRESENTATION_KEYS, compared: list[int] | None = None) -> list[Diff]:
    """Layer 4 for one pair of figure trees (summary, reconciliation or logical counts): every differing leaf is a counted `figure`
    Diff named by its dotted path (`periods.7d.results.new_postings`), with `old` and `new` as numbers only. Paths in `skip`
    are presentation and are not compared. `compared[0]` receives the number of leaves compared."""
    out: list[tuple[tuple[str, ...], Any, Any]] = []
    n = _leaves(old, new, (), out, tuple(skip))
    if compared is not None:
        compared.append(n)
    head = (prefix,) if prefix else ()
    return [Diff(4, "figure", ".".join((*head, *path)), f"old {_number(a)} new {_number(b)}") for path, a, b in out]


def _tracker_without_identity_only_jobs(events: list[lg.Event], ledger: compact.Ledger, tracker: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[Diff]]:
    """Pitfall 9: a hand-added tracker row for a job that only Identity (or Tally) holds changes the tracker join between the two
    sides. Such a row (its parsed job key, or its exact stored URL, names a job that has no row left in the compact view) is
    removed from both sides and listed as declared `tracker_identity_job`, so it cannot flap the clock."""
    kept_keys = {ev.key for ev in ledger.events}
    gone: dict[str, lg.Event] = {}
    for ev in events:
        if ev.event == lg.SEEN and ev.key not in kept_keys and ev.key not in gone:
            gone[ev.key] = ev
    if not gone:
        return list(tracker), []
    gone_urls = {str(ev.detail.get("url") or "").strip(): key for key, ev in sorted(gone.items(), reverse=True) if str(ev.detail.get("url") or "").strip()}
    kept_urls = {str(ev.detail.get("url") or "").strip() for ev in ledger.events if ev.event in (lg.SEEN, lg.EVALUATED)}
    rows: list[dict[str, str]] = []
    diffs: list[Diff] = []
    for row in tracker:
        url = (row.get("Apply_URL") or "").strip()
        ident = parse_job_url(url)
        match = ident.key if ident is not None and ident.key in gone else gone_urls.get(url) if url and url not in kept_urls and not (ident is not None and ident.key in kept_keys) else None
        if match is None:
            rows.append(row)
        else:
            diffs.append(Diff(4, "tracker_identity_job", match, declared=True))
    return rows, diffs


def _figures(events: list[lg.Event], ledger: compact.Ledger, now: datetime, tz: tzinfo, runs: list[Any], boards: dict[str, Any], discovery: dict[str, str],
             tracker: list[dict[str, str]], compared: dict[str, int]) -> list[Diff]:  # fmt: skip
    """Layer 4. The same arguments go to both sides; only the events differ (all rows, or the compact view with its folded counts)."""
    rows, diffs = _tracker_without_identity_only_jobs(events, ledger, tracker)
    folded = ledger.folded()
    seen_rows = Counter(ev.key for ev in events if ev.event == lg.SEEN)
    kept_keys = {ev.key for ev in ledger.events}
    row_counts_differ = any(n > 1 and key not in kept_keys for key, n in seen_rows.items())  # a duplicate row of a folded key: the two sides hold different numbers of rows

    def add(found: list[Diff]) -> None:
        for d in found:
            diffs.append(Diff(d.layer, d.kind, d.ref, d.detail, declared=row_counts_differ and d.ref in ROW_COUNT_FIGURES))

    args: dict[str, Any] = {"runs": runs, "boards": boards, "discovery": discovery, "tracker": rows}
    leaves: list[int] = []
    old = rp.build_summary(now=now, tz=tz, events=events, **args)
    new = rp.build_summary(now=now, tz=tz, events=ledger.events, folded=folded, **args)
    add(compare_figures(old, new, compared=leaves))
    compared["figures_summary"] = leaves[-1]
    for label, span in RECONCILE_WINDOWS:
        window = {"start": now - span if span else ALL_TIME_START, "end": now}
        a = rp.reconcile(runs=runs, events=events, tracker=rows, **window)
        b = rp.reconcile(runs=runs, events=ledger.events, tracker=rows, folded=folded, **window)
        add(compare_figures(a, b, prefix=f"reconcile.{label}", skip=(), compared=leaves))
        compared[f"figures_reconcile_{label}"] = leaves[-1]
    a = storage_report.logical_counts(events)
    b = storage_report.logical_counts(ledger.events, folded=folded, identity=ledger.identity)
    add(compare_figures(a, b, prefix="logical", skip=(), compared=leaves))
    compared["figures_logical"] = leaves[-1]
    return diffs


def check_dual(
    events: list[lg.Event], ledger: compact.Ledger, *, now: datetime, tz: tzinfo = timezone.utc, runs: Iterable[Any] = (),
    boards: dict[str, Any] | None = None, discovery: dict[str, str] | None = None, tracker: Iterable[dict[str, str]] = (),
) -> ParityReport:  # fmt: skip
    """Compare the full Events rows with the compact view `ledger` (see the module docstring). Every difference is returned;
    `counted` and `declared` tell them apart. `now` is the run's own clock (the state counts ask whether an alert is due); `tz`,
    `runs`, `boards`, `discovery` and `tracker` are what the Dashboard is built from (layer 4), identical on both sides."""
    t0 = time.monotonic()
    compared: dict[str, int] = {}
    diffs = _seen_set(events, ledger, compared) + _tally(events, ledger, compared) + _state_counts(events, ledger, now, compared)
    diffs += _figures(events, ledger, now, tz, list(runs), boards or {}, discovery or {}, list(tracker), compared)
    return ParityReport(diffs, compared, round(time.monotonic() - t0, 2))
