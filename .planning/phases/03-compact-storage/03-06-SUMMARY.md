---
phase: 03-compact-storage
plan: 06
subsystem: storage
tags: [cutover, restore, tab-swap, batchUpdate, parity-gate, workflow-inputs, mode-notes]

requires:
  - phase: 03-compact-storage
    provides: "plans 03-01..03-05: Identity and Tally, the parity bar and fresh parity (check_dual), StorageState, the Dashboard READY TO CUT OVER signal, dual writing live since 2026-10-29"
provides:
  - "python hunter.py --storage-cutover (workflow input storage_cutover): gate, Events_New copy, read-back count and SHA-256, would-be parity, one batchUpdate with two ordered renames, mode compact"
  - "python hunter.py --storage-restore (workflow input storage_restore): appends the post-cutover rows to Events_Legacy, renames in one batch, mode restored; refused after the first fold"
  - "compact.retained_events, rows_checksum, cutover_record, restore_record, parse_stamp, ModeDecision (a str with a note)"
  - "state.sheet_grid, build_events_new, swap_events, append_events_to, load_events_from, protect_tab in the Sheet and CSV stores; EVENTS_FAILED_TAB"
  - "storage_report.before_snapshot"
  - "poller run notes 'storage cutover incomplete' and 'storage state: compact without Events_Legacy' (degraded, reason storage, no check, no clock)"
affects: [03-07 fold, 03-08 deploy decision, 03-09 live cutover]

actuals:
  tokens: 31907
  tasks: 3
  commits: 4
plan_head_before: 2eedc23d688eec68d5bd5db363dc309aaeb11cbb
plan_head_after: ebe4cb9295d56248ea295b73105bff16708724ab
commits: 4

tech-stack:
  added: []
  patterns:
    - "one spreadsheets.batchUpdate with two ordered updateSheetProperties requests is the only way a ledger tab is ever renamed"
    - "a state-changing command verifies the copy twice (read back count and checksum, then parity on the would-be state) before it renames anything"
    - "an interrupted structural change is detected from the tabs (Events_Legacy beside a dual key) and finished by running the command again, never by hand"
    - "ModeDecision subclasses str, so every existing comparison with a mode keeps working while a note rides along"

key-files:
  created:
    - tests/test_storage_cutover.py
  modified:
    - compact.py
    - state.py
    - hunter.py
    - storage_report.py
    - pipeline.py
    - .github/workflows/job_hunter.yml
    - tests/test_deployment.py
    - SPEC.md
    - DECISIONS.md
    - DEPLOY.md
    - STATUS.md

key-decisions:
  - "P3-06 refined (flagged, AGENTS rule 1): the restore is a command that appends the post-cutover rows to Events_Legacy before the rename pair, because renaming by hand would make jobs first seen after the cutover look new"
  - "A cutover re-run only finishes an interrupted swap when Events_Legacy is the old ledger: at least as many rows as any recorded run loaded, every seen job key held by Events or Identity, no missing row older than its newest row"
  - "restored is terminal: no command leaves it; compacting again needs a new owner decision"
  - "Both commands run under the existing poller lease (no new LEASE_TTL label); exit codes 0 done, 1 refused, 2 error"

patterns-established:
  - "Refusal tests compare a full snapshot of the Sheets fake (values, write counter, batches, tab titles) before and after"
  - "Mutation checks are applied with the bytecode cache off, observed failing and reverted by restoring a saved copy of the file"

requirements-completed: [STOR-01]

coverage:
  - id: D1
    description: "Owner-triggered cutover on the Sheets fake: gate, Events_New copy, read-back count and checksum, would-be parity, ONE batch of two ordered renames (Events -> Events_Legacy, Events_New -> Events), mode compact with the cutover record and the before snapshot, Dashboard refresh; a poller run on the swapped state sees no old job as new and alerts the new job once"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_storage_cutover.py#CutoverTracerTests"
        status: pass
    human_judgment: false
  - id: D2
    description: "Every unsafe state is refused with one line and zero writes: bar not met, stale bar, hand-edited key, not seeded, mode compact, mode restored, an Events_Legacy that is not the old ledger, a fresh parity difference; a read-back that loses or changes a row, a copy that fails parity and an error at the rename leave Events untouched; the dry run writes nothing"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_storage_cutover.py#CutoverGateTests"
        status: pass
    human_judgment: false
  - id: D3
    description: "An interrupted cutover (renamed, key not saved) makes the next poller run write as dual with the note, degraded and without a check, and running the cutover again finishes the record without copying; a compact key without Events_Legacy writes as dual with its note"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_storage_cutover.py#InterruptedCutoverTests, MissingLegacyTests"
        status: pass
    human_judgment: false
  - id: D4
    description: "Restore before any fold keeps the old ledger plus every post-cutover row, no old job looks new and no alert is sent twice afterwards; restored mode writes every observation to Events again with no check; refused after storage.fold.first_day; repeatable after an interruption before or after the rename"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_storage_cutover.py#RestoreTests"
        status: pass
    human_judgment: false
  - id: D5
    description: "Workflow inputs storage_cutover and storage_restore (boolean, fixed run commands, excluded from the poller and from REQUIRE_TELEGRAM, 13 of 25 inputs) and the main() wiring (poller lease, local write refusal, mutually exclusive flags, no new lease label)"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_deployment.py#test_storage_cutover_and_restore_inputs_are_boolean_owner_steps_excluded_from_the_poller; tests/test_storage_cutover.py#DispatchTests"
        status: pass
    human_judgment: false
  - id: D6
    description: "SPEC, D-57, DEPLOY and STATUS describe the cutover, the restore, the modes, the P3-06 refinement and when the owner should cut over (early in a UTC day; the first fold is the point of no return)"
    requirement: STOR-01
    verification: []
    human_judgment: true
    rationale: "The documents tell the owner when to cut over and when to restore, and flag the P3-06 refinement for the plan 03-08 decision; only the owner can judge the wording and accept the added command"
  - id: D7
    description: "The real swap on the real Sheet: Google applying the two renames in one batch, in order, keeping the hidden flag and the protection, and the real seconds of copying about 200,000 rows"
    requirement: STOR-01
    verification: []
    human_judgment: true
    rationale: "Everything here ran against the in-memory Sheets fake, which interprets the renames itself; plan 03-09 does the real swap and needs the owner's decision and credentials"

duration: 18min
completed: 2026-10-29
status: complete
---

# Phase 3 Plan 06: Owner-triggered cutover and emergency restore Summary

**`--storage-cutover` copies the retained Events rows to a hidden Events_New, verifies the copy twice (read-back count and SHA-256, then parity on the would-be state) and swaps the tabs in one ordered batchUpdate only when the bar is met and a fresh parity check is clean; `--storage-restore` undoes it before the first fold by appending the post-cutover rows first, so no job looks new and no alert repeats; both are workflow inputs, mocked only**

## Performance

- **Duration:** 18 min
- **Started:** 2026-10-29T18:09:20Z
- **Completed:** 2026-10-29T18:27:14Z (last task commit `ebe4cb9`; this SUMMARY commit follows)
- **Tasks:** 3 (tracer, TDD task, docs and workflow task)
- **Files modified:** 12 (1 created)
- **Tests:** full suite 787 -> 836, all offline (`Ran 836 tests ... OK`); 48 new in `tests/test_storage_cutover.py`, 1 new in `tests/test_deployment.py`

## Accomplishments

- **Cutover (P3-06, P3-14).** `hunter.run_storage_cutover` refuses (exit 1, one line, zero writes) unless the stored mode is `dual`, the stores are seeded, `StorageState.bar(now)` is met (recomputed), no `Events_Legacy` exists and a fresh four-layer parity check with the real tracker counts nothing. It then writes `compact.retained_events` to a hidden `Events_New`, reads it back (count plus `compact.rows_checksum`), runs parity on the would-be state, and only then calls `swap_events("cutover")`: ONE `spreadsheets.batchUpdate` with two `updateSheetProperties` requests, Events -> Events_Legacy first. `Events_Legacy` stays hidden and gets a warning-only protection; the `storage` key says `compact` with `cutover` = `{at, retained_rows, legacy_rows, checksum, before}`; the Dashboard is refreshed. Nothing is deleted except a leftover scratch `Events_New`.
- **Before snapshot.** `storage_report.before_snapshot` records the Events rows, the grid and the cells per tab and in total (`state.sheet_grid()`, from the sheet metadata), the median `Runs.Load_S` of the last 24 completed non-rehearsal runs and the median daily growth of `Runs.Events_Rows` over the last 7 complete UTC days (`null` where nothing was measured).
- **Restore (P3-06 made concrete).** `hunter.run_storage_restore` works only while the effective mode is `compact` and `fold.first_day` is empty: it appends every Events row with Time at or after `cutover.at` to Events_Legacy (idempotent), checks the count, renames Events -> Events_Failed and Events_Legacy -> Events in one batch and sets mode `restored`. After the first fold it refuses with the replay message.
- **Modes in the poller.** `compact.effective_mode` returns a `ModeDecision` (a `str` plus a `note`); `pipeline.run_cycle` adds the note to the run, `degraded_reason` maps both notes to `storage`, and the parity check and clock are skipped in those states and in `restored`.
- **Interruptions.** A swap done but not recorded is noticed by the next poller run (`storage cutover incomplete: run storage_cutover again`) and finished by running the cutover again, which first proves that `Events_Legacy` really is the old ledger. A restore whose swap is done but not recorded is finished by running it again.
- **Workflow and documents.** Boolean inputs `storage_cutover` and `storage_restore` with fixed commands, excluded from the poller and `REQUIRE_TELEGRAM`; SPEC, D-57 (including the flagged P3-06 refinement), DEPLOY (when to cut over, when to restore) and STATUS.

## Task Commits

1. **Task 1: Tracer, cutover end to end on the Sheets fake** - `cb3117e` (feat)
2. **Task 2: gate refusals, interrupted cutovers, restore, mode notes** - `0bfafe3` (test, RED) then `7cb58d4` (feat, GREEN)
3. **Task 3: workflow inputs, deployment test, SPEC, D-57, DEPLOY, STATUS** - `ebe4cb9` (docs)

**Plan metadata:** the `docs(03-06): complete ...` commit that follows this file.

## Tracer gate

`human_verify_mode` is the default `end-of-phase` (no auto mode in the config), and the tracer `<verify>` is automated only: `tests.test_storage_cutover -k CutoverTracer` (7 tests) and the full suite (798 OK) were re-run after the tracer commit and passed. Tracer verified end-to-end, expansion followed.

## TDD evidence (Task 2)

- **RED** (`0bfafe3`): `NO_COLOR=1 .venv/bin/python -m unittest tests.test_storage_cutover` exited 1 (5 failures, 15 errors of 47). Target `InterruptedCutoverTests.test_the_next_poller_run_writes_as_dual_notes_it_is_degraded_and_records_no_check`: `gsd_run check tdd-red-evidence` returned `RED_EVIDENCE_OK` (`target_test_failed`, format `unittest`, 20 `FAIL:`/`ERROR:` headers for the 20 counted). Semantic assessment: the target ran a real poller run on the Sheets fake in the interrupted state and failed on the planned assertion (the note `storage cutover incomplete` was missing; the old code ran the dual parity check against the half-swapped ledger and counted 101 differences), not on an import or fixture fault. The restore, dispatch and restore-mode tests failed with `AttributeError: module 'hunter' has no attribute 'run_storage_restore'` inside the test body (the planned interface did not exist; no `unittest.loader._FailedTest`); three `Events_Legacy` refusal tests failed with exit 2 instead of 1. The tests for the gates and the faults already passed at RED because the tracer commit had built the gate itself (characterization of code from Task 1).
- **GREEN** (`7cb58d4`): all 48 tests of the file and the full suite (835) pass. Three tests were tightened in that commit after the stronger completion check was designed (the old-row case needs a row count that passes the first check; a checksum-only mismatch test was added).
- **TDD gate:** `test(03-06)` 0bfafe3 precedes `feat(03-06)` 7cb58d4.
- **Mutation checks** (each applied with `PYTHONDONTWRITEBYTECODE=1`, observed failing, reverted from a saved copy; the working files were compared with the saved copies afterwards):
  - restore without appending the post-cutover rows: 3 fail (including `test_after_a_restore_a_poller_run_sees_nothing_old_as_new_and_sends_no_second_alert`)
  - the two rename requests in reverse order: 24 fail (including the tracer's order assertion)
  - bar check removed: 4 fail; fresh parity gate removed: 3 fail; checksum comparison removed: 1 fails (the new checksum-only test); would-be parity removed: 1 fails; fold gate removed: 1 fails; restore taking every row instead of those at or after `cutover.at`: 6 fail; `protect_tab` removed: 1 fails; the parity check not skipped in the incomplete state (pipeline): 2 fail.
  - One slip, caught and fixed: my mutation helper restored `hunter.py` and `state.py` but not `pipeline.py`, so the last mutant stayed in `pipeline.py` for one full-suite run (2 failures); the line was restored by hand and `git diff pipeline.py` shows only the intended change. Nothing was committed while it was mutated.

## Files Created/Modified

- `compact.py` - `retained_events`, `rows_checksum`, `cutover_record`, `restore_record`, `parse_stamp`, `ModeDecision`, the two note constants; `effective_mode` returns the decision
- `state.py` - `EVENTS_FAILED_TAB`, `_warning_protection`, `_swap_pairs`; per store `sheet_grid`, `build_events_new`, `swap_events`, `append_events_to`, `load_events_from`, `protect_tab`; `tab_exists(fresh=)`
- `storage_report.py` - `before_snapshot`
- `hunter.py` - `run_storage_cutover`, `_finish_cutover`, `run_storage_restore`, `_finish_restore`, `_read_tracker`, `_parity_report` (shared with `run_storage_parity`), the two flags (mutually exclusive), `inventory_mode`, the `writes` expression, the poller-lease dispatch
- `pipeline.py` - the mode note on the run, the `storage` degraded reasons, no check in an unfinished state
- `.github/workflows/job_hunter.yml` - inputs, steps, poller `if:`, `REQUIRE_TELEGRAM`
- `tests/test_storage_cutover.py` - `CutoverTracerTests`, `BeforeSnapshotTests`, `CutoverGateTests`, `InterruptedCutoverTests`, `MissingLegacyTests`, `RestoreTests`, `DispatchTests`
- `tests/test_deployment.py` - pinned `REQUIRE_TELEGRAM` expression, the static owner-steps test
- `SPEC.md`, `DECISIONS.md` (D-57), `DEPLOY.md`, `STATUS.md` - see Accomplishments

## Decisions Made

- **P3-06 refinement, flagged for the owner (AGENTS rule 1).** The restore is a command that appends the post-cutover rows first; renaming `Events_Legacy` back by hand would lose them and could alert old jobs twice. It adds a command and an input that CONTEXT did not name and changes nothing unless dispatched. To be surfaced at the plan 03-08 deploy decision.
- A cutover re-run completes an interrupted swap only after proving that `Events_Legacy` is the old ledger (three checks); a tab with that name that is not refuses and changes nothing.
- `restored` is terminal; no command leaves it.
- Rows that no reader parses (blank key or event) are not copied to the compact `Events`; they stay in `Events_Legacy` only. `legacy_rows` counts parsed rows.
- Exit codes 0 / 1 / 2 and the existing `poller` lease for both commands (details in D-57).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical] A cutover re-run could flip to compact on an `Events_Legacy` that is not the old ledger**
- **Found during:** Task 2 (designing the "Events_Legacy present" refusal; the first version of the completion path only compared seen sets, so an empty or near-empty tab with that name passed)
- **Issue:** compact mode followed by the plan 03-07 fold would then delete rows with no copy, and a restore would rename an empty ledger in.
- **Fix:** the completion path also requires at least as many rows as any recorded run loaded from Events and no missing Events row older than the tab's newest row, besides the seen-set check; three refusal tests, one per condition.
- **Files modified:** hunter.py, tests/test_storage_cutover.py
- **Committed in:** 7cb58d4

**2. [Rule 2 - Missing critical] A restore whose swap is done but whose record is not saved had no way back**
- **Found during:** Task 2 (the pipeline note `compact without Events_Legacy` would repeat forever and no fold could ever run)
- **Fix:** `run_storage_restore` finishes the record when the key says `compact`, `Events_Legacy` is gone and `Events_Failed` exists (`_finish_restore`); test `test_a_restore_whose_record_was_not_saved_is_finished_by_running_it_again`. The plan listed no such behaviour.
- **Files modified:** hunter.py, tests/test_storage_cutover.py
- **Committed in:** 7cb58d4

**3. [Rule 1 - Bug] Stale tab cache made the cutover treat an existing `Events_Legacy` as absent**
- **Found during:** Task 2 (three RED tests got exit 2 from the rename guard instead of exit 1 from the gate)
- **Issue:** `SheetState.tab_exists` answered from the titles cached at `ensure()`.
- **Fix:** `tab_exists(title, fresh=True)` in both stores, used by both commands.
- **Files modified:** state.py, hunter.py
- **Committed in:** 7cb58d4

**4. [Rule 3 - Blocking] Existing deployment test asserted a substring of the old `REQUIRE_TELEGRAM` expression**
- **Found during:** Task 3 (`inputs.storage_parity) && 'no'` no longer occurs once the expression is extended)
- **Fix:** it now asserts `inputs.storage_parity ||`; the whole expression stays pinned by the plan's test.
- **Files modified:** tests/test_deployment.py
- **Committed in:** ebe4cb9

**5. [Documentation, AGENTS rule 1] STATUS.md was not in the plan's `files_modified`**
- STATUS records what is verified and what is blocked, so a short section says that plan 03-06 is built and mocked only. Committed in ebe4cb9.

---

**Total deviations:** 5 (2 Rule 2, 1 Rule 1, 1 Rule 3, 1 documentation). **Impact on plan:** the fixes make the new commands refuse in more unsafe states; no scope creep beyond the restore-record completion.

## Issues Encountered

- `CutoverTracerTests` first compared an alert's `url`, which the fake scorer fixes to `https://u`; it now checks the alerted job key in the new Events rows.
- A test clock detail: a poller run after the cutover must have a time at or after `cutover.at`, otherwise a restore would miss its rows; the test helper moves the Harness clock to the cutover time first. In production the clocks only move forward.
- The workflow's `Check configuration` step still lists `GROQ_API_KEY` as required for every run, including the two new commands, which need no Groq key (same as plan 03-04's note). Not changed: it affects every report.
- Deferred item from plan 03-01 stays open: compact-mode checks and how a lost Tally count is reported (`Ledger.negative()`) are not part of this plan; plan 03-07 (fold) is where compact-mode checks arrive.

## Authentication Gates

None. The agent read no `.env`, no `Resume.pdf` or `resume.txt` and no service-account file; no Google, Groq or Telegram call was made, nothing was pushed or dispatched.

## User Setup Required

None. The two new inputs exist only after the owner pushes this code (plan 03-08); production runs the previous workflow until then.

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model: T-03-23 (gate recomputes the bar and runs a fresh parity; stale bar, hand-edited key and parity-difference tests), T-03-24 (one batch with ordered renames; the order is asserted and mutation-checked; `ensure()` still refuses a missing `Events`), T-03-25 (read-back count and checksum, then would-be parity; mutation-checked), T-03-26 (restore appends first; mutation-checked), T-03-27 (both commands are in the `writes` expression and take the poller lease; `DispatchTests`), T-03-28 (boolean inputs, fixed commands; static test). The new tab `Events_Failed` is created only by a restore and holds a copy of rows already in the Sheet.

## Next Phase Readiness

- Ready for plan 03-07 (the 7-day fold, which is the point of no return for the restore) and the before/after report. The cutover record carries `at`, `retained_rows`, `legacy_rows`, `checksum` and `before` for it.
- Plan 03-08 (deploy decision) must surface the P3-06 refinement and the two new inputs; plan 03-09 does the real swap and must record the live observations listed in STATUS (Google's batch, the hidden flag and protection after the rename, seconds for about 200,000 rows).
- Production is unchanged: dual mode since 2026-10-29, nothing of this plan is pushed. The earliest `READY TO CUT OVER` is 2026-11-02 00:00 UTC.

## Self-Check: PASSED

- All 12 created or modified files exist (`[ -f ]` printed FOUND for each).
- Commits `cb3117e`, `0bfafe3`, `7cb58d4`, `ebe4cb9` are ancestors of HEAD; `gsd-tools check evaluation-scope --plan 03-06 --commits-only` resolved them (status `resolved`).
- TDD gate: `test(03-06)` precedes `feat(03-06)`.
- Acceptance criteria re-run: `def run_storage_cutover` 1, `def swap_events` 2, `updateSheetProperties` in state.py 1, `def retained_events` 1, `def before_snapshot` 1, `def sheet_grid` 2, `def run_storage_restore` 1, `"--storage-restore"` 1, `storage cutover incomplete` in pipeline.py 1, `compact without Events_Legacy` in pipeline.py 1, `python hunter.py --storage-cutover` 1, `python hunter.py --storage-restore` 1, `storage_cutover:` 1, `storage_restore:` 1, `Events_Failed` in DECISIONS.md 2, the pinned expression in tests/test_deployment.py 1, `class RestoreTests` 1.
- Plan verification: `tests.test_storage_cutover tests.test_deployment` 84 OK; full suite `Ran 836 tests ... OK`.
- Mocked versus live: everything above is mocked (CSV store, in-memory Sheets fake, fake ATS, scorer and alert channel). No claim of live verification of Sheets, Groq or Telegram is made.
- No untracked generated files; the six pre-existing untracked planning paths were not committed.

---
*Phase: 03-compact-storage*
*Completed: 2026-10-29*
