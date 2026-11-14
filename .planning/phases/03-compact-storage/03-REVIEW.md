---
phase: 03-compact-storage
reviewed: 2026-11-14T00:00:00Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - DECISIONS.md
  - SPEC.md
  - STATUS.md
  - compact.py
  - tests/test_storage_parity.py
findings:
  critical: 0
  warning: 1
  info: 10
  total: 11
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-11-14
**Depth:** standard (incremental re-review: `git diff 2d521bc HEAD` for fix commit e83d563 (WR-06) and its doc changes, each hunk read in its surrounding code: `compact.StorageState.record_compact_check` / `last_identity_entries`, `pipeline.storage_check`, `parity._identity_loss` / `_identity_invariants` / `check_compact`, `hunter.run_storage_parity`)
**Files Reviewed:** 5
**Status:** issues_found

## Summary

The WR-06 fix is correct and complete for the finding as stated. `kept = max(previous or 0, identity_entries) if identity_entries is not None else previous` handles each case I traced:

- **First check, no recorded count.** `previous` is None, so `max(0, n)` records `n`. A first check whose count is None records nothing, and the key is absent (pinned by `test_a_first_check_with_no_identity_count_to_record_records_none`).
- **Failed or uncounted check.** `pipeline.storage_check` passes `identity_entries=None` when the check raised, and `check_compact` always sets `compared["identity_entries"]`. The mark is kept in both cases. A raised check also counts 1 itself, so the fold is held back anyway.
- **Growth above the mark.** The mark rises, `_identity_loss` compares `entries < entries_before`, and a count equal to or above the mark counts 0.
- **Other writers of `identity_entries`.** There are none. `compact.py:754-756` is the only writer. `last_identity_entries()` is read at `pipeline.py:234`, `hunter.py:2025` and `compact.py:752`. The dual-mode `record_check` (`compact.py:732`) rebuilds `last_check` without the key. That only matters before the cutover, and the first compact check after the cutover then records afresh, as STATUS says.
- **Restore and dual modes.** `record_compact_check` runs only in compact mode (`pipeline.py:244`). `restored` and `dual` never touch the mark, and `--storage-restore` is refused once a fold has run. Nothing else can shrink Identity legitimately in those modes.
- **The `--storage-parity` command.** It reads the same mark and is read-only. The loss therefore shows as exit 1 on every invocation.

The tests pin the fix:

- `test_the_recorded_identity_count_is_a_high_water_mark` exercises record, fall, repeated fall, None, return to the mark and growth.
- The integration tests assert the mark is kept, the run is degraded on every later run, and a repair clears it.
- I ran `.venv/bin/python -m unittest discover -s tests`: `Ran 934 tests ... OK`. STATUS says 931 after WR-05 and 934 after WR-06, which matches.

The docs match the code. SPEC, DECISIONS D-57 and STATUS all say "high-water mark, never lowered automatically", state the operational cost (degraded every run, fold held back, `Events` growing) and state that there is no acknowledgement step. Every check is labelled mocked and "not deployed", and no live Sheets, Groq or Telegram claim is made. That satisfies AGENTS rule 5. No behaviour contradicts SPEC or DECISIONS, so rule 1 is not triggered.

**One new WARNING (WR-07).** The mark counts raw entries, duplicates included. Repairing an `identity_duplicate` therefore turns into a permanent `identity_shrunk`. There are two new INFO items. IN-01..IN-08 are carried forward unchanged.

Resolved:

| Earlier finding | Fix commit | Verification |
|---|---|---|
| WR-01 restore guard open after a partial fold | a2247a9 | `storage_fold` saves `fold.started_day` before the first delete and skips the fold for the run if that save fails. `fold_record` turns the marker into `first_day`. `hunter.run_storage_restore` refuses on either field. `fold_touched` is set before the first request. The marker is taken back only when no request went out. |
| WR-02 Identity loss undetected, `ensure()` recreates an empty tab | 58d9ec2 | `ensure()` refuses a missing Identity or Tally tab in compact mode. `identity_shrunk` and `identity_unreadable` are counted. The one-shot weakness was WR-06, now fixed. See WR-07 for a remaining edge. |
| WR-03 Tally write failure became a permanent undercount | 024319f | `carry_tally` stores the counts-only row in `storage.pending_tally`. It is written at the next run start and deduplicated against the snapshot. See IN-08. |
| WR-04 stale Identity cache overwrote the sheet | 6648949 | `write_identity` drops the cache on any exception and re-reads Identity before the next plan. |
| WR-05 the fold ignored the same run's integrity check | 8b02697 | `storage_check` returns `report.counted`. The fold runs only when it is 0. |
| WR-06 `identity_shrunk` reported once, then the lower count became the reference | e83d563 | `record_compact_check` keeps `max(previous or 0, current)`. Traced for first check, failed check, growth, restore and dual modes, and every other writer. Tests, 934 in all, pass offline. Docs match. See WR-07 and IN-09 for residual points. |

## Critical Issues

None.

## Warnings

### WR-07: The high-water mark counts duplicate Identity entries, so repairing `identity_duplicate` becomes a permanent `identity_shrunk`

**File:** `compact.py:752-756` (`record_compact_check`), `parity.py:111-128` (`_identity_invariants`, which sums `len(row.entries())`), `parity.py:362-372` (`_identity_loss`)
**Issue:** The mark is the raw entry count (`entries += len(found)` per row). It includes entries that `_identity_invariants` itself flags as `identity_duplicate`. `record_compact_check` raises the mark on every check, including one that counted a difference. Trace:

1. A bad write or hand edit leaves a posting ID twice in one stem, so the count goes from 100 to 101. The check counts `identity_duplicate 1`, degrades the run and holds the fold back.
2. That same check records 101 as the new mark.
3. The owner removes the duplicate, which is the correct repair for the flagged difference. The count falls to 100.
4. The next check sees 100 against 101 and counts `identity_shrunk`. This persists on every run, because nothing re-adds an ID and the mark never falls. Removing a duplicate loses no posting ID. The owner is forced to put a junk entry back, or edit the Discovery `storage` key, to clear a difference that the previous fix made it cure.

This is a defect in the new semantics. Before WR-06 the shrink reported once and cleared. After WR-06, the repair of a flagged, genuinely recoverable difference creates a permanent false positive. It shares the cause of the "no acknowledgement" cost, but it is a different failure: here the owner did the right thing and there is no right way out. It is not the "no ack mechanism" complaint. The same applies to `identity_count` repairs that change the entry count. Fixing a hand-written `Count` does not alter entries, but removing a malformed or duplicated entry does.

**Fix:** Make the mark measure distinct posting IDs, which is what dedupe uses, and raise it only from a check that has no Identity-level difference. A minimal version counts distinct `(stem, id)` pairs in `_identity_invariants`:
```python
seen = set()
for row in ident.all_rows():
    found = row.entries()
    seen.update((row.stem, compact.decode_entry(e)[1]) for e in found)
...
return out, len(seen)   # used for compared["identity_entries"]
```
This is less correct for the integer-sum use elsewhere, so alternatively skip the raise when the check counted any `identity_duplicate` or `identity_unreadable`:
```python
raise_ok = identity_entries is not None and not identity_dirty  # pass a flag from storage_check
kept = max(previous or 0, identity_entries) if raise_ok else previous
```
Add a test: record 100, inject one duplicate (101, counted `identity_duplicate`), remove it, and assert the next check counts 0.

## Info

### IN-01: `parity.py` docstring is wrong about its imports

**File:** `parity.py:3-4`
**Issue:** The docstring says the module "imports `compact` and `ledger` only (never state, pipeline or hunter)". It also imports `reporting`, `storage_report` (which imports `state`) and `boards`. There is no cycle today, but the stated invariant is false and will not protect a future change. Still open, unchanged by this fix set.
**Fix:** State the real constraint (no import of `pipeline` or `hunter`), or move the shared figure code so the claim becomes true.

### IN-02: Removing `Events_Legacy` silently flips a compact system back to dual writing

**File:** `compact.py:585-600` (`effective_mode`)
**Issue:** If the stored mode is compact and `Events_Legacy` is gone, the poller writes as dual. Baselines go back into Events, and the fold and the check stop. DECISIONS P3-08 describes removing `Events_Legacy` as a later owner decision "with an export plan". As written, that decision cannot be carried out without a code change. The WR-02 fix adds a related, deliberate coupling: `_compact_mode_stored` calls `effective_mode(..., legacy_present=True)`, so the `ensure()` guard also assumes the legacy tab exists. Still open.
**Fix:** Before the owner removes the tab, add a recorded state (for example `storage.legacy_retired_at` or a `--storage-retire-legacy` step) that `effective_mode` and `_compact_mode_stored` honour. Until then, note it in DEPLOY.md.

### IN-03: The workflow lets `storage_cutover` and `storage_restore` run in one job

**File:** `.github/workflows/job_hunter.yml:170-175` (and the `inputs` block)
**Issue:** The CLI makes the two flags mutually exclusive, but each is a separate workflow step guarded only by its own input. Ticking both runs the cutover and then the restore in the same dispatch. Still open (workflow unchanged).
**Fix:** Add a first step that fails when more than one of the owner-step or report inputs is true.

### IN-04: The cutover checksum covers only `key|time|event`

**File:** `compact.py:372-377` (`rows_checksum`)
**Issue:** The comment says the checksum compares "the rows it meant to copy" with the rows read back. It hashes three of the seven columns, so a changed `Freshness`, `Disposition`, `Published` or `Detail` passes. `Events_Legacy` stays whole, so this is not a data-loss path. Still open.
**Fix:** Hash `"\x1f".join(ev.to_row())` per row.

### IN-05: Dead variable and unused imports

**File:** `reporting.py:492` (`first_event`), `storage_report.py:10,18` (`json`, `fr`)
**Issue:** `first_event` is assigned and never read, and `json` and `fr` are imported and never used. Still open (neither file changed).
**Fix:** Delete them.

### IN-06: Read-only commands read three tabs sequentially without the lease

**File:** `state.py:608-621` and `state.py:893-906` (`load_ledger`), `hunter.py` (`run_storage_parity`, `run_storage_report`, `run_pilot_report`), `dashboard.py:594`
**Issue:** `load_ledger` reads Events, then Identity, then Tally with separate calls. A manual `--storage-parity` or `--dashboard` that overlaps a poller run can see Events from before the run and Tally or Identity from after it, which gives counted differences that disappear on the next run. The WR-02 fix now also compares the Identity entry count in `--storage-parity` against `last_check.identity_entries`, which a racing poller run advances. After WR-06 the mark only grows, so a racing read can only produce a false `identity_shrunk` in the direction of an old snapshot against a newer mark. Mitigated by the one-run-at-a-time concurrency group. Still open.
**Fix:** Document that a parity difference should be re-run before it is trusted, or read all three tabs in one `values_batch_get`.

### IN-07: `first_day` is dated by the fold that ends, not by the one that started

**File:** `compact.py:466` (`fold_record`)
**Issue:** `first = previous.get("first_day") or (_utc_day(now) if rows > 0 or previous.get("started_day") else "")`. When a fold fails after its first delete on day D and finishes on day D+1, `first_day` becomes D+1 although rows went on D. The restore guard is unaffected, because it also honours the marker until the fold ends. `storage_report.py:316` and `:349` read `fold.first_day` as the start of the "after the cutover and first fold" window and `first_fold_day`. The window then starts later than the truth, which is the conservative direction, but the reported `first_fold_day` is wrong.
**Fix:** Prefer the marker's day: `previous.get("first_day") or previous.get("started_day") or (_utc_day(now) if rows > 0 else "")`.

### IN-08: The Tally carry holds zero-total rows and drops the newest row when full

**File:** `compact.py:707-715` (`keep_tally`), `pipeline.py:372-383` (`carry_tally`)
**Issue:** Two small quality points on the WR-03 carry.
1. Every run appends a Tally row, including runs that observed nothing (`total` 0). `test_a_carried_row_stays_until_it_can_be_written...` shows this: the carry holds `[3, 0]`. A zero-count row has nothing to lose, because no baseline count is missing and `repair_plan` has nothing to rebuild. Carrying it spends one of the 20 slots for nothing and adds a Discovery write per failing run.
2. When the carry is full, the newest row is the one left out (`keep_tally` returns False). The newest row is the one most likely to hold fresh baseline counts, so the permanent undercount WR-03 fixed comes back after 20 consecutive failures. Realistically a Tally outage that long also fails the Discovery save that persists the carry. The cap is deliberate, so this is a robustness note, not a defect.
**Fix:** In `carry_tally`, return early when `row.total == 0`. When the carry is full, either drop the oldest zero-count row first or log and note `storage tally carry full` in `run.notes`, so the owner sees the gap. The log line is currently the only trace.

### IN-09: The new tests do not pin the claim that matters most for the fix, "the fold stays held back"

**File:** `tests/test_storage_parity.py:777-801` and `:906-937`
**Issue:** The WR-06 purpose, stated in SPEC, D-57 and STATUS, is that an unrepaired loss "holds the fold back" on every later run. The new tests assert the note, the degraded outcome, the counted figure and the mark across three runs. None asserts `storage fold skipped: integrity check counted 1 differences` or that no rows were deleted for `identity_shrunk` specifically. The code path is right: `storage_check` returns `report.counted` and `pipeline` gates on it, and `tests/test_storage_cutover.py:984-1018` cover the gate with another difference. A future change to how `identity_shrunk` counts, or marking it declared, would not fail any test that names the fold. There is also a stray second blank line before `test_an_identity_row_with_no_stem_or_a_bad_chunk_is_counted_identity_unreadable` (about `tests/test_storage_parity.py:937`).
**Fix:** In `test_a_loss_nobody_repairs_is_counted_on_every_later_check...`, assert each degraded run's notes contain `storage fold skipped` when a fold is due, or add one test in the fold case class that removes a baseline-only ID and checks the Events row count is unchanged across two runs. Remove the extra blank line.

### IN-10: The documented repair path has no tooling and the mark can be stuck high by a transient over-read

**File:** `STATUS.md` (WR-06 cost paragraph), `SPEC.md:111`, `compact.py:754`
**Issue:** The docs give "restore the missing IDs to `Identity`, for example from `Events_Legacy`" as the only repair. No command does it. The poller's start-of-run repair rebuilds only Tally groups, not Identity, and `Identity` is a codec cell (chunked, escaped entries with a `Count` column), so a hand edit is error-prone, which the test itself needs seven lines of cell surgery to do. Also, because the mark can only rise, a single over-read (a transient read that returns extra rows, or duplicates as in WR-07) leaves it stuck high for good. The user chose not to add an acknowledgement input, so this is only an operational cost, not a defect. It is better recorded than discovered during an incident.
**Fix:** Add a short runbook note to DEPLOY.md or STATUS ("to clear a stuck `identity_shrunk`, set `last_check.identity_entries` in the Discovery `storage` key to the true count, after confirming nothing is lost"), and consider a read-only `--storage-parity` line that prints the mark and the current count, so the owner can see which side moved.

---

_Reviewed: 2026-11-14_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
