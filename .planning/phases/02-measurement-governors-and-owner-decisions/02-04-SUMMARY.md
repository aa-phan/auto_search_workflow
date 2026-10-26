---
phase: 02-measurement-governors-and-owner-decisions
plan: 04
subsystem: run-deadlines
tags: [deadlines, poll-cutoff, eval-cutoff, alert-cutoff, groq-deadline, poll-order, runs-columns, decisions]

requires:
  - phase: 02-measurement-governors-and-owner-decisions
    provides: "GroqDeferred and the 'deferred' EvalOutcome (nothing recorded, no attempt) from plan 02-03; the stage-4 alert loop from plan 02-02"
provides:
  - "boards.poll_boards(deadline=...) and PollResult.skipped_deadline, a flag distinct from the 429 skipped"
  - "pipeline POLL_CUTOFF_S / EVAL_CUTOFF_S / ALERT_CUTOFF_S (15 / 20 / 22 min) measured from process start via Deps.clock and Deps.process_t0"
  - "Monitored boards polled longest-unpolled first (Last_Attempt_At ascending, blank first, key tiebreak)"
  - "Four Runs columns: Eval_Deadline_Skipped, Eval_Cut, Boards_Skipped_Deadline, Alerts_Deferred"
  - "Degraded reasons 'poll cutoff' and 'alert cutoff' from counters; an evaluation cut leaves the run ok"
  - "GroqClient.deadline, _check_deadline and TokenBudget.wait(deadline=): no Groq attempt, backoff sleep or token wait outlives the evaluation cutoff"
  - "hunter.main anchors PROCESS_T0 first; POLL_CUTOFF_MINUTES / EVAL_CUTOFF_MINUTES environment overrides"
  - "SPEC (Loops, State model, Operational dashboard, Observability) and DECISIONS D-51"
affects: [02-05, 02-07, 02-08, reporting, dashboard]

actuals:
  tokens: 16200
  tasks: 3
  commits: 5
plan_head_before: 5ee3300edda4f582876828d8ebd639f730690e60
plan_head_after: c7d0c58af148db5ca71245bc8bbe1c29349b6198

tech-stack:
  added: []
  patterns:
    - "Injectable monotonic clock (Deps.clock, FakeClock in tests) with every deadline derived once at the top of run_cycle from an absolute process anchor"
    - "A cut is a pre-check before the work (no event, no attempt, no state change): the same shape as the Groq budget skip"
    - "Degraded reasons come from counters, never from note substrings, so a deadline skip cannot be confused with the 429 backoff note"

key-files:
  created:
    - .planning/phases/02-measurement-governors-and-owner-decisions/deferred-items.md
  modified:
    - boards.py
    - pipeline.py
    - state.py
    - hunter.py
    - tests/test_governors.py
    - tests/test_hunter.py
    - SPEC.md
    - DECISIONS.md

key-decisions:
  - "D-51: three cutoffs from process start (poll 15, Groq 20, alerts 22 minutes) inside the 25-minute workflow timeout, longest-unpolled-first polling so a cut board goes first next run"
  - "Outcome rules P2-07: poll cut degraded, evaluation cut ok with a counter and note; alert cut degraded is a discretion choice made in this plan (a fresh alert waiting an hour deserves the owner's attention)"
  - "Cutoffs are environment knobs (POLL_CUTOFF_MINUTES, EVAL_CUTOFF_MINUTES), not Settings rows; the alert cutoff stays a pipeline constant"

requirements-completed: [MEAS-04]

coverage:
  - id: D1
    description: "A run that reaches the poll cutoff stops starting polls, leaves the remaining boards untouched (no failure count, no last_attempt_at, no baseline, no events) at the front of the next run's queue, counts them in Boards_Skipped_Deadline, and reports itself degraded with reason 'poll cutoff' and never the 429 backoff note"
    requirement: MEAS-04
    verification:
      - kind: unit
        ref: "tests/test_governors.py#PollCutoffTests (poll_boards_deadline_marks_rest_skipped_deadline_not_skipped, poll_cutoff_skipped_board_keeps_state_and_goes_first_next_run, outcome_poll_cutoff_makes_run_degraded, run_that_polled_every_board_before_the_cutoff_is_ok)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Boards are polled longest-unpolled first: blank last_attempt_at first, then ascending, ties by board key"
    requirement: MEAS-04
    verification:
      - kind: unit
        ref: "tests/test_governors.py#PollCutoffTests.test_poll_order_is_longest_unpolled_first_with_key_tiebreak"
        status: pass
    human_judgment: false
  - id: D3
    description: "Evaluation stops at the cutoff with nothing recorded against the cut jobs (run stays ok, Eval_Cut and Eval_Deadline_Skipped, note), verified-fresh jobs are scored first, a Groq deadline deferral is an evaluation cut and not a transient failure, and a late start (lease wait) cuts at process minute 20"
    requirement: MEAS-04
    verification:
      - kind: unit
        ref: "tests/test_governors.py#EvalCutoffTests (outcome_eval_cutoff_leaves_run_ok_with_counter_and_note, eval_cutoff_scores_verified_fresh_first, late_start_anchors_cutoffs_at_process_start, run_without_process_anchor_counts_from_its_own_start, outcome_groq_deadline_deferral_is_not_transient)"
        status: pass
    human_judgment: false
  - id: D4
    description: "Alerts still run after the evaluation cutoff; an alert past the alert cutoff stays pending with no event and no attempt (Alerts_Deferred, run degraded with reason 'alert cutoff') and is delivered once by the next run"
    requirement: MEAS-04
    verification:
      - kind: unit
        ref: "tests/test_governors.py#EvalCutoffTests (alert_cutoff_leaves_alert_pending_with_no_attempt, alerts_still_run_after_the_evaluation_cutoff)"
        status: pass
    human_judgment: false
  - id: D5
    description: "A Groq call cannot outlive the evaluation cutoff: no request after the deadline, the per-minute token wait, and the request-error, 429 and 5xx backoff sleeps all stop with GroqDeferred('deadline'); without a deadline behaviour is unchanged"
    requirement: MEAS-04
    verification:
      - kind: unit
        ref: "tests/test_hunter.py#GroqDeadlineTests (8 tests)"
        status: pass
    human_judgment: false
  - id: D6
    description: "The four Runs columns round-trip, old rows load with zeros, and main anchors PROCESS_T0 first, wires process_t0 / cutoffs / GroqClient.deadline, parses POLL_CUTOFF_MINUTES and EVAL_CUTOFF_MINUTES (default, override, non-numeric, clamp), and leaves --url unbounded"
    requirement: MEAS-04
    verification:
      - kind: unit
        ref: "tests/test_governors.py#ForcedLimitTests.test_runs_budget_columns_round_trip_and_old_rows_load; tests/test_hunter.py#ConfigDeadlineTests (3 tests)"
        status: pass
    human_judgment: false
  - id: D7
    description: "SPEC Loops / State model / Operational dashboard / Observability and DECISIONS D-51 describe the cutoffs, the order, the outcome split and the flagged unmeasured-setup assumption"
    requirement: MEAS-04
    verification: []
    human_judgment: true
    rationale: "Document wording, and the owner-facing discretion choice that an alert cut degrades the run, need the owner's reading; greps only prove the text exists"
  - id: D8
    description: "Real run durations against the 25-minute timeout and the real cut counters in production"
    requirement: MEAS-04
    verification: []
    human_judgment: true
    rationale: "Mocked only (fake clock): no live run was made (AGENTS rule 5); the live p95 of Duration_S and the Boards_Skipped_Deadline / Eval_Cut counters are read from production Runs rows in plan 02-07"

duration: 7min
completed: 2026-10-26
status: complete
---

# Phase 2 Plan 04: Run deadlines and longest-unpolled-first polling Summary

**Every run now stops starting board polls 15 minutes after the process started, Groq calls after 20 and alert sends after 22 (anchored before the writer-lease wait, inside the 25-minute workflow timeout), polls the longest-unpolled boards first so a cut board goes first next run, and a Groq client that raises `GroqDeferred("deadline")` instead of waiting or retrying past the cutoff; a poll or alert cut makes the run `degraded`, an evaluation cut leaves it `ok`, and nothing is recorded against a cut board, job or alert.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-10-26T18:00:50Z
- **Completed:** 2026-10-26T18:08:00Z
- **Tasks:** 3 (one tracer, two TDD)
- **Files modified:** 9 (1 created, 8 modified)

## Accomplishments

- **Tracer (Task 1).** `poll_boards(deadline=...)` returns `PollResult.skipped_deadline` (never the 429 `skipped`) for a board not started before the cutoff; the pipeline sorts active boards by `(last_attempt_at or "", key)`, skips such boards before `apply_poll_result` (record untouched, no events for its jobs), counts them in `Boards_Skipped_Deadline`, adds the note "poll cutoff after N min: M boards not polled this run (polled first next run)" and makes the run `degraded` (reason `poll cutoff`, from the counter). The four Runs columns and the `RunRecord` reader were added (old rows load with zeros), together with the `Deps.clock` / `process_t0` / three cutoff fields.
- **Evaluation and alert cutoffs (Task 2).** Stage 3 checks the evaluation deadline first in every iteration (`eval_cut`, `eval_deadline_skipped` = this job and the rest, break); a `deferred` outcome with message `deadline` is the same cut, any other message stays a budget skip. Stage 4 checks the alert deadline per alert: no send, no event, no attempt, `Alerts_Deferred`, run `degraded` (reason `alert cutoff`); alerts still run after the evaluation cutoff. `GroqClient.deadline`, `_check_deadline(upcoming_sleep)` before every attempt and before the request-error, fallback-429 and 5xx backoff sleeps, and `TokenBudget.wait(tokens, deadline=)` bound every wait.
- **Process anchor and configuration (Task 3).** `PROCESS_T0 = time.monotonic()` is the first statement of `main`; `groq.deadline = PROCESS_T0 + cfg.eval_cutoff_s` and `Deps(clock=time.monotonic, process_t0=PROCESS_T0, poll_cutoff_s=..., eval_cutoff_s=...)`; `Config.poll_cutoff_s` / `eval_cutoff_s` from `POLL_CUTOFF_MINUTES` / `EVAL_CUTOFF_MINUTES` (defaults 15 / 20, at least 1 minute, non-numeric falls back). `--url` and `--delivery-test` keep an unbounded client. SPEC (Loops, State model, Operational dashboard, Observability) and DECISIONS D-51 updated.

## Task Commits

1. **Task 1: Tracer, poll cutoff end to end** - `3721d98` (feat; tracer: test and code together)
2. **Task 2: Evaluation and alert cutoffs, Groq client deadline** - RED `786d675` (test), GREEN `346f817` (feat)
3. **Task 3: Process-start anchor, cutoff configuration, SPEC and D-51** - RED `b7bca31` (test), GREEN `c7d0c58` (feat)

**Plan metadata:** recorded in the `docs(02-04)` commits that follow this file.

## TDD Gate Compliance

RED and GREEN gate commits are present for both TDD tasks (each `test(02-04)` commit precedes its `feat(02-04)` commit); no REFACTOR commit was needed.

**RED, Task 2 (`786d675`).** Command `NO_COLOR=1 .venv/bin/python -m unittest tests.test_governors.EvalCutoffTests tests.test_hunter.GroqDeadlineTests`, exit 1, 15 tests, 11 failing, 4 passing (regression guards for unchanged behaviour). `gsd check tdd-red-evidence` returned `RED_EVIDENCE_OK` (`target_test_failed`, target `test_deadline_stops_429_backoff_sleep`). Semantic assessment: the target ran and failed on its planned assertion (`GroqDeferred not raised`: the client slept through the 30 s backoff past the deadline); the pipeline tests failed on their planned counters and flags (`eval_cut` False where True was planned, 2 evaluations where 1 was planned, 3 where 2). No syntax, import, collection or fixture fault: `GroqClient.deadline`, `Deps.eval_cutoff_s` and `RunRecord.eval_cut` already existed from the tracer or are plain attributes.

**RED, Task 3 (`b7bca31`).** Command `NO_COLOR=1 .venv/bin/python -m unittest tests.test_hunter.ConfigDeadlineTests`, exit 1, 3 tests, 2 failing, 1 passing (the `--url` guard). `RED_EVIDENCE_OK` for the target `test_deadline_main_anchors_process_start_and_wires_the_cutoffs`, which failed on its planned assertion (`None != 5000.0`: `deps.process_t0` was never set by `main`). The Config test failed with `AttributeError: 'Config' object has no attribute 'poll_cutoff_s'`, i.e. the planned interface did not exist yet.

## Mutation checks (each applied, observed failing, then reverted; `__pycache__` cleared after each)

| Mutation | Result |
| --- | --- |
| Reuse the 429 `skipped` flag and note for the deadline skip (Task 1) | 3 failed: degraded outcome test, `poll_boards` flag test, keeps-state test |
| Call `apply_poll_result` for a deadline-skipped board (Task 1) | `test_poll_cutoff_skipped_board_keeps_state_and_goes_first_next_run` failed |
| Remove the longest-unpolled sort (Task 1) | 2 failed: order test and keeps-state / first-next-run test |
| Anchor at `run_cycle` start instead of `process_t0` (Task 2) | `test_late_start_anchors_cutoffs_at_process_start` failed |
| Stop treating a `deadline` deferral as an evaluation cut (falls to the budget-skip branch; Task 2) | `test_outcome_groq_deadline_deferral_is_not_transient` failed |
| Remove the deadline check in `TokenBudget.wait` (Task 2) | `test_deadline_stops_token_wait_loop` failed (guarded by a sleep counter, so it fails instead of hanging) |
| Remove the alert cutoff check (Task 2) | `test_alert_cutoff_leaves_alert_pending_with_no_attempt` failed |

## Files Created/Modified

- `boards.py` - `PollResult.skipped_deadline`, `poll_boards(deadline=)`
- `pipeline.py` - cutoff constants, `Deps.clock/process_t0/*_cutoff_s`, poll order and cut handling, evaluation and alert cutoffs, `degraded_reason` counters
- `state.py` - four Runs columns, `RunRecord` fields and positional reader
- `hunter.py` - `TokenBudget.wait(deadline=)`, `GroqClient.deadline/_check_deadline`, `Config` cutoffs, `PROCESS_T0` and wiring in `main`
- `tests/test_governors.py` - `FakeClock`, `PollCutoffTests` (6), `EvalCutoffTests` (7), extended Runs round-trip test
- `tests/test_hunter.py` - `GroqDeadlineTests` (8), `ConfigDeadlineTests` (3)
- `SPEC.md`, `DECISIONS.md` (D-51) - contract and decision record
- `.planning/phases/02-measurement-governors-and-owner-decisions/deferred-items.md` - a pre-existing `TokenBudget.wait` defect found along the way

## Decisions Made

- D-51 recorded as planned (see key-decisions above).
- **For the owner:** an alert cut degrades the run (discretion choice, flagged in D-51 as not part of P2-07). Keep `EVAL_CUTOFF_MINUTES` below 22, otherwise alerts for jobs scored late are deferred to the next run.

## Deviations from Plan

### Auto-fixed Issues

None to code. Small documented differences:

**1. [Interpretation] A Groq `deadline` deferral counts every waiting job, not just 1**
- **Found during:** Task 2
- **Issue:** the plan says the `deadline` deferral adds 1 to `eval_deadline_skipped` and breaks; the loop then leaves the remaining jobs waiting too, so the counter and the note "M jobs wait for the next run" would under-report.
- **Fix:** both cut paths add this job and every later job in the batch (`len(batch) - (i - 1)`), matching the loop-top check. The planned test assertions (`eval_cut`, not transient, outcome ok, no event, loop stops) are unchanged.
- **Files modified:** pipeline.py

**2. [Rule 2 - hardening] Extra tests beyond the plan's list**
- **Found during:** Tasks 1 to 3
- **Fix:** added `test_poll_boards_without_deadline_polls_everything`, `test_run_that_polled_every_board_before_the_cutoff_is_ok`, `test_run_without_process_anchor_counts_from_its_own_start`, `test_alerts_still_run_after_the_evaluation_cutoff`, `test_token_budget_wait_without_deadline_waits_for_the_window`, `test_deadline_stops_5xx_backoff_sleep`, `test_deadline_stops_request_error_backoff_sleep`, `test_a_deadline_with_time_left_does_not_change_the_result`, `test_deadline_single_job_check_keeps_the_client_unbounded`, `test_deadline_main_anchors_process_start_and_wires_the_cutoffs`. The existing Runs round-trip test was updated for the four new columns (its `RUN_COLUMNS[-7:]` slice moved to `[-11:-4]`).
- **Files modified:** tests/test_governors.py, tests/test_hunter.py

---

**Total deviations:** 0 code deviations; 2 small interpretation and test additions.
**Impact on plan:** none on behavior or scope. The Groq prompt, scoring rule, `Min_Alert_Score` and `MAX_JOBS_PER_RUN` (30, P2-08) are untouched (AGENTS rule 7).

## Issues Encountered

- A latent defect in `TokenBudget.wait` (an `IndexError` when the window empties while one call's estimate alone exceeds 90% of the per-minute limit) surfaced while writing the token-wait test. It predates this plan and is outside MEAS-04, so it is logged in `deferred-items.md`, not fixed; the test uses a large per-minute limit to avoid it.
- The suite grew from 573 to 597 tests; all pass offline.

## Known Stubs

None.

## Threat Flags

None. T-02-11 (run exceeding the 25-minute timeout) is mitigated by the process-anchored cutoffs and the client deadline, tested with a fake clock including the late-start case; T-02-12 (board state after a cut) is mitigated by the distinct `skipped_deadline` flag and the keeps-state test.

## Verification Evidence (mocked vs live)

- `.venv/bin/python -m unittest tests.test_governors -k poll -q` (6 tests), `tests.test_governors -q` (34 tests) and `tests.test_hunter -k deadline -q` (11 tests) pass.
- `.venv/bin/python -m unittest discover -s tests`: 597 tests, OK, offline.
- **Mocked only.** A fake monotonic clock drove every cutoff; no live Groq, Sheets, ATS or Telegram call was made (AGENTS rule 5). Not verified live: real run durations against the 25-minute timeout (the observed maximum is 770 s), the unmeasured GitHub setup steps before process start (flagged in D-51), and the real cut counters. Those come from production Runs rows in plan 02-07.

## User Setup Required

None - no external service configuration required. Optional: set `POLL_CUTOFF_MINUTES` / `EVAL_CUTOFF_MINUTES` in the workflow environment to tune the cutoffs (defaults 15 and 20).

## Next Phase Readiness

- Ready for the next Phase 2 plan. ROADMAP criterion 3 (deadline part) holds in offline forced-limit tests, pending the production Runs rows read in plan 02-07.
- Watch item: `Duration_S` p95 against 24 minutes; lower `EVAL_CUTOFF_MINUTES` if it approaches that (GitHub setup time is not measured).

## Self-Check: PASSED

`boards.py`, `pipeline.py`, `state.py`, `hunter.py`, `tests/test_governors.py`, `tests/test_hunter.py`, `SPEC.md` and `DECISIONS.md` exist; commits `3721d98`, `786d675`, `346f817`, `b7bca31` and `c7d0c58` are ancestors of HEAD; `grep "deadline=poll_deadline" pipeline.py`, `def _check_deadline` and `deadline=self.deadline` in hunter.py, `PROCESS_T0 = time.monotonic()` as the first statement of `main`, `process_t0=PROCESS_T0` and `groq.deadline = PROCESS_T0` each print one line; `state.RUN_COLUMNS[-4:]` is the four new columns; RED (`test(02-04)`) and GREEN (`feat(02-04)`) gate commits exist for both TDD tasks; `git rev-list --count 5ee3300..HEAD` is 5; no unexpected file deletions.

---
*Phase: 02-measurement-governors-and-owner-decisions*
*Completed: 2026-10-26*
