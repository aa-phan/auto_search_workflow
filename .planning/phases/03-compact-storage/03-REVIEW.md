---
phase: 03-compact-storage
reviewed: 2026-11-14T00:00:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - DECISIONS.md
  - SPEC.md
  - STATUS.md
  - compact.py
  - hunter.py
  - parity.py
  - pipeline.py
  - state.py
  - tests/test_compact.py
  - tests/test_storage_cutover.py
  - tests/test_storage_parity.py
findings:
  critical: 0
  warning: 1
  info: 8
  total: 9
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-11-14
**Depth:** standard (incremental re-review: `git diff 4a9d568 HEAD` for the five fix commits a2247a9, 58d9ec2, 024319f, 6648949, 8b02697 and the doc commit 60786e7, each hunk read in its surrounding code: `pipeline.run_cycle`, `storage_fold`, `storage_check`, `state.SheetState` / `CsvState`, `compact.StorageState`, `parity.check_compact`, `hunter.run_storage_restore`)
**Files Reviewed:** 11
**Status:** issues_found

## Summary

I re-read the five fixes adversarially, looking for a way each one still fails or breaks something that worked. **All five earlier warnings are resolved and I found no regression and no BLOCKER.** One new WARNING and two new INFO items remain, and the six earlier INFO items are still open.

Resolved (each traced against the diff; none of the fixes was found incomplete):

| Earlier finding | Fix commit | Verification |
|---|---|---|
| WR-01 restore guard open after a partial fold | a2247a9 | `storage_fold` saves `fold.started_day` before the first delete, and skips the fold for the run if that save fails. `fold_record` turns the marker into `first_day`, even for a fold that then finds nothing left. `hunter.run_storage_restore` refuses on either field. `SheetState.fold_touched` and `CsvState.fold_touched` are set before the first request, so a lost reply counts as "touched". The marker is taken back only when no request went out. The `getattr(state, "fold_touched", True)` default is conservative. |
| WR-02 Identity loss undetected, `ensure()` recreates an empty tab | 58d9ec2 | `ensure()` refuses a missing Identity or Tally tab in compact mode, in both `SheetState` and `CsvState`. Restored mode and a missing Discovery tab still recreate it. `identity_shrunk` and `identity_unreadable` are counted. Limit: see WR-06. |
| WR-03 Tally write failure became a permanent undercount | 024319f | `carry_tally` stores the counts-only row in `storage.pending_tally`. It is written at the next run start before `repair_plan`, deduplicated against the snapshot by (Run_ID, Run_At), and the repair skips the groups it is still waiting for. Malformed entries are dropped on load. The carry is bounded. See IN-08 for two quality points. |
| WR-04 stale Identity cache overwrote the sheet | 6648949 | `write_identity` drops the cache on any exception (`BaseException`) and re-reads Identity before the next plan. Both lost-reply shapes (batch_update applied, and append applied with a failed row read-back) have tests that pass. |
| WR-05 the fold ignored the same run's integrity check | 8b02697 | `storage_check` returns `report.counted`, and a check that raised returns 1. The fold runs only when `check_counted == 0`. `None` (the check did not run) also skips it. Declared differences do not block it. |

**Doc check.**
- SPEC.md, DECISIONS.md D-57 and STATUS.md match the code. They name the new fields (`started_day`, `pending_tally`, `identity_shrunk`, `identity_unreadable`, `identity_entries`) and the new `ensure()` refusal.
- They state the one-shot reporting of `identity_shrunk` and that a persistent difference holds the fold back.
- They label every check as mocked, say "NOT deployed", and claim no live Sheets, Groq or Telegram verification. That honours AGENTS rule 5.
- The "Ran 931 tests ... OK" claim is correct: I ran `.venv/bin/python -m unittest discover -s tests` and got `Ran 931 tests ... OK`.
- Freshness is untouched. Identity stays ATS + board + posting ID. Seen, evaluated and alerted stay separate. WR-03 and WR-01 each turn a transient error into a retried state instead of a permanent record, as AGENTS rule 4 asks.

**Test run:** offline only (`tests/fake_sheets.py`, the CSV store, hand-built ledgers). Nothing was verified against the live Sheets API.

## Critical Issues

None.

## Warnings

### WR-06: `identity_shrunk` is reported once, then the lowered count becomes the new reference

**File:** `compact.py:739-757` (`record_compact_check`), `pipeline.py:247-251` (`storage_check`), `parity.py:362-372` (`_identity_loss`)
**Issue:** The WR-02 fix compares this check's Identity entry count with `last_check.identity_entries`. `record_compact_check` then stores the current count even when it is lower (`kept = identity_entries if identity_entries is not None else previous`). Trace:

1. Check N records 100 entries.
2. Rows are deleted from Identity by a hand edit or a bad sort.
3. Check N+1 sees 80, counts `identity_shrunk` (80 vs 100), degrades the run and skips that day's fold. It records 80.
4. Check N+2 compares 80 with 80, so it counts 0. Runs return to OK, NEEDS ATTENTION clears, and the fold runs again on the damaged Identity.

The loss is permanent, because Identity is append-only and nothing re-adds baseline-only IDs. The signal lasts one run, about an hour. A weekend owner never sees it. `last_diffs` is overwritten by the next clean check. SPEC and STATUS document "reported for the run that sees it, then the lower count is the new reference", so this is a deliberate design, but it defeats the purpose of the fix. WR-02's own impact statement was that baseline-only IDs lost silently make old postings look new, and boards under `FLOOD_MIN_JOBS` re-evaluate and re-add every old posting. After one hour that damage is silent again. The fold's per-key test only protects the rows it deletes, not the baseline IDs.

**Fix:** Keep a high-water mark. Never lower `last_check.identity_entries` automatically:
```python
kept = max(previous or 0, identity_entries) if identity_entries is not None else previous
```
A permanent `identity_shrunk` then holds the fold back and keeps the run degraded until the owner restores the tab or acknowledges the loss. The acknowledgement can be a documented reset of `last_check.identity_entries`, or a `--storage-ack-identity` step. A deliberate, owner-approved rebuild of Identity is the only legitimate way to shrink it. Update SPEC, D-57 and the STATUS note ("reported for the run that sees it") with the change, and extend `test_an_id_that_only_identity_holds_and_was_removed_is_counted_identity_shrunk_on_the_next_run`, which currently asserts the one-shot behaviour (`last_check["identity_entries"] == recorded - 1`).

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
**Issue:** `load_ledger` reads Events, then Identity, then Tally with separate calls. A manual `--storage-parity` or `--dashboard` that overlaps a poller run can see Events from before the run and Tally or Identity from after it, which gives counted differences that disappear on the next run. The WR-02 fix now also compares the Identity entry count in `--storage-parity` against `last_check.identity_entries`, which a racing poller run advances. Mitigated by the one-run-at-a-time concurrency group. Still open.
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

---

_Reviewed: 2026-11-14_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
