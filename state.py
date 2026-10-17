"""Persistence for internal state: Boards registry, Events ledger, Runs log.

SheetState keeps them in hidden tabs of the user's Google Sheet (no Git, nothing to maintain);
CsvState is the local fallback. Events and Runs are append-only; Boards rows are upserted in a
request per chunk because rows are updated every poll (row-level, never a full rewrite).
"""

from __future__ import annotations

import csv
import fcntl
import json
import logging
import os
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Iterable

from boards import STAMP, BoardRecord, merge_provenance
from ledger import EVENT_COLUMNS, Event

log = logging.getLogger("hunter")

BOARDS_TAB, EVENTS_TAB, RUNS_TAB = "Boards", "Events", "Runs"
BOARD_COLUMNS = [
    "Board_Key", "ATS", "Board", "Status", "Discovered_At", "Source", "Baselined_At",
    "Last_Attempt_At", "Last_Success_At", "Consecutive_Failures", "Last_Job_Count", "Last_Error",
    "Region", "Name", "Validation", "Last_Validated_At", "Relevant_Jobs", "Provenance",
    "Eligible_Jobs", "Relevance_At", "Activity_Since", "Complete_Polls", "Last_New_Relevant_At",
    "New_Relevant_7d", "New_Relevant_30d", "Pool", "Pool_Since", "Trial_Until", "Trials", "Weak_Streak",
    "Pool_Reason", "Outages",
]  # fmt: skip
LOCK_TAB = "Lock"
LOCK_COLUMNS = ["Holder", "Label", "Acquired_At", "Expires_At"]  # one row: the advisory writer lease
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
    "Pool_Established", "Pool_Exploration", "Waiting_Relevant", "Oldest_Waiting_Hours", "Relevant_Coverage_Pct",
    "Graduated", "Demoted", "Parked_Policy", "Rebalance",
    "Result_Boards", "Result_Parked", "Result_Invalid", "Result_Awaiting_Validation",
    "Duration_S", "Load_S", "Discovery_S", "Poll_S", "Evaluate_S", "Events_Rows", "Boards_Rows",
    "Sheets_Reads", "Sheets_Writes", "Sheets_429", "ATS_Requests", "ATS_429", "ATS_Seconds", "Groq_Calls", "Groq_429",
    "Run_ID", "Finished_At", "Outcome", "Run_Kind", "Search_Failed", "Search_Account_Used", "Credit_Status",
    "Eval_Attempted", "Eval_Transient", "Eval_Failed", "Code_Version",
]  # fmt: skip
RUN_ID_COLUMN = RUN_COLUMNS.index("Run_ID") + 1  # 1-based sheet column
# Run outcomes. A run-start record is written first with STARTED; the end of the run overwrites it. A record that
# still says STARTED after the workflow timeout means the run was interrupted (killed, timed out, lost its runner).
OUTCOME_STARTED, OUTCOME_OK, OUTCOME_DEGRADED, OUTCOME_FAILED = "started", "ok", "degraded", "failed"
KIND_PRODUCTION, KIND_REHEARSAL = "production", "rehearsal"  # rehearsal = a local run (never GitHub Actions): excluded from reports
CREDIT_NONE, CREDIT_REPORTED, CREDIT_UNRESOLVED = "none", "reported", "unresolved"  # search credit accounting for the run
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
    search_credits: int = 0  # search credits spent (Tavily: 1 per basic search)
    search_repeated: int = 0  # results already returned earlier in the same run
    new_unique_boards: int = 0  # boards in the results that the registry had never seen
    eligible_boards: int = 0  # result boards that passed admission (validated, monitored)
    promoted_boards: int = 0  # result boards promoted into monitoring this run
    verified_fresh_matches: int = 0  # unique result jobs verified fresh and matching the title gate
    pool_established: int = 0  # monitored boards in the established pool at the end of the run
    pool_exploration: int = 0  # monitored boards on an exploration trial
    waiting_relevant: int = 0  # validated boards with something open for the user's targets, waiting for a slot
    oldest_waiting_hours: int | None = None  # how long the longest-waiting of them has waited
    relevant_coverage_pct: int | None = None  # share of boards with open relevant jobs that are actually monitored
    graduated: int = 0  # boards that became established this run
    demoted: int = 0  # boards returned to the waiting list this run
    parked_policy: int = 0  # monitored boards parked by provider policy this run
    rebalance: str = ""  # "" = not due, "report" = plan recorded only, "applied"
    # Breakdown of the unique boards the search results named (new to the registry OR already known):
    # eligible_boards + result_parked + result_invalid + result_awaiting_validation = result_boards.
    result_boards: int = 0
    result_parked: int = 0  # provider policy parks them (SmartRecruiters)
    result_invalid: int = 0  # validation proved the board does not exist
    result_awaiting_validation: int = 0  # candidates: validation was transient or past this run's inline limit
    # Diagnostics for auditing the deployment's limits (measured, per run; whole seconds):
    duration_s: int = 0  # whole run, start to the moment its record is written
    load_s: int = 0  # loading the registry, ledger and Runs from the Sheet
    discovery_s: int = 0
    poll_s: int = 0  # listing every monitored board plus classifying their jobs
    evaluate_s: int = 0  # hydration, scoring, tracker writes and alerts
    events_rows: int = 0  # Events rows loaded at the start (grows with every job ever seen)
    boards_rows: int = 0  # registry rows loaded at the start
    sheets_reads: int = 0  # Google Sheets API read requests (quota: about 60 per minute per user)
    sheets_writes: int = 0
    sheets_429: int = 0  # quota rejections that were retried
    ats_requests: int = 0  # requests to the ATS list/posting APIs
    ats_429: int = 0
    ats_seconds: int = 0  # summed request time (requests run 8 at a time)
    groq_calls: int = 0
    groq_429: int = 0
    # Reporting instrumentation (blank on rows written before it existed; never back-filled):
    run_id: str = ""  # stable identity of this run; ledger events carry it in their detail (`run`)
    finished_at: str = ""  # when the run record was completed; blank while STARTED
    outcome: str = ""  # started | ok | degraded | failed ("" = a row written before outcomes were recorded)
    run_kind: str = ""  # production | rehearsal ("" = unknown, written before the kind was recorded)
    search_failed: int = 0  # search requests that errored: whether the provider charged for them is unknown
    search_account_used: int | None = None  # the provider's own counter as read this run (None = not read)
    credit_status: str = ""  # none (no search) | reported (every charge came from a response) | unresolved (a failed request may have been charged)
    eval_attempted: int = 0  # evaluation attempts made this run (retries included; not unique jobs)
    eval_transient: int = 0  # attempts that ended in a temporary failure (retried later, nothing recorded per job)
    eval_failed: int = 0  # attempts recorded as failures against the job (bounded)
    code_version: str = ""  # first 8 characters of the commit that ran (GITHUB_SHA): reports use it to find the periods a deployment or correction affected

    @property
    def completed(self) -> bool:
        """False only for a run-start record that was never finished. Rows from before outcomes existed count as completed."""
        return self.outcome != OUTCOME_STARTED

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
                   *(num(i) or 0 for i in range(19, 30)), num(30), num(31), *(num(i) or 0 for i in range(32, 35)), row[35],
                   *(num(i) or 0 for i in range(36, 55)),
                   row[55], row[56], row[57], row[58], num(59) or 0, num(60), row[61], num(62) or 0, num(63) or 0, num(64) or 0, row[65])  # fmt: skip


def board_to_row(b: BoardRecord) -> list[Any]:
    return [b.key, b.ats, b.board, b.status, b.discovered_at, b.source, b.baselined_at, b.last_attempt_at,
            b.last_success_at, b.consecutive_failures, b.last_job_count, b.last_error,
            b.region, b.name, b.validation, b.last_validated_at, b.relevant_jobs,
            json.dumps(b.provenance, separators=(",", ":"), ensure_ascii=False)[:40000],
            *("" if v is None else v for v in (
                b.eligible_jobs, b.relevance_at, b.activity_since, b.complete_polls, b.last_new_relevant_at,
                b.new_relevant_7d, b.new_relevant_30d, b.pool, b.pool_since, b.trial_until, b.trials, b.weak_streak,
                b.pool_reason[:200])),
            json.dumps(b.outages, separators=(",", ":"))[:20000] if b.outages else "",
            ]  # fmt: skip


def _outages(cell: str) -> list[list[str]]:
    try:
        data = json.loads(cell) if cell else []
    except ValueError:
        return []
    return [[str(a), str(b)] for a, b in data if isinstance(a, str) and isinstance(b, str)] if isinstance(data, list) and all(isinstance(o, list) and len(o) == 2 for o in data) else []


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
        row[25], row[26], row[27], num(row[28]), num(row[29]), row[30], _outages(row[31]),
    )  # fmt: skip


def _chunks(rows: list[list[Any]], n: int = APPEND_CHUNK):
    for i in range(0, len(rows), n):
        yield rows[i : i + n]


# --------------------------------------------------------------------------- advisory writer lease


@dataclass
class Lease:
    ok: bool
    token: str = ""
    held_by: str = ""  # who blocks us, when ok is False


def _lease_expired(expires: str, now: datetime) -> bool:
    try:
        return datetime.strptime(expires, STAMP).replace(tzinfo=timezone.utc) <= now
    except ValueError:
        return True  # unreadable expiry: never block forever on garbage


def _stamp(dt: datetime) -> str:
    return dt.strftime(STAMP)


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
            (INVENTORY_TAB, INVENTORY_COLUMNS, 50), (DISCOVERY_TAB, DISCOVERY_COLUMNS, 20), (LOCK_TAB, LOCK_COLUMNS, 5),
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
            have = getattr(ws, "col_count", None)
            if isinstance(have, int) and have < len(columns):  # an in-place row update cannot write past the grid's last column
                ws.add_cols(len(columns) - have)
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

    # -- advisory writer lease: serializes the processes that share this registry (see D-31)
    def acquire_lease(self, label: str, ttl: timedelta, now: datetime, *, settle: float = 3.0, sleep: Any = time.sleep) -> Lease:
        """Take the single writer lease, unless a live one is held by someone else. Google Sheets has no
        atomic compare-and-set, so this is write-then-verify: the holder writes its token, waits `settle`
        seconds and reads it back. Two processes that start within `settle` seconds of each other can
        still both believe they won only if their writes interleave exactly; GitHub's shared concurrency
        group is the real serializer for scheduled and manually dispatched workflows, this lease is what
        makes a local command respect them (and vice versa)."""
        ws = self.sh.worksheet(LOCK_TAB)
        rows = ws.get_all_values()
        cur = rows[1] if len(rows) > 1 else []
        if cur and cur[0] and not _lease_expired(cur[3] if len(cur) > 3 else "", now):
            return Lease(False, held_by=f"{cur[1] if len(cur) > 1 else '?'} until {cur[3] if len(cur) > 3 else '?'}")
        token = f"{label}:{uuid.uuid4().hex[:12]}"
        ws.update(values=[[token, label, _stamp(now), _stamp(now + ttl)]], range_name="A2", value_input_option="RAW")
        sleep(settle)
        back = ws.get_all_values()
        if len(back) > 1 and back[1] and back[1][0] == token:
            return Lease(True, token)
        return Lease(False, held_by=f"{back[1][1] if len(back) > 1 and len(back[1]) > 1 else '?'} (won the race)")

    def holds_lease(self, token: str, now: datetime) -> bool:
        """Does this token still own an unexpired lease? (Checked when a run ends: a run that outlived its
        TTL has lost exclusion and must say so.)"""
        rows = self.sh.worksheet(LOCK_TAB).get_all_values()
        cur = rows[1] if len(rows) > 1 else []
        return bool(cur and cur[0] == token and not _lease_expired(cur[3] if len(cur) > 3 else "", now))

    def release_lease(self, token: str) -> None:
        ws = self.sh.worksheet(LOCK_TAB)
        rows = ws.get_all_values()
        if len(rows) > 1 and rows[1] and rows[1][0] == token:  # never release someone else's lease
            ws.update(values=[["", "", "", ""]], range_name="A2", value_input_option="RAW")

    def _current_statuses(self, ws: Any) -> dict[str, tuple[int, str]]:
        """Board key -> (sheet row, CURRENT status), read fresh from the sheet (two column reads when the
        worksheet supports them, else one full read)."""
        if hasattr(ws, "col_values"):
            keys, statuses = ws.col_values(1), ws.col_values(4)
        else:
            values = ws.get_all_values()
            keys = [r[0] if r else "" for r in values]
            statuses = [r[3] if len(r) > 3 else "" for r in values]
        return {k: (i, statuses[i - 1] if i - 1 < len(statuses) else "") for i, k in enumerate(keys, start=1) if i > 1 and k}

    def _reconcile(self, ws: Any, row_no: int, incoming: BoardRecord) -> None:
        """A row this writer may not overwrite: fold only its provenance/name into the stored row."""
        try:
            raw = ws.row_values(row_no) if hasattr(ws, "row_values") else ws.get_all_values()[row_no - 1]
            cur = board_from_row(list(raw))
            if cur is not None and merge_provenance(cur, incoming):
                ws.batch_update([{"range": f"A{row_no}", "values": [board_to_row(cur)]}], value_input_option="RAW")
        except Exception as exc:  # reconciliation is best effort; the skip itself is already safe
            log.warning("Could not reconcile provenance for %s: %s", incoming.key, exc)

    def save_boards(self, records: Iterable[BoardRecord], *, skip_if_status: frozenset[str] | set[str] = frozenset()) -> list[str]:
        """Upsert ONLY the given records: known rows are updated in place, unknown ones appended.

        `skip_if_status` is a best-effort guard for the importer, NOT an atomic compare-and-set: the
        status is read just before the write, and Google Sheets offers no conditional write, so a writer
        that promotes the row in between is not detected. What actually prevents overlapping writers is
        serialization (one GitHub concurrency group for every state-writing workflow, plus the advisory
        writer lease). A row that is skipped is not lost: its provenance and name are merged into the
        stored row. Returns the keys that were skipped."""
        recs = list(records)
        skipped: list[str] = []
        if not recs:
            return skipped
        ws = self.sh.worksheet(BOARDS_TAB)
        current: dict[str, tuple[int, str]] | None = None
        if skip_if_status:
            current = self._current_statuses(ws)
            keep = []
            for r in recs:
                row = current.get(r.key)
                if row is not None:
                    self._row_of[r.key] = row[0]
                if row is not None and row[1] in skip_if_status:
                    skipped.append(r.key)
                    self._reconcile(ws, row[0], r)
                else:
                    keep.append(r)
            recs = keep
        updates = [(self._row_of[r.key], r) for r in recs if r.key in self._row_of]
        fresh = [r for r in recs if r.key not in self._row_of]
        if fresh:  # another process may have appended some of these since we loaded: look again
            index = {k: v[0] for k, v in current.items()} if current is not None else {}
            if current is None:
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
        return skipped

    def load_events(self) -> list[Event]:
        rows = self.sh.worksheet(EVENTS_TAB).get_all_values()[1:]
        return [e for e in (Event.from_row(r) for r in rows) if e]

    def append_events(self, events: list[Event]) -> None:
        ws = self.sh.worksheet(EVENTS_TAB)
        for chunk in _chunks([e.to_row() for e in events]):
            ws.append_rows(chunk, value_input_option="RAW", table_range="A1")

    def append_run(self, run: RunRecord) -> None:
        self.sh.worksheet(RUNS_TAB).append_rows([run.to_row()], value_input_option="RAW", table_range="A1")

    def begin_run(self, run: RunRecord) -> None:
        """Persist the run-start record (outcome `started`) so a run that never finishes is visible."""
        self.append_run(run)

    def finish_run(self, run: RunRecord) -> None:
        """Complete the run's own record in place (found by Run_ID). If it cannot be found (the start record was
        never written) the finished record is appended instead, so a run always leaves exactly one record."""
        ws = self.sh.worksheet(RUNS_TAB)
        ids = ws.col_values(RUN_ID_COLUMN) if run.run_id else []
        rows = [i for i, v in enumerate(ids, start=1) if i > 1 and v == run.run_id]
        if not rows:
            self.append_run(run)
            return
        ws.update(values=[run.to_row()], range_name=f"A{rows[-1]}", value_input_option="RAW")

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

    def save_boards(self, records: Iterable[BoardRecord], *, skip_if_status: frozenset[str] | set[str] = frozenset()) -> list[str]:
        """Upsert the given records into the registry file (atomic replace). Records whose CURRENT
        status in the file is in `skip_if_status` are not written; their keys are returned."""
        recs = list(records)
        skipped: list[str] = []
        if not recs:
            return skipped
        boards = self.load_boards()
        for r in recs:
            if skip_if_status and (cur := boards.get(r.key)) is not None and cur.status in skip_if_status:
                skipped.append(r.key)
                merge_provenance(cur, r)  # reconcile: the discovery facts are kept, the row is otherwise untouched
                continue
            boards[r.key] = r
        p = self._path(BOARDS_TAB)
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(BOARD_COLUMNS)
            w.writerows(board_to_row(b) for b in sorted(boards.values(), key=lambda b: b.key))
        os.replace(tmp, p)  # atomic
        return skipped

    def load_events(self) -> list[Event]:
        return [e for e in (Event.from_row(r) for r in self._rows(EVENTS_TAB)) if e]

    def append_events(self, events: list[Event]) -> None:
        with self._path(EVENTS_TAB).open("a", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(e.to_row() for e in events)

    def append_run(self, run: RunRecord) -> None:
        with self._path(RUNS_TAB).open("a", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(run.to_row())

    def begin_run(self, run: RunRecord) -> None:
        self.append_run(run)

    def finish_run(self, run: RunRecord) -> None:
        p = self._path(RUNS_TAB)
        rows = self._rows(RUNS_TAB)
        idx = [i for i, r in enumerate(rows) if run.run_id and len(r) >= RUN_ID_COLUMN and r[RUN_ID_COLUMN - 1] == run.run_id]
        if not idx:
            self.append_run(run)
            return
        rows[idx[-1]] = [str(c) for c in run.to_row()]
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(RUN_COLUMNS)
            w.writerows(rows)
        os.replace(tmp, p)  # atomic

    def load_runs(self) -> list[RunRecord]:
        return [r for r in (RunRecord.from_row(x) for x in self._rows(RUNS_TAB)) if r]

    _lock_fds: dict[str, int] = {}  # token -> the open, flock-ed file descriptor that IS the lease

    def acquire_lease(self, label: str, ttl: timedelta, now: datetime, *, settle: float = 0.0, sleep: Any = time.sleep) -> Lease:
        """Local files: an exclusive `flock` on `lock.json`, held for as long as the owner lives. The kernel
        arbitrates (atomic on one machine, released automatically if the process dies), so unlike the Sheet
        lease this one IS exclusive; it needs no expiry (`ttl` is recorded for information only). An earlier
        version created the file and then wrote it: a second process could read the empty file and take over."""
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / "lock.json"
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            try:
                cur = json.loads(os.pread(fd, 4096, 0).decode() or "{}")
            except ValueError:
                cur = {}
            os.close(fd)
            return Lease(False, held_by=f"{cur.get('label', '?')} since {cur.get('acquired', '?')}")
        token = f"{label}:{uuid.uuid4().hex[:12]}"
        os.ftruncate(fd, 0)
        os.pwrite(fd, json.dumps({"holder": token, "label": label, "acquired": _stamp(now), "expires": _stamp(now + ttl)}).encode(), 0)
        CsvState._lock_fds[token] = fd
        return Lease(True, token)

    def holds_lease(self, token: str, now: datetime) -> bool:
        fd = CsvState._lock_fds.get(token)
        if fd is None:
            return False
        try:
            return json.loads(os.pread(fd, 4096, 0).decode() or "{}").get("holder") == token
        except (OSError, ValueError):
            return False

    def release_lease(self, token: str) -> None:
        fd = CsvState._lock_fds.pop(token, None)  # a token this process does not own releases nothing
        if fd is None:
            return
        try:
            os.ftruncate(fd, 0)
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

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
