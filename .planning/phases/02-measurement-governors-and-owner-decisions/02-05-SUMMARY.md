---
phase: 02-measurement-governors-and-owner-decisions
plan: 05
subsystem: dashboard-yield-view
tags: [dashboard, reporting, tracker-rows, combo-chart, age-when-found, feedback-per-cohort, reconciliation, meas-01]

requires:
  - phase: 02-measurement-governors-and-owner-decisions
    provides: "Run deadlines and the pure reporting/dashboard split from D-40/D-41; per-job JobFacts from the Events ledger"
provides:
  - "reporting.tracker_join: tracker rows joined to ledger jobs by identity, exact stored URL as a diagnostic fallback only"
  - "reporting._yield and summary['yield']: 14-day tracker rows per found-day by cohort, per-period rows/by_cohort/by_ats/by_age/feedback, join counts, day_unknown, reconcile with missing_from_tracker"
  - "reporting.age_bucket and AGE_BUCKETS (inclusive bounds; unknown is never fresh)"
  - "Needs-attention row 'tracker missing kept jobs' only when the missing list is non-empty"
  - "dashboard combo chart kind (Chart.series_types, Chart.stacked), BAND_LINES_STACK, hidden yield and age blocks, top chart 'Tracker rows per day · target 20-30', age bar chart, TRACKER ROWS · 7 DAYS table"
  - "pilot reconcile uses tracker_join and names missing kept jobs (keys and stamps) and the stored-URL count"
  - "SPEC Operational dashboard layout and metric rule 9; DECISIONS D-52"
affects: [02-07, 02-08, reporting, dashboard, pilot]

actuals:
  tokens: 14000
  tasks: 3
  commits: 4
plan_head_before: be6c8e3dd6c2960fa2611e0292b150ec86e78fd7
plan_head_after: 960d8fd9a9a0be844b5868ed90070fcf08ceea29

tech-stack:
  added: []
  patterns:
    - "Pure reporting computes the yield from the ledger and tracker; the dashboard only renders counts, keys and dates (no tracker free text)"
    - "Day of a tracker row = display-time-zone day of its job's ledger evaluated event; Date_Found text only as a fallback"
    - "Chart data block cells: blank = unknown day, applied to the target lines too"

key-files:
  created: []
  modified:
    - reporting.py
    - dashboard.py
    - tests/test_reporting.py
    - SPEC.md
    - DECISIONS.md

key-decisions:
  - "D-52: the found-day comes from the ledger evaluated instant in the display time zone, not from the user-formatted Date_Found text (flagged for the owner's acceptance)"
  - "D-52: the NEEDS ATTENTION row for ledger-kept jobs missing from the tracker is applied literally (P2-12): it shows whenever the all-time mismatch is not 0"
  - "D-52: the 20-30 band is two constant LINE series on a stacked COMBO chart; BAND_LINES_STACK switches the upper series to the 10-row difference if a real Sheet stacks lines (unverified assumption A7, checked in plan 02-07)"

patterns-established:
  - "Joins from tracker to ledger go through reporting.tracker_join; the stored-URL match is diagnostic and never defines identity or dedupe"
  - "Unknown age (unmatched row, day precision, missing or future publication time) is its own bucket and is never counted as fresh"

requirements-completed: [MEAS-01]

coverage:
  - id: D1
    description: "Top Dashboard chart 'Tracker rows per day · target 20-30': 14 days of tracker rows per found-day split by verified fresh / Recent / other, with the 20-30 target as two flat lines (request shape)"
    requirement: "MEAS-01"
    verification:
      - kind: unit
        ref: "tests/test_reporting.py#YieldTests.test_dashboard_top_chart_is_tracker_rows_combo_with_target_band"
        status: pass
      - kind: unit
        ref: "tests/test_reporting.py#YieldTests.test_yield_counts_tracker_rows_per_local_day_by_cohort"
        status: pass
    human_judgment: true
    rationale: "Whether the real Google Sheet draws the two target lines flat at 20 and 30 (not stacked) is a rendering fact no offline test can assert; plan 02-07 checks it live and BAND_LINES_STACK is the switch"
  - id: D2
    description: "A tracker row counts on the display-time-zone day its job was evaluated; local midnight belongs to the new day; publication and first sight never bucket days; unmatched rows use Date_Found or are day unknown"
    requirement: "MEAS-01"
    verification:
      - kind: unit
        ref: "tests/test_reporting.py#YieldTests.test_yield_day_boundary_local_midnight_belongs_to_new_day"
        status: pass
      - kind: unit
        ref: "tests/test_reporting.py#YieldTests.test_yield_day_comes_from_the_evaluation_not_the_publication_or_first_sight"
        status: pass
      - kind: unit
        ref: "tests/test_reporting.py#YieldTests.test_yield_unmatched_row_uses_date_found_or_unknown_day"
        status: pass
    human_judgment: false
  - id: D3
    description: "Age when found in inclusive buckets <=1h, 1-12h, 12-24h, 24-72h, older, unknown; day-precision, missing, future and unmatched are unknown and never fresh; shown as a 7-day bar chart"
    requirement: "MEAS-01"
    verification:
      - kind: unit
        ref: "tests/test_reporting.py#YieldTests.test_yield_age_buckets_inclusive_upper_bounds_and_unknown_for_day_precision"
        status: pass
      - kind: unit
        ref: "tests/test_reporting.py#YieldTests.test_yield_age_counts_come_from_matched_rows_in_the_period"
        status: pass
    human_judgment: false
  - id: D4
    description: "My_Feedback mix (Would apply / Maybe / Irrelevant / unlabelled, free text apart) per cohort in a TRACKER ROWS table, so Recent rows are reported apart from verified-fresh rows"
    requirement: "MEAS-01"
    verification:
      - kind: unit
        ref: "tests/test_reporting.py#YieldTests.test_yield_feedback_mix_per_cohort"
        status: pass
      - kind: unit
        ref: "tests/test_reporting.py#YieldTests.test_dashboard_page_has_the_age_chart_the_tracker_rows_table_and_no_tracker_text"
        status: pass
    human_judgment: false
  - id: D5
    description: "Tracker-versus-ledger reconciliation by identity (stored URL as a diagnostic fallback), per-ATS rows, missing kept jobs named by key and evaluated stamp, and a Needs-attention row only when the missing list is non-empty"
    requirement: "MEAS-01"
    verification:
      - kind: unit
        ref: "tests/test_reporting.py#YieldTests.test_yield_reconcile_names_missing_keys_both_directions"
        status: pass
      - kind: unit
        ref: "tests/test_reporting.py#YieldTests.test_yield_stored_url_fallback_matches_custom_domain_url"
        status: pass
      - kind: unit
        ref: "tests/test_reporting.py#YieldTests.test_yield_rows_by_ats_keep_the_provider_baseline"
        status: pass
      - kind: unit
        ref: "tests/test_reporting.py#YieldTests.test_dashboard_needs_attention_row_only_when_mismatch_nonzero"
        status: pass
      - kind: unit
        ref: "tests/test_pilot_corrections.py (reconcile extended, unchanged assertions)"
        status: pass
    human_judgment: false
  - id: D6
    description: "Page still has exactly four charts with fixed ids 7100-7103; the old Relevant-jobs and Alerts-and-additions charts leave the page; re-rendering is identical; cohort labels match hunter.FRESHNESS_LABELS"
    requirement: "MEAS-01"
    verification:
      - kind: unit
        ref: "tests/test_reporting.py#YieldTests.test_dashboard_rerun_is_identical"
        status: pass
      - kind: unit
        ref: "tests/test_reporting.py#YieldTests.test_dashboard_cohort_labels_match_hunter_freshness_labels"
        status: pass
      - kind: unit
        ref: "tests/test_reporting.py#DashboardTabTests.test_charts_are_added_with_fixed_ids_and_last_times_charts_are_deleted_first"
        status: pass
    human_judgment: false
  - id: D7
    description: "SPEC Operational dashboard layout and metric rule 9, and DECISIONS D-52, describe the yield view exactly as built"
    requirement: "MEAS-01"
    verification: []
    human_judgment: true
    rationale: "Documentation accuracy against the built behaviour is a reading judgment; D-52 also asks the owner to accept two choices"

duration: 5min
completed: 2026-10-26
status: complete
---

# Phase 2 Plan 05: Dashboard Yield View Summary

**Dashboard top chart of tracker rows per found-day split verified fresh / Recent / other with a 20-30 target band, an age-when-found bar chart, a per-cohort My_Feedback table, and a tracker-versus-ledger reconciliation that flags ledger-kept jobs missing from the tracker**

## Performance

- **Duration:** 5 min
- **Started:** 2026-10-26T18:09:22Z
- **Completed:** 2026-10-26T18:15Z
- **Tasks:** 3 (one tracer, one TDD, one docs)
- **Files modified:** 5

## Accomplishments

- `reporting._yield` counts tracker ROWS per found-day for 14 days by cohort. The day is the display-time-zone day of the job's ledger `evaluated` event (P2-09), local midnight belongs to the new day, and days before the first tracker row ever are unknown (blank) while later empty days are a measured 0. Rows with no ledger match use their `Date_Found` text, else are counted in `day_unknown`.
- `tracker_join` joins rows to ledger jobs by `parse_job_url(Apply_URL).key`, and only as a diagnostic fallback by the exact stored URL (so a Greenhouse custom-domain row still matches); it never defines identity or dedupe.
- The page's first chart is now a stacked COMBO chart (three COLUMN cohort series, two dashed LINE target series at 20 and 30); the alerts-and-additions chart became the age-when-found bar chart; a TRACKER ROWS · 7 DAYS table shows rows and the My_Feedback mix per cohort plus the reconciliation line and per-ATS rows. Still four charts with ids 7100-7103.
- `age_bucket` uses inclusive bounds (60 min, 12 h, 24 h, 72 h); an unmatched row, a day-precision or missing publication time and a future publication time are `unknown` and never counted as fresh.
- A `tracker missing kept jobs` row appears under NEEDS ATTENTION only when ledger-kept jobs are missing from the tracker, naming up to three keys; the pilot report's `reconcile` uses the same join and lists the missing keys (keys and stamps only).

## Task Commits

1. **Task 1: Tracer, tracker rows per found-day to the top COMBO chart** - `2f31f63` (feat)
2. **Task 2: Age, feedback per cohort, reconciliation** - RED `3693f7d` (test), GREEN `da7b690` (feat)
3. **Task 3: SPEC "Operational dashboard" and D-52** - `960d8fd` (docs)

**Plan metadata:** recorded in the `docs(02-05)` commits that follow this file.

## TDD Gate Compliance

Task 2 (`tdd="true"`): RED `3693f7d` precedes GREEN `da7b690`; no REFACTOR commit was needed. Task 1 is a tracer (tests and implementation in one commit, as the plan specifies). The plan itself is `type: execute`, not `type: tdd`.

**RED evidence (Task 2).** `NO_COLOR=1 .venv/bin/python -m unittest tests.test_reporting.YieldTests` exited 1 with 15 tests, 6 failing: `test_yield_age_buckets_...` (AttributeError: no `age_bucket`), `test_yield_age_counts_...`, `test_yield_feedback_mix_per_cohort` and `test_yield_rows_by_ats_...` (KeyError: `by_age`, `feedback`, `by_ats`), `test_dashboard_needs_attention_row_only_when_mismatch_nonzero` (AssertionError 0 != 1) and the page test (the old "Alerts delivered and tracker additions" chart was still there). `gsd check tdd-red-evidence` on the Needs-attention test returned `RED_EVIDENCE_OK` / `target_test_failed`. Semantic assessment: every failing test ran and failed on the planned missing behaviour, not on syntax, import, fixture or collection faults. The other five YieldTests behaviour tests (day boundary, unmatched Date_Found, reconcile both directions, stored-URL fallback, rerun, cohort labels) were already green because the Task 1 tracer built `tracker_join`, `day_unknown` and the reconcile lists; they pin that behaviour and the stored-URL one was mutation-checked (below).

## Mutation checks (each reverted, suite green after)

Task 1:
- bucketing by `seen_at` instead of `eval_at` fails `test_yield_day_boundary_...` and `test_yield_day_comes_from_the_evaluation_...`
- writing 0 instead of blank for days before the first row fails `test_yield_counts_tracker_rows_per_local_day_by_cohort` and the day-from-evaluation test

Task 2:
- treating day precision as time-precise fails the bucket test and `test_yield_age_counts_...`
- adding the Needs-attention row when the missing list is empty (`is not None`) fails `test_dashboard_needs_attention_row_only_when_mismatch_nonzero`
- removing the stored-URL fallback fails `test_yield_stored_url_fallback_matches_custom_domain_url`

`__pycache__` was cleared before each mutated run and before the final suite run.

## Files Created/Modified

- `reporting.py` - `JobFacts.url`, `TARGET_ROWS_PER_DAY`, `COHORTS`, `COHORT_OF_LABEL`, `AGE_BUCKETS`, `age_bucket`, `tracker_join`, `_yield`, `summary["yield"]`, `_failures(tracker_missing=...)`, `reconcile` extended with `missing_from_tracker` and `by_stored_url`, `format_reconciliation` prints the missing keys (at most 10, then "and N more")
- `dashboard.py` - `Chart.series_types` / `Chart.stacked`, `combo` chart kind, `BAND_LINES_STACK`, hidden yield and age blocks, new first chart and age bar chart, TRACKER ROWS · 7 DAYS section
- `tests/test_reporting.py` - `YieldTests` (15 tests), two existing dashboard tests updated for the swapped chart slots
- `SPEC.md` - Operational dashboard layout text, hidden-block note, metric rule 9
- `DECISIONS.md` - D-52

## Decisions Made

- D-52 records the owner decisions P2-09..P2-12 and two choices taken here for the owner's acceptance: the day comes from the ledger `evaluated` instant (RESEARCH Open Question 3), and the Needs-attention row is applied literally (Open Question 2). If the 2 jobs flagged on 2026-10-25 turn out to be rows the owner deleted, the row stays until they are restored or the owner decides; plan 02-07 presents that choice with the diagnostic.
- The band is two constant LINE series on a stacked combo. Whether Sheets stacks LINE series is unverified (A7); `BAND_LINES_STACK` is the one-line switch.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Two existing dashboard tests assumed the old chart slots**
- **Found during:** Task 1 and Task 2
- **Issue:** `test_chart_data_block_is_chronological_...` read `grid.charts[0]` as the trend-block line chart, and `test_bar_chart_series_target_the_bottom_axis_...` keyed specs by chart kind and read a `column` chart; the deliberate chart swap (D-52) broke both.
- **Fix:** the first test now selects the `stacked_column` ("Runs per day") chart, which still reads the trend block; the second checks both bar charts target the bottom axis and that the stacked-column and combo charts target the left axis. Their intent (hidden data block, series header, bottom axis for bars) is unchanged.
- **Files modified:** tests/test_reporting.py
- **Verification:** full suite green (612 tests)
- **Committed in:** `2f31f63`, `da7b690`

**2. [Rule 2 - Missing critical] Two extra `Date_Found` formats parsed for unmatched rows**
- **Found during:** Task 1
- **Issue:** cells are written USER_ENTERED, so Sheets may re-render `Date_Found` with a 24-hour clock (RESEARCH Pitfall 5); the four listed formats would send such rows to "day unknown".
- **Fix:** added `%m/%d/%Y %H:%M:%S` and `%m/%d/%Y %H:%M` after the four planned formats. Fallback only; matched rows never parse the text.
- **Files modified:** reporting.py
- **Committed in:** `2f31f63`

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 missing critical)
**Impact on plan:** both are small and keep the plan's behaviour; no scope creep. Extra tests beyond the plan's list: day from evaluation rather than publication or first sight, age counts from matched rows, and a page test (four charts and ids, removed charts gone, no tracker free text on the page).

## Issues Encountered

None. The unchanged pilot tests pass with the extended `reconcile`.

## Authentication Gates

None.

## Known Stubs

None. No hard-coded empty values reach the UI; the unknown values are the intended blank/n-a cells.

## Threat Flags

None. No new network endpoint, auth path, file access or schema change; the page shows counts, job keys and dates only (T-02-13, T-02-14), and `age_bucket` keeps unknown age out of fresh (T-02-15).

## User Setup Required

None - no external service configuration required.

## Verification scope (mocked versus live)

Everything here is offline and mocked: request shapes are checked against the fake spreadsheet. Nothing was rendered in a real Google Sheet, so the band's flat 20/30 lines, the chart layout and the reconcile diagnostic against the production tracker are NOT verified; they are live checks in plan 02-07 (AGENTS rule 5). `MEAS-01` is listed in `requirements-completed` as this plan's requirement, but the shared-ID gate keeps it unmarked in REQUIREMENTS.md until plan 02-07 (which also declares it) finishes.

## Next Phase Readiness

- Ready for plan 02-06 (and 02-07, whose live checks cover the real-Sheet render, `BAND_LINES_STACK` and the 2-missing-jobs diagnostic).
- Open for the owner: accept or change the two D-52 choices.

## Self-Check: PASSED

`reporting.py`, `dashboard.py`, `tests/test_reporting.py`, `SPEC.md` and `DECISIONS.md` exist; commits `2f31f63`, `3693f7d`, `da7b690` and `960d8fd` are ancestors of HEAD; `def tracker_join`, `def _yield` and `def age_bucket` each appear once in reporting.py and `reporting.py` has no `hunter` import; `BAND_LINES_STACK` and `"COMBO"` appear in dashboard.py; `grep -c "Alerts delivered and tracker additions" dashboard.py` is 0; `## D-52`, `tracker rows per day by cohort`, `TRACKER ROWS` and `9. *Tracker rows.*` are present; RED (`test(02-05)`) and GREEN (`feat(02-05)`) gate commits exist for Task 2; `git rev-list --count be6c8e3..HEAD` is 4; the full suite (`.venv/bin/python -m unittest discover -s tests`, 612 tests) passes offline; no unexpected file deletions.

---
*Phase: 02-measurement-governors-and-owner-decisions*
*Completed: 2026-10-26*
