---
phase: 03-compact-storage
reviewed: 2026-11-06T00:00:00Z
depth: standard
files_reviewed: 19
files_reviewed_list:
  - compact.py
  - parity.py
  - state.py
  - pipeline.py
  - hunter.py
  - storage_report.py
  - reporting.py
  - dashboard.py
  - pilot.py
  - .github/workflows/job_hunter.yml
  - tests/fake_sheets.py
  - tests/test_compact.py
  - tests/test_storage_parity.py
  - tests/test_storage_pipeline.py
  - tests/test_storage_cutover.py
  - tests/test_storage_report.py
  - tests/test_deployment.py
  - tests/test_hunter.py
  - tests/test_reporting.py
findings:
  critical: 0
  warning: 5
  info: 6
  total: 11
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-11-06
**Depth:** standard (diff 767a305..HEAD, each changed file read in context; call chains followed across compact / state / pipeline / hunter / parity / reporting / storage_report / pools / ledger)
**Files Reviewed:** 19
**Status:** issues_found

## Summary

I read the fold, the merged seen view and the compact integrity check adversarially, because the code is live and the fold deletes rows.

**The core is sound.** I found no BLOCKER. I traced these paths and could not break them:

- **Fold selection (`compact.fold_plan`).**
  - Only a key whose first `seen` row is `filtered` or `stale` and at least 7 days old is a candidate.
  - Its posting ID must be in the Identity set read at run start.
  - Its (Run_ID, Run_At) Tally group must hold at least as many observations of that dimension as Events still retains.
  - Rows are deleted by sheet row number, highest range first.
  - `SheetState.fold_events` first re-reads the key and event columns and refuses the whole fold if any planned row no longer holds the planned key as a `seen` row.
  - A stale row number or a concurrent writer therefore cannot delete the wrong rows.
- **Merged seen view in `pipeline.run_cycle`.**
  - `seen(key)` is "Identity entry or a `seen` state from Events".
  - Alertable jobs (`fr.ALERTABLE` = verified fresh only) are `pending` rows. They are never identity-class and never folded.
  - `evaluated` and `alerted` events always stay in Events, so a fold, a cutover or a restore cannot make an alerted job alertable again.
  - I fuzzed the Identity codec (`%`, `,`, `%2C`, `%25`, newlines, non-ASCII) and chunk planning for round trips and idempotence. No failure.
- **Observation write point.**
  - The order is Events, Identity, Tally, Boards.
  - In compact mode an Identity failure propagates before Boards is saved, so the board re-baselines.
  - The crash path in `finally` never double-splits.
- **Tally weighting.** `reporting._count_seen` and `_folded_fact` pass folded counts through the same code as real jobs. `tally_dim` and `job_facts` map source, pass kind, freshness and date-known identically.

The five WARNINGs are:

- **WR-01:** a gap in the restore guard (`fold.first_day`).
- **WR-02:** the compact integrity check is blind to Identity loss, and `ensure()` silently recreates a deleted Identity tab.
- **WR-03:** a Tally write failure becomes a permanent undercount in compact mode.
- **WR-04:** `write_identity` can overwrite sheet entries from a stale cache.
- **WR-05:** the destructive fold does not consult the same run's integrity check.

The INFOs are documentation drift, a workflow input combination and small quality items.

Test run: `python3 -m unittest discover -s tests` under the system Python 3.9 gives 910 tests with 1 failure and 5 errors. All of them are environmental: `gspread` and `requests` are not installed, `assertNoLogs` needs 3.10+, and a subprocess lease test imports the missing modules. None touches Phase 3 code. The suite was not re-run under the project's Python 3.12 environment. Everything in the storage tests is mocked (`tests/fake_sheets.py`); nothing here was verified against the live Sheets API.

## Warnings

### WR-01: A fold that deleted rows but did not record `first_day` leaves the restore guard open (and under-counts `rows_total`)

**File:** `compact.py:457-466` (`fold_record`), `pipeline.py:271-278` (`storage_fold`), `state.py:551-571` (`fold_events`)
**Issue:** The restore is refused only while `storage.fold.first_day` is unset (`hunter.py` `run_storage_restore`). `first_day` is written only after (a) `fold_events` returned and (b) `save_discovery_state` succeeded. Two realistic paths delete rows without ever recording it:

1. `fold_events` sends several `batchUpdate` calls (500 `deleteDimension` requests each). If call 1 succeeds and call 2 raises (timeout, 5xx), `storage_fold` returns False before touching `storage.fold`. Rows are gone, `first_day` is unset, and `--storage-restore` is allowed until the next run completes the fold. `tests/test_storage_cutover.py::test_a_half_folded_run...` asserts `fold == {}` after this failure, so it locks the behaviour in.
2. All batches succeed but the `save_discovery_state` that records the fold fails ("storage write failed"). The next run re-plans from a fresh load, finds nothing left, and calls `fold_record(prev, now, rows=0, ...)`. I confirmed that this returns `{'last_day':..., 'last_rows': 0, 'rows_total': 0}` with no `first_day`, so the guard stays open permanently, and `rows_total` omits the earlier deletions.

A restore in that state renames `Events_Legacy` back to `Events` and appends only the post-cutover rows still present. Post-cutover filtered or stale rows that a fold already removed are lost from the restored ledger. Identity still holds their IDs, so there is no duplicate alert, but the per-job rows and the report counts are gone. This is exactly what the guard exists to prevent.

**Fix:** Record the intent before the destructive call. In `storage_fold`, when `plan.rows` is non-empty, set `storage.fold["first_day"]` (if unset) and save the `storage` key before calling `state.fold_events`. A fold that then deletes nothing is harmless, because the restore is merely refused earlier. If the save fails, skip the fold for this run and add the note. Keep `fold_record` as is, and add a test that fails `fold_events` after the first batch and asserts `first_day` is set.

### WR-02: The compact integrity check cannot detect Identity loss, and `ensure()` quietly recreates a deleted Identity tab

**File:** `parity.py:301-332` (`_kept_in_identity`), `compact.py:148-156` (`IdentityRow.from_row`), `state.py:315-335` (`SheetState.ensure`)
**Issue:** After the fold, the keys that matter most for "old jobs looking new" (baselines and folded rows) have no Events row, so `check_compact` has nothing to compare them with. The docstring admits this ("a known limit"). The practical consequences:

- If the Identity tab is deleted, `ensure()` creates a fresh empty one. `Identity` is in its create-if-missing list, and the Events-missing guard does not cover it. `repair_plan` re-adds only IDs that still have an Events row. The compact check then reports clean, because every kept key is repaired and the baseline-only IDs are not looked at.
- `IdentityRow.from_row` silently drops any row whose stem is blank or whose `Chunk` is not an integer (a hand edit, a stray sort). Those IDs vanish from `seen()` and nothing counts or reports the dropped rows.
- Impact: boards with fewer than 30 unseen jobs (below `FLOOD_MIN_JOBS`) re-observe every old posting as new. Those jobs are re-evaluated by Groq and re-added to the tracker (cost and clutter). A duplicate Telegram alert is unlikely, because only `pending` verified-fresh jobs are alertable and they stay in Events. The tracker and evaluation damage is still real, and it is silent.

**Fix:** Identity is append-only, so its entry count must never fall.
1. Store `identity_entries` (and optionally per-stem counts) in `storage.last_check`. In `check_compact`, compare against the previous value and count a decrease as `identity_shrunk`.
2. Count unparseable Identity rows in `load_ledger` and report them as a counted difference.
3. In compact mode (stored mode compact and `Events_Legacy` present), make `ensure()` raise like the Events-missing guard when `Identity` or `Tally` is missing, with a message pointing at `Events_Legacy` as the recovery source.

### WR-03: A Tally write failure in compact mode becomes a permanent undercount (AGENTS rule 4)

**File:** `pipeline.py:358-364` (`persist_observations`), `compact.py:546-562` (`repair_plan`)
**Issue:** The Tally append is contained in both modes. In dual mode `repair_plan` rebuilds a missing group from the Events rows on the next run. In compact mode a run's baseline observations have no Events rows, so the repair has nothing to rebuild from. A group that held only baselines is never repaired. A group with baselines plus kept filtered or stale rows gets a Tally row written from the kept rows only. `tally_negative` compares against retained rows only, so it cannot see the shortfall. The baseline totals on the Dashboard and in the pilot reconciliation are then understated for good, and the only trace is a one-off `storage write failed` note. This turns a transient Sheets error into a permanent record.

**Fix:** When the Tally append fails, keep the `TallyRow` (counts only) as `pending_tally` in the `storage` key. At run start, append and clear it before `repair_plan`. Alternatively, write Tally before Identity in compact mode and treat its failure like an Identity failure.

### WR-04: `write_identity` rewrites rows from its in-memory cache without checking the sheet

**File:** `state.py:629-633`, `compact.py:216-255` (`plan_additions`)
**Issue:** For rows that already exist, `write_identity` sends `batch_update` of the full cell contents computed from `self._identity`, a cache loaded at run start and updated only after each request returns. If a request is applied by Google but the client sees an error (a read timeout after the write) or `col_values` fails after an `append_rows`, the cache is behind the sheet. The failure is contained: the seed or repair is logged as failed, or in dual mode `storage write failed`. A later `write_identity` in the same run (the run's own observations) then rebuilds the stem's highest chunk from the stale cache and overwrites the cell, dropping the entries that the earlier request had actually written. Baseline-only IDs lost this way are not repaired by `repair_plan`, because only IDs with Events rows are.

**Fix:** After any exception inside `write_identity`, invalidate the cache (`self._identity = None`). The next call reloads from the sheet, which `write_identity` already does when the cache is None, so the next plan is built from what the sheet holds. Optionally, when a write fails, re-read the Identity tab before the next write in the same run.

### WR-05: The fold does not consult the integrity check the same run just ran

**File:** `pipeline.py:885-909`
**Issue:** Step 5 runs `storage_check` (`check_compact`) and records the result. Step 6 then folds, whatever step 5 found. The fold's own per-key tests (key in the start-of-run Identity set, Tally group not below the retained count) cover `identity_missing` and `tally_negative` for the candidate rows. They do not cover the other counted classes (`identity_duplicate`, `identity_count`, `identity_entry`, `identity_marker`, `tally_count`, `figure_checks`), which signal a damaged Identity or Tally. A permanent, irreversible delete trusts exactly the data the check just called inconsistent. The check also uses the same snapshot, so gating costs nothing.

**Fix:** Skip the fold (note `storage fold skipped: integrity check counted N differences`, leave `fold.last_day` unset) when `report.counted > 0` for this run. `storage_check` would need to return the report or the count. The next clean run folds.

## Info

### IN-01: `parity.py` docstring is wrong about its imports

**File:** `parity.py:3-4`
**Issue:** The docstring says the module "imports `compact` and `ledger` only (never state, pipeline or hunter)". It imports `reporting`, `storage_report` (which imports `state`) and `boards`. There is no cycle today (`pipeline` imports `parity` and `state`, and nothing imports `pipeline` back), but the stated invariant is false and will not protect a future change.
**Fix:** State the real constraint (no import of `pipeline` or `hunter`), or move the shared figure code so the claim becomes true.

### IN-02: Removing `Events_Legacy` silently flips a compact system back to dual writing

**File:** `compact.py:594-595` (`effective_mode`), `compact.py:566`
**Issue:** If the stored mode is compact and `Events_Legacy` is gone, the poller writes as dual. Baselines go back into Events, the fold and the check stop, and every run is degraded. DECISIONS P3-08 describes removing `Events_Legacy` as a later owner decision "with an export plan". As written, that decision cannot be carried out without a code change, and doing it by hand reintroduces the growth that compaction fixed.
**Fix:** Before the owner removes the tab, add a recorded state (for example `storage.legacy_retired_at` or a `--storage-retire-legacy` step) that `effective_mode` honours. Until then, note it in DEPLOY.md.

### IN-03: The workflow lets `storage_cutover` and `storage_restore` run in one job

**File:** `.github/workflows/job_hunter.yml:150-170` (and the `inputs` block)
**Issue:** The CLI makes the two flags mutually exclusive, but each is a separate workflow step guarded only by its own input. Ticking both runs the cutover and then the restore in the same dispatch. Before the first fold, the restore succeeds and immediately undoes the cutover. The same applies to other input combinations. Only the poll step is guarded against all of them.
**Fix:** Add a first step that fails when more than one of the owner-step or report inputs is true.

### IN-04: The cutover checksum covers only `key|time|event`

**File:** `compact.py:371-376` (`rows_checksum`)
**Issue:** The comment says the checksum compares "the rows it meant to copy" with the rows read back. It hashes three of the seven columns. A copy with a changed `Freshness`, `Disposition`, `Published` or `Detail` passes the checksum. The would-be parity check catches the identity-relevant cases (kind, Tally dimensions), and `Events_Legacy` stays whole, so this is not a data-loss path.
**Fix:** Hash `"\x1f".join(ev.to_row())` per row, which is the canonical full row the copy was written from.

### IN-05: Dead variable and unused imports

**File:** `reporting.py:492` (`first_event`), `storage_report.py:10,18` (`json`, `fr`)
**Issue:** `first_event` is assigned and never read, and `json` and `fr` are imported and never used. All three predate Phase 3, but this phase edited both modules and left them.
**Fix:** Delete them.

### IN-06: Read-only commands read three tabs sequentially without the lease

**File:** `state.py:573-585` (`load_ledger`), `hunter.py` (`run_storage_parity`, `run_storage_report`, `run_pilot_report`), `dashboard.py:594`
**Issue:** `load_ledger` reads Events, then Identity, then Tally with separate calls. A manual `--storage-parity` or `--dashboard` that overlaps a poller run can see Events from before the run and Tally or Identity from after it. That produces counted differences (`identity_extra` and `tally_*` in dual mode) or shifted `folded()` counts that disappear on the next run, which can restart the 3-day clock or raise a transient NEEDS ATTENTION. This is mitigated by the one-run-at-a-time concurrency group.
**Fix:** Document that a parity difference should be re-run before it is trusted, or read all three tabs in one `values_batch_get`.

---

_Reviewed: 2026-11-06_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
