# Phase 3: Compact storage - Pattern Map

**Mapped:** 2026-10-29
**Files analyzed:** 17 (3 new modules/tests groups counted individually below)
**Analogs found:** 16 / 17 (all analog paths verified git-tracked via `git ls-files`)

Note: line numbers are from the working tree at mapping time (HEAD 47d68d4). Re-grep before editing.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `compact.py` (NEW) | utility (pure domain) | transform | `storage_report.py` (`classify`, constants) + `ledger.py` (`replay`) | role-match |
| `state.py` (MOD: `SheetState`, `CsvState`, tab consts, `ensure`) | service (persistence) | CRUD / batch | itself (`ensure`, `_widen_header`, `append_events`, `_chunks`, CsvState twin) | exact |
| `pipeline.py` (MOD: `seen` helper, write block ~L595, `degraded_reason`) | service (orchestration) | event-driven | itself (rule 1 block, `degraded_reason` notes mechanism) | exact |
| `reporting.py` (MOD: `_count_seen`, reconcile, ledger-row figures) | service | transform | itself (`build_summary` counter block ~L315) | exact |
| `dashboard.py` (MOD: storage signal, `load_ledger`) | component (render) | request-response | itself (~L585) | exact |
| `pilot.py` (MOD: merged view) | service | transform | itself | exact |
| `storage_report.py` (MOD: allocated cells, before/after, `classify` delegates to `compact`) | utility | transform | itself | exact |
| `hunter.py` (MOD: `--storage-parity`, `--storage-cutover`, `inventory_mode`, `writes`) | controller (CLI) | request-response | `--storage-report` branch (~L2043, L2079) | exact |
| `.github/workflows/job_hunter.yml` (MOD: two inputs, steps, `if:`, `REQUIRE_TELEGRAM`) | config | request-response | `storage_report` input/step (L32, L107, L124, L147) | exact |
| `tests/test_deployment.py` (MOD: pinned expression L233) | test | request-response | itself | exact |
| `tests/test_hunter.py` (MOD: tab-set test) | test | CRUD | itself (`test_bootstrap_creates_user_tabs_and_hidden_state_tabs`) | exact |
| `tests/fake_sheets.py` (NEW shared fake) | test utility | CRUD | fakes in `tests/test_hunter.py`, `tests/test_inventory.py` | partial |
| `tests/test_compact.py` (NEW) | test | transform | `tests/test_storage_report.py` | role-match |
| `tests/test_storage_parity.py` (NEW) | test | transform | `tests/test_storage_report.py` + `tests/test_core.py` Harness | role-match |
| `tests/test_storage_cutover.py` (NEW) | test | batch | `tests/test_hunter.py` fakes + `tests/test_core.py` Harness | partial |
| `tests/test_core.py` (MOD: Harness `events()`/`states()`) | test | CRUD | itself (~L121-125) | exact |
| `SPEC.md`, `DECISIONS.md` (D-57), `STATUS.md`, `PILOT_LOG.md`, `AGENTS.md` Layout line | docs | n/a | existing D-4x entries | exact |

## Pattern Assignments

### `compact.py` (utility, transform)

**Analog:** `storage_report.py` (the same identity/baseline split and constants) and `ledger.py` (pure, dataclass based, no I/O).

**Imports and constants to reuse** (`storage_report.py` L11-26):
```python
from __future__ import annotations
import json, math, statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import freshness as fr
import ledger as lg
from boards import MONITORED, STATUS_VALIDATED, BoardRecord, admission_order
from state import RunRecord

EVENT_COLUMNS = 7
SHEET_CELL_LIMIT = 10_000_000
CELL_CHAR_LIMIT = 50_000
COMPACT_CELL_CHARS = 40_000  # leave headroom under the 50,000-character cell limit
COMPACT_COLUMNS = 5  # Board_Key, Chunk, Baselined_At, Count, IDs
```
Caution: `storage_report` imports `state`; `state` will import `compact`. `compact.py` must NOT import `state` or `storage_report` (cycle). Move `COMPACT_CELL_CHARS` to `compact.py` and have `storage_report` import it.

**Core pattern to relocate: the identity-class rule** (`storage_report.py` L40-52). `compact.identity_class(ev)` is this logic, returning `"baseline" | "filtered" | "stale" | None`; `storage_report.classify` then calls it (one definition):
```python
if ev.event == lg.SEEN:
    if ev.disposition == lg.BASELINED:
        return "baseline"
    if ev.disposition in (lg.FILTERED, lg.STALED):
        return "identity"
    return "operational"
return "operational"
```

**Stem rule** (analog in `storage_report.analyze` L77-79; RESEARCH finding 2 says use the job-key stem, never `BoardRecord.key`):
```python
parts = ev.key.split("|", 2)
board = "|".join(parts[:2])
```
Keys with fewer than 3 segments are unkeyable: keep in Events, never fold, report as parity diff class `unkeyable`.

**Merged view feeding `seen`:** `ledger.replay` (L78-100) stays the source of per-job state for Events rows; `Ledger` adds `identity_seen: set[str]` instead of `JobState` stubs. Do not edit `ledger.observe_new` (Phase 4 owns it).

**Disposition constants** (`ledger.py` L23, L28): `PENDING, BASELINED, FILTERED, STALED = "pending", "baseline", "filtered", "stale"`; `_DETAIL_LIMIT = 45000`.

Codec, chunking, delete-request and subtract-the-retained snippets are in RESEARCH.md "Code Examples" (no codebase analog; use as written).

---

### `state.py` (service, CRUD/batch)

**Analog:** itself.

**Tab constants pattern** (L37-42):
```python
LOCK_TAB = "Lock"
LOCK_COLUMNS = ["Holder", "Label", "Acquired_At", "Expires_At"]
DISCOVERY_TAB = "Discovery"
DISCOVERY_COLUMNS = ["Key", "Value", "Updated_At"]
```
Add `IDENTITY_TAB/IDENTITY_COLUMNS = ["Board_Key","Chunk","Baselined_At","Count","IDs"]`, `TALLY_TAB/TALLY_COLUMNS = ["Run_ID","Run_At","Total","Counts"]`.

**Tab create/hide pattern** (`SheetState.ensure`, L270-288). Add Identity and Tally to the tuple; the protection call goes inside the same cosmetic try/except (test_inventory fakes lack `batch_update`):
```python
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
        ws.hide()
    except Exception as exc:
        log.warning("Could not tidy the %s tab: %s", title, exc)
```
Also add the RESEARCH Pattern 7 step 5 guard here: raise if `Events` is missing while `Events_New`/`Events_Legacy` exists. Note `Discovery` is created with `rows=20`; add at most one `storage` key.

**Append pattern** (`append_events` L428-431) and `_chunks` (L238-240, `APPEND_CHUNK = 2000`, L66). Reuse for Tally and Events_New; do NOT reuse for Identity (character-budget the request instead):
```python
def append_events(self, events: list[Event]) -> None:
    ws = self.sh.worksheet(EVENTS_TAB)
    for chunk in _chunks([e.to_row() for e in events]):
        ws.append_rows(chunk, value_input_option="RAW", table_range="A1")
```

**In-place update pattern** (`save_boards`, ~L415-418), for Identity last-chunk cell updates:
```python
for i in range(0, len(updates), self.UPDATE_CHUNK):
    chunk = updates[i : i + self.UPDATE_CHUNK]
    ws.batch_update([{"range": f"A{row}", "values": [board_to_row(r)]} for row, r in chunk], value_input_option="RAW")
```
`SheetState` also tracks `self._row_of` learned at load time: mirror for Identity `(Board_Key, Chunk) -> row`.

**Loader pattern to change** (`load_events` L424-426). The new loader must keep sheet row numbers; `Event.from_row` returning `None` currently shifts indexes:
```python
rows = self.sh.worksheet(EVENTS_TAB).get_all_values()[1:]
return [e for e in (Event.from_row(r) for r in rows) if e]
```
Keep `load_events()` unchanged for raw callers; add `load_ledger()` returning `(row_no, Event)` pairs plus Identity and Tally.

**CsvState twin** (L486-496 `ensure`, `_rows` L498, `load_events` L534). Add Identity and Tally to the tuple so `identity.csv`/`tally.csv` exist:
```python
for title, columns in (
    (BOARDS_TAB, BOARD_COLUMNS), (EVENTS_TAB, EVENT_COLUMNS), (RUNS_TAB, RUN_COLUMNS), (INVENTORY_TAB, INVENTORY_COLUMNS),
    (DISCOVERY_TAB, DISCOVERY_COLUMNS),
):
```
Every new `SheetState` method needs a `CsvState` twin (offline tests use it).

---

### `pipeline.py` (service, event-driven)

**Analog:** itself.

**Load point** (L207-210) becomes `load_ledger()`; `events_loaded` is still used for `run.events_rows`:
```python
d.state.ensure()
boards = d.state.load_boards()
events_loaded = d.state.load_events()
states = lg.replay(events_loaded)
```

**Four `seen` sites** (L320, L419, L429, L532) all use the same expression; replace with one helper `seen(key)`:
```python
is_unseen_job=lambda i: not (states.get(i.key) and states[i.key].seen),
unseen = [j for j in res.jobs if not (states.get(j.ident.key) and states[j.ident.key].seen)]
...
st = states.get(job.ident.key)
if st and st.seen:
    if st.evaluated is not None:
        pending_events += lg.observe_known(job, st, now)
    continue
ev = lg.observe_new(job, obs, d.title_gate)
pending_events.append(ev)
states[ev.key] = lg.replay([ev])[ev.key]   # in-run addition: also add identity-class keys to identity_seen
```
Identity-only jobs never have `evaluated`, so `observe_known` is not affected.

**Durable write order (rule 1)** (L595-599). This is the single write point; extend to Events -> Identity (marker on last chunk) -> Tally -> `save_boards`:
```python
# Rule 1: observations are durable BEFORE the registry says "baselined".
if not d.dry_run:
    d.state.append_events(pending_events)
    pending_events = []
    d.state.save_boards(dirty.values())
```
Update the pipeline header rule-1 comment (~L595 area and file header) in the same change.

**Degraded reason via run notes** (L178-186). Add a `"storage"` reason keyed off `run.notes`, with no new Runs column:
```python
if "final write failed" in run.notes or "run-start record not written" in run.notes:
    reasons.append("persistence")
if run.alerts_failed:
    reasons.append("alerts")
```
Deadlines: poll/eval/alert cutoffs at L200-202 (`t0 + d.poll_cutoff_s`, etc.); the fold must check these.

---

### `reporting.py` (service, transform)

**Analog:** itself, `build_summary` counter block (L310-330).

**Refactor target.** Extract the body into `_count_seen(c, f)` and call it for real facts and synthetic Tally facts:
```python
for f in facts.values():
    if f.seen_at is not None:
        c = day[local(f.seen_at)]
        out = f.outcome()
        c["seen"] += 1
        c[f"out:{out}"] += 1
        c[f"ats:{f.ats}"] += 1
        if out != "baseline":
            c["seen_new"] += 1
            c[f"src:{f.source}"] += 1
            c[f"new_ats:{f.ats}"] += 1
            c["new_date_known" if f.date_known else "new_date_unknown"] += 1
```
Do not inject synthetic facts into `facts` used by `_yield`, `_groq`, `_failures`, `tracker_join`. Also add folded totals to the ledger-row figures (~L477-488) and to `reconcile`'s `seen` list (~L1053). `_checks` (~L951-966) must still pass in compact mode. Source mapping (`serper` -> `search`, blank -> `unknown`) is at L205-206: reuse, do not duplicate.

---

### `hunter.py` (controller, request-response)

**Analog:** the `--storage-report` wiring.

**argparse** (L2043):
```python
parser.add_argument("--storage-report", action="store_true", help="print what the Events ledger is made of ...; read only, changes nothing")
```
**`inventory_mode`** (L2047): append `or args.storage_parity or args.storage_cutover` (no GROQ key demanded). Also add `--storage-cutover` to the `writes` expression (L2047/L2088) so `local_write_refusal` applies; `--storage-parity` is read-only like `--storage-report`.

**Dispatch branch** (L2079-2082):
```python
if args.storage_report:
    state = store.state
    print(storage_report.format_report(storage_report.analyze(state.load_events(), state.load_boards(), state.load_runs(), fr.utcnow())))
    return 0
```
Consumers to route through the merged view: L1965 (pilot report), L1994 (rebalance report, PENDING only, raw events fine), L2081 (storage report). Cutover runs under the `poller` lease via `writer_lease` (no new `LEASE_TTL` entry; see `tests/test_deployment.py` ~L125-129).

---

### `.github/workflows/job_hunter.yml` (config)

**Analog:** `storage_report` input and step. Four places must change together.

Input (L32-35):
```yaml
      storage_report:
        description: "Print what the Events ledger is made of ... (read only: nothing is pruned, compacted or archived)"
        type: boolean
        default: false
```
`REQUIRE_TELEGRAM` (L107):
```yaml
REQUIRE_TELEGRAM: ${{ (inputs.pilot_report || inputs.rebalance_report || inputs.dashboard || inputs.storage_report) && 'no' || 'yes' }}
```
Poller exclusion (L124): `if: ${{ !inputs.rebalance_report && !inputs.pilot_report && !inputs.delivery_test && !inputs.dashboard && !inputs.storage_report }}`

Step (L146-148):
```yaml
      - name: Storage report (read only)
        if: ${{ inputs.storage_report }}
        run: python hunter.py --storage-report
```
Add `storage_parity` and `storage_cutover` booleans, extend all three expressions, add one step each. Use booleans only (no expression injection).

---

### `tests/test_deployment.py` / `tests/test_hunter.py` / `tests/test_core.py` (MOD)

- `tests/test_deployment.py:233` pins the literal expression; update to the new one in the same change:
```python
self.assertIn("(inputs.pilot_report || inputs.rebalance_report || inputs.dashboard || inputs.storage_report) && 'no' || 'yes'", text)
```
- `tests/test_hunter.py` `test_bootstrap_creates_user_tabs_and_hidden_state_tabs` asserts the exact tab set: add `Identity` and `Tally` (hidden).
- `tests/test_core.py` Harness (L121-125): switch to the merged view:
```python
def events(self, key=None, kind=None):
    return [e for e in self.state.load_events() if (key is None or e.key == key) and (kind is None or e.event == kind)]
def states(self) -> dict[str, lg.JobState]:
    return lg.replay(self.state.load_events())
```
Harness `run()` (L110-118) builds `pl.Deps(...)` with `state=self.state`; reuse it for interrupted-run (SC4) tests.

---

### `tests/test_compact.py`, `tests/test_storage_parity.py`, `tests/test_storage_cutover.py` (NEW)

**Analog:** `tests/test_storage_report.py` for pure-function tests; `tests/test_core.py` Harness for pipeline-level ones.

**Test file preamble and helpers** (`test_storage_report.py` L1-33):
```python
from __future__ import annotations
import sys, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import boards as bd  # noqa: E402
import freshness as fr  # noqa: E402
import ledger as lg  # noqa: E402
import state as st_mod  # noqa: E402

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)

def ts(**kw: float) -> str:
    return (NOW - timedelta(**kw)).strftime("%Y-%m-%dT%H:%M:%SZ")

def seen(key: str, when: str, disp: str, **d: object) -> lg.Event:
    return lg.Event(when, key, lg.SEEN, fr.BASELINE if disp == lg.BASELINED else fr.VERIFIED_FRESH, disp, "", {"source": "poll", ...})
```
Required cases (from RESEARCH): mixed-case Lever board stem round trip; IDs containing `,` and `%`; a half-folded run (no double count); mutation check per Tally dimension; payload cap (fake raises over 50,000 chars/oversized request); Identity chunk marker only on last chunk (interrupted write leaves incomplete); fold never deletes a row whose ID is not in Identity; swap atomic ordering; `ensure()` refuses when `Events` is missing but `Events_Legacy` exists.

Tests stay offline (AGENTS rule 8) and must label themselves mocked (rule 5).

### `tests/fake_sheets.py` (NEW)

**Analog:** the three existing fakes (`tests/test_hunter.py` FakeWorksheet with `__getattr__` that asserts `delete_rows`/`clear` are never called; `tests/test_inventory.py` `FakeSh`/`FakeWs`, which have no `batch_update`). Read those two before writing it: the new fake must interpret `batchUpdate` requests (`updateSheetProperties`, `deleteDimension`, `addProtectedRange`), keep `col_count`, and raise on over-large cells/requests. Existing tests must keep their own fakes (they lack `batch_update`).

---

## Shared Patterns

### Tab pair (SheetState + CsvState)
**Source:** `state.py` `ensure()` for both classes (L270-288, L486-496).
**Apply to:** every new persistence method (identity, tally, fold, swap, storage key). Offline tests run on `CsvState`.

### Cosmetic-failure containment
**Source:** `state.py` L283-287 (`try: freeze; hide; except Exception: log.warning`).
**Apply to:** protection setup on Identity (and optionally Events_Legacy).

### Degraded-run signalling by run notes
**Source:** `pipeline.py` L178-186 (`degraded_reason`).
**Apply to:** parity difference (P3-07) and "parity not evaluated". Parity code is wrapped in try/except so it never stops job processing.

### Rule 1 durable order
**Source:** `pipeline.py` L595-599.
**Apply to:** all observation writes; the fold deletes only after Identity is read back (rule 4).

### Read-only CLI vs writing CLI
**Source:** `hunter.py` `--storage-report` (read-only) vs `writes` expression (L2047/L2088).
**Apply to:** `--storage-parity` (read-only, no lease), `--storage-cutover` (writes, lease, `--dry-run`).

### Discovery key/value for small state
**Source:** `DISCOVERY_TAB` (`state.py` L39-40; 8 keys, created with 20 rows).
**Apply to:** the single `storage` key (mode, parity clock, cutover record).

## No Analog Found

| File / piece | Role | Data Flow | Reason |
|---|---|---|---|
| Atomic tab swap, descending `deleteDimension` fold, `addProtectedRange` | persistence | batch | No code uses `spreadsheets.batchUpdate` for structure changes today (only `fetch_sheet_metadata` in `dashboard._existing_chart_ids`). Use RESEARCH.md "Code Examples". |
| Parity engine (`compact.parity`) and parity clock | utility | transform | New concept; compose from `reporting.build_summary`, `reconcile`, `storage_report.analyze` run on old vs simulated rows (RESEARCH Pattern 6). |
| Identity codec (kind prefix, percent-escaping, 40,000 char chunking) | utility | transform | New; RESEARCH Pattern 2 snippets. |

## Metadata

**Analog search scope:** repo root `*.py`, `tests/`, `.github/workflows/`.
**Files scanned:** state.py, storage_report.py, ledger.py, pipeline.py (targeted ranges), reporting.py (L310-330), hunter.py (argparse and dispatch), job_hunter.yml, test_storage_report.py, test_core.py (harness). Page 2 of RESEARCH.md (lines 415-504, Validation Architecture) was not read.
**Pattern extraction date:** 2026-10-29
