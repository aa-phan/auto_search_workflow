---
phase: 03-compact-storage
plan: 04
subsystem: storage
tags: [dashboard, reporting, parity, storage-parity, workflow, docs, ready-to-cut-over]

requires:
  - phase: 03-compact-storage
    provides: "plan 03-01 Identity and Tally; plan 03-02 StorageState.bar and the in-run check; plan 03-03 merged-view reports and parity layer 4"
provides:
  - "reporting.build_summary summary['storage'] (mode, clock, readiness, P3-11 note) and storage_parts()"
  - "Dashboard SYSTEM line Storage with READY TO CUT OVER (dual mode, bar met only) and the muted P3-11 note under Unique jobs first observed"
  - "NEEDS ATTENTION row 'storage parity difference' (at most 3 sanitized refs)"
  - "reporting.reconcile 'from_tally' and the note in format_reconciliation; parity layer 4 skips it"
  - "parity.format_report and hunter.run_storage_parity (--storage-parity, read only, exit 0 / 1 / 2)"
  - "workflow input storage_parity and the step 'Storage parity (read only)'"
  - "SPEC, D-57, STATUS (Phase 3 section, all mocked), DEPLOY and README updated for the first dual-write deploy"
affects: [03-05 live checks, 03-06 cutover and restore, 03-07 fold]

actuals:
  tokens: 13363
  tasks: 3
  commits: 4
plan_head_before: ab77fe3c0991de455995da97dd73e9b60fb6aa1f
plan_head_after: 0bb628dcdc39a6dd3745baaf2f5a535b07b0587a
commits: 4

tech-stack:
  added: []
  patterns:
    - "readiness is recomputed from the recorded days on every build (StorageState.bar), never stored or inferred from time"
    - "presentation keys (summary['storage'], reconcile['from_tally']) are skipped by the parity comparison but every figure is still compared"
    - "stored differences are shown only when they match `kind ref (numbers)`: a hand-edited Discovery key cannot put a URL or free text on the page"
    - "a read-only command is tested by a full snapshot of the Sheets fake before and after, plus a writer lease patched to fail"

key-files:
  created: []
  modified:
    - reporting.py
    - dashboard.py
    - parity.py
    - hunter.py
    - .github/workflows/job_hunter.yml
    - tests/test_reporting.py
    - tests/test_hunter.py
    - tests/test_deployment.py
    - tests/test_storage_report.py
    - SPEC.md
    - DECISIONS.md
    - STATUS.md
    - DEPLOY.md
    - README.md
    - .planning/phases/03-compact-storage/deferred-items.md

key-decisions:
  - "READY TO CUT OVER needs the bar met AND stored mode dual AND a valid seed time; compact and restored never show it"
  - "The NEEDS ATTENTION row shows only stored differences of the form `kind ref (numbers)` and never changes the headline status"
  - "--storage-parity refuses (exit 2) unless the stored mode is dual and the stores are seeded; 0 = no counted differences, 1 = differences"
  - "reconcile gains a presentation count `from_tally` (drives the P3-11 note) that parity layer 4 skips"

patterns-established:
  - "DashboardStorageTests build the Discovery key with the real StorageState, so the bar is computed by the code under test's own collaborator, not hand-written JSON"

requirements-completed: [STOR-01]

coverage:
  - id: D1
    description: "Dashboard SYSTEM line Storage: not seeded, dual (seeded date, last check, k of 3 clean complete days, admission), compact (since, last fold, last check), restored; READY TO CUT OVER exactly when the recorded days meet the bar in dual mode after seeding, once, never in compact or restored mode, never from elapsed time, a stored flag or a damaged key"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_reporting.py#DashboardStorageTests (ready_to_cut_over*, storage_line*, damaged_storage_key)"
        status: pass
    human_judgment: false
  - id: D2
    description: "NEEDS ATTENTION row `storage parity difference` when the newest check counted differences: at most 3 job keys, run ids or figure paths, no title or URL even from a hand-edited key, per-mode action (dual: Events authoritative, nothing deleted, clock restarted; compact: Identity plus Events); no row for a clean, declared-only or missing check"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_reporting.py#DashboardStorageTests (needs_attention_row, never_carries_title_url, no_row_without)"
        status: pass
    human_judgment: false
  - id: D3
    description: "P3-11 note under `Unique jobs first observed`, in format_text and under the reconciliation's first-observed line, only when folded counts exist or were counted in the window; with nothing folded no note and the grid equals the old grid plus the Storage line; parity layer 4 still compares every figure and skips only the two presentation keys"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_reporting.py#DashboardStorageTests, CompactParityTests; tests/test_storage_report.py#ReconcileParityTests; tests/test_storage_parity.py"
        status: pass
    human_judgment: false
  - id: D4
    description: "`python hunter.py --storage-parity` is read only (full snapshot of the Sheets fake unchanged, writer lease forbidden, no Groq key), prints compared counts, at most 50 differences, declared differences and the clock; exit 0 / 1 / 2"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_hunter.py#StorageParityCommandTests"
        status: pass
    human_judgment: false
  - id: D5
    description: "Workflow input storage_parity is boolean with a fixed command step, excluded from the poller `if:` and from REQUIRE_TELEGRAM, within GitHub's 25-input limit"
    requirement: STOR-01
    verification:
      - kind: unit
        ref: "tests/test_deployment.py#test_storage_parity_input_is_read_only_and_excluded_from_the_poller"
        status: pass
    human_judgment: false
  - id: D6
    description: "SPEC, D-57, STATUS (Phase 3 section, every row mocked, not-verified-live list naming A2), DEPLOY and README describe dual writing, parity, the Storage signal, the storage_parity input and the warning on editing Identity"
    requirement: STOR-01
    verification:
      - kind: other
        ref: "grep -c 'Phase 3 compact storage (D-57' STATUS.md; grep -c storage_parity SPEC.md DEPLOY.md; grep -c Identity README.md"
        status: pass
    human_judgment: true
    rationale: "The documents record what the owner should expect on the first deploy and which checks are still unverified live; only the owner can judge that the wording is the intended bar and that nothing is overclaimed"

duration: 10min
completed: 2026-10-29
status: complete
---

# Phase 3 Plan 04: The owner's storage signal and the read-only parity command Summary

**The Dashboard now shows the storage mode, the 3-day parity clock and `READY TO CUT OVER` (recomputed from the recorded days, dual mode only), lists a parity difference under NEEDS ATTENTION with at most three sanitized references, notes where totals come from Tally, and `python hunter.py --storage-parity` (workflow input `storage_parity`) runs the same check read only with exit codes 0 / 1 / 2; the contract documents are ready for the dual-write deploy with every check labelled mocked**

## Performance

- **Duration:** 10 min
- **Started:** 2026-10-29T17:30:02Z
- **Completed:** 2026-10-29T17:39:47Z (last task commit; the SUMMARY commit follows)
- **Tasks:** 3 (tracer, TDD task, docs task)
- **Files modified:** 15 (0 created)

## Accomplishments

- **Storage signal (P3-05, P3-06).** `reporting._storage` loads the Discovery key through `compact.StorageState` and asks `bar(now)` on every build. `ready_to_cut_over` is true only when the bar is met, the stored mode is `dual` and the seed time parses. `dashboard._storage_text` joins the clauses of `reporting.storage_parts` and appends ` · READY TO CUT OVER`. The plain-text `STORAGE` line in `format_text` uses the same clauses and says `ready to cut over: yes|no`.
- **NEEDS ATTENTION row (P3-07).** `storage parity difference` (severity 1, ref `Identity / Tally`, count = counted, since = the check time) names the first three stored differences, and only those matching `kind ref (numbers)`; its action differs by mode. A clean, declared-only or missing check gives no row.
- **P3-11 note.** `reporting.TALLY_NOTE` shows once under `Unique jobs first observed` (a muted merged row), in `format_text` and under the reconciliation's first-observed line (`reconcile` returns `from_tally`). With nothing folded no note appears and the page is the old page plus the Storage line.
- **`--storage-parity`.** `hunter.run_storage_parity` loads the merged ledger, runs, boards, Discovery state and tracker, runs `parity.check_dual` against `simulate_compact`, and prints `parity.format_report` (header, mode and seed time, compared counts, counted and declared differences up to 50, the clock). Exit 0 / 1 / 2. It takes no lease, writes nothing and is dispatched with the other read-only reports, before the `writes` block, in `inventory_mode` (no Groq key, no resume).
- **Workflow.** Boolean input `storage_parity` (11 inputs now), the step `Storage parity (read only)` with the fixed command, `&& !inputs.storage_parity` in the poller `if:`, and the pinned `REQUIRE_TELEGRAM` expression extended.
- **Documents.** SPEC (what the owner sees, the command and its exit codes, the layout line), D-57 (plan 03-04 discretion choices), STATUS (`Phase 3 compact storage (D-57; plans 03-01..03-04)`: every row mocked, the not-verified-live list naming A2, migration notes), DEPLOY (`Compact storage (D-57)`), README (Identity and Tally, the warning).

## Task Commits

1. **Task 1: Tracer, Storage line, READY TO CUT OVER, NEEDS ATTENTION row, P3-11 note** - `86589ac` (feat)
2. **Task 2: `--storage-parity` and the workflow input** - `e734e75` (test, RED) then `f1e90b9` (feat, GREEN)
3. **Task 3: SPEC, D-57, STATUS, DEPLOY, README** - `0bb628d` (docs)

**Plan metadata:** the `docs(03-04): complete ...` commit that follows this file.

## Tracer gate

Interactive run (no auto mode in config), `human_verify_mode` default `end-of-phase`, tracer `<verify>` automated only: `tests.test_reporting -k DashboardStorage` (14 tests) and the full suite (781 OK) were run before the tracer commit and the suite again after every later task (787 OK). Tracer verified end-to-end, expansion followed.

## TDD evidence

- **Task 2 RED** (`e734e75`): `NO_COLOR=1 .venv/bin/python -m unittest tests.test_hunter.StorageParityCommandTests` exited 1 (5 of 5 failing). Target `test_the_command_needs_no_groq_key_and_is_dispatched_before_the_writer_lease`: `gsd_run check tdd-red-evidence` returned `RED_EVIDENCE_OK` (`target_test_failed`, format `unittest`). Semantic assessment: the target ran and failed on its planned assertion (`'"--storage-parity"' not found` in `hunter.py`), not on an import or fixture fault; the other four fail with `AttributeError: module 'hunter' has no attribute 'run_storage_parity'` inside the test body (the planned interface is missing; no `unittest.loader._FailedTest`). The deployment test failed on `assertIn("storage_parity", names)` and the updated pinned `REQUIRE_TELEGRAM` expression.
- **Task 2 GREEN** (`f1e90b9`): 5 hunter tests and the 2 deployment tests pass; full suite 787 OK. One test needed a larger synthetic ledger (70 extra baselines) to exceed the 50-line limit; fixed in the same commit.
- **Mutation checks** (each applied with `PYTHONDONTWRITEBYTECODE=1`, observed failing, reverted, files compared with the original afterwards):
  - Task 1 (reporting.py): readiness without the dual-mode condition fails 2; all stored differences shown instead of three fails 1; the sanitiser removed fails 1; the note always set fails 1; a row for declared-only differences fails 4. Dropping `seeded is not None` from the readiness test **survived**: `StorageState.bar` already returns not met for an unseeded or unparseable state, so the guard is redundant and kept on purpose.
  - Task 2: exit code always 0 fails 2; a Discovery write inside the command fails 3; a writer lease taken fails 3; the listing limit raised to 500 fails 1; the not-seeded refusal removed fails 1.

## Files Created/Modified

- `reporting.py` - `_storage`, `storage_parts`, `TALLY_NOTE`, `_SAFE_DIFF`, the NEEDS ATTENTION row in `_failures`, the STORAGE line in `format_text`, `from_tally` in `reconcile`, the note in `format_reconciliation`
- `dashboard.py` - `_storage_text`, the Storage line after Groq, the muted note under `Unique jobs first observed`
- `parity.py` - `format_report`, `MAX_REPORT_LINES`, `RECONCILE_PRESENTATION` (layer 4 skips `from_tally`)
- `hunter.py` - `run_storage_parity`, `--storage-parity`, `inventory_mode`, dispatch; imports `compact` and `parity`
- `.github/workflows/job_hunter.yml` - input `storage_parity`, step, poller exclusion, `REQUIRE_TELEGRAM`
- `tests/test_reporting.py` - `DashboardStorageTests` (14); `CompactParityTests` compare the summary without the `storage` section and expect exactly the note row as the grid difference
- `tests/test_hunter.py` - `StorageParityCommandTests` (5); the tests directory is put on `sys.path`
- `tests/test_deployment.py` - pinned expression and `test_storage_parity_input_is_read_only_and_excluded_from_the_poller`
- `tests/test_storage_report.py` - reconcile equality ignores `from_tally`
- `SPEC.md`, `DECISIONS.md`, `STATUS.md`, `DEPLOY.md`, `README.md` - see Accomplishments
- `.planning/phases/03-compact-storage/deferred-items.md` - the `tests.test_hunter` standalone-run item is resolved

## Decisions Made

- Readiness is recomputed from the recorded days and requires dual mode and a valid seed time (T-03-17: a hand-edited key cannot claim it; plan 03-06 re-checks before acting).
- Only stored differences shaped `kind ref (numbers)` are shown (T-03-18); the row never changes the headline status.
- `--storage-parity` refuses unless the stored mode is `dual` (stricter than the effective mode: a stored `compact` without `Events_Legacy` is also refused). Recorded in D-57.
- `Check configuration` in the workflow still lists `GROQ_API_KEY` as required for every run, as it already did for the other read-only reports; `--storage-parity` itself needs no key. Not changed (outside this plan, and changing it affects all reports); noted in D-57 and STATUS.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Existing parity-equality tests could not hold once the summary and the reconciliation carry presentation data**
- **Found during:** Task 1 (full suite after adding `summary["storage"]` and `reconcile["from_tally"]`)
- **Issue:** `CompactParityTests` (3 tests plus the rendered-grid test) and `ReconcileParityTests` asserted whole-dict or whole-grid equality between the all-rows side and the folded side. The new `storage.folded_total` / `detail_note`, the P3-11 note row and `from_tally` differ between those sides by design (P3-11). Without a fix, the parity check itself would also have counted `from_tally` as a figure difference in every compact run (35 tests, among them nine governor tests and the parity tests, failed until it was skipped).
- **Fix:** `parity.RECONCILE_PRESENTATION` skips `from_tally` (the summary's `storage` key was already skipped by plan 03-03); the tests compare the summary without the `storage` section, and the rendered grids differ by exactly the note row.
- **Files modified:** parity.py, tests/test_reporting.py, tests/test_storage_report.py
- **Verification:** full suite 781 OK after the change; every figure is still compared.
- **Committed in:** 86589ac

**2. [Rule 2 - Missing critical] A hand-edited `storage` key could put free text or a URL on the public-facing page**
- **Found during:** Task 1 (threat model T-03-18)
- **Issue:** `last_diffs` is a list of strings in a Sheet tab the owner can edit; showing it verbatim would put whatever is stored into NEEDS ATTENTION and the dry-run log.
- **Fix:** `_SAFE_DIFF` accepts only `kind ref (numbers)`; anything else is dropped. Test `test_the_row_never_carries_title_url_or_free_text_even_from_a_hand_edited_key`, with a mutation check.
- **Files modified:** reporting.py, tests/test_reporting.py
- **Committed in:** 86589ac

**3. [Rule 3 - Blocking] `tests.test_hunter` could not be run on its own**
- **Found during:** Task 2 (the plan's verify command runs `tests.test_deployment tests.test_hunter` and the new tests import `test_core`, `fake_sheets`, `test_storage_pipeline`)
- **Fix:** `tests/test_hunter.py` puts the tests directory on `sys.path` (like the other test modules). This also resolves the deferred item recorded in plan 03-01.
- **Files modified:** tests/test_hunter.py, deferred-items.md
- **Committed in:** e734e75 (deferred-items in the metadata commit)

**4. [Documentation, AGENTS rule 1] DECISIONS.md was not in the plan's `files_modified` list for tasks 1 and 2**
- D-57 collects each plan's discretion choices, so the plan 03-04 paragraph went there with SPEC.md (the plan's own task 3 lists DECISIONS.md).

---

**Total deviations:** 4 (1 Rule 2, 2 Rule 3, 1 documentation). **Impact on plan:** none on behavior beyond the stated fixes; no scope creep.

## Issues Encountered

- The first version of the "more than 50 differences" test used a ledger with only 15 differences; the test now seeds 70 extra baseline rows.
- The test for "no note when nothing is folded" first asserted the word `Tally` was absent, but the dual-mode Storage text legitimately says "Identity and Tally written beside Events"; it now asserts the note's own phrase (`Tally tab`).

## User Setup Required

None. Mocked only: synthetic ledgers, the CSV store and the in-memory Sheets fake. Nothing here was verified against Google Sheets, Groq, Telegram or GitHub Actions; the workflow edit was checked statically and was neither pushed nor dispatched. Deployment is plan 03-05 and needs the owner's consent.

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model: T-03-15 (boolean input, fixed `run:` line, pinned by a static test), T-03-16 (no lease, zero-write snapshot test, mutation-checked), T-03-17 (readiness recomputed by `bar(now)`; damaged keys tested), T-03-18 (refs only, sanitiser, tested).

## Next Phase Readiness

- Ready for 03-05 (live checks and the first deploy with the owner's consent): the owner can read the Storage line and dispatch `storage_parity`; STATUS lists what is unverified (A2, seed size and time, check seconds, the render, the workflow input in Actions).
- Full offline suite: 787 tests OK (767 before this plan, 20 new).

## Self-Check: PASSED

- All 14 created/modified source, test and document files exist; no new files.
- Commits found on the branch: 86589ac, e734e75, f1e90b9, 0bb628d (`gsd-tools check evaluation-scope --plan 03-04 --commits-only` resolved them).
- TDD gate: `test(03-04)` e734e75 precedes `feat(03-04)` f1e90b9.
- Acceptance criteria re-run: `grep -c "storage parity difference" reporting.py` 1; `grep -c "READY TO CUT OVER" dashboard.py` 1; `grep -c '"Storage"' dashboard.py` 1; `grep -c "def run_storage_parity" hunter.py` 1; `grep -c '"--storage-parity"' hunter.py` 1; `grep -c "storage_parity:" .github/workflows/job_hunter.yml` 1; `grep -c "python hunter.py --storage-parity" .github/workflows/job_hunter.yml` 1; `grep -c "inputs.storage_report || inputs.storage_parity) && 'no' || 'yes'" tests/test_deployment.py` 1; `grep -c "Phase 3 compact storage (D-57" STATUS.md` 1; `grep -c storage_parity SPEC.md` 1 and `DEPLOY.md` 1; `grep -c Identity README.md` 1; `awk ... STATUS.md | grep -ci live` 2; `tracker_identity_job` in DECISIONS.md 2; plan verification `tests.test_reporting tests.test_hunter tests.test_deployment` 229 OK; full suite `Ran 787 tests ... OK`.

---
*Phase: 03-compact-storage*
*Completed: 2026-10-29*
