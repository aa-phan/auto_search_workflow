---
phase: 02-measurement-governors-and-owner-decisions
plan: 06
subsystem: groq-visibility
tags: [groq, dashboard, reporting, pilot-report, limits-audit, tokens-per-call, meas-02, meas-03, status]

requires:
  - phase: 02-measurement-governors-and-owner-decisions
    provides: "Runs token/limit/skip/cut columns (02-03, 02-04), Discovery key groq_budget (eval_budget.GROQ_BUDGET_KEY), evaluated payload key model, pure reporting/dashboard split (02-05)"
provides:
  - "reporting._groq and summary['groq']: today's UTC-day tokens per model against budget, 7-day sums, token_runs, tokens_per_completion (with n), cached_share_pct, scored_by_model; JobFacts.eval_model"
  - "Dashboard SYSTEM line 'Groq' (budget per model, scored-by-model split, tokens per call with n, cached share, budget skips, evaluation cuts, poll cuts, alerts deferred; n/a when unknown)"
  - "pilot limits-audit keys groq_tokens_*, groq_token_runs, groq_tokens_per_completion, groq_completions_per_day, groq_cached_share_pct, groq_tokens_by_utc_day, governor counters, duration_p95_s, groq_limits_latest and four report lines"
  - "SPEC pilot/limits-audit and SYSTEM-line text; STATUS section 'Phase 2 governors and measurement (D-49..D-52)' with mocked-versus-live table and migration notes"
affects: [02-07, 02-08, reporting, dashboard, pilot]

actuals:
  tokens: 12000
  tasks: 2
  commits: 4
plan_head_before: 750f41ba3eff2a013a02bdcf3e2f9fefa795ab31
plan_head_after: e820957daf21a46e8859aa16d0c4295add1e2d96

tech-stack:
  added: []
  patterns:
    - "Hand-editable JSON from Discovery/Runs is parsed tolerantly; unparseable renders n/a, never 0"
    - "Public-log lines print counts, model ids and x-ratelimit-* values only, each matched against a safe pattern"
    - "Per-call figures cover only the runs that recorded tokens (unknown is not zero)"

key-files:
  created: []
  modified:
    - reporting.py
    - dashboard.py
    - pilot.py
    - tests/test_reporting.py
    - tests/test_pilot.py
    - SPEC.md
    - STATUS.md

key-decisions:
  - "No new decision record: the plan adds read-outs only (no settings, flags or Runs columns); D-50 and D-51 already cover what is measured"
  - "scored_by_model counts only evaluations that reached scoring (kept or score outcome); gate rejections never call Groq and would otherwise inflate 'not recorded'"
  - "A Discovery groq_budget record from an earlier UTC day shows today at 0 used (record_day kept), mirroring how eval_budget loads it"

patterns-established:
  - "Rate-limit header values reach the public log only when the model id and each x-ratelimit-* value match a strict allow pattern"

requirements-completed: [MEAS-02, MEAS-03]

coverage:
  - id: D1
    description: "Dashboard SYSTEM 'Groq' line: today's per-model use against budget, 7-day scored-by-model split, tokens per call with n, cached share, budget skips, evaluation cuts, poll cuts, alerts deferred; n/a when unknown"
    requirement: "MEAS-03"
    verification:
      - kind: unit
        ref: "tests/test_reporting.py#GroqSummaryTests.test_dashboard_groq_line_shows_budget_split_and_cuts"
        status: pass
      - kind: unit
        ref: "tests/test_reporting.py#GroqSummaryTests.test_groq_summary_reads_today_from_the_budget_record_and_7d_from_runs"
        status: pass
      - kind: unit
        ref: "tests/test_reporting.py#GroqSummaryTests.test_groq_summary_counts_scored_evaluations_by_model"
        status: pass
      - kind: unit
        ref: "tests/test_reporting.py#GroqSummaryTests.test_groq_summary_unknown_when_nothing_recorded"
        status: pass
    human_judgment: true
    rationale: "Offline tests assert the text and numbers; how the line reads in the real Sheet (width, wrapping) and its figures against real Runs are live checks in plan 02-07 / 02-08"
  - id: D2
    description: "Pilot limits audit prints Groq tokens per scoring call with n, tokens per UTC day per model, completions per day, cached share, governor counters, run duration p95 and the latest rate-limit header values; runs before the token columns are not counted as zero-token runs"
    requirement: "MEAS-02"
    verification:
      - kind: unit
        ref: "tests/test_pilot.py#DiagnosticsTests.test_limits_audit_groq_tokens_per_call_cached_share_and_cuts"
        status: pass
      - kind: unit
        ref: "tests/test_pilot.py#DiagnosticsTests.test_limits_audit_groq_is_unknown_when_no_run_recorded_tokens"
        status: pass
      - kind: unit
        ref: "tests/test_pilot.py#DiagnosticsTests.test_the_report_audits_limits_from_measured_runs_only"
        status: pass
    human_judgment: false
  - id: D3
    description: "The public pilot-report log prints counts, model ids and x-ratelimit-* values only; a poisoned limits record (Authorization key, Bearer-like model id or value) never reaches it"
    requirement: "MEAS-02"
    verification:
      - kind: unit
        ref: "tests/test_pilot.py#DiagnosticsTests.test_limits_audit_groq_lines_print_counts_only"
        status: pass
    human_judgment: false
  - id: D4
    description: "STATUS.md Phase 2 section (D-49..D-52) states what was verified offline versus not verified live, the offline test count, mutation checks and migration notes; SPEC describes the new report and dashboard figures"
    requirement: "MEAS-02"
    verification: []
    human_judgment: true
    rationale: "Documentation accuracy against what was built and what remains unverified is a reading judgment"

duration: 12min
completed: 2026-10-26
status: complete
---

# Phase 2 Plan 06: Groq Visibility Summary

**Groq consumption is now readable two ways: a Groq SYSTEM line on the Dashboard (today's tokens per model against budget, the week's model split, tokens per call with n, cuts) and Groq lines in the read-only pilot report's limits audit, with STATUS.md consolidating what Phase 2 verified offline and what is still not verified live**

## Performance

- **Duration:** about 12 min
- **Completed:** 2026-10-26T18:21Z
- **Tasks:** 2 (one tracer, one TDD)
- **Files modified:** 7

## Accomplishments

- `reporting._groq` reads today's per-model use and budget from the Discovery `groq_budget` record (UTC day; a record from an earlier day counts as 0 used today), sums the 7-day Runs tokens, completions, cached share and governor counters, and splits scored evaluations by model from the ledger. Tokens per call covers only the runs that recorded tokens (`token_runs`), so rows from before the columns are never a zero-token run.
- The Dashboard SYSTEM section has a `Groq` line after Search credits; every unknown value prints `n/a`.
- The pilot limits audit gained the Groq token, per-day, cached-share, governor and duration-p95 figures and the latest recorded `x-ratelimit-*` values, so MEAS-02's measured tokens per call can be read from the public read-only workflow log without credentials. Only `x-ratelimit-*` keys, model ids matching `[A-Za-z0-9._/-]{1,60}` and values matching `[A-Za-z0-9._:+-]{1,40}` can be printed.
- STATUS.md has the `## Phase 2 governors and measurement (D-49..D-52; plans 02-02..02-06)` section and the 2026-10-25 daily-check target line; SPEC.md lists the new Runs columns, the Groq figures and the SYSTEM line.

## Task Commits

1. **Task 1: Tracer, Groq usage from Runs, the budget record and the ledger to a Dashboard line** - `5580a70` (feat)
2. **Task 2: Groq figures in the pilot limits audit** - RED `6652bdf` (test), GREEN `5ba5b02` (feat), docs `e820957` (docs: SPEC and STATUS)

**Plan metadata:** recorded in the `docs(02-06)` commits that follow this file.

## TDD Gate Compliance

Task 2 (`tdd="true"`): RED `6652bdf` precedes GREEN `5ba5b02`; no REFACTOR commit was needed. Task 1 is a tracer (tests and implementation in one commit, as the plan specifies). The plan itself is `type: execute`.

**RED evidence (Task 2).** `NO_COLOR=1 .venv/bin/python -m unittest tests.test_pilot -q`: 34 tests, 3 new, all 3 failing: `KeyError: 'groq_tokens_primary'` and `KeyError: 'groq_token_runs'` (limits keys absent) and an `AssertionError` on the missing needle `tokens per scoring call 2000` in the printed report. `gsd check tdd-red-evidence` on the target `test_limits_audit_groq_tokens_per_call_cached_share_and_cuts` returned `RED_EVIDENCE_OK` / `target_test_failed`. Semantic assessment: each failing test ran and failed on the planned missing behaviour, not on syntax, import, fixture or collection faults. The existing `test_the_report_audits_limits_from_measured_runs_only` passed unchanged throughout.

## Mutation checks (each applied, observed failing, reverted; `__pycache__` cleared before each run)

- Task 1: counting completions of runs without recorded tokens in `tokens_per_completion` fails `test_groq_summary_reads_today_from_the_budget_record_and_7d_from_runs`.
- Task 2: treating every timed run as a token run fails `test_limits_audit_groq_tokens_per_call_cached_share_and_cuts` and `test_limits_audit_groq_is_unknown_when_no_run_recorded_tokens`.
- Task 2: removing the `x-ratelimit-` prefix filter fails `test_limits_audit_groq_lines_print_counts_only`. (First attempt survived because the poisoned value was also rejected by the value pattern; the test poison was strengthened to a value that passes the pattern and the mutation then failed as required.)

## Files Created/Modified

- `reporting.py` - `JobFacts.eval_model`, `_count`, `_budget_today`, `_groq`, `summary["groq"]`, `eval_budget` import (key and day helper only)
- `dashboard.py` - `_groq_text` and the `Groq` SYSTEM line
- `pilot.py` - limits keys, `_p95`, `_groq_limits_latest` with the allow patterns, four limits-audit lines
- `tests/test_reporting.py` - `GroqSummaryTests` (5 tests: the four planned plus the earlier-UTC-day record)
- `tests/test_pilot.py` - three Groq limits-audit tests
- `SPEC.md` - pilot limits-audit columns and Groq figures, SYSTEM line list
- `STATUS.md` - Phase 2 section, last-updated line, target-status line

## Decisions Made

- No DECISIONS entry: the plan adds read-outs only; D-50 / D-51 already define what is measured. Choices taken inside the plan are listed in the frontmatter `key-decisions`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Interpretation] `groq_budget` shape**
- **Found during:** Task 1
- **Issue:** the plan's action text describes the parsed record as `{"day", "models": {...}}`, while the plan's interfaces and `eval_budget.GroqBudget.to_json` persist `{"day","used","exhausted","budgets"}`.
- **Fix:** the persisted shape is parsed; `summary["groq"]["today"]` has the `{"day", "record_day", "models": {model: {"used","budget","exhausted"}}}` shape the action describes.
- **Files modified:** reporting.py
- **Committed in:** `5580a70`

**2. [Rule 1 - Bug avoided] scored_by_model counts only evaluations that reached scoring**
- **Found during:** Task 1
- **Issue:** "with a score" would count gate rejections (closed postings carry score 0 and no model), inflating `not recorded` with jobs that never called Groq.
- **Fix:** count evaluations whose outcome is `kept` or `score`.
- **Files modified:** reporting.py, tests/test_reporting.py (a gate-rejection and an out-of-window evaluation are in the test)
- **Committed in:** `5580a70`

**3. [Rule 2 - Missing critical] Public log allow-patterns and a stricter poison test**
- **Found during:** Task 2
- **Issue:** the plan prints stored header values; a hand-edited or damaged `Groq_Limits` could carry other keys or text into a public log (T-02-16).
- **Fix:** only `x-ratelimit-*` keys, model ids matching a safe pattern and values matching a safe pattern are printed; the RED test's poison data was strengthened in the GREEN commit (a poisoned key, model id and value).
- **Files modified:** pilot.py, tests/test_pilot.py
- **Committed in:** `5ba5b02`

**4. [Extension] Test data**
- The Dashboard 7-day test adds a run with completions but no tokens (answers without a usage figure) so the mutation "count untokened runs" is detectable, and an extra test covers a budget record from an earlier UTC day.

---

**Total deviations:** 4 (1 interpretation, 1 bug avoided, 1 missing critical, 1 test extension)
**Impact on plan:** small and within the plan's intent; no scope creep, no setting, flag or Runs column added.

## Issues Encountered

None. A BSD `sed -i` call failed in this shell (the file was left unchanged); the edit was redone with Python.

## Authentication Gates

None.

## Known Stubs

None. Unknown values are the intended `n/a` text or `None`, never 0.

## Threat Flags

None. No new endpoint, auth path or schema change; T-02-16 (public log) and T-02-17 (malformed JSON) are mitigated and tested.

## User Setup Required

None - no external service configuration required.

## Verification scope (mocked versus live)

Everything here is offline and mocked: hand-built Runs, Discovery and ledger records and the fake spreadsheet. Nothing was rendered in a real Sheet and no real Groq, Sheets or Telegram call was made. The Groq line's look in the real Sheet, real Runs rows with the new columns and the measured tokens per call (MEAS-02) are live checks in plan 02-07 / 02-08 (AGENTS rule 5). `MEAS-02` and `MEAS-03` are listed as this plan's requirements; the shared-ID gate may keep them open until the later plans that also declare them finish.

## Next Phase Readiness

- Ready for plan 02-07 (live render, `BAND_LINES_STACK`, the two missing tracker rows) and 02-08 (live Groq measurement via the pilot report's new lines).
- Full suite: 620 tests pass offline (`.venv/bin/python -m unittest discover -s tests`).
- Deferred item carried from 02-04 stays in `deferred-items.md` (`TokenBudget.wait` empty-window `IndexError`, pre-existing).

## Self-Check: PASSED

`reporting.py`, `dashboard.py`, `pilot.py`, `tests/test_reporting.py`, `tests/test_pilot.py`, `SPEC.md` and `STATUS.md` exist; commits `5580a70`, `6652bdf`, `5ba5b02` and `e820957` are ancestors of HEAD; `def _groq` appears once in reporting.py and `line("Groq"` once in dashboard.py; `groq_tokens_per_completion` and `duration_p95_s` appear in both `build_report` and `_limits_lines`; STATUS.md contains `## Phase 2 governors and measurement (D-49..D-52`, a `**mocked**` table row, `620 tests` matching the actual `Ran 620 tests` output, and `stays conditional on the Groq plan decision`; SPEC.md contains `tokens per scoring call`; RED (`test(02-06)`) and GREEN (`feat(02-06)`) commits exist for Task 2; `git rev-list --count 750f41b..HEAD` is 4; the full suite passes offline; no file deletions in any commit.

---
*Phase: 02-measurement-governors-and-owner-decisions*
*Completed: 2026-10-26*
