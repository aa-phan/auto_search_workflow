---
phase: 03-compact-storage
plan: 07
subsystem: storage
tags: [fold, deleteDimension, storage-report, allocated-cells, integrity-check, growth-simulation, compact-mode]

requires:
  - phase: 03-compact-storage
    provides: "plans 03-01..03-06: Identity and Tally, StorageState, the cutover and the restore, the `cutover` record with the before snapshot, sheet_grid, the merged Ledger view"
provides:
  - "compact.fold_plan, delete_ranges, fold_record, FoldPlan, FOLD_REQUESTS_PER_BATCH and StorageState.fold_due, record_compact_check"
  - "state.fold_events in the Sheet store (descending deleteDimension batches of at most 500, key check first) and the CSV store (atomic rewrite)"
  - "pipeline: the once-a-UTC-day fold after the cutover day (FOLD_CUTOFF_S 20 min), the run notes `storage fold: N rows (M kept: not durable yet)` and `storage fold failed: <type>`, the compact-mode integrity check in every run"
  - "storage_report.analyze(grid=, storage=): tabs, allocated cells and share of 10,000,000, median Load_S of the last 24 runs, daily growth in allocated cells, before_after; sections TABS, BEFORE / AFTER THE CUTOVER, COMPACT STORAGE (projection while dual writing; not measured)"
  - "parity.check_compact and the compact branch of `--storage-parity`"
affects: [03-08 deploy decision, 03-09 live cutover and first fold]

actuals:
  tokens: 30090
  tasks: 3
  commits: 5
plan_head_before: feb5d807bec01cb34243a9369e8e13ca4b7dcb26
plan_head_after: ce936a0eebec245497c519593247013f5d8e6651
commits: 5

tech-stack:
  added: []
  patterns:
    - "a structural delete is planned on the start-of-run snapshot, verified against a fresh read of the planned rows, and sent bottom-up in batches that are atomic one by one, so an interruption leaves a consistent sheet and the next run plans again"
    - "durability is proven BEFORE a delete (Identity and Tally as read at run start); a failing candidate is kept, counted and retried the next day after the start-of-run repair"
    - "a report that must not claim what it did not measure labels the figure a projection while dual writing and prints `not measured yet` until a complete UTC day follows the first fold"
    - "the offline growth simulation drives the real split, retained and fold code over 28 days instead of re-deriving the rates"

key-files:
  created: []
  modified:
    - compact.py
    - state.py
    - pipeline.py
    - storage_report.py
    - hunter.py
    - parity.py
    - tests/test_storage_cutover.py
    - tests/test_storage_report.py
    - tests/test_storage_parity.py
    - tests/test_hunter.py
    - SPEC.md
    - DECISIONS.md
    - STATUS.md
    - DEPLOY.md

key-decisions:
  - "The fold is the point of no return (P3-01, costly): flagged in D-57; it acts only in compact mode, on a UTC day after the cutover day, so nothing in production changes before the owner's cutover (plan 03-09)"
  - "`fold.first_day` is set only by the first fold that deleted a row, so a fold that deleted nothing does not block the restore; `last_day` is set by every fold that ran to its end"
  - "fold_events checks the planned rows against a fresh read of the key and event columns before the first delete (T-03-29 hardening beyond the plan)"
  - "Daily growth in allocated cells = median over complete UTC days of 7 x the change in Runs.Events_Rows (+ Identity and Tally row growth since the cutover for the after figure), only days strictly after fold.first_day; the compact figure while dual writing is a labelled projection"
  - "The compact integrity check closes the 03-01 deferred item with a stated limit: only Events -> Identity can be checked; a lost count of baselines alone cannot be detected"
  - "`--storage-parity` in compact mode runs the integrity check (exit 0/1); restored and unseeded still exit 2; the old compact-refusal test was replaced"

patterns-established:
  - "Every mutation check is applied with PYTHONDONTWRITEBYTECODE=1, observed failing, restored from a saved copy and compared byte for byte (cmp) before the next run"
  - "Shared test bases without test methods (CutoverCase, FoldCase) are imported into other test modules for state setup without duplicating tests"

requirements-completed: [STOR-01]

coverage:
  - id: D1
    description: "Fold on the Sheets fake: the first compact-mode run of a UTC day after the cutover day deletes exactly the filtered or stale rows at or before now - 7 x 24 h (exactly 7 x 24 h goes, one second younger stays) that are durable in Identity and Tally, in ONE batch of descending deleteDimension ranges; Events_Legacy, operational rows and the Identity and Tally tabs untouched; the fold record and the run note"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_storage_cutover.py#FoldTests, FoldPlanTests, FoldStoreTests"
        status: pass
    human_judgment: false
  - id: D2
    description: "Fold safety: no fold before the cutover, on the cutover's own UTC day (23:59:59 included), twice a day, in dual or restored mode, with a compact key but no Events_Legacy, in a dry run or past the 20-minute cutoff; a row whose ID or Tally count is not durable is kept, counted and folded the next day; a failed or half-done fold leaves last_day unset, counts every job once and is finished by the next run; a shifted row refuses the whole fold"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_storage_cutover.py#FoldTests, FoldBeforeCutoverTests, FoldStoreTests"
        status: pass
    human_judgment: false
  - id: D3
    description: "Every Dashboard figure, the summary and the logical counts are the same before and after a fold (a half-folded run counts each job once)"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_storage_cutover.py#FoldTests.test_every_dashboard_figure_is_the_same_before_and_after_the_fold, test_a_half_folded_run_counts_each_job_once_and_the_next_run_finishes_it"
        status: pass
    human_judgment: false
  - id: D4
    description: "Storage report: per-tab rows, columns and allocated cells with the total and its share of 10,000,000, median Load_S of the last 24 runs, daily growth in allocated cells (after figure only over complete days after the first fold), BEFORE / AFTER THE CUTOVER from the cutover snapshot, the projection label while dual writing, n/a for unmeasured figures, the command wiring and the unreadable-metadata fallback"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_storage_report.py#AllocatedCellsTests, BeforeAfterTests, CommandsReadTheMergedViewTests"
        status: pass
    human_judgment: false
  - id: D5
    description: "SC3 offline: 28 days at 700 boards through the real split_observations, retained_events and fold_plan give about 36,800 allocated cells a day with every row kept against about 1,700 after the folds (ratio above 20, at least 10 required)"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_storage_report.py#GrowthSimulationTests"
        status: pass
    human_judgment: false
  - id: D6
    description: "Compact-mode integrity check in every poller run and in --storage-parity: identity_missing, identity_kind, the codec invariants, tally_missing, tally_negative, tally_count and figure_checks are counted by name; a difference degrades the run; compact runs record no clock day; a check that raises or runs past the cutoff behaves like the dual check; restored and unseeded still exit 2"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_storage_parity.py#IntegrityCheckTests, IntegrityTests; tests/test_hunter.py#StorageParityCommandTests"
        status: pass
    human_judgment: false
  - id: D7
    description: "SPEC, D-57, DEPLOY and STATUS words for the fold (the point of no return), the report's new sections, the integrity check and its limits, and the list of what only a live run can show"
    requirement: STOR-01
    verification: []
    human_judgment: true
    rationale: "The documents tell the owner what the fold deletes for good and what is still unproven; only the owner can judge the wording before the plan 03-08 deploy decision"
  - id: D8
    description: "The real fold: Google applying several hundred deleteDimension ranges in one batchUpdate (research A5), the first fold's duration at about 35,000 rows, allocated cells from the real metadata, the Events_Legacy protection prompt"
    requirement: STOR-01
    verification: []
    human_judgment: true
    rationale: "Everything here ran against the in-memory Sheets fake, which interprets deleteDimension itself; plan 03-09 observes the real fold with the owner's decision and credentials"

duration: 66min
completed: 2026-10-29
status: complete
---

# Phase 3 Plan 07: The 7-day fold, the storage report and the compact integrity check Summary

**Week-old title-gated and stale rows now leave Events in one bottom-up `deleteDimension` batch once per UTC day after the cutover day, only when their IDs and counts are already durable in Identity and Tally; `--storage-report` prints allocated cells per tab, load time and before/after growth (a labelled projection while dual writing); and every compact-mode run checks that Identity and Tally agree with the rows Events keeps. All mocked: nothing is pushed or run against the real Sheet.**

## Performance

- **Duration:** 66 min
- **Started:** 2026-10-29T18:29:00Z
- **Completed:** 2026-10-29T19:36:00Z
- **Tasks:** 3 (tracer, TDD task, TDD task)
- **Files modified:** 14 (none created); +1,500 / -55 lines
- **Tests:** full suite 836 -> 910, all offline (`Ran 910 tests ... OK`): FoldPlanTests 10, FoldStoreTests 4, FoldBeforeCutoverTests 1, FoldTests 17, AllocatedCellsTests 5, BeforeAfterTests 7, GrowthSimulationTests 4, IntegrityCheckTests 12, IntegrityTests 11, two storage-report command tests, one `--storage-parity` compact test (one older compact-refusal test replaced)

## Accomplishments

- **The fold (P3-03, tracer).** `compact.fold_plan(ledger, now)` selects every `seen` row of each key whose first observation is a keyable `filtered` or `stale` row at or before `now - 7 x 24 h`, but only when the key's ID is in the Identity set read at run start AND its (Run_ID, Run_At) Tally group exists with at least the retained count; failing candidates are kept and counted once per key. `state.fold_events` sends `deleteDimension` for contiguous ranges, highest first, 500 requests per `spreadsheets.batchUpdate`, after a fresh read confirms that every planned row still holds its key in a `seen` row. The poller folds once per UTC day, only in compact mode, only after the cutover's UTC day, after the alert stage and the check, not past 20 minutes, never in a dry run. Notes: `storage fold: N rows (M kept: not durable yet)`; a failure adds `storage fold failed: <type>` (degraded) and leaves `fold.last_day` unset.
- **The storage report (SC3).** `analyze(grid=, storage=)` and `format_report` add `TABS` (Events, Identity, Tally, Events_Legacy first, then every other tab, with the share of the 10,000,000-cell limit), the median Load_S of the last 24 runs, the median daily growth in allocated cells and `BEFORE / AFTER THE CUTOVER`; while dual writing the compact figure is printed under `COMPACT STORAGE (projection while dual writing; not measured)`. `--storage-report` reads `sheet_grid()` and the `storage` key and survives an unreadable metadata call.
- **The offline order-of-magnitude check.** `GrowthSimulationTests` drives the real `split_observations`, `retained_events` and `fold_plan` over 28 days at 700 boards (admission wave of 140 boards on day 3, cutover on day 14, folds from day 15): about 36,800 allocated cells a day with every row kept against about 1,700 after the folds, a ratio above 20 (the plan required 10; D-43 estimated about 26,200 against about 1,300 at 500 boards).
- **The compact integrity check.** `parity.check_compact` (Identity codec, every kept identity-class key in Identity, no Tally group missing or below its retained count via `Ledger.negative()`, empty consistency list from the merged summary) runs in every compact-mode poller run (same cutoff and containment, `last_check` recorded, no clock day) and in `--storage-parity` (exit 0/1; restored and unseeded exit 2). It closes the open plan 03-01 item on `Ledger.negative()` with a stated limit.

## Task Commits

1. **Task 1: Tracer, the fold** - `2b4137f` (feat; tests and implementation in one tracer commit)
2. **Task 2: storage report** - `ffbf5f6` (test, RED) then `d449d67` (feat, GREEN)
3. **Task 3: compact integrity check, STATUS** - `574ccbb` (test, RED) then `ce936a0` (feat, GREEN)

**Plan metadata:** the `docs(03-07): complete ...` commits that follow this file.

## Tracer gate

`human_verify_mode` is the default `end-of-phase`, auto mode is off (`_auto_chain_active` false) and the tracer `<verify>` is automated only: `tests.test_storage_cutover -k Fold` (32 tests) and the full suite (868 tests at that point) were re-run after the tracer commit and passed. Tracer verified end-to-end, expansion followed.

## TDD evidence

- **Task 2 RED** (`ffbf5f6`): `NO_COLOR=1 .venv/bin/python -m unittest tests.test_storage_report` exited 1 (11 errors of 40). `gsd_run check tdd-red-evidence` returned `RED_EVIDENCE_OK` (`target_test_failed`, 11 failing tests) for the target `BeforeAfterTests.test_after_the_first_fold_both_sides_are_printed_and_only_days_after_the_first_fold_count_for_growth`. Semantic assessment: the target ran and failed inside its own body with `TypeError: analyze() got an unexpected keyword argument 'grid'`, the planned interface not existing yet (no load or fixture fault, no `_FailedTest`). `GrowthSimulationTests` passed at RED by design: they drive code that Task 1 already built (characterization). **GREEN** (`d449d67`): 42 tests of the module and the full suite (886) pass.
- **Task 3 RED** (`574ccbb`): `NO_COLOR=1 .venv/bin/python -m unittest tests.test_storage_parity -k Integrity` exited 1 (8 failures, 13 errors of 23): `RED_EVIDENCE_OK` for the target `IntegrityTests.test_an_identity_id_removed_for_a_kept_gated_row_degrades_the_run_and_the_next_runs_repair_clears_it`, which failed on `AssertionError: 'ok' != 'degraded'` (a compact-mode run performed no check), the pure tests erroring on the missing `parity.check_compact`. Two tests (cutoff skip, restored refusal) passed at RED because their planned behaviour is also the absence of a check. **GREEN** (`ce936a0`): 23 tests and the full suite (910) pass.
- **TDD gate:** `test(03-07)` `ffbf5f6` precedes `feat(03-07)` `d449d67`; `test(03-07)` `574ccbb` precedes `feat(03-07)` `ce936a0`. Task 1 is a `type="tracer"` task (not `tdd="true"`): its tests were written first but committed with the implementation.

## Mutation checks

Each applied with `PYTHONDONTWRITEBYTECODE=1`, observed failing, restored from a saved copy and compared with `cmp` before the next run or commit.

- **Task 1:** ranges in ascending order (6 fail, including the plan's named FoldTest and `FoldStoreTests`); Identity-membership test dropped (2 fail: the kept-row test and its pure twin); Tally test dropped (3 fail); fold allowed on the cutover day, `>=` instead of `>` (2 fail); the pipeline's mode and note guard removed (1 fails: compact key without `Events_Legacy`).
- **Task 2:** after-growth window including the first fold day (3 fail); Identity and Tally side growth dropped (3 fail); fold disabled in the simulation (2 fail: the ratio and the one-week test); the projection label removed (2 fail).
- **Task 3:** Identity-presence test dropped (3 fail); `tally_negative` dropped (2 fail); clock days recorded in compact mode (1 fails); compact check not run (7 fail); summary checks not run (2 fail).
- **One slip, caught:** my first Task 3 mutation helper restored from a wrong file name, so five mutants stayed applied in `parity.py` and `pipeline.py` for one more run; I restored both files from the saved copies, confirmed with `cmp` that they were byte-identical to the pre-mutation copies and re-ran the mutants one at a time (the figures above). Nothing was committed while a mutant was applied.

## Files Created/Modified

- `compact.py` - `FOLD_REQUESTS_PER_BATCH`, `FoldPlan`, `fold_plan` (skips parsing rows younger than the cut), `delete_ranges`, `fold_record`, `StorageState.fold_due`, `record_compact_check`
- `state.py` - `fold_events` in `SheetState` and `CsvState`
- `pipeline.py` - `FOLD_CUTOFF_S`, `storage_fold`, the fold step, the compact-mode branch of `storage_check`, `storage fold failed` in `degraded_reason`
- `storage_report.py` - `analyze(grid=, storage=)`, `_cells_and_growth`, `_before_after`, `_side_cells_per_day`, `_cells_section`, shared helpers with `before_snapshot`
- `hunter.py` - `--storage-report` passes the grid and the storage key; `run_storage_parity` runs `check_compact` in compact mode
- `parity.py` - `check_compact`, `_kept_in_identity`, `_tally_integrity`, `_summary_checks`, `_identity_invariants` (factored out of `_seen_set`, behaviour unchanged)
- `tests/test_storage_cutover.py`, `tests/test_storage_report.py`, `tests/test_storage_parity.py` - the new test classes; `tests/test_hunter.py` - the compact-refusal test replaced
- `SPEC.md`, `DECISIONS.md` (D-57), `STATUS.md`, `DEPLOY.md` - the fold, the report sections, the integrity check, the mocked/not-verified lists
- `.planning/phases/03-compact-storage/deferred-items.md` - the 03-01 item marked resolved with its limit

## Decisions Made

- The fold is the costly point of no return (P3-01) and is flagged in D-57; it cannot act before the owner's cutover.
- `fold.first_day` is set by the first fold that deleted a row; a zero-row fold changes nothing irreversible and does not block the restore (`last_day` is still set so it does not repeat that day).
- Growth in cells, the allocated-cells source (sheet metadata), the simulation's model and the integrity check's limits are written in D-57 and STATUS.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical] A shifted row could be deleted by the fold**
- **Found during:** Task 1 (threat T-03-29, "index shift"; the planned `fold_events(rows)` trusted the row numbers loaded at run start)
- **Issue:** a hand edit between the load and the delete (an inserted or removed row) would make `deleteDimension` remove an unrelated row, irreversible in the app.
- **Fix:** `fold_events(rows, expect=None)` takes the planned key of each row (`FoldPlan.row_keys`); before the first request the store reads the key and event columns fresh and raises if any planned row no longer holds its key in a `seen` row. The pipeline always passes it; the plan's one-argument call still works.
- **Files modified:** compact.py, state.py, pipeline.py, tests/test_storage_cutover.py
- **Verification:** `FoldStoreTests.test_a_row_that_no_longer_holds_the_planned_key_refuses_before_any_delete` and the CSV twin
- **Committed in:** 2b4137f

**2. [Rule 3 - Blocking] An existing test asserted the superseded behaviour of `--storage-parity` in compact mode**
- **Found during:** Task 3 (full suite after the GREEN change)
- **Issue:** `tests/test_hunter.py` expected exit 2 for stored mode `compact`; the plan makes `--storage-parity` run the integrity check there.
- **Fix:** the test now covers only `restored` and the unseeded state; a new test runs the compact check (exit 0 on a clean state).
- **Files modified:** tests/test_hunter.py (not in the plan's `files_modified`)
- **Committed in:** ce936a0

**3. [Documentation, AGENTS rule 1] Files outside the plan's list**
- DEPLOY.md (it described `--storage-parity` as dual-only) and `.planning/phases/03-compact-storage/deferred-items.md` (the 03-01 item) were updated so the documents do not contradict the code.

**4. [Discretion] Smaller choices not named by the plan**, all recorded in D-57: `first_day` only after a row was deleted; the note is omitted when a fold deleted nothing and kept nothing; `fold_plan` skips parsing rows younger than the cut by comparing stamps as strings (same result, about 3x faster); the compact check's `identity_entry` kind for malformed entries.

---

**Total deviations:** 4 (1 Rule 2, 1 Rule 3, 1 documentation, 1 discretion). **Impact on plan:** the key check makes the fold refuse in one more unsafe state; no scope creep.

## Issues Encountered

- My first fold-test expectations ignored that the cut moves with `now` (a retry at +30 min or the next day folds jobs 33, 11 and 12 too); the tests now retry at the same instant or assert the next day's extra rows explicitly.
- `FoldTests.edit_identity` first left the `Count` column stale, which the compact check rightly counted as `identity_count`; the helper now removes the entry the way a clean removal would.
- The plan's example `fold_events(rows)` could not see the row-shift risk (see deviation 1).
- The simulation costs about 3.5 s of the 15 s suite; kept at 700 boards as the plan states.

## Authentication Gates

None. The agent read no `.env`, no `Resume.pdf`, `resume.txt` or service-account file; no Google, Groq or Telegram call was made; nothing was pushed, deployed or dispatched.

## User Setup Required

None. The fold and the report changes exist only after the owner pushes this code (plan 03-08); production runs the previous code in dual mode until then.

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model: T-03-29 (row numbers from the start-of-run load, descending contiguous ranges, Identity membership and Tally group required, ascending-order mutation, plus the key check above), T-03-30 (compact mode only, date after the cutover day, `last_day` guard, Events sheet id only), T-03-31 (500 requests per call as a constant, 20-minute cutoff, failure leaves `last_day` unset; the real limit is a plan 03-09 observation), T-03-32 (projection label, after-figures only from complete days after the first fold).

## Next Phase Readiness

- Ready for plan 03-08 (deploy decision): it must surface that the fold is the point of no return (costly), the P3-06 restore refinement from plan 03-06 and the new `--storage-parity` compact behaviour.
- Plan 03-09 (live) must observe what STATUS lists as not verified live: the rename pair, `deleteDimension` batches of several hundred ranges (research A5) and the first fold's duration at about 35,000 rows, allocated cells from the real metadata, the Events_Legacy protection prompt, the integrity check's seconds at the real size.
- Production is unchanged: dual mode since 2026-10-29, nothing of this plan is pushed. The earliest `READY TO CUT OVER` is 2026-11-02 00:00 UTC.

## Self-Check: PASSED

- All 14 modified files exist (`git status` clean except the pre-existing untracked planning paths and this plan's planning files); no file was created.
- Commits `2b4137f`, `ffbf5f6`, `d449d67`, `574ccbb`, `ce936a0` are ancestors of HEAD (`git rev-list --count feb5d80..HEAD` = 5 before this file).
- TDD gate: `test(03-07)` precedes `feat(03-07)` for Tasks 2 and 3.
- Acceptance criteria re-run: `def fold_plan` 1, `FOLD_REQUESTS_PER_BATCH = 500` 1, `def fold_events` in state.py 2, `deleteDimension` in state.py 2, `FOLD_CUTOFF_S` in pipeline.py 3, `BEFORE / AFTER THE CUTOVER` in storage_report.py 1, `projection while dual writing` 1, `sheet_grid()` in hunter.py 3, `def check_compact` 1, `tally_negative` in parity.py 3, `deleteDimension` in STATUS.md 3, `A5` in STATUS.md 2.
- Plan verification: `tests.test_storage_cutover tests.test_storage_report tests.test_storage_parity` OK; full suite `Ran 910 tests ... OK`.
- Mocked versus live: everything above is mocked (CSV store, the in-memory Sheets fake, fake ATS, scorer and alert channel, synthetic ledgers). No claim of live verification of Sheets, Groq or Telegram is made.
- No untracked generated files; the six pre-existing untracked planning paths were not committed.

---
*Phase: 03-compact-storage*
*Completed: 2026-10-29*
