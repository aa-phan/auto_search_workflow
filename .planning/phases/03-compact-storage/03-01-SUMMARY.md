---
phase: 03-compact-storage
plan: 01
subsystem: storage
tags: [identity, tally, dual-write, sheets, csv, dedupe, google-sheets-fake]

requires:
  - phase: 02-measurement-governors-and-owner-decisions
    provides: degraded-run signalling through run notes (degraded_reason), run ids on every observation, the offline Harness
provides:
  - compact.py (pure): Identity codec, Tally rows, observation split, merged ledger view, storage modes
  - hidden Identity (warning-only protected) and Tally tabs in both stores, with load_ledger, write_identity, append_tally, tab_exists
  - pipeline write order Events -> Identity -> Tally -> Boards and a merged seen() over Events plus Identity
  - ensure() refusal to recreate Events when Events_Legacy or Events_New exists
  - tests/fake_sheets.py shared in-memory Sheets fake (batchUpdate requests, caps, fault injection)
  - D-57 (owner storage design approval), SPEC subsection, AGENTS layout line
affects: [03-02 seeding and repair, 03-03 parity, cutover, fold, reports, Phase 4 observe_new]

actuals:
  tokens: 22437
  tasks: 3
  commits: 4
plan_head_before: 767a305a753bdf0233e17e4d8b19a0d9ac49a10c
plan_head_after: 230ce46d0fc0041aa694e971bfad8e42f7fe4ac2
commits: 4

tech-stack:
  added: []
  patterns:
    - "pure model module imported by the persistence layer (compact.py must not import state)"
    - "completion marker on a board's highest Identity chunk; chunks written in ascending order"
    - "character-budgeted Sheets requests, cache updated per successful request so a failure leaves it equal to the sheet"
    - "idempotent upserts keyed by (Board_Key, Chunk); entries deduplicated by posting ID"

key-files:
  created:
    - compact.py
    - tests/fake_sheets.py
    - tests/test_compact.py
    - tests/test_storage_pipeline.py
  modified:
    - state.py
    - pipeline.py
    - tests/test_hunter.py
    - DECISIONS.md
    - SPEC.md
    - AGENTS.md

key-decisions:
  - "Identity is keyed by the job-key stem ats|board_lowercased, never BoardRecord.key or a URL (AGENTS rule 3)"
  - "An entry is a one-letter kind (b/f/s) plus the posting ID with % -> %25 then , -> %2C; every cell stays text"
  - "Request budget counts every cell character of a row (stem, chunk, marker, count, IDs), not only the IDs text"
  - "A Tally failure is contained in both modes; an Identity failure is contained in dual mode and stops the run before save_boards in compact mode"
  - "compact mode applies only when the Discovery key storage says compact AND Events_Legacy exists; otherwise the run writes as dual"

patterns-established:
  - "Observation write point as one closure (persist_observations) reused by the crash-flush in finally"
  - "Fault injection per worksheet (fail_on_write_to) for interrupted-write tests"

requirements-completed: [STOR-01]

coverage:
  - id: D1
    description: "Pure compact.py: Identity codec with escaping, 40,000-character chunking with the completion marker on the highest chunk, stem keying incl. mixed-case Lever, Tally rows, observation split, storage modes"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_compact.py#IdentityCodecTests, TallyTests, SplitTests, ModeTests"
        status: pass
    human_judgment: false
  - id: D2
    description: "Dual write in the pipeline: Events, then Identity, then Tally, then Boards; a run whose Events lack a board's baseline rows treats the Identity IDs as seen (no new seen event, no evaluation, no repeat alert)"
    requirement: STOR-01
    verification:
      - kind: integration
        ref: "tests/test_storage_pipeline.py#DualWriteTracerTests"
        status: pass
    human_judgment: false
  - id: D3
    description: "Compact mode (baseline observations write no Events row) and the interrupted multi-chunk baseline (SC4) on the Sheet store, plus the same fault contained in dual mode"
    requirement: STOR-01
    verification:
      - kind: integration
        ref: "tests/test_storage_pipeline.py#CompactModeTests, InterruptedBaselineTests"
        status: pass
    human_judgment: false
  - id: D4
    description: "Sheet persistence of Identity and Tally within the cell and request limits, in-place growth, learned row numbers, reload equality"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_compact.py#SheetIdentityTests, CsvLedgerTests"
        status: pass
    human_judgment: false
  - id: D5
    description: "Whole-sheet warning-only protection on Identity and the Events guard in ensure() (both stores)"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_compact.py#EnsureTests"
        status: pass
    human_judgment: true
    rationale: "The request shape is checked against a fake only; whether a warning-only protection lets the service account write, and how the real Sheet stores a long IDs cell, are live checks (plan 03-05)"
  - id: D6
    description: "D-57, the SPEC subsection and the AGENTS layout line describe the dual-write design"
    requirement: STOR-01
    verification:
      - kind: other
        ref: "grep -c '^## D-57' DECISIONS.md; grep -c '### Compact storage (D-57)' SPEC.md; grep -c 'compact.py' AGENTS.md"
        status: pass
    human_judgment: true
    rationale: "The documents record the owner's decision in the owner's words; only the owner can confirm they state what was approved"

duration: 12min
completed: 2026-10-29
status: complete
---

# Phase 3 Plan 01: Dual-write core of compact storage Summary

**Identity and Tally tabs written beside Events (Events, then Identity, then Tally, then Boards), a posting ID in Identity counted as seen everywhere, compact mode for baselines, Sheet persistence within the 40,000-character cell and 1,000,000-character request limits, and D-57 recording the owner's storage approval**

## Performance

- **Duration:** 12 min
- **Started:** 2026-10-29T16:40:17Z
- **Completed:** 2026-10-29T16:52:00Z
- **Tasks:** 3 (tracer, TDD task with RED and GREEN commits, documents)
- **Files modified:** 10 (4 created, 6 modified)

## Accomplishments

- A real run on the CSV store writes Events, then Identity (one chunk per board stem, completion marker on the highest chunk), then one Tally row, then Boards. A run whose Events had lost a board's baseline rows (simulated compact storage) treats those IDs as seen: no new `seen` event, no evaluation, and one alert in total across two further runs.
- Compact mode (Discovery key `storage` says `compact` and `Events_Legacy` exists) writes no Events row for a baseline; filtered, stale and every operational row keep their full row; an identity-class row that cannot be keyed stays in Events.
- Sheet persistence: requests budgeted by cell characters (never by row count), existing chunks updated in place through the single-cell `A{row}` anchor, new chunks appended with their row numbers read back, the in-memory Identity cache equal to the sheet after a failed request, idempotent redo.
- Interrupted baseline (SC4): a compact-mode Identity write cut off at chunk 3 of 5 stops the run before `save_boards`; the next run is a baseline pass again (0 `pending` seen events, 0 alerts), ends with all 5,050 IDs once and the marker on the highest chunk. The same fault in dual mode is contained: run `degraded` (reason `storage`), Events holds all 5,050 rows, board baselined.
- `ensure()` creates `Identity` and `Tally` hidden and frozen in both stores, issues one whole-sheet `warningOnly` protected range on Identity, and refuses to recreate `Events` when `Events_Legacy` or `Events_New` exists (every command inherits it through `bootstrap()`).
- D-57 records the owner's storage design approval (P3-01..P3-14, discretion choices, conflicts resolved), amends D-43, closes the D-03 200k-row review and annotates D-48 row 9; SPEC gains "Compact storage (D-57)" and the hidden-tab list names Identity and Tally.

## Task Commits

1. **Task 1: Tracer** - `0af4289` (feat)
2. **Task 2: Identity persistence, protection, Events guard, compact mode, interrupted baseline** - `b586374` (test, RED) then `4879021` (feat, GREEN)
3. **Task 3: D-57, SPEC subsection, AGENTS layout** - `230ce46` (docs)

**Plan metadata:** the `docs(03-01): complete ...` commit that follows this file.

## Tracer gate

Interactive run, `human_verify_mode` default `end-of-phase`, tracer `<verify>` automated only: the tracer's verify (`tests.test_storage_pipeline` plus the full suite) was re-run after the tracer commit (4 new tests, suite 637 OK) and again at every later task. Tracer verified end-to-end, expansion followed.

## TDD evidence (Task 2)

- **RED** (`b586374`): `.venv/bin/python -m unittest tests.test_compact` exited 1 (12 failing of 43). Target `tests.test_compact.EnsureTests.test_ensure_protects_identity_with_a_warning_only_whole_sheet_range`: `gsd_run check tdd-red-evidence` returned `RED_EVIDENCE_OK` (`target_test_failed`, format `unittest`). Semantic assessment: the target ran and failed on its planned assertion (`FAIL`, `0 != 1` protected ranges after `ensure()`), not on an import, fixture or syntax fault. The other 11 failures were the missing Sheet half and the missing guard. The codec, split, mode, Tally and CSV tests (and `CompactModeTests`) passed already at RED because plan Task 1 builds `compact.py` and the CSV store; they are proven discriminating by the mutation checks below.
- **GREEN** (`4879021`): the 54 tests of `test_compact` and `test_storage_pipeline` pass; full suite 687 OK.
- **Mutation checks** (each applied, observed failing, reverted): (1) completion marker on chunk 1 instead of the highest chunk fails 4 tests (`IdentityCodecTests.test_the_completion_marker_is_only_on_the_highest_chunk`, `SheetIdentityTests` x2, `CsvLedgerTests`); (2) dropping the `%` escape fails `test_escape_round_trip` and `test_percent_is_escaped_before_the_comma`; (3) swallowing a compact-mode Identity failure fails `InterruptedBaselineTests.test_a_cut_off_compact_baseline_is_a_baseline_pass_again_with_nothing_alerted`; (4) making `seen()` ignore Identity fails `DualWriteTracerTests`.

## Files Created/Modified

- `compact.py` - pure Identity codec, `TallyRow`, `IdentityRow`, `IdentitySet` (planning of chunk rows), `split_observations`, `Ledger`, `effective_mode`
- `state.py` - Identity and Tally constants and tabs, `load_ledger`, `write_identity`, `append_tally`, `tab_exists` in both stores, protection and Events guard in `ensure()`
- `pipeline.py` - `seen()` helper at the four membership sites, `persist_observations()` write point, crash flush through the split, degraded reason `storage`, rule 1 text
- `tests/fake_sheets.py` - shared Sheets fake
- `tests/test_compact.py` - `IdentityCodecTests`, `TallyTests`, `SplitTests`, `ModeTests`, `SheetIdentityTests`, `EnsureTests`, `CsvLedgerTests` (43 tests)
- `tests/test_storage_pipeline.py` - `DualWriteTracerTests`, `CompactModeTests`, `InterruptedBaselineTests` (11 tests)
- `tests/test_hunter.py` - the bootstrap test names the ten tabs and both new hidden tabs
- `DECISIONS.md`, `SPEC.md`, `AGENTS.md` - D-57, subsection, layout line

## Decisions Made

- Followed the plan's discretion choices (layout, kind prefix, in-place growth, one Tally row per run, mode from the Discovery key, failure containment); they are recorded in D-57.
- `Split.identity` carries already-encoded entries per stem, so one place (`plan_additions`) owns deduplication and the 40,000-character cap for both stores.
- An identity-class event whose encoded entry alone exceeds the cell cap is treated like an unkeyable row (stays in Events) instead of producing an oversized cell.
- `restored` storage mode is read but treated like `dual` by the split (everything still goes to Events); later plans define its own behaviour.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Request budget undercounted the cells it sends**
- **Found during:** Task 2 GREEN (`SheetIdentityTests.test_a_request_never_carries_more_than_the_character_budget`, 1,000,674 > 1,000,000)
- **Issue:** the first `write_identity` weighed a request by the length of the `IDs` text only, so Board_Key, Chunk, Baselined_At and Count cells pushed a request over the budget the plan states as "characters of Identity cells".
- **Fix:** each row is weighed by the characters of all its cells.
- **Files modified:** state.py
- **Verification:** the test now passes; the fake also rejects any request over 2,000,000 characters.
- **Committed in:** 4879021

### Process note (not a code deviation)

**Commits are on the branch `gsd/phase-03-plan-01`, not on `main`.** The executor's pre-commit assertion reported `main` as a protected/default branch (`git.base-branch --is-protected main` = true; no `git.allow_default_branch_commits` override in `.planning/config.json`), and the dispatch asked for commits on main. The branch was created from `main` at `767a305` before the first commit. Nothing was committed to `main`, `.planning/config.json` was not touched, and no history was rewritten. The orchestrator decides how the four commits (plus the plan-metadata commit) reach `main`.

**Total deviations:** 1 auto-fixed (Rule 1). **Impact on plan:** none beyond the stated fix.

## Issues Encountered

- `python -m unittest tests.test_hunter` run on its own errors in `MovedColumnTests.test_a_missing_tracker_header_is_listed_under_needs_attention` (`from test_core import T0`: the `tests` directory is not on the path outside `discover`). Pre-existing, in code this plan does not touch; `python -m unittest discover -s tests` is unaffected and passes. Logged in `deferred-items.md`.
- Consequence to carry into plan 03-02 (parity): when a compact-mode Identity write is interrupted, the IDs that were already durable (2,424 in the test) have no Tally count, because the run fails before its Tally write and the next run only observes the rest. This follows the plan's write order (a count lost, never an ID lost); parity must treat Identity entries without Tally counts from an interrupted run as expected, or repair them.
- `storage_report.py` keeps its own `COMPACT_CELL_CHARS = 40_000` and `classify()`; the plan's file list does not include it, so `compact.IDENTITY_CELL_CHARS` and `compact.identity_class` are a second definition until a later plan makes `storage_report` import them.

## User Setup Required

None - no external service configuration required. The live checks (warning-only protection versus the service account, how the Sheet stores a long `IDs` cell, the first production dual-write run) belong to plan 03-05; nothing here was verified against Google Sheets, Groq or Telegram.

## Known Stubs

None.

## Next Phase Readiness

- Ready for 03-02 (seeding from the loaded ledger, repair of Identity IDs missing for Events rows, the rest of the `storage` key). `load_ledger()` already returns Events row numbers, the Identity set and the Tally rows; `write_identity` and `append_tally` are idempotent and chunked for hundreds of seed rows.
- Mocked only: CSV store and an in-memory Sheets fake. Full offline suite: 687 tests OK (633 at HEAD 47d68d4, 54 new).

## Self-Check: PASSED

---
*Phase: 03-compact-storage*
*Completed: 2026-10-29*
