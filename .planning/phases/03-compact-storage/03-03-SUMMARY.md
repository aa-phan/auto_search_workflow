---
phase: 03-compact-storage
plan: 03
subsystem: storage
tags: [reporting, parity, tally, identity, dashboard, pilot-report, storage-report, figures]

requires:
  - phase: 03-compact-storage
    provides: "plan 03-01 compact.py codecs and load_ledger; plan 03-02 simulate_compact, Ledger.folded, parse_dim, FoldedCount, parity.check_dual layers 1 to 3"
provides:
  - "reporting: _count_seen(c, f, n) weighted counting, _folded_fact, folded parameter on clean_inputs / build_summary / reconcile"
  - "dashboard.build, hunter --pilot-report and --storage-report read the merged ledger view (Events rows + Identity + Tally)"
  - "storage_report.logical_counts, analyze(ledger=...), JOBS RECORDED line; classify and COMPACT_CELL_CHARS delegate to compact"
  - "parity layer 4: compare_figures, tracker_identity_job declared class, figures compared in every dual-mode run"
  - "pipeline.Deps.tracker_rows and display_tz, wired in hunter.main"
affects: [03-04 --storage-parity command and Dashboard storage section, 03-05 live checks, 03-06 cutover, 03-07 fold]

actuals:
  tokens: 16606
  tasks: 3
  commits: 5
plan_head_before: 3d579c3a81f9ee5de81de39d272c10d006d1c753
plan_head_after: 258b6389d69a3d39584d455d4370e2d17063b40f
commits: 5

tech-stack:
  added: []
  patterns:
    - "one counting path: a folded Tally count is a weighted representative job passed through the same seen-only counter code as a real job"
    - "subtract-the-retained: the folded count is the Tally count minus the Events rows still present, never both"
    - "figure comparison by dotted path with numbers only (a string is shown as `text`, never copied)"
    - "declared classes are removed from both sides before comparing (tracker rows for identity-only jobs)"

key-files:
  created: []
  modified:
    - reporting.py
    - dashboard.py
    - pilot.py
    - storage_report.py
    - parity.py
    - pipeline.py
    - hunter.py
    - tests/test_reporting.py
    - tests/test_storage_report.py
    - tests/test_storage_parity.py
    - SPEC.md
    - DECISIONS.md
    - .planning/phases/03-compact-storage/deferred-items.md

key-decisions:
  - "A folded count passes through the same counting code as real jobs (weight n), has a synthetic key, is never in `facts` and is never pending, so it cannot add to verified-fresh, latency, alert or tracker figures"
  - "Identity or Tally damage that changes a figure is counted twice (its own kind and a figure): the clock restarts either way and the figure names what the user would have seen"
  - "Declared (listed, never counted): tracker rows for identity-only jobs, and the three row-count figures when a folded key has a duplicate seen row"
  - "The check reads the tracker once per run through Deps.tracker_rows; an unreadable tracker is compared as empty on both sides"

patterns-established:
  - "Figure Diffs: layer 4, kind `figure`, ref = dotted path (segments restricted to harmless characters), detail = `old N new M`"
  - "Tests share one synthetic dual-write world (`compact_world` in tests/test_reporting.py) for reporting, storage report and parity"

requirements-completed: [STOR-01]

coverage:
  - id: D1
    description: "The Dashboard summary built from the kept Events rows plus Identity and Tally equals the summary from all Events rows (all three periods, outcome partition, freshness denominators including date known/unknown, latency, trend, source_freshness, exclusions), in UTC and America/Chicago with now minutes after local midnight, for the simulated and the half-folded view; consistency checks stay empty; the rendered grid has the same values"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_reporting.py#CompactParityTests"
        status: pass
    human_judgment: false
  - id: D2
    description: "reporting.reconcile and pilot.build_report give identical numbers from the merged view and from all Events rows for a 7-day and an all-time window; the latency samples (pending jobs only) are unchanged; a folded count outside the window is not counted"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_storage_report.py#ReconcileParityTests"
        status: pass
    human_judgment: false
  - id: D3
    description: "storage_report.logical_counts (jobs by purpose, disposition and UTC day, boards with baselines, baseline jobs per board, work to preserve) is identical from the merged view and from all rows; a duplicate seen row changes neither side; classify and COMPACT_CELL_CHARS delegate to compact; --pilot-report and --storage-report read the merged ledger"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_storage_report.py#LogicalCountsTests, ClassifyDelegationTests, CommandsReadTheMergedViewTests"
        status: pass
    human_judgment: false
  - id: D4
    description: "Parity layer 4 in check_dual: a consistent world has zero counted differences in both time zones; a flipped Tally date letter and a Tally run time moved back a day are counted figure Diffs named by dotted path (numbers only); tracker rows for identity-only jobs are declared tracker_identity_job; duplicate-row count figures are declared"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_storage_parity.py#FigureTests"
        status: pass
    human_judgment: false
  - id: D5
    description: "Every dual-mode poller run's check reads the tracker once through Deps.tracker_rows in Deps.display_tz; an unreadable tracker is compared as empty and the check still completes with zero counted differences"
    requirement: STOR-01
    verification:
      - kind: integration
        ref: "tests/test_storage_parity.py#FigurePipelineTests"
        status: pass
    human_judgment: false
  - id: D6
    description: "SPEC metric rule 10, the parity layer 4 sentence and the D-57 plan 03-03 paragraph describe the merged view, the folded-count rules, the figure comparison and the declared classes"
    requirement: STOR-01
    verification:
      - kind: other
        ref: "grep -c 'Compacted rows' SPEC.md; grep -c 'Plan 03-03' DECISIONS.md"
        status: pass
    human_judgment: true
    rationale: "The documents record choices the owner left to the implementation (a figure is counted beside the Identity or Tally difference that caused it; which classes are declared); only the owner can confirm they are the intended bar before the cutover"

duration: 17min
completed: 2026-10-29
status: complete
---

# Phase 3 Plan 03: Reports read the merged view; parity layer 4 compares the figures Summary

**The Dashboard, the pilot reconciliation and the storage counts now read Events rows plus Identity and Tally through one weighted counting path, and every dual-mode poller run compares those figures between all rows and the simulated compact view, naming any difference by its dotted path with numbers only**

## Performance

- **Duration:** 17 min
- **Started:** 2026-10-29T17:10:18Z
- **Completed:** 2026-10-29T17:27:18Z (last task commit; the SUMMARY commit follows)
- **Tasks:** 3 (tracer, TDD task, TDD task)
- **Files modified:** 13 (0 created)

## Accomplishments

- **One counting path (P3-10).** `reporting._count_seen(c, f, n)` is the seen-only part of the Dashboard's per-day counters. Real jobs pass n = 1; each folded Tally count (Tally minus the retained Events rows, per run and dimension) is one representative job carrying weight n, with a synthetic key that never enters `facts`. It carries only the class recorded at first observation, so it never adds to verified-fresh, latency, alert, pending or tracker figures. Rehearsal runs' folded counts are excluded and counted under `events_from_rehearsal_runs`; counts without a run id are kept, unattributed. `ledger_events_read` and `latest_ledger_event` include the folded totals and run times.
- **Every consumer reads the merged view.** `dashboard.build`, `hunter.run_pilot_report` and the new `hunter.run_storage_report` (`--storage-report`) call `state.load_ledger()`; `--rebalance-report` keeps reading pending jobs only. In dual mode with consistent stores `ledger.folded()` is empty, so all three print exactly what they printed before.
- **Reconciliation and storage counts (P3-11).** `reporting.reconcile(folded=...)` adds each folded count inside the window (by run time) to the cohort total and to its outcome (baseline, stale, title-gated); `pilot.build_report(folded=...)` passes it through. `storage_report.logical_counts` gives the figures that must not depend on where an observation is stored (first-seen jobs by purpose, disposition and UTC day; baseline jobs per board from Identity `b` entries; jobs awaiting evaluation or alert); `analyze(ledger=...)` adds them and `format_report` prints one `JOBS RECORDED (Events rows plus Identity and Tally)` line. `classify` asks `compact.identity_class` and `COMPACT_CELL_CHARS = compact.IDENTITY_CELL_CHARS` (a deferred item from 03-01, now resolved).
- **Parity layer 4.** `parity.check_dual(..., tz, runs, boards, discovery, tracker)` builds the summary and both reconciliation windows (`[now - 7 days, now]`, `[2020-01-01, now]`) and the logical counts from all rows and from the compact view with identical arguments, and compares them leaf by leaf (`compare_figures`; the presentation key `storage` is skipped). A difference is a counted `figure` Diff named by a dotted path with `old N new M`; a string leaf is shown as `text`, never copied. `compared` lists `figures_summary`, `figures_reconcile_7d`, `figures_reconcile_all`, `figures_logical`.
- **Declared classes (Pitfall 9).** A tracker row whose parsed job key, or exact stored URL, names a job that only Identity or Tally still holds is removed from both sides and listed as declared `tracker_identity_job`. When a folded key has a duplicate `seen` row, the three row-count figures are declared too (the simulation removes every row of the key while Tally counts it once).
- **Wiring.** `Deps.tracker_rows` and `Deps.display_tz` (wired in `hunter.main` from `store.tracker_rows` and `store.display_tz`); the tracker is read once per checked run after the alert stage, contained (an unreadable tracker is compared as empty and logged by exception type only).
- Mocked scale check: `check_dual` on a synthetic 194,000-row ledger took 6.4 s including layers 1 to 3 (offline; the real cost at about 200,000 rows is a live observation for plan 03-05).

## Task Commits

1. **Task 1: Tracer, Dashboard from the merged view** - `e07a020` (feat)
2. **Task 2: Pilot reconciliation, pilot report and storage counts** - `5ba3b83` (test, RED) then `0509cd7` (feat, GREEN)
3. **Task 3: Parity layer 4** - `51deb3e` (test, RED) then `258b638` (feat, GREEN)

**Plan metadata:** the `docs(03-03): complete ...` commit that follows this file.

## Tracer gate

Interactive run, `human_verify_mode` default `end-of-phase`, tracer `<verify>` automated only: `tests.test_reporting -k CompactParity` (9 tests) and the full suite (743 OK) were run before the tracer commit and the suite was re-run after every later task (final 767 OK). Tracer verified end-to-end, expansion followed.

## TDD evidence

- **Task 2 RED** (`5ba3b83`): `.venv/bin/python -m unittest tests.test_storage_report` exited 1 (1 failure, 21 errors). Target `ClassifyDelegationTests.test_classify_asks_compact_for_the_identity_class_instead_of_deciding_itself`: `gsd_run check tdd-red-evidence` returned `RED_EVIDENCE_OK` (`target_test_failed`, format `unittest`). Semantic assessment: the target ran and failed on its planned assertion (`'baseline' != 'identity'`: `classify` decided on its own instead of asking `compact.identity_class`), not on an import or fixture fault. The 21 errors are the planned interface missing (`logical_counts`, `analyze(ledger=)`, `reconcile(folded=)`, `build_report(folded=)`); the `unittest.loader._FailedTest` case did not occur.
- **Task 2 GREEN** (`0509cd7`): 24 tests in `tests.test_storage_report` pass (two command-level tests were added during GREEN); full suite 757 OK.
- **Task 3 RED** (`51deb3e`): `.venv/bin/python -m unittest tests.test_storage_parity` exited 1 (4 failures, 7 errors of 50). Target `FigureTests.test_a_tally_date_letter_flipped_is_a_counted_figure_difference_named_by_its_path`: `RED_EVIDENCE_OK`. Semantic assessment: it failed on `assertTrue(any(... figure ... new_postings_date ...))` with `[]` (check_dual compared layers 1 to 3 only), the planned behaviour, with the layer-2 `tally_count` already present. The 40 earlier tests passed at RED.
- **Task 3 GREEN** (`258b638`): 50 tests pass; full suite 767 OK.
- **Mutation checks** (each applied with `PYTHONDONTWRITEBYTECODE=1`, observed failing, reverted):
  - Task 1 (compact.py / reporting.py): counting folded facts without subtracting the retained rows (`Ledger.folded` returns the whole Tally) fails 12 CompactParity subtests (half-folded, freshness denominator, rehearsal, blank run id, rendered grid, simulated view); omitting the `date` dimension when building the folded fact (`published=None`) fails 5 (freshness denominator, simulated view, one-counting-path test).
  - Task 2: counting folded counts outside the reconcile window fails 8 (window test, 7-day and all-time reconcile, pilot report, command output); counting baseline rows that Identity already holds fails the half-folded logical-counts test.
  - Task 3 (parity.py): not removing tracker rows for identity-only jobs fails `test_a_hand_added_tracker_row...` and the pipeline tracker test; not feeding the folded counts to the merged side fails 13; copying strings into figure details fails `test_compare_figures_names_nested_paths...`; dropping the declared row-count class fails the duplicate-row test; skipping the logical counts fails the consistent-world and two pipeline tests.

## Files Created/Modified

- `reporting.py` - `_count_seen`, `_folded_fact`, `FOLDED_PUBLISHED`, `Clean.folded`, `folded` on `clean_inputs`, `build_summary`, `reconcile`
- `dashboard.py` - `build` loads `state.load_ledger()`
- `pilot.py` - `build_report(folded=())`
- `storage_report.py` - `logical_counts`, `analyze(ledger=)`, JOBS RECORDED line, `classify` / `COMPACT_CELL_CHARS` from compact
- `parity.py` - layer 4: `compare_figures`, `_figures`, tracker removal, declared classes, new `check_dual` arguments
- `pipeline.py` - `Deps.tracker_rows`, `Deps.display_tz`, `storage_check` reads the tracker and passes runs, boards, Discovery state and tz
- `hunter.py` - merged-view consumers, `run_storage_report`, Deps wiring
- `tests/test_reporting.py` - `World`, `compact_world` (shared synthetic dual-write world), `CompactParityTests`
- `tests/test_storage_report.py` - `ClassifyDelegationTests`, `LogicalCountsTests`, `ReconcileParityTests`, `CommandsReadTheMergedViewTests`
- `tests/test_storage_parity.py` - `FigureTests`, `FigurePipelineTests`; plan 02 exact-kind tests look at layers 1 to 3
- `SPEC.md`, `DECISIONS.md` - metric rule 10, parity layer 4, D-57 plan 03-03 paragraph
- `.planning/phases/03-compact-storage/deferred-items.md` - the `storage_report` duplicate definitions item is resolved

## Decisions Made

- Followed the plan's discretion choices (weighted representative job, sentinel publication instant, `storage` key skipped, Pitfall 9 declared); they are recorded in D-57.
- A figure is counted beside the Identity or Tally difference that caused it (the plan's own example lists `figure` plus `tally_count`); the same holds for Identity damage through the baseline-per-board figure.
- `logical_counts` takes no clock: `needs_alert` ignores its `now`, so a fixed epoch is passed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan 02 tests pinned an exact difference set that layer 4 legitimately extends**
- **Found during:** Task 3 GREEN
- **Issue:** eight existing `tests/test_storage_parity.py` tests asserted the exact counted kinds (`identity_missing` alone, `tally_missing` + `tally_orphan` alone, `storage parity: 1 differences (...)`, `Storage: mode=dual, 1 counted`). With layer 4, Identity or Tally damage that changes a figure is also a counted `figure`.
- **Fix:** `MutationTests.assertOnly` and the state-counter test look at layers 1 to 3 (the figure is asserted separately); the pipeline tests expect `storage parity: 2 differences (figure 1, identity_missing 1)`, the named `figure logical.baseline_jobs_per_board.greenhouse|acme (old 3 new 2)` and `2 counted`.
- **Files modified:** tests/test_storage_parity.py
- **Verification:** `tests.test_storage_parity` 50 OK
- **Committed in:** 258b638

**2. [Rule 2 - Missing critical] Duplicate `seen` rows of a folded key made the row-count figures flap the clock**
- **Found during:** Task 3 (designing the declared classes)
- **Issue:** the simulation removes every row of a folded key, Tally counts it once, so `ledger_events_read`, `latest_ledger_event` and `events_from_rehearsal_runs` differ by the duplicates, although AGENTS and D-57 already declare duplicate `seen` rows as not counted.
- **Fix:** those three figures are declared (listed, not counted) only when such a duplicate exists; test `test_a_duplicate_seen_row_of_a_folded_key_declares_the_row_count_figures_only`.
- **Files modified:** parity.py, tests/test_storage_parity.py
- **Committed in:** 258b638

**3. [Rule 3 - Blocking] The `--storage-report` branch was inline in `main` and could not be tested**
- **Found during:** Task 2 (command-level test)
- **Fix:** moved into `hunter.run_storage_report(store)` (same behaviour plus the merged ledger).
- **Files modified:** hunter.py
- **Committed in:** 0509cd7

**4. [Documentation, AGENTS rule 1] DECISIONS.md was not in the plan's file list**
- The D-57 entry collects each plan's discretion choices ("Later plans append their own"), so the plan 03-03 paragraph was added there with SPEC.md.
- **Committed in:** 258b638

---

**Total deviations:** 4 (1 Rule 1, 1 Rule 2, 1 Rule 3, 1 documentation). **Impact on plan:** none on behaviour beyond the stated fixes; no scope creep.

## Issues Encountered

- I `source`d the markdown `gsd-run-resolver.md` by mistake (it hung and was moved to the background); I killed my three stray shell processes and called the CLI with `node ~/.claude/gsd-core/bin/gsd-tools.cjs` instead. Nothing in the repository was affected.
- An earlier version of the date-flip test picked a run 30 days back, outside the 30-day period, so it produced no figure difference; the selection now uses a run between 8 and 27 days old.

## User Setup Required

None. Mocked only: synthetic ledgers, the CSV store and the in-memory Sheets fake. Nothing here was verified against Google Sheets, Groq or Telegram. The real size of the check (seconds at about 200,000 rows, the extra Job Tracker read per run) and the live comparison of the figures are plan 03-05's observations.

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model: T-03-12 (double counting, forked counter) is mitigated by the single `_count_seen` path, subtract-the-retained, empty `checks` and the layer-4 comparison in every dual run; T-03-13 by the declared `tracker_identity_job` class; T-03-14 by numbers-only figure details and harmless path segments (tested, including the mutation that copies strings). The extra tracker read per run uses the existing tracker access.

## Next Phase Readiness

- Ready for 03-04 (`--storage-parity` command and the Dashboard `storage` section): `parity.check_dual` now takes everything the Dashboard needs, and the `storage` summary key is already skipped by the figure comparison.
- Full offline suite: 767 tests OK (734 before this plan, 33 new).

## Self-Check: PASSED

- Created/modified files exist (13 files; no new files).
- Commits found on the branch: e07a020, 5ba3b83, 0509cd7, 51deb3e, 258b638.
- Acceptance criteria re-run: `grep -c "def _count_seen" reporting.py` 1, `grep -c "folded" reporting.py` 23, `grep -c "load_ledger()" dashboard.py` 1; `grep -c "def logical_counts" storage_report.py` 1, `compact.identity_class` 1, `load_ledger()` in hunter.py 2, `folded` in pilot.py 3; `class FigureTests` 1, `tracker_identity_job` in parity.py 3, `tracker_rows` in pipeline.py 5, `tracker_rows=store.tracker_rows` in hunter.py 1; full suite `Ran 767 tests ... OK`.

---
*Phase: 03-compact-storage*
*Completed: 2026-10-29*
