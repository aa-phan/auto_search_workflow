---
phase: 02-measurement-governors-and-owner-decisions
plan: 03
subsystem: scoring-governor
tags: [groq, token-budget, rate-limits, discovery-state, runs-columns, decisions]

requires:
  - phase: 02-measurement-governors-and-owner-decisions
    provides: D-48 owner-decision list (decision 2, budget-driven fallback, points at D-50); D-49 and the Harness alert helpers from plan 02-02
provides:
  - "eval_budget.GroqBudget: pure per-model UTC-day token budget with a 20% verified-fresh reserve, exhaust flag and JSON round trip (Discovery key groq_budget)"
  - "run_cycle pre-checks Deps.can_score before hydration, persists the budget at each flush and in finally, and treats a budget skip or a 'deferred' outcome as nothing recorded and no attempt"
  - "Seven new Runs columns: Groq_Tokens_Primary, Groq_Tokens_Fallback, Groq_Prompt_Tokens, Groq_Cached_Tokens, Groq_Completions, Groq_Limits, Eval_Budget_Skipped"
  - "hunter.GroqClient spends the budget per model (primary then fallback), raises GroqDeferred when both are spent, meters usage and x-ratelimit-* response headers, and treats a daily-limit 429 as model spent without sleeping"
  - "Settings rows Groq_Daily_Token_Budget (170000, provisional) and Groq_Fallback_Daily_Token_Budget (blank = same); Runs.Notes names the effective budget and its source every run"
  - "SPEC (Filtering order, State model, Observability), DECISIONS D-50 and README Settings table"
affects: [02-04, 02-07, 02-08, phase-04, reporting, dashboard]

actuals:
  tokens: 15800
  tasks: 3
  commits: 5
plan_head_before: d7ac7ec25a16871de4a4ec936de65dff0f170d49
plan_head_after: d0e97fe85d9f5a275147bf98591ca96a23a13e45

tech-stack:
  added: []
  patterns:
    - "Shared pure budget object: restored in place at run start, charged by the client, saved by the pipeline (same shape as search.SearchBudget)"
    - "A budget skip is a pre-check before any work (no hydration, no event, no attempt); mid-call exhaustion is a 'deferred' outcome handled identically"
    - "Whole-Discovery-dict saves only: save_budget never runs before the tab was loaded and the saved dict is rebound after the Rule-1 save so cursors and queues are not lost"
    - "Untrusted usage, header and persisted-JSON values go through _int / tolerant load and never raise"

key-files:
  created:
    - eval_budget.py
    - tests/test_governors.py
  modified:
    - pipeline.py
    - state.py
    - hunter.py
    - tests/test_hunter.py
    - tests/test_reporting.py
    - SPEC.md
    - DECISIONS.md
    - README.md

key-decisions:
  - "D-50: per-model UTC-day Groq token budget (default 170000 = 85% of the public 200,000 tokens/day figure, provisional until MEAS-02), last 20% for verified-fresh jobs, budget-driven fallback accepted by the owner as the D-16 OK"
  - "Counting basis is usage.total_tokens charged to the answering model; a missing usage or a 400 json_validate_failed answer charges the pre-call estimate (over-counting is the safe direction); cached tokens are recorded separately"
  - "A budget skip leaves the run ok (P2-07): degraded_reason is unchanged; the note 'groq daily budget reached: N jobs wait (no attempt used)' and Eval_Budget_Skipped carry the signal"
  - "The --url and --delivery-test paths stay unbudgeted and persist nothing; the 15% headroom covers them (T-02-07)"

requirements-completed: [MEAS-03]

coverage:
  - id: D1
    description: "A persisted per-model daily budget gates evaluation end to end: with a budget of 0 every pending job stays pending with no events and no attempts, the next UTC day scores it, and usage survives between runs in the Discovery tab next to the rotation cursor"
    requirement: MEAS-03
    verification:
      - kind: unit
        ref: "tests/test_governors.py#ForcedLimitTests (budget_zero_leaves_job_pending, next_utc_day_scores, usage_persists_across_runs_in_discovery_tab, deferred_outcome_records_nothing, crash_before_load_writes_no_discovery_state)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Budget arithmetic: boundary at cap-1/cap/cap+1, 80% non-fresh cap with integer floor, UTC-midnight rollover, tolerant load of blank/invalid/foreign JSON, zero never spends, deterministic model order"
    requirement: MEAS-03
    verification:
      - kind: unit
        ref: "tests/test_governors.py#BudgetTests"
        status: pass
    human_judgment: false
  - id: D3
    description: "Every run records the Groq tokens it used (per model, prompt, cached, completions, limits headers, budget skips) in seven new Runs columns; old rows load with zeros"
    requirement: MEAS-03
    verification:
      - kind: unit
        ref: "tests/test_governors.py#ForcedLimitTests.test_runs_budget_columns_round_trip_and_old_rows_load"
        status: pass
      - kind: unit
        ref: "tests/test_governors.py#ForcedLimitTests.test_run_row_records_the_tokens_the_run_used"
        status: pass
    human_judgment: false
  - id: D4
    description: "GroqClient spends each model's budget (fallback when the primary is spent, GroqDeferred when both are), charges usage to the answering model, treats a daily-limit 429 as model spent without sleeping, keeps only x-ratelimit-* response headers, and the evaluator maps a deferral to a deferred outcome and records the scoring model"
    requirement: MEAS-03
    verification:
      - kind: unit
        ref: "tests/test_hunter.py#GroqBudgetTests (15 tests)"
        status: pass
    human_judgment: false
  - id: D5
    description: "Settings rows parse (default 170000, blank fallback = same, negative clamps to 0, float string truncates) and main wires one shared budget into the client and the pipeline with the source note in Runs.Notes"
    requirement: MEAS-03
    verification:
      - kind: unit
        ref: "tests/test_hunter.py#GroqSettingsTests (4 tests)"
        status: pass
    human_judgment: false
  - id: D6
    description: "SPEC Filtering order / State model / Observability, DECISIONS D-50 and the README Settings table describe the budget, its provisional default and its source, and what is not changed"
    requirement: MEAS-03
    verification: []
    human_judgment: true
    rationale: "Document wording and the owner-facing provisional-default flag need the owner's reading; greps only prove the text exists"
  - id: D7
    description: "Real Groq limits and token use under the budget (live behaviour of the 170000 default, the UTC reset assumption, the unrecorded x-ratelimit values)"
    requirement: MEAS-03
    verification: []
    human_judgment: true
    rationale: "Mocked only: no live Groq call was made (AGENTS rule 5); the live figures come from production Runs rows in plans 02-07 and 02-08"

duration: 7min
completed: 2026-10-26
status: complete
---

# Phase 2 Plan 03: Groq daily token governor Summary

**A persisted per-model daily Groq token budget (170000 by default, provisional) now stops scoring before Groq's limit, keeps the last 20% for verified-fresh jobs, falls back from the primary to the second model when the primary is spent, leaves budget-skipped jobs pending with nothing recorded, and every run records the tokens, cached tokens, completions and rate-limit headers it saw in seven new Runs columns.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-10-26T17:51:23Z
- **Completed:** 2026-10-26T17:59:00Z
- **Tasks:** 3 (one tracer, two TDD)
- **Files modified:** 10 (2 created, 8 modified)

## Accomplishments

- **Tracer (Task 1).** `eval_budget.GroqBudget` (pure) is restored from the Discovery tab at run start, checked per job through `Deps.can_score` before hydration, charged by the client, and saved at every flush and in `finally`. A forced zero budget leaves the job pending with no event and no attempt, the run stays `ok` with the note "groq daily budget reached: 1 jobs wait (no attempt used)", and the next UTC day scores it. The saved Discovery dict is rebound after the Rule-1 save so a budget save never drops the rotation cursor, pending queue or rebalance keys; `save_budget` does nothing before the tab was loaded or in a dry run, and a failed save only adds a note.
- **Groq client (Task 2).** `GroqClient` picks the model with `GroqBudget.pick_model(order(), fresh=...)` on every attempt, raises `GroqDeferred` (not a `TransientError`) when both models are spent, charges `usage.total_tokens` to the model that answered (estimate when usage is missing or unusable, and for a 400 `json_validate_failed` answer), meters primary/fallback tokens, prompt tokens, cached tokens and completions, and keeps the six `x-ratelimit-*` response headers per model (40 characters each, at most 1,000 characters in total, request headers never read). A 429 with `retry-after` above 60 seconds or a body naming per day/TPD/RPD marks the model spent with no sleep. The evaluator passes `fresh=` (verified-fresh jobs may use the reserve), maps `GroqDeferred` to `EvalOutcome("deferred")` before the transient and generic handlers, and records `model` in the payload of scored evaluations.
- **Settings, wiring and documents (Task 3).** `Groq_Daily_Token_Budget` (170000) and `Groq_Fallback_Daily_Token_Budget` (blank = same) with descriptions saying what they limit and where the figure came from; `main` builds one shared `GroqBudget`, attaches it to the client and the pipeline, and `Runs.Notes` states the budget and its source (Settings tab, environment or default) every run. SPEC, DECISIONS D-50 and the README Settings table updated.

## Task Commits

1. **Task 1: Tracer, persisted daily budget gates evaluation end to end** - `c60f0e8` (feat; tracer: test and code together, as a tracer is production code)
2. **Task 2: GroqClient spends the daily budget per model** - RED `c0be180` (test), GREEN `7512d9d` (feat)
3. **Task 3: Settings rows, main wiring, SPEC and D-50** - RED `a4037ce` (test), GREEN `d0e97fe` (feat)

**Plan metadata:** recorded in the `docs(02-03): complete` commit that follows this file.

## TDD Gate Compliance

RED and GREEN gate commits are present for both TDD tasks (test commits precede their feat commits); no REFACTOR commit was needed.

**RED, Task 2 (`c0be180`).** Command `NO_COLOR=1 .venv/bin/python -m unittest tests.test_hunter.GroqBudgetTests`, exit 1, 15 tests, 15 failing. `gsd check tdd-red-evidence` returned `RED_EVIDENCE_OK` (`target_test_failed`, target `test_daily_limit_429_by_retry_after_marks_model_spent_without_sleeping`). Semantic assessment: the target ran and failed because the planned interface did not exist yet (`TypeError: GroqClient.__init__() got an unexpected keyword argument 'budget'` in 15 tests, `AttributeError` for `GroqDeferred` and `daily`, `TypeError` for `Evaluation(model=...)`), not a syntax, import, collection or fixture fault; the planned assertions (model marked spent, no sleep, fallback used) were never reached, which is the expected RED for a new constructor parameter.

**RED, Task 3 (`a4037ce`).** Command `NO_COLOR=1 .venv/bin/python -m unittest tests.test_hunter.GroqSettingsTests`, exit 1, 4 tests, 4 failing; `RED_EVIDENCE_OK` for the target `test_main_runs_with_a_per_model_budget_wired_into_client_and_pipeline`, which failed on its planned assertion (`AssertionError: unexpectedly None`: `deps.groq_budget` was None). The other three failed on missing `Settings.groq_daily_token_budget`, missing `groq_budget_note` and a `KeyError` for the new default row, i.e. the planned interface did not exist yet.

## Mutation checks (each applied, observed failing, then reverted)

| Mutation | Result |
| --- | --- |
| Drop the reserve term from `GroqBudget.cap` (Task 1) | 4 failed: floor/reserve test, pick-model order, 80% reserve test, forced-limit reserve test |
| `<=` instead of `<` in `can_spend` (Task 1) | 6 failed: boundary test, zero-never-spends, forced-limit zero and next-day tests, and others |
| Remove the `can_score` pre-check (Task 1) | 3 failed: forced-limit zero, next-day and reserve tests |
| Remove the `discovery_state = save_values` rebind (Task 1) | `test_forced_limit_usage_persists_across_runs_in_discovery_tab` failed (rotation cursor lost) |
| Sleep on a daily-limit 429 (Task 2) | `..._by_retry_after_..._without_sleeping` and `..._by_body_text_...` failed |
| Catch `GroqDeferred` after the generic handler (Task 2) | `test_evaluator_maps_deferral_to_deferred_outcome_without_failure` failed |
| Charge the fallback model's tokens to the primary (Task 2) | `test_charges_usage_tokens_to_the_answering_model_and_meters_cached` failed |

## Files Created/Modified

- `eval_budget.py` - pure `GroqBudget` (`load`, `restore`, `cap`, `can_spend`, `pick_model`, `charge`, `exhaust`, `to_json`, `summary`), `GROQ_BUDGET_KEY`, `FRESH_RESERVE_PCT`, `day_of`
- `pipeline.py` - `Deps.groq_budget/can_score/groq_limits`, `save_budget`, stage-3 pre-check, `deferred` outcome, token metering into the run record, `discovery_state` rebind
- `state.py` - seven Runs columns and `RunRecord` fields appended after `Code_Version`; positional reader extended
- `hunter.py` - `GroqDeferred`, `Evaluation.model`, `GroqClient` budget integration (`order`, `_model`, `_spend`, `_learn_limits`, `limits_json`, daily-limit 429), `_int`, `_is_daily_limit`, evaluator deferral and model, Settings rows and fields, `groq_budget_note`, `main` wiring
- `tests/test_governors.py` - `BudgetTests` (10) and `ForcedLimitTests` (11)
- `tests/test_hunter.py` - `GroqBudgetTests` (15) and `GroqSettingsTests` (4)
- `tests/test_reporting.py` - `_Groq.evaluate` accepts `**kw`
- `SPEC.md`, `DECISIONS.md` (D-50), `README.md` - contract and user documentation

## Decisions Made

- D-50 recorded as planned (see key-decisions above).
- **For the owner:** the 170000 default is provisional (85% of Groq's public 200,000 tokens/day figure) until this account's limits page is read (MEAS-02). The live Settings tab is never widened automatically, so on the existing Sheet the default applies until the two rows are added; `Runs.Notes` says so every run.
- A budget of exactly `Groq_Daily_Token_Budget = 0` stops all scoring by design.

## Deviations from Plan

### Auto-fixed Issues

None to code. Small documented differences:

**1. [Interpretation] `eval_budget.py` does not import `freshness`**
- **Found during:** Task 1
- **Issue:** the plan lists `freshness as fr` among the imports, but nothing in the pure budget needs it (callers pass `fresh=` as a boolean), so the import would be unused.
- **Fix:** imports are `json`, `dataclasses` and `datetime` only.

**2. [Rule 2 - hardening] Extra tests and guards beyond the plan's list**
- **Found during:** Tasks 1 and 2
- **Issue:** the plan's behavior list did not cover a dry run, a failed budget save, a callback failure, a per-minute 429 that must not mark the day spent, a model spent during the call, bounded `limits_json`, or the `main` wiring.
- **Fix:** added `test_forced_limit_dry_run_never_saves_the_budget`, `..._failed_budget_save_never_stops_the_run`, `..._reserve_leaves_the_last_share_to_fresh_jobs`, `test_run_row_records_the_tokens_the_run_used`, `test_groq_limits_callback_failure_leaves_the_column_blank`, `test_a_per_minute_429_is_not_a_daily_limit`, `test_a_model_spent_during_the_call_is_not_retried`, `test_limits_json_is_bounded_and_empty_without_answers`, `test_main_runs_with_a_per_model_budget_wired_into_client_and_pipeline` and a Settings-rows test. GroqBudgetTests has 15 tests instead of twelve.
- **Files modified:** tests/test_governors.py, tests/test_hunter.py

**3. [Documentation] README Settings table**
- **Found during:** Task 3
- **Issue:** README lists every Settings row for the user; the two new rows would be undocumented there.
- **Fix:** two table rows and one sentence about older Sheets. Not in the plan's file list.
- **Files modified:** README.md
- **Committed in:** d0e97fe

**4. [Small robustness choice] `_int` treats booleans and negatives as unusable; a reported total of 0 charges the estimate**
- **Found during:** Task 2
- **Fix:** `_int(True, d)` and negative numbers return the default; `_int(total) or est`. Over-counting is the safe direction.

---

**Total deviations:** 0 code deviations; 4 small documentation, test and robustness additions.
**Impact on plan:** none on behavior or scope. The Groq prompt, scoring rule, `Min_Alert_Score`, the tracker threshold and `MAX_JOBS_PER_RUN` are untouched (AGENTS rule 7).

## Issues Encountered

- None blocking. `__pycache__` was cleared after the mutation runs before the full suite was re-run, as instructed. The suite grew from 533 to 573 tests; all pass.

## Known Stubs

None.

## Threat Flags

None. T-02-08 (untrusted usage, header and persisted JSON), T-02-09 (daily-limit 429 loop) and T-02-10 (only `x-ratelimit-*` response headers stored, the API key never appears in `limits_json`) are mitigated and tested; T-02-07 (`--url` / `--delivery-test` unbudgeted) is the accepted risk recorded in D-50.

## Verification Evidence (mocked vs live)

- `.venv/bin/python -m unittest tests.test_governors -q` (21 tests), `tests.test_governors -k forced -q` (8 tests) and `tests.test_hunter -k Groq -q` (27 tests) pass.
- `.venv/bin/python -m unittest discover -s tests`: 573 tests, OK, offline (533 before this plan).
- **Mocked only.** No live Groq, Sheets or Telegram call was made (AGENTS rule 5). Not verified live: the real reset time of Groq's daily limit (UTC day is a stand-in), the real `x-ratelimit-*` header values, whether the 170000 default sits below this account's actual daily token limit, and the Sheets round trip of the `groq_budget` row (CSV state only). Live figures come from production Runs rows in plans 02-07 and 02-08.

## User Setup Required

None - no external service configuration required. Optional: add the two `Groq_*` rows to the live Settings tab to change the budget; without them the default applies and Runs.Notes says so.

## Next Phase Readiness

- Ready for the next Phase 2 plan. The Groq part of ROADMAP criterion 3 (token recording and the forced-limit test) holds in offline tests, pending the production Runs rows.
- The 20-30 a day target remains conditional on the Groq plan decision (MEAS-02, D-53); the budget makes the limit visible and stops evaluation before it.

## Self-Check: PASSED

`eval_budget.py`, `tests/test_governors.py` and the eight modified files exist; commits `c60f0e8`, `c0be180`, `7512d9d`, `a4037ce` and `d0e97fe` are ancestors of HEAD; `class GroqDeferred`, `def limits_json` and `except GroqDeferred` (line before `except TransientError` in `make_evaluator`) are present; `grep "discovery_state = save_values" pipeline.py` prints one line; RED (`test(02-03)`) and GREEN (`feat(02-03)`) gate commits exist for both TDD tasks; `git rev-list --count d7ac7ec..HEAD` is 5.

---
*Phase: 02-measurement-governors-and-owner-decisions*
*Completed: 2026-10-26*
