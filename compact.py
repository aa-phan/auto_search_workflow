"""Compact storage model (DECISIONS D-57): the Identity codec, the Tally rows, the observation split and the merged ledger view.

Pure: no I/O, no Sheets, no clock. state.py imports this module (it persists what is planned here) and the pipeline
calls it, so it must never import state, reporting, storage_report, pipeline or hunter (that would be a cycle).

What leaves the Events ledger as an identity entry is a `seen` event whose disposition is `baseline`, `filtered` or
`stale` (P3-01): its posting ID is all that dedupe needs. Entries are stored per job-key STEM (`ats|board_lowercased`, the
first two `|` segments of the job key), never per `BoardRecord.key` (Lever and Workable keep their case there, job keys do
not) and never per URL (AGENTS rule 3). Only posting IDs, stems and counts are ever written: no titles, URLs, locations or
text (the repository and its logs are public).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import freshness as fr
import ledger as lg

STORAGE_KEY = "storage"  # the Discovery key holding the storage mode (JSON)
IDENTITY_CELL_CHARS = 40_000  # one Identity cell; the Sheets limit is 50,000 characters
IDENTITY_REQUEST_CHARS = 1_000_000  # Identity cell characters in one Sheets write (Google recommends at most 2 MB)
MODE_DUAL, MODE_COMPACT, MODE_RESTORED = "dual", "compact", "restored"
FOLD_AGE = timedelta(days=7)  # a filtered or stale row older than this leaves Events (after cutover); the parity check simulates the same cut
PARITY_DAYS = 3  # complete consecutive UTC days of clean checked runs the bar needs (P3-05)
PARITY_MIN_RUNS_PER_DAY = 12  # checked runs a UTC day needs to count (about half of the hourly runs; DECISIONS D-57)
STORAGE_DAYS_KEPT = 14  # days of parity bookkeeping kept in the `storage` key
MAX_LISTED_DIFFS = 10  # differences named in the `storage` key
MAX_DIFF_CHARS = 200  # one named difference is cut to this many characters (the key must stay far below the 45,000-character Discovery cell cap)

KIND_OF = {lg.BASELINED: "b", lg.FILTERED: "f", lg.STALED: "s"}  # disposition -> one-letter kind prefix of an entry
DISPOSITION_OF = {kind: disposition for disposition, kind in KIND_OF.items()}


# --------------------------------------------------------------------------- identity entries


def identity_class(ev: lg.Event) -> str | None:
    """The disposition (`baseline`, `filtered` or `stale`) when this event is an identity-only observation, else None."""
    if ev.event == lg.SEEN and ev.disposition in KIND_OF:
        return ev.disposition
    return None


def stem_and_id(key: str) -> tuple[str, str] | None:
    """`ats|board|posting id` -> (`ats|board`, posting id). None when the key has fewer than three `|` segments or an empty id:
    such a row cannot be stemmed and always stays in Events."""
    parts = key.split("|", 2)
    if len(parts) < 3 or not parts[2]:
        return None
    return f"{parts[0]}|{parts[1]}", parts[2]


def encode_entry(kind: str, posting_id: str) -> str:
    """One kind letter plus the posting ID with `%` -> `%25` first, then `,` -> `%2C` (entries are comma separated)."""
    return kind + posting_id.replace("%", "%25").replace(",", "%2C")


def decode_entry(entry: str) -> tuple[str, str]:
    """The inverse of `encode_entry`: undo the escapes in the reverse order."""
    return entry[:1], entry[1:].replace("%2C", ",").replace("%25", "%")


def identity_entry(ev: lg.Event) -> tuple[str, str] | None:
    """(stem, encoded entry) for an identity-class event that can be keyed, else None. None means the row always stays in
    Events: its key has fewer than three segments, or its entry alone would not fit one cell."""
    disposition = identity_class(ev)
    parts = stem_and_id(ev.key) if disposition else None
    if disposition is None or parts is None:
        return None
    entry = encode_entry(KIND_OF[disposition], parts[1])
    return None if len(entry) > IDENTITY_CELL_CHARS else (parts[0], entry)


# --------------------------------------------------------------------------- tally


def tally_dim(ev: lg.Event) -> str:
    """The dimension an identity-class observation is counted under: `ats|source|disposition|pass|freshness|date`.
    Source is mapped exactly as `reporting.job_facts` maps it; date is `k` when the publication time parses, else `u`."""
    d = ev.detail
    source = str(d.get("source") or "")
    source = "search" if source in {"serper", "search"} else source or "unknown"
    date = "k" if ev.published and fr.parse_instant(ev.published)[0] is not None else "u"
    return "|".join((ev.key.split("|")[0], source, ev.disposition, str(d.get("pass") or ""), ev.freshness, date))


def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class TallyRow:
    """One row per run that reached the observation write point: the run's identity-class counts."""

    run_id: str
    run_at: str
    total: int
    counts: dict[str, int] = field(default_factory=dict)

    def to_row(self) -> list[str]:
        return [self.run_id, self.run_at, str(self.total), json.dumps(self.counts, sort_keys=True, separators=(",", ":"))]

    @classmethod
    def from_row(cls, row: list[str]) -> "TallyRow | None":
        row = list(row) + [""] * (4 - len(row))
        if not row[1]:
            return None
        try:
            raw = json.loads(row[3]) if row[3] else {}
        except ValueError:
            return None
        if not isinstance(raw, dict):
            return None
        counts = {str(k): n for k, v in raw.items() if (n := _int(v) if not isinstance(v, bool) else None) is not None}
        total = _int(row[2])
        return cls(row[0], row[1], sum(counts.values()) if total is None else total, counts)


# --------------------------------------------------------------------------- identity rows


@dataclass(frozen=True)
class IdentityRow:
    """One chunk of one stem: `Board_Key, Chunk, Baselined_At, Count, IDs`. `row_no` is its sheet (or file) row, 0 when new."""

    stem: str
    chunk: int
    baselined_at: str
    count: int
    ids: str
    row_no: int = 0

    def to_row(self) -> list[str]:
        return [self.stem, str(self.chunk), self.baselined_at, str(self.count), self.ids]

    def entries(self) -> list[str]:
        return [e for e in self.ids.split(",") if e]

    @classmethod
    def from_row(cls, row: list[str], row_no: int = 0) -> "IdentityRow | None":
        row = list(row) + [""] * (5 - len(row))
        chunk = _int(row[1])
        if not row[0] or chunk is None:
            return None
        n = _int(row[3])
        ids = row[4]
        return cls(row[0], chunk, row[2], len([e for e in ids.split(",") if e]) if n is None else n, ids, row_no)


class IdentitySet:
    """Every stem's chunk rows (ordered by chunk) and the posting ID -> kind mapping they hold."""

    def __init__(self) -> None:
        self._rows: dict[str, list[IdentityRow]] = {}
        self._kinds: dict[str, dict[str, str]] = {}

    @classmethod
    def from_rows(cls, rows: Iterable[IdentityRow]) -> "IdentitySet":
        out = cls()
        for r in rows:
            out._rows.setdefault(r.stem, []).append(r)
        for stem in out._rows:
            out._reindex(stem)
        return out

    def _reindex(self, stem: str) -> None:
        rows = sorted(self._rows[stem], key=lambda r: (r.chunk, r.row_no))
        self._rows[stem] = rows
        kinds: dict[str, str] = {}
        for r in rows:
            for entry in r.entries():
                kind, pid = decode_entry(entry)
                kinds.setdefault(pid, kind)
        self._kinds[stem] = kinds

    def copy(self) -> "IdentitySet":
        """An independent snapshot (rows are immutable, so lists and dicts are copied, not the rows)."""
        out = IdentitySet()
        out._rows = {stem: list(rows) for stem, rows in self._rows.items()}
        out._kinds = {stem: dict(kinds) for stem, kinds in self._kinds.items()}
        return out

    def stems(self) -> list[str]:
        return sorted(self._rows)

    def rows(self, stem: str) -> list[IdentityRow]:
        return list(self._rows.get(stem, []))

    def all_rows(self) -> list[IdentityRow]:
        return [r for stem in self.stems() for r in self._rows[stem]]

    def baselined_at(self, stem: str) -> str:
        """The completion marker: the stamp on the stem's highest chunk (blank = the set is incomplete or absent)."""
        rows = self._rows.get(stem)
        return rows[-1].baselined_at if rows else ""

    def keys(self) -> set[str]:
        return {f"{stem}|{pid}" for stem, kinds in self._kinds.items() for pid in kinds}

    def kind(self, key: str) -> str | None:
        split = stem_and_id(key)
        return self._kinds.get(split[0], {}).get(split[1]) if split else None

    def __len__(self) -> int:
        return sum(len(k) for k in self._kinds.values())

    def plan_additions(self, additions: dict[str, list[str]], stamp: str) -> list[IdentityRow]:
        """The chunk rows that change when these entries (already encoded) are added. IDs already present for the stem are
        skipped, so planning the same additions twice adds nothing. The stem's highest chunk is extended while its cell stays
        at most IDENTITY_CELL_CHARS; the overflow opens new chunk numbers; the completion marker (`stamp`) goes on the stem's
        new highest chunk only. Returns only the changed rows, ascending by stem and chunk. Nothing is stored until `apply`."""
        planned: list[IdentityRow] = []
        for stem in sorted(additions):
            known = self._kinds.get(stem, {})
            fresh: list[str] = []
            queued: set[str] = set()
            for entry in additions[stem]:
                _, pid = decode_entry(entry)
                if pid in known or pid in queued or not entry[1:]:
                    continue
                queued.add(pid)
                fresh.append(entry)
            if not fresh:
                continue
            existing = self._rows.get(stem, [])
            if existing:
                last = existing[-1]
                chunk, row_no, marker, cell = last.chunk, last.row_no, last.baselined_at, last.entries()
            else:
                chunk, row_no, marker, cell = 1, 0, "", []
            touched: dict[int, tuple[int, str, list[str]]] = {}  # chunk -> (row_no, marker, entries)
            changed = False  # has the current cell gained an entry (an untouched full chunk is not rewritten)
            size = len(",".join(cell))
            for entry in fresh:
                grown = size + (1 if cell else 0) + len(entry)
                if cell and grown > IDENTITY_CELL_CHARS:
                    if changed:
                        touched[chunk] = (row_no, marker, cell)
                    chunk, row_no, marker, cell, changed, grown = chunk + 1, 0, "", [], False, len(entry)
                cell.append(entry)
                size, changed = grown, True
            touched[chunk] = (row_no, stamp, cell)  # the highest chunk carries the stamp of the write that completed the set
            for number in sorted(touched):
                row_no_, marker_, cell_ = touched[number]
                planned.append(IdentityRow(stem, number, marker_, len(cell_), ",".join(cell_), row_no_))
        return planned

    def apply(self, rows: Iterable[IdentityRow]) -> None:
        """Take over rows that were written successfully (a row keeps the sheet row number the store knew for it)."""
        for r in rows:
            current = self._rows.setdefault(r.stem, [])
            same = [c for c in current if c.chunk == r.chunk]
            if same and not r.row_no:
                r = replace(r, row_no=same[-1].row_no)
            self._rows[r.stem] = [c for c in current if c.chunk != r.chunk] + [r]
            self._reindex(r.stem)


# --------------------------------------------------------------------------- the observation split


@dataclass
class Split:
    events: list[lg.Event]  # what goes to Events, in order
    identity: dict[str, list[str]]  # stem -> encoded entries to add to Identity
    tally: dict[str, int]  # dimension key -> number of identity-class observations of this run


def split_observations(events: Iterable[lg.Event], mode: str) -> Split:
    """Split a run's pending events at the one observation write point. Every identity-class observation is counted in the
    tally; a keyable one also becomes an Identity entry. In compact mode a keyable BASELINE observation is not written to
    Events (P3-02); filtered and stale observations keep their full row, operational rows always stay in Events, and so does
    an identity-class row that cannot be keyed (fewer than three segments, or an entry too long for one cell)."""
    kept: list[lg.Event] = []
    identity: dict[str, list[str]] = defaultdict(list)
    tally: dict[str, int] = defaultdict(int)
    for ev in events:
        disposition = identity_class(ev)
        if disposition is None:
            kept.append(ev)
            continue
        tally[tally_dim(ev)] += 1
        keyed = identity_entry(ev)
        if keyed is None:
            kept.append(ev)  # unkeyable: stays in Events (never folded)
            continue
        identity[keyed[0]].append(keyed[1])
        if not (mode == MODE_COMPACT and disposition == lg.BASELINED):
            kept.append(ev)
    return Split(kept, dict(identity), dict(tally))


# --------------------------------------------------------------------------- reading the Events rows as identity observations


def first_seen_identity(events: Iterable[lg.Event]) -> dict[str, lg.Event]:
    """The first `seen` event of each key, kept only when it is identity-class (the one `replay` lets win; a later `seen` row
    for the same key is a duplicate that Tally and every report ignore)."""
    first: dict[str, lg.Event | None] = {}
    for ev in events:
        if ev.event != lg.SEEN or ev.key in first:
            continue
        first[ev.key] = ev if identity_class(ev) else None
    return {key: ev for key, ev in first.items() if ev is not None}


def tally_recount(events: Iterable[lg.Event]) -> dict[tuple[str, str], Counter[str]]:
    """What Tally should hold for these Events rows: per (run id, run time) the identity-class dimension counts of the
    first-seen rows. Rows written before run ids existed have the blank run id and their own time."""
    out: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for ev in first_seen_identity(events).values():
        out[(str(ev.detail.get("run") or ""), ev.time)][tally_dim(ev)] += 1
    return dict(out)


def parse_stamp(text: Any) -> datetime | None:
    """A ledger stamp (`2026-10-29T17:46:37Z`) as an aware UTC instant; None when it is anything else."""
    try:
        return datetime.strptime(str(text), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def event_time(ev: lg.Event) -> datetime | None:
    """The event Time as an aware UTC instant (None when it is not in the ledger's own stamp format)."""
    return parse_stamp(ev.time)


def simulate_compact(events: list[lg.Event], now: datetime) -> list[lg.Event]:
    """The Events rows a compact store would still hold: minus every keyable baseline `seen` row and minus every keyable
    filtered or stale `seen` row whose Time is at or before `now - FOLD_AGE` (every `seen` row of such a key goes). Unkeyable
    rows and every operational row are always kept. Used by the parity check only; nothing is deleted."""
    cutoff = now - FOLD_AGE
    dropped: set[str] = set()
    for key, ev in first_seen_identity(events).items():
        if identity_entry(ev) is None:
            continue
        when = event_time(ev)
        if identity_class(ev) == lg.BASELINED or (when is not None and when <= cutoff):
            dropped.add(key)
    return [ev for ev in events if not (ev.event == lg.SEEN and ev.key in dropped)]


def retained_events(ledger: "Ledger", now: datetime) -> list[lg.Event]:
    """The Events rows a cutover keeps (P3-06): all of them except every `seen` row of a key whose first observation is a keyable
    baseline, or a keyable filtered or stale row at or before `now - FOLD_AGE`, and only when the key is in Identity (a row whose ID
    Identity does not hold is never dropped, so a cutover can only lose what Identity can give back). Unkeyable rows, operational rows
    and the last seven days of gated rows stay, and the rows keep their order. This is `simulate_compact` plus the Identity condition;
    the parity bar guarantees that the two agree, and the cutover checks it again on the copy."""
    cutoff = now - FOLD_AGE
    held = ledger.identity.keys()
    dropped: set[str] = set()
    for key, ev in first_seen_identity(ledger.events).items():
        if identity_entry(ev) is None or key not in held:
            continue
        when = event_time(ev)
        if identity_class(ev) == lg.BASELINED or (when is not None and when <= cutoff):
            dropped.add(key)
    return [ev for ev in ledger.events if not (ev.event == lg.SEEN and ev.key in dropped)]


def rows_checksum(events: Iterable[lg.Event]) -> str:
    """SHA-256 (hex) of the newline-joined `key|time|event` lines of these rows, in order: what the cutover compares between the rows it
    meant to copy and the rows it read back from the new tab."""
    digest = hashlib.sha256()
    digest.update("\n".join(f"{ev.key}|{ev.time}|{ev.event}" for ev in events).encode("utf-8"))
    return digest.hexdigest()


def cutover_record(now: datetime, *, retained_rows: int, legacy_rows: int, checksum: str, before: dict[str, Any]) -> dict[str, Any]:
    """The `cutover` record of the `storage` key: when, how many rows stayed in Events and how many the old tab holds, the checksum of
    the copy and the before snapshot (`storage_report.before_snapshot`). Counts and hashes only."""
    return {"at": lg.stamp(now.astimezone(timezone.utc)), "retained_rows": retained_rows, "legacy_rows": legacy_rows, "checksum": checksum, "before": before}


def restore_record(now: datetime, *, appended_rows: int | None) -> dict[str, Any]:
    """The `restore` record: when the cutover was undone and how many post-cutover rows the old ledger was given first (None when a rerun only finished the record)."""
    return {"at": lg.stamp(now.astimezone(timezone.utc)), "appended_rows": appended_rows}


FOLD_REQUESTS_PER_BATCH = 500  # `deleteDimension` requests in one spreadsheets.batchUpdate (no documented cap; measured live on the first fold, research A5)


@dataclass(frozen=True)
class FoldPlan:
    """What one fold deletes from Events: the sheet rows (ascending, the numbers loaded at run start) and, per candidate key that stays
    because its durability is not proven yet, the reason: the posting ID is not in the Identity set read at run start, or the
    (Run_ID, Run_At) Tally group is missing or holds fewer observations than Events still retains for it. `row_keys` names the key each
    row must still hold when the delete is sent (the Sheet store checks it, so a shifted row is never deleted)."""

    rows: list[int]
    skipped_not_in_identity: int = 0
    skipped_no_tally: int = 0
    row_keys: dict[int, str] = field(default_factory=dict)

    @property
    def skipped(self) -> int:
        return self.skipped_not_in_identity + self.skipped_no_tally


def fold_plan(ledger: "Ledger", now: datetime) -> FoldPlan:
    """The 7-day fold (P3-03): every `seen` row of each key whose first observation is a keyable `filtered` or `stale` row with Time at or
    before `now - FOLD_AGE`, but only when the key is durable elsewhere: its posting ID is in the Identity set of `ledger` AND its
    (Run_ID, Run_At) Tally group exists with at least as many observations of the row's dimension as Events still retains (the same test as
    `Ledger.negative()`). A candidate failing either test is kept and counted, once per key. Baselines (written to Identity only after the
    cutover) and every operational row are never selected. Pure: `ledger` is the start-of-run snapshot and nothing is changed."""
    if len(ledger.event_rows) != len(ledger.events):
        raise ValueError("the ledger carries no sheet row numbers; refusing to plan a fold")
    cutoff = now - FOLD_AGE
    cutoff_stamp = lg.stamp(cutoff.astimezone(timezone.utc))
    held = ledger.identity.keys()
    totals = ledger.tally_totals()
    retained = ledger.retained_counts()
    selected: set[str] = set()
    not_in_identity = no_tally = 0
    for key, ev in first_seen_identity(ledger.events).items():
        if identity_class(ev) not in (lg.FILTERED, lg.STALED) or identity_entry(ev) is None:
            continue
        if len(ev.time) == len(cutoff_stamp) and ev.time > cutoff_stamp:
            continue  # a well-formed stamp sorts like its instant: younger than the cut (and a malformed one of this length is skipped below anyway); saves parsing most rows
        when = event_time(ev)
        if when is None or when > cutoff:
            continue
        if key not in held:
            not_in_identity += 1
            continue
        group, dim = (str(ev.detail.get("run") or ""), ev.time), tally_dim(ev)
        if group not in totals or totals[group].get(dim, 0) < retained.get(group, Counter()).get(dim, 0):
            no_tally += 1
            continue
        selected.add(key)
    picked = sorted((n, ev.key) for ev, n in zip(ledger.events, ledger.event_rows) if ev.event == lg.SEEN and ev.key in selected)
    return FoldPlan([n for n, _ in picked], not_in_identity, no_tally, dict(picked))


def delete_ranges(rows: Iterable[int]) -> list[tuple[int, int]]:
    """Contiguous inclusive 1-based row ranges `(first, last)` of these sheet rows, the HIGHEST range first: deleting from the bottom up
    leaves every lower row number where the plan found it."""
    out: list[tuple[int, int]] = []
    for n in sorted(set(rows), reverse=True):
        if out and out[-1][0] == n + 1:
            out[-1] = (n, out[-1][1])
        else:
            out.append((n, n))
    return out


def fold_record(previous: dict[str, Any], now: datetime, *, rows: int, skipped: int) -> dict[str, Any]:
    """The `fold` record of the `storage` key after a fold that ran to its end: `last_day` (the UTC day: at most one fold a day),
    `last_rows` and `last_skipped` of this fold, `rows_total` over all folds and `first_day`, set once by the first fold that deleted a row
    (the restore is refused from then on; a fold that deleted nothing changes nothing irreversible). Counts and dates only."""
    total = (_int(previous.get("rows_total")) or 0) + rows
    out: dict[str, Any] = {"last_day": _utc_day(now), "last_rows": rows, "last_skipped": skipped, "rows_total": total}
    first = previous.get("first_day") or (_utc_day(now) if rows > 0 else "")
    if first:
        out["first_day"] = first
    return out


def parse_dim(dim: str) -> dict[str, Any]:
    """The inverse of `tally_dim`: ats, source, disposition, pass, freshness and whether the publication date was known."""
    ats, source, disposition, pass_kind, freshness, date = (dim.split("|") + [""] * 6)[:6]
    return {"ats": ats, "source": source, "disposition": disposition, "pass": pass_kind, "freshness": freshness, "date_known": date == "k"}


@dataclass(frozen=True)
class FoldedCount:
    """Observations that Tally counted but the Events rows no longer hold (`n` > 0), for one run and dimension."""

    run_id: str
    run_at: str
    dim: str
    n: int


# --------------------------------------------------------------------------- the merged view and the mode


@dataclass
class Ledger:
    """What one run loads: the Events rows (with their sheet row numbers), the Identity set and the Tally rows."""

    events: list[lg.Event]
    event_rows: list[int]  # the sheet row of each event above (header = row 1)
    identity: IdentitySet
    tally: list[TallyRow]

    def identity_keys(self) -> set[str]:
        return self.identity.keys()

    def tally_totals(self) -> dict[tuple[str, str], Counter[str]]:
        """The Tally counts per (run id, run time): rows with the same run id and time add up."""
        out: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
        for row in self.tally:
            out[(row.run_id, row.run_at)].update(row.counts)
        return dict(out)

    def retained_counts(self) -> dict[tuple[str, str], Counter[str]]:
        """The same counts recomputed from the Events rows this ledger holds."""
        return tally_recount(self.events)

    def folded(self) -> list[FoldedCount]:
        """Tally minus the retained recount, per (run id, run time, dimension), only where positive: the observations that
        no longer have an Events row. Nothing is folded in dual mode, so the list is empty there."""
        retained = self.retained_counts()
        out = []
        for (run_id, run_at), counts in sorted(self.tally_totals().items()):
            have = retained.get((run_id, run_at), Counter())
            out += [FoldedCount(run_id, run_at, dim, n - have.get(dim, 0)) for dim, n in sorted(counts.items()) if n > have.get(dim, 0)]
        return out

    def negative(self) -> list[FoldedCount]:
        """Where Tally is BELOW the retained recount (a Tally write was lost); `n` is the shortfall."""
        totals = self.tally_totals()
        out = []
        for (run_id, run_at), have in sorted(self.retained_counts().items()):
            counts = totals.get((run_id, run_at), Counter())
            out += [FoldedCount(run_id, run_at, dim, n - counts.get(dim, 0)) for dim, n in sorted(have.items()) if n > counts.get(dim, 0)]
        return out


@dataclass
class Repair:
    """What the stores lack compared with the Events rows: Identity entries (encoded, by stem) and whole Tally runs."""

    identity: dict[str, list[str]] = field(default_factory=dict)
    tally: list[TallyRow] = field(default_factory=list)

    @property
    def ids(self) -> int:
        return sum(len(v) for v in self.identity.values())

    def __bool__(self) -> bool:
        return bool(self.identity or self.tally)


def repair_plan(ledger: Ledger) -> Repair:
    """Identity entries for every keyable identity-class Events row whose key Identity lacks, and one Tally row for every
    (run id, run time) group that has identity-class Events rows but no Tally row. Idempotent: planning again after the writes
    gives an empty plan, so an interrupted seed is completed without writing an ID or a group twice."""
    known = ledger.identity.keys()
    identity: dict[str, list[str]] = defaultdict(list)
    for key, ev in first_seen_identity(ledger.events).items():
        keyed = identity_entry(ev)
        if keyed is not None and key not in known:
            identity[keyed[0]].append(keyed[1])
    have = {(row.run_id, row.run_at) for row in ledger.tally}
    tally = [
        TallyRow(run_id, run_at, sum(counts.values()), dict(sorted(counts.items())))
        for (run_id, run_at), counts in sorted(tally_recount(ledger.events).items(), key=lambda kv: (kv[0][1], kv[0][0]))
        if (run_id, run_at) not in have
    ]
    return Repair(dict(identity), tally)


NOTE_CUTOVER_INCOMPLETE = "storage cutover incomplete: run storage_cutover again; "  # the run note when Events_Legacy exists but the `storage` key still says dual
NOTE_COMPACT_WITHOUT_LEGACY = "storage state: compact without Events_Legacy, writing as dual; "  # the run note when the key says compact but the old tab is gone


class ModeDecision(str):
    """The storage mode a run writes in (a `str`, so every caller that compares it with MODE_DUAL, MODE_COMPACT or MODE_RESTORED keeps
    working) plus `note`: the run note that says why the stored state was not taken at its word (empty when it was)."""

    note: str

    def __new__(cls, mode: str, note: str = "") -> "ModeDecision":
        out = super().__new__(cls, mode)
        out.note = note
        return out


def effective_mode(raw: str | None, *, legacy_present: bool) -> ModeDecision:
    """The storage mode a run writes in. `compact` applies only when the `storage` key says so AND `Events_Legacy` exists; every
    state that does not add up writes as `dual`, the safe direction (everything still goes to Events), and says why in `note`:
    the key says compact but the old tab is gone (`NOTE_COMPACT_WITHOUT_LEGACY`), or the old tab exists while the key still says
    dual, a cutover that was interrupted between the tab rename and the key write (`NOTE_CUTOVER_INCOMPLETE`). In both the run
    records no parity check and no clock (the pipeline skips them) until the owner repairs the state. `restored` is kept as it is."""
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        data = {}
    mode = data.get("mode") if isinstance(data, dict) else None
    if mode == MODE_RESTORED:
        return ModeDecision(MODE_RESTORED)
    if mode == MODE_COMPACT:
        return ModeDecision(MODE_COMPACT) if legacy_present else ModeDecision(MODE_DUAL, NOTE_COMPACT_WITHOUT_LEGACY)
    return ModeDecision(MODE_DUAL, NOTE_CUTOVER_INCOMPLETE if legacy_present else "")


# --------------------------------------------------------------------------- the `storage` key (parity bookkeeping)


DAY_FIELDS = ("runs", "diff_runs", "failed", "admissions")


def _utc_day(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _clean_days(raw: Any) -> dict[str, dict[str, int]]:
    days: dict[str, dict[str, int]] = {}
    if isinstance(raw, dict):
        for day, rec in raw.items():
            if isinstance(day, str) and isinstance(rec, dict):
                days[day] = {k: (n if (n := _int(rec.get(k)) if not isinstance(rec.get(k), bool) else None) is not None else 0) for k in DAY_FIELDS}
    return days


@dataclass(frozen=True)
class BarStatus:
    """Where the parity bar stands (P3-05): the clean complete UTC days counted so far (at most PARITY_DAYS), whether the bar is
    met, whether one of the counted days saw a board admission, and the length of the clean streak that ends yesterday."""

    days_counted: int
    met: bool
    admission_seen: bool
    streak: int


def _dict(raw: Any) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


@dataclass
class StorageState:
    """The Discovery key `storage` (JSON): the storage mode, when the stores were seeded and the parity clock. Reading is
    tolerant: blank, truncated or hand-edited JSON gives a fresh state (never seeded, no clean day), so nothing is assumed met.

    `days` is keyed by the UTC date of the run's start: `runs` (checked runs), `diff_runs` (runs with a counted difference or a
    failed check), `failed` (checks that raised) and `admissions` (boards promoted into monitoring in the checked runs). The
    records `cutover`, `fold` and `restore` stay empty here; later plans fill them and this class preserves them."""

    mode: str = MODE_DUAL
    seeded_at: str | None = None
    days: dict[str, dict[str, int]] = field(default_factory=dict)
    bar_met_at: str | None = None
    last_check: dict[str, Any] = field(default_factory=dict)
    last_diffs: list[str] = field(default_factory=list)
    cutover: dict[str, Any] = field(default_factory=dict)
    fold: dict[str, Any] = field(default_factory=dict)
    restore: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)  # fields this version does not know, kept as they were

    _KNOWN = ("mode", "seeded_at", "days", "bar_met_at", "last_check", "last_diffs", "cutover", "fold", "restore")

    @classmethod
    def load(cls, raw: str | None) -> "StorageState":
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        mode = data.get("mode")
        seeded = data.get("seeded_at")
        met = data.get("bar_met_at")
        diffs = data.get("last_diffs")
        return cls(
            mode=mode if mode in (MODE_DUAL, MODE_COMPACT, MODE_RESTORED) else MODE_DUAL,
            seeded_at=seeded if isinstance(seeded, str) and seeded else None,
            days=_clean_days(data.get("days")),
            bar_met_at=met if isinstance(met, str) and met else None,
            last_check=_dict(data.get("last_check")),
            last_diffs=[x for x in diffs if isinstance(x, str)] if isinstance(diffs, list) else [],
            cutover=_dict(data.get("cutover")),
            fold=_dict(data.get("fold")),
            restore=_dict(data.get("restore")),
            extra={k: v for k, v in data.items() if k not in cls._KNOWN},
        )

    def to_json(self) -> str:
        body = {
            **self.extra, "mode": self.mode, "seeded_at": self.seeded_at, "days": self.days, "bar_met_at": self.bar_met_at,
            "last_check": self.last_check, "last_diffs": self.last_diffs, "cutover": self.cutover, "fold": self.fold, "restore": self.restore,
        }  # fmt: skip
        return json.dumps(body, sort_keys=True, separators=(",", ":"))

    def record_check(
        self, now: datetime, *, counted: int, declared: int, admissions: int, failed: bool = False, diffs: Iterable[str] = (),
        compared: int = 0, seconds: float = 0.0,
    ) -> None:  # fmt: skip
        """Record one checked run under the UTC day it started in (a run at 00:00:00 UTC is in the new day). A counted difference
        or a failed check restarts the clock: it makes the day unclean and clears `bar_met_at`. `diffs` are the named differences
        (at most MAX_LISTED_DIFFS kept, each cut to MAX_DIFF_CHARS); days older than STORAGE_DAYS_KEPT are dropped."""
        day = self.days.setdefault(_utc_day(now), dict.fromkeys(DAY_FIELDS, 0))
        day["runs"] += 1
        if counted > 0 or failed:
            day["diff_runs"] += 1
            self.bar_met_at = None
        if failed:
            day["failed"] += 1
        day["admissions"] += max(0, admissions)
        self.last_check = {"at": lg.stamp(now.astimezone(timezone.utc)), "counted": counted, "declared": declared, "compared": compared, "seconds": round(seconds, 1)}
        self.last_diffs = [str(text)[:MAX_DIFF_CHARS] for text in list(diffs)[:MAX_LISTED_DIFFS]]
        for old in sorted(self.days)[:-STORAGE_DAYS_KEPT]:
            del self.days[old]
        if self.bar_met_at is None and counted == 0 and not failed and self.bar(now).met:
            self.bar_met_at = lg.stamp(now.astimezone(timezone.utc))

    def fold_due(self, now: datetime) -> bool:
        """May a fold start at `now` (P3-03)? Only in stored mode `compact`, only on a UTC day AFTER the UTC day of the cutover (the restore
        stays possible for the rest of that day), and at most once a UTC day (`fold.last_day`). A cutover record without a readable time never folds."""
        cut = parse_stamp(self.cutover.get("at"))
        if self.mode != MODE_COMPACT or cut is None:
            return False
        today = _utc_day(now)
        return today > _utc_day(cut) and self.fold.get("last_day") != today

    def bar(self, now: datetime) -> BarStatus:
        """Apply the bar to the complete UTC days before `now`'s day, newest first: a day counts only when it started after
        `seeded_at` (the seed day never counts), has at least PARITY_MIN_RUNS_PER_DAY checked runs and not one run with a
        difference. The bar is met when the PARITY_DAYS most recent complete days all count and one of them saw an admission.
        The current, incomplete day never counts, but a difference found today blocks the bar at once (P3-07: any difference
        restarts the clock, and today can never become one of the counted days)."""
        try:
            seeded = datetime.strptime(self.seeded_at or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return BarStatus(0, False, False, 0)
        today = now.astimezone(timezone.utc).date()
        counted: list[dict[str, int]] = []
        for back in range(1, STORAGE_DAYS_KEPT + 1):
            day = today - timedelta(days=back)
            rec = self.days.get(day.isoformat())
            started = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
            if rec is None or started <= seeded or rec["runs"] < PARITY_MIN_RUNS_PER_DAY or rec["diff_runs"] > 0:
                break
            counted.append(rec)
        streak = len(counted)
        admission = any(rec["admissions"] > 0 for rec in counted[:PARITY_DAYS])
        dirty_today = self.days.get(today.isoformat(), {}).get("diff_runs", 0) > 0
        return BarStatus(min(streak, PARITY_DAYS), streak >= PARITY_DAYS and admission and not dirty_today, admission, streak)
