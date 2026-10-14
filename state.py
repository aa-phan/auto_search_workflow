"""Persistence for internal state: Boards registry, Events ledger, Runs log.

SheetState keeps them in hidden tabs of the user's Google Sheet (no Git, nothing to maintain);
CsvState is the local fallback. Events and Runs are append-only; Boards is rewritten in a
single atomic request because rows are updated every poll.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import tempfile
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Iterable

from boards import BoardRecord
from ledger import EVENT_COLUMNS, Event

log = logging.getLogger("hunter")

BOARDS_TAB, EVENTS_TAB, RUNS_TAB = "Boards", "Events", "Runs"
BOARD_COLUMNS = [
    "Board_Key", "ATS", "Board", "Status", "Discovered_At", "Source", "Baselined_At",
    "Last_Attempt_At", "Last_Success_At", "Consecutive_Failures", "Last_Job_Count", "Last_Error",
    "Region", "Name", "Validation", "Last_Validated_At", "Relevant_Jobs", "Provenance",
    "Eligible_Jobs", "Relevance_At", "Activity_Since", "Complete_Polls", "Last_New_Relevant_At",
    "New_Relevant_7d", "New_Relevant_30d", "Pool", "Pool_Since", "Trial_Until", "Trials", "Weak_Streak",
    "Pool_Reason",
]  # fmt: skip
DISCOVERY_TAB = "Discovery"
DISCOVERY_COLUMNS = ["Key", "Value", "Updated_At"]  # key -> JSON: rotation cursor, retry queue, last run's queries
INVENTORY_TAB = "Inventory"
INVENTORY_COLUMNS = ["Source", "Fetched_At", "SHA256", "Rows", "As_Of", "Status", "Note"]
RUN_COLUMNS = [
    "Run_At", "Discovery", "Boards_Total", "Boards_OK", "Boards_Failed", "Boards_Added", "New_Jobs",
    "Verified_Fresh", "Evaluated", "Alerts_Sent", "Alerts_Failed", "Gap_Since_Prev_Run_Min",
    "Max_Board_Gap_Min", "Max_Alert_Lag_Min", "Notes",
    "Boards_Discovered", "Boards_Validated", "Boards_Monitored", "Boards_Activated",
    "Search_Queries", "Search_Pages", "Search_Credits", "Search_Repeated", "New_Unique_Boards",
    "Eligible_Boards", "Promoted_Boards", "Verified_Fresh_Matches",
]  # fmt: skip
APPEND_CHUNK = 2000


@dataclass
class RunRecord:
    run_at: str
    discovery: bool = False
    boards_total: int = 0
    boards_ok: int = 0
    boards_failed: int = 0
    boards_added: int = 0
    new_jobs: int = 0
    verified_fresh: int = 0
    evaluated: int = 0
    alerts_sent: int = 0
    alerts_failed: int = 0
    gap_since_prev_run_min: int | None = None
    max_board_gap_min: int | None = None
    max_alert_lag_min: int | None = None
    notes: str = ""
    boards_discovered: int = 0  # every board in the registry
    boards_validated: int = 0  # validated OK (valid or valid-but-empty)
    boards_monitored: int = 0  # actively polled (new + active)
    boards_activated: int = 0  # promoted into monitoring this run
    search_queries: int = 0  # discovery queries started (rotation slots)
    search_pages: int = 0  # result pages fetched
    search_credits: int = 0  # Serper credits spent (1 per page)
    search_repeated: int = 0  # results already returned earlier in the same run
    new_unique_boards: int = 0  # boards in the results that the registry had never seen
    eligible_boards: int = 0  # result boards that passed admission (validated, monitored)
    promoted_boards: int = 0  # result boards promoted into monitoring this run
    verified_fresh_matches: int = 0  # unique result jobs verified fresh and matching the title gate

    def to_row(self) -> list[Any]:
        out = []
        for f in fields(self):
            v = getattr(self, f.name)
            out.append("" if v is None else ("yes" if v is True else "no" if v is False else v))
        return out

    @classmethod
    def from_row(cls, row: list[str]) -> "RunRecord | None":
        if not row or not row[0]:
            return None
        row = list(row) + [""] * (len(RUN_COLUMNS) - len(row))

        def num(i: int) -> int | None:
            try:
                return int(float(row[i]))
            except ValueError:
                return None

        return cls(row[0], row[1] == "yes", num(2) or 0, num(3) or 0, num(4) or 0, num(5) or 0, num(6) or 0, num(7) or 0,
                   num(8) or 0, num(9) or 0, num(10) or 0, num(11), num(12), num(13), row[14],
                   num(15) or 0, num(16) or 0, num(17) or 0, num(18) or 0,
                   *(num(i) or 0 for i in range(19, 27)))  # fmt: skip


def board_to_row(b: BoardRecord) -> list[Any]:
    return [b.key, b.ats, b.board, b.status, b.discovered_at, b.source, b.baselined_at, b.last_attempt_at,
            b.last_success_at, b.consecutive_failures, b.last_job_count, b.last_error,
            b.region, b.name, b.validation, b.last_validated_at, b.relevant_jobs,
            json.dumps(b.provenance, separators=(",", ":"), ensure_ascii=False)[:40000],
            *("" if v is None else v for v in (
                b.eligible_jobs, b.relevance_at, b.activity_since, b.complete_polls, b.last_new_relevant_at,
                b.new_relevant_7d, b.new_relevant_30d, b.pool, b.pool_since, b.trial_until, b.trials, b.weak_streak,
                b.pool_reason[:200])),
            ]  # fmt: skip


def board_from_row(row: list[str]) -> BoardRecord | None:
    if len(row) < 3 or not row[1] or not row[2]:
        return None
    row = list(row) + [""] * (len(BOARD_COLUMNS) - len(row))

    def num(s: str) -> int:
        try:
            return int(float(s))
        except ValueError:
            return 0

    def maybe(s: str) -> int | None:
        """A hand-edited or never-measured cell is unknown (None), never an error and never a silent 0."""
        try:
            return int(float(s))
        except ValueError:
            return None

    try:
        prov = json.loads(row[17]) if row[17] else {}
    except ValueError:
        prov = {}
    return BoardRecord(
        row[1], row[2], row[4], row[5], row[3] or "new", row[6], row[7], row[8], num(row[9]), num(row[10]), row[11],
        row[12], row[13], row[14], row[15], num(row[16]), prov if isinstance(prov, dict) else {},
        maybe(row[18]), row[19], row[20], num(row[21]), row[22], maybe(row[23]), maybe(row[24]),
        row[25], row[26], row[27], num(row[28]), num(row[29]), row[30],
    )  # fmt: skip


def _chunks(rows: list[list[Any]], n: int = APPEND_CHUNK):
    for i in range(0, len(rows), n):
        yield rows[i : i + n]


class SheetState:
    """State in hidden tabs of the user's spreadsheet."""

    UPDATE_CHUNK = 500

    def __init__(self, spreadsheet: Any) -> None:
        self.sh = spreadsheet
        self._row_of: dict[str, int] = {}  # board key -> sheet row, learned at load time

    def ensure(self) -> None:
        tabs = {w.title: w for w in self.sh.worksheets()}
        for title, columns, rows in (
            (BOARDS_TAB, BOARD_COLUMNS, 1000), (EVENTS_TAB, EVENT_COLUMNS, 5000), (RUNS_TAB, RUN_COLUMNS, 1000),
            (INVENTORY_TAB, INVENTORY_COLUMNS, 50), (DISCOVERY_TAB, DISCOVERY_COLUMNS, 20),
        ):  # fmt: skip
            if title in tabs:
                continue
            ws = self.sh.add_worksheet(title=title, rows=rows, cols=len(columns))
            ws.append_rows([columns], value_input_option="RAW")
            try:
                ws.freeze(rows=1)
                ws.hide()  # internal state: out of the user's way, still readable by the script
            except Exception as exc:
                log.warning("Could not tidy the %s tab: %s", title, exc)
            log.info("Created the hidden %s tab", title)
        self._widen_header(BOARDS_TAB, BOARD_COLUMNS)
        self._widen_header(RUNS_TAB, RUN_COLUMNS)

    def _widen_header(self, tab: str, columns: list[str]) -> None:
        """A tab created before newer columns existed gets the new header names
        (header row only; no data row is touched)."""
        try:
            ws = self.sh.worksheet(tab)
            header = ws.row_values(1) if hasattr(ws, "row_values") else []
            if header and header != columns and header == columns[: len(header)]:
                ws.update(values=[columns], range_name="A1", value_input_option="RAW")
        except Exception as exc:  # cosmetic: rows are read positionally either way
            log.warning("Could not widen the %s header: %s", tab, exc)

    def load_boards(self) -> dict[str, BoardRecord]:
        rows = self.sh.worksheet(BOARDS_TAB).get_all_values()[1:]
        self._row_of = {}
        out: dict[str, BoardRecord] = {}
        for i, row in enumerate(rows, start=2):
            b = board_from_row(row)
            if b:
                out[b.key] = b
                self._row_of[b.key] = i
        return out

    def save_boards(self, records: Iterable[BoardRecord]) -> None:
        """Upsert ONLY the given records: known rows are updated in place, unknown ones appended.
        Writers own different rows (the poller owns monitored boards, the importer owns
        candidates), so a long-running writer can never overwrite another's progress."""
        recs = list(records)
        if not recs:
            return
        ws = self.sh.worksheet(BOARDS_TAB)
        updates = [(self._row_of[r.key], r) for r in recs if r.key in self._row_of]
        fresh = [r for r in recs if r.key not in self._row_of]
        if fresh:  # another process may have appended some of these since we loaded: look again
            index = {}
            for i, row in enumerate(ws.get_all_values()[1:], start=2):
                b = board_from_row(row)
                if b:
                    index[b.key] = i
            appended = []
            for r in fresh:
                if r.key in index:
                    updates.append((index[r.key], r))
                    self._row_of[r.key] = index[r.key]
                else:
                    appended.append(r)
            fresh = appended
        for i in range(0, len(updates), self.UPDATE_CHUNK):
            chunk = updates[i : i + self.UPDATE_CHUNK]
            ws.batch_update([{"range": f"A{row}", "values": [board_to_row(r)]} for row, r in chunk], value_input_option="RAW")
        for chunk in _chunks([board_to_row(r) for r in fresh]):
            ws.append_rows(chunk, value_input_option="RAW", table_range="A1")

    def load_events(self) -> list[Event]:
        rows = self.sh.worksheet(EVENTS_TAB).get_all_values()[1:]
        return [e for e in (Event.from_row(r) for r in rows) if e]

    def append_events(self, events: list[Event]) -> None:
        ws = self.sh.worksheet(EVENTS_TAB)
        for chunk in _chunks([e.to_row() for e in events]):
            ws.append_rows(chunk, value_input_option="RAW", table_range="A1")

    def append_run(self, run: RunRecord) -> None:
        self.sh.worksheet(RUNS_TAB).append_rows([run.to_row()], value_input_option="RAW", table_range="A1")

    def load_runs(self) -> list[RunRecord]:
        rows = self.sh.worksheet(RUNS_TAB).get_all_values()[1:]
        return [r for r in (RunRecord.from_row(x) for x in rows) if r]

    # -- discovery bookkeeping (rotation cursor, hydration retry queue, last run's queries)
    def load_discovery_state(self) -> dict[str, str]:
        rows = self.sh.worksheet(DISCOVERY_TAB).get_all_values()[1:]
        return {r[0]: r[1] for r in rows if len(r) >= 2 and r[0]}

    def save_discovery_state(self, values: dict[str, str], stamp: str) -> None:
        """Rewrite the (tiny) tab body in one request. Keys are never removed, only overwritten,
        so a shorter body can never leave stale rows behind."""
        ws = self.sh.worksheet(DISCOVERY_TAB)
        rows = [[k, v[:45000], stamp] for k, v in sorted(values.items())]
        if rows:
            ws.update(values=rows, range_name="A2", value_input_option="RAW")

    # -- inventory bookkeeping (last-known-good metadata per source)
    def load_inventory_meta(self) -> dict[str, dict[str, str]]:
        rows = self.sh.worksheet(INVENTORY_TAB).get_all_values()[1:]
        return {r[0]: dict(zip(INVENTORY_COLUMNS[1:], list(r[1:]) + [""] * 6)) for r in rows if r and r[0]}

    def save_inventory_meta(self, meta: dict[str, dict[str, str]]) -> None:
        ws = self.sh.worksheet(INVENTORY_TAB)
        rows = [[src, *(m.get(c, "") for c in INVENTORY_COLUMNS[1:])] for src, m in sorted(meta.items())]
        if rows:
            ws.update(values=rows, range_name="A2", value_input_option="RAW")


class CsvState:
    """Local-file fallback (development, or Sheets not configured)."""

    def __init__(self, directory: Path) -> None:
        self.dir = directory

    def _path(self, name: str) -> Path:
        return self.dir / f"{name.lower()}.csv"

    def ensure(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        for title, columns in (
            (BOARDS_TAB, BOARD_COLUMNS), (EVENTS_TAB, EVENT_COLUMNS), (RUNS_TAB, RUN_COLUMNS), (INVENTORY_TAB, INVENTORY_COLUMNS),
            (DISCOVERY_TAB, DISCOVERY_COLUMNS),
        ):
            p = self._path(title)
            if not p.exists() or p.stat().st_size == 0:
                with p.open("w", newline="", encoding="utf-8") as fh:
                    csv.writer(fh).writerow(columns)

    def _rows(self, title: str) -> list[list[str]]:
        p = self._path(title)
        if not p.exists():
            return []
        with p.open(newline="", encoding="utf-8") as fh:
            return list(csv.reader(fh))[1:]

    def load_boards(self) -> dict[str, BoardRecord]:
        recs = (board_from_row(r) for r in self._rows(BOARDS_TAB))
        return {b.key: b for b in recs if b}

    def save_boards(self, records: Iterable[BoardRecord]) -> None:
        """Upsert the given records into the registry file (atomic replace)."""
        recs = list(records)
        if not recs:
            return
        boards = self.load_boards()
        for r in recs:
            boards[r.key] = r
        p = self._path(BOARDS_TAB)
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(BOARD_COLUMNS)
            w.writerows(board_to_row(b) for b in sorted(boards.values(), key=lambda b: b.key))
        os.replace(tmp, p)  # atomic

    def load_events(self) -> list[Event]:
        return [e for e in (Event.from_row(r) for r in self._rows(EVENTS_TAB)) if e]

    def append_events(self, events: list[Event]) -> None:
        with self._path(EVENTS_TAB).open("a", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(e.to_row() for e in events)

    def append_run(self, run: RunRecord) -> None:
        with self._path(RUNS_TAB).open("a", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(run.to_row())

    def load_runs(self) -> list[RunRecord]:
        return [r for r in (RunRecord.from_row(x) for x in self._rows(RUNS_TAB)) if r]

    def load_discovery_state(self) -> dict[str, str]:
        return {r[0]: r[1] for r in self._rows(DISCOVERY_TAB) if len(r) >= 2 and r[0]}

    def save_discovery_state(self, values: dict[str, str], stamp: str) -> None:
        p = self._path(DISCOVERY_TAB)
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(DISCOVERY_COLUMNS)
            w.writerows([k, v, stamp] for k, v in sorted(values.items()))
        os.replace(tmp, p)

    def load_inventory_meta(self) -> dict[str, dict[str, str]]:
        return {r[0]: dict(zip(INVENTORY_COLUMNS[1:], list(r[1:]) + [""] * 6)) for r in self._rows(INVENTORY_TAB) if r and r[0]}

    def save_inventory_meta(self, meta: dict[str, dict[str, str]]) -> None:
        p = self._path(INVENTORY_TAB)
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(INVENTORY_COLUMNS)
            w.writerows([src, *(m.get(c, "") for c in INVENTORY_COLUMNS[1:])] for src, m in sorted(meta.items()))
