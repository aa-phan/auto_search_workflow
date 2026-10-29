---
phase: 03-compact-storage
plan: 02
subsystem: storage
tags: [parity, seeding, repair, identity, tally, parity-clock, dual-write, discovery-key]

requires:
  - phase: 03-compact-storage
    provides: "plan 03-01: compact.py codecs, Identity and Tally tabs, load_ledger/write_identity/append_tally, dual write order, storage modes"
provides:
  - "parity.py (pure, read-only): Diff, ParityReport, check_dual with the seen-set, Tally-recount and state-count layers"
  - "compact.py: simulate_compact, tally_recount, first_seen_identity, Ledger.folded/negative/tally_totals, parse_dim, repair_plan, StorageState (tolerant load, record_check, bar), BarStatus, parity constants"
  - "pipeline: seed and repair at run start, snapshot check after the alert stage, degraded reason storage, STORAGE_CHECK_CUTOFF_S"
  - "Discovery key storage: mode, seeded_at, days, bar_met_at, last_check, last_diffs, cutover/fold/restore records"
  - "SPEC and D-57 text for seeding, repair, the check, a difference and the bar"
affects: [03-03 figures layer, 03-04 --storage-parity command, 03-05 live checks, 03-06 cutover, 03-07 fold]

actuals:
  tokens: 23588
  tasks: 3
  commits: 5
plan_head_before: 78f7a3c3de4c45377ed8be810a78ebe0d78373dd
plan_head_after: 7c7a64ec177d724e57efb33e501a97b74fad54ae
commits: 5

tech-stack:
  added: []
  patterns:
    - "repair as a set difference between the Events rows and the stores, so a seed or repair that was interrupted is completed without writing an ID or a Tally run twice"
    - "check on the start-of-run snapshot after the alert stage (one-run lag, never delays a poll or an alert)"
    - "parity state in one tolerant Discovery JSON key; run note keyed degraded reason instead of a new Runs column"
    - "pure parity module compared against a simulated compact view of the same rows"

key-files:
  created:
    - parity.py
    - tests/test_storage_parity.py
  modified:
    - compact.py
    - pipeline.py
    - state.py
    - tests/test_storage_pipeline.py
    - AGENTS.md
    - SPEC.md
    - DECISIONS.md

key-decisions:
  - "A run belongs to the UTC day it started in; the bar needs three complete UTC days after the seed day, 12 checked runs each, no difference, and an admission among them"
  - "A difference found today blocks the bar until three clean complete days follow it (P3-07: the clock starts again), although today is never a counted day"
  - "Declared (listed, never counted): unkeyable keys and duplicate seen rows; everything else counts"
  - "A check that raises is the counted difference check_failed; a check skipped past 22 minutes is not recorded"
  - "load_ledger() returns a copy of the Identity set so a later write_identity never changes a snapshot"

patterns-established:
  - "Diff refs are job keys, run id with its time, dimension keys or counter names; details are numbers only"
  - "A repair on an already seeded store joins the run's single storage log line"

requirements-completed: [STOR-01]

coverage:
  - id: D1
    description: "The first poller run after deploy seeds Identity for every keyable identity-class Events row and one Tally row per (run id, run time) group (blank Run_ID for rows from before run ids), then writes the storage key; an interrupted seed is completed by the next run with nothing written twice; dry runs neither seed nor record"
    requirement: STOR-01
    verification:
      - kind: integration
        ref: "tests/test_storage_pipeline.py#SeedTests"
        status: pass
    human_judgment: false
  - id: D2
    description: "Every dual-mode run after the seed checks the start-of-run snapshot after the alert stage (seen set both ways with kind, Count, cell size, marker, duplicates and stem; Tally recount per run and dimension; state counts from replay of all rows against the simulated compact view) and records the result and the clock in the storage key"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_storage_parity.py#MutationTests, SimulationTests"
        status: pass
      - kind: integration
        ref: "tests/test_storage_pipeline.py#SeedTests.test_the_next_run_checks_the_previous_writes_and_records_zero_counted_differences"
        status: pass
    human_judgment: false
  - id: D3
    description: "Each of eight mutations (Identity ID removed or added, kind letter, Count, highest-chunk marker, Tally row lost, Tally run id changed, Tally date dimension flipped) gives its named counted kind; unkeyable and duplicate seen rows are declared not counted"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_storage_parity.py#MutationTests"
        status: pass
    human_judgment: false
  - id: D4
    description: "A difference, a raised check or a failed repair degrades the run (reason storage), restarts the clock and never changes detection, evaluation or alerts; the repair re-adds a removed ID and the next run is ok; a deadline-skipped check is not recorded"
    requirement: STOR-01
    verification:
      - kind: integration
        ref: "tests/test_storage_parity.py#PipelineDifferenceTests"
        status: pass
    human_judgment: false
  - id: D5
    description: "The parity clock: three complete consecutive UTC days after the seed day, 12 checked runs each, no difference, one admission; midnight UTC belongs to the new day; 11 runs do not count; the current day never counts; pruning to 14 days and 10 named differences; tolerant load"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_storage_parity.py#ClockTests"
        status: pass
    human_judgment: false
  - id: D6
    description: "No title, URL, location or tracker text reaches the storage key, the run notes or the storage log line"
    requirement: STOR-01
    verification:
      - kind: integration
        ref: "tests/test_storage_parity.py#PipelineDifferenceTests.test_the_storage_key_the_notes_and_the_log_never_hold_job_text"
        status: pass
    human_judgment: false
  - id: D7
    description: "SPEC.md, D-57 and the AGENTS layout line describe seeding, repair, the check, a difference and the bar with the chosen constants"
    requirement: STOR-01
    verification:
      - kind: other
        ref: "grep -c PARITY_MIN_RUNS_PER_DAY DECISIONS.md; grep -c 'parity.py' AGENTS.md"
        status: pass
    human_judgment: true
    rationale: "The documents record choices the owner left to the implementation (12 runs a day, the day rules, the declared classes); only the owner can confirm they are the intended bar before the cutover"

duration: 15min
completed: 2026-10-29
status: complete
---

# Phase 3 Plan 02: Seeding, repair and the storage parity clock Summary

**The first poller run after deploy seeds Identity and the historical Tally from the Events rows it loads; every later dual run repairs what the stores lack, checks the previous runs' writes after the alert stage in three layers, and records a three-day parity clock in the Discovery key `storage` while Events stays authoritative**

## Performance

- **Duration:** 15 min
- **Started:** 2026-10-29T16:55:48Z
- **Completed:** 2026-10-29T17:11:00Z
- **Tasks:** 3 (tracer, TDD task, TDD task)
- **Files modified:** 9 (2 created, 7 modified)

## Accomplishments

- **Seed and repair.** With no `storage` key the run adds an Identity entry for every keyable identity-class Events row and one Tally row per (run id, run time) group (rows from before run ids share a blank `Run_ID` and keep their own time), then saves `storage` (`mode` `dual`, `seeded_at`). The plan is a set difference, so the next run completes an interrupted seed without writing an ID or a run twice (test: Tally append fails on the first call; after the next run every ID and every group exists exactly once). The same repair runs at the start of every run. An empty ledger counts as a successful seed. Dry runs neither seed nor record.
- **Check after the alert stage on the start-of-run snapshot** (one-run lag, documented): layer 1 the seen set both ways plus kind letter, `Count`, 40,000-character cell, highest-chunk marker, duplicate IDs and stem round trip; layer 2 the Tally recount per (Run_ID, Run_At, dimension); layer 3 jobs awaiting evaluation or alert, error attempts and abandoned stages per stage from `replay` of all rows versus of the simulated compact view. Unkeyable keys and duplicate `seen` rows are declared (listed, not counted).
- **A difference changes nothing but the record.** The run is `degraded` (`storage parity: N differences (kinds)`, reason `storage`), up to 10 named differences go into the `storage` key, the clock restarts, and a job whose ID was removed from Identity is not observed again, evaluated or alerted twice, while the next run's repair re-adds it. A check that raises is the counted difference `check_failed` (never zero); a check skipped past 22 minutes of process time is not recorded.
- **Parity clock.** `StorageState.bar(now)` applies the three-day bar (complete UTC days after the seed day, 12 checked runs each, no difference, one admission), `bar_met_at` is set once and cleared by any difference, days are pruned to 14, named differences to 10 of at most 200 characters; truncated or hand-edited JSON gives a fresh state.
- **One storage log line per run**, counts only (mode, counted and declared differences, keys and Tally runs compared, checked runs today, complete days toward the bar, admission seen, check seconds; the seed run logs IDs, Identity rows, boards and Tally runs written; a repair joins the check line).
- `load_ledger()` now returns a copy of the Identity set: a later `write_identity` changes the store's cache, never a snapshot already handed out (needed so the check really sees the previous runs' writes).

## Task Commits

1. **Task 1: Tracer, seed and first check** - `e32e40d` (feat)
2. **Task 2: Named differences, repair, degraded runs** - `87537a3` (test, RED) then `d523e5a` (feat, GREEN)
3. **Task 3: Parity clock, SPEC and D-57** - `ea4cf52` (test, RED) then `7c7a64e` (feat, GREEN)

**Plan metadata:** the `docs(03-02): complete ...` commit that follows this file.

## Tracer gate

Interactive run, `human_verify_mode` default `end-of-phase`, tracer `<verify>` automated only: the verify (`tests.test_storage_pipeline -k Seed` plus the full suite) was re-run after the tracer commit (5 Seed tests, suite 694 OK) and at every later task (final suite 734 OK). Tracer verified end-to-end, expansion followed.

## TDD evidence

- **Task 2 RED** (`87537a3`): `.venv/bin/python -m unittest tests.test_storage_parity` exited 1 (1 failing of 24). Target `PipelineDifferenceTests.test_the_storage_key_the_notes_and_the_log_never_hold_job_text`: `gsd_run check tdd-red-evidence` returned `RED_EVIDENCE_OK` (`target_test_failed`, format `unittest`). Semantic assessment: the target ran and failed on its planned assertion (`2 != 1` storage log lines: a repair logged its own line beside the check line), not on an import or fixture fault. The other 23 tests passed at RED because Task 1 (the tracer) already built `parity.py` and its difference kinds, as the plan sequences; they are proven discriminating by the mutation checks below (unexpected green was investigated, not ignored).
- **Task 2 GREEN** (`d523e5a`): a repair now joins the check line; 24 tests and the full suite pass.
- **Task 3 RED** (`ea4cf52`): `-k Clock` exited 1 (12 failing of 16: 3 failures, 9 errors for the missing `bar`). Target `ClockTests.test_twenty_days_are_pruned_to_the_last_fourteen`: `RED_EVIDENCE_OK`. Semantic assessment: it failed on `assertEqual(sorted(state.days), ...)` (20 days kept, not 14); the error-class failures are the missing `bar` method, which is the planned behaviour under test.
- **Task 3 GREEN** (`7c7a64e`): 16 clock tests pass; full suite 734 OK.
- **Mutation checks** (each applied, observed failing, reverted):
  - Task 2 (parity.py): layer 1 one direction only (no `identity_extra`) fails `test_one_identity_id_added`; dropping the kind comparison fails `test_a_kind_letter_changed`; also: no `identity_missing`, no Count check, no marker check, no `tally_missing`, no `tally_orphan`, no per-dimension `tally_count`, no state counts: each fails its own test.
  - Task 3 (compact.py): counting the current incomplete UTC day fails three ClockTests; dropping the admission requirement fails `test_without_an_admission_in_the_three_days_the_bar_is_not_met` and `test_an_admission_before_the_three_days_does_not_help`; also: seed day counting, 11 runs sufficing, a difference not clearing `bar_met_at`, no pruning, a difference today not blocking, the day taken from a local date: each fails its own test.
  - Task 1: dropping the Identity snapshot copy in `load_ledger` fails both `SnapshotTests`.

## Files Created/Modified

- `parity.py` - `Diff`, `ParityReport`, `check_dual` (layers 1 to 3); imports `compact` and `ledger` only
- `compact.py` - parity constants, `identity_entry`, `IdentitySet.copy`, `first_seen_identity`, `tally_recount`, `simulate_compact`, `parse_dim`, `FoldedCount`, `Ledger.tally_totals/retained_counts/folded/negative`, `Repair`/`repair_plan`, `StorageState`, `BarStatus`
- `pipeline.py` - `storage_check`, seed and repair at run start, check after the alert stage, `STORAGE_CHECK_CUTOFF_S`, degraded reasons
- `state.py` - `load_ledger` returns an Identity copy in both stores
- `tests/test_storage_parity.py` - `MutationTests`, `SimulationTests`, `ClockTests`, `PipelineDifferenceTests` (40 tests)
- `tests/test_storage_pipeline.py` - `SeedTests`, `SnapshotTests` (7 tests)
- `AGENTS.md`, `SPEC.md`, `DECISIONS.md` - layout entry, parity text, D-57 plan 03-02 choices and constants

## Decisions Made

- Followed the plan's discretion choices (one `storage` key, no new Runs column, check after alerts on the snapshot, 12 runs a day, declared classes); they are recorded in D-57.
- `Ledger.negative()` returns `FoldedCount` rows whose `n` is the shortfall (retained minus Tally), so a lost Tally count has the same shape as a folded count.
- `identity_entry(ev)` is the single definition of "keyable" used by the split, the repair, the simulation and the check (an entry too long for one cell counts as unkeyable everywhere).
- `record_check` also takes `compared` and `seconds` so `last_check` carries the check's duration for plan 03-05's live read (T-03-11).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] A difference found today did not restart the clock**
- **Found during:** Task 3 (writing the clock tests against P3-07)
- **Issue:** the plan's bar looks only at complete days, so a difference on the current day left the three complete days before it clean and `met` stayed true (and the next clean run would have set `bar_met_at` again), although P3-07 says any difference starts the clock again.
- **Fix:** `bar()` is not met while the current day has a run with a difference; the current day still never counts toward the three days. Documented in D-57 and covered by `test_a_difference_today_blocks_the_bar_even_though_the_three_complete_days_before_it_are_clean`; mutation (dropping the block) fails two ClockTests.
- **Files modified:** compact.py
- **Committed in:** 7c7a64e

**2. [Rule 1 - Bug] A repair run logged two storage lines**
- **Found during:** Task 2 RED (the privacy and log test)
- **Issue:** the repair logged its own line next to the check line, against "each poller run logs one storage line".
- **Fix:** a repair on a seeded store joins the check line (`, repaired N IDs ...`); the seed run keeps its own seed line.
- **Files modified:** pipeline.py
- **Committed in:** d523e5a

**Total deviations:** 2 auto-fixed (both Rule 1). **Impact on plan:** none beyond the stated fixes.

## Issues Encountered

- Python's bytecode cache hid two mutations (same size, same second); the mutation runs were repeated with `PYTHONDONTWRITEBYTECODE=1` and all mutations were observed failing. No product code is affected.
- Hand-off from 03-01 (an interrupted compact-mode Identity write leaves durable IDs without a Tally count): in dual mode the repair re-derives any missing Tally run from the Events rows, so the count is restored. In compact mode a baseline has no Events row, so nothing can re-derive its count; the in-run check is dual-only, and `Ledger.negative()` plus the compact-mode checks belong to plans 03-06/03-07. Logged in `deferred-items.md`.
- Existing tests needed no change: none pinned the exact Discovery key set or the number of Discovery writes (the suite passed unchanged after the pipeline change).

## User Setup Required

None. Nothing here was verified against Google Sheets, Groq or Telegram. The live checks (the real seed size of about 190,000 IDs in one run, the check's seconds at about 200,000 rows, whether the Discovery tab's 20 rows hold the new key) belong to plan 03-05.

## Known Stubs

None. The `cutover`, `fold` and `restore` records in the `storage` key are intentionally empty until plans 03-06 and 03-07 fill them (preserved on load and save, tested).

## Threat Flags

None. The only new surface is the `storage` Discovery key (T-03-07 mitigated by tolerant load, pruning and caps, T-03-08 by `check_failed`, the 12-run day rule and the unrecorded skip, T-03-09 by checking both directions plus kind, Count, marker and stem, T-03-10 by key-only refs with a test on the stored JSON, notes and log, T-03-11 by running after alerts with a 22-minute skip and the seconds recorded).

## Next Phase Readiness

- Ready for 03-03 (the figures layer): `compact.simulate_compact`, `Ledger.folded()` and `parity.check_dual` give it the compact view and the Tally minus the retained recount.
- Mocked only: the CSV store and the in-memory Sheets fake. Full offline suite: 734 tests OK (687 before this plan, 47 new).

## Self-Check: PASSED

- Created files exist: parity.py, tests/test_storage_parity.py (and the modified files).
- Commits found on the branch: e32e40d, 87537a3, d523e5a, ea4cf52, 7c7a64e.
- Acceptance criteria re-run: `grep -c "^def check_dual" parity.py` 1; no import of state, pipeline or hunter in parity.py; `class StorageState` and `def repair_plan` 1 each; `STORAGE_CHECK_CUTOFF_S` 3 uses in pipeline.py; `class MutationTests`, `class PipelineDifferenceTests`, `class ClockTests` 1 each; `parity.py` in AGENTS.md; `PARITY_MIN_RUNS_PER_DAY = 12` and `PARITY_DAYS = 3` in compact.py and the constant named in DECISIONS.md.

---
*Phase: 03-compact-storage*
*Completed: 2026-10-29*
