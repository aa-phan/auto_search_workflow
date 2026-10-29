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

import json
from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import Any, Iterable

import freshness as fr
import ledger as lg

STORAGE_KEY = "storage"  # the Discovery key holding the storage mode (JSON)
IDENTITY_CELL_CHARS = 40_000  # one Identity cell; the Sheets limit is 50,000 characters
IDENTITY_REQUEST_CHARS = 1_000_000  # Identity cell characters in one Sheets write (Google recommends at most 2 MB)
MODE_DUAL, MODE_COMPACT, MODE_RESTORED = "dual", "compact", "restored"

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
        parts = stem_and_id(ev.key)
        entry = encode_entry(KIND_OF[disposition], parts[1]) if parts else ""
        if parts is None or len(entry) > IDENTITY_CELL_CHARS:
            kept.append(ev)  # unkeyable: stays in Events (never folded)
            continue
        identity[parts[0]].append(entry)
        if not (mode == MODE_COMPACT and disposition == lg.BASELINED):
            kept.append(ev)
    return Split(kept, dict(identity), dict(tally))


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


def effective_mode(raw: str | None, *, legacy_present: bool) -> str:
    """The storage mode a run writes in. `compact` applies only when the `storage` key says so AND `Events_Legacy` exists;
    otherwise the run writes as `dual`, the safe direction (everything still goes to Events)."""
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        return MODE_DUAL
    mode = data.get("mode") if isinstance(data, dict) else None
    if mode == MODE_COMPACT and legacy_present:
        return MODE_COMPACT
    if mode == MODE_RESTORED:
        return MODE_RESTORED
    return MODE_DUAL
