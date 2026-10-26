---
phase: 02-measurement-governors-and-owner-decisions
plan: 02
subsystem: delivery
tags: [alerts, telegram, ledger, redaction, retry-semantics, decisions]

requires:
  - phase: 02-measurement-governors-and-owner-decisions
    provides: D-48 owner-decision list (decision 10 points at D-49)
provides:
  - "`alerted` is written only when send_alert returned True; no accepting channel leaves the job alert-pending and the run degraded"
  - "pipeline.classify_alert_failure: HTTP 5xx/429 transient, everything else bounded at 5 attempts (owner decision P2-18)"
  - "pipeline.redact and Deps.secrets: bot token, chat id and webhook URL never reach the ledger, notes or log"
  - "hunter.ALERT_FIELD_CHARS and _cap: Telegram free text capped before escaping, joined HTML no longer sliced"
  - "SPEC State model and DECISIONS D-49 (plus D-07/D-21 amendment notes) describing the policy and its accepted risk"
affects: [02-07, 02-08, phase-03, reporting, dashboard]

actuals:
  tokens: 9000
  tasks: 3
  commits: 6
plan_head_before: b30a691f2c5980a9bc55f1ece5d72a6ccdc4a8b2
plan_head_after: 2736b527df902a9f3114040570dcaea078891527

tech-stack:
  added: []
  patterns:
    - "Alert stage records an event only on confirmed acceptance; a missing channel is configuration and uses no attempt"
    - "Every string that can embed a secret goes through pipeline.redact before the ledger, Runs.Notes or the log"
    - "Free text is capped before html.escape so a message is never cut inside markup"

key-files:
  created: []
  modified:
    - pipeline.py
    - hunter.py
    - tests/test_core.py
    - tests/test_hunter.py
    - .github/workflows/job_hunter.yml
    - SPEC.md
    - DECISIONS.md
    - .planning/INGEST-CONFLICTS.md

key-decisions:
  - "D-49: an alert is recorded only when a channel accepted it; alert sends without an HTTP response are bounded at 5 (owner decision P2-18, amends D-07 and D-21 for the alert stage)"
  - "A missing channel uses no attempt and writes no event: it is configuration, not a send failure (AGENTS rule 4), but it degrades the run"
  - "Recorded exception to AGENTS rule 4 for the alert stage only; AGENTS.md itself is not edited"

requirements-completed: [MEAS-05]

coverage:
  - id: D1
    description: "A run where no channel accepts the message records no alerted event, uses no attempt, counts Alerts_Failed, degrades the run with the no-channel note, and the next working run delivers once"
    requirement: MEAS-05
    verification:
      - kind: unit
        ref: "tests/test_core.py#AlertRecordingTests.test_alert_not_accepted_by_any_channel_is_not_recorded_alerted"
        status: pass
    human_judgment: false
  - id: D2
    description: "Alert sends that fail without an HTTP response are bounded at 5 attempts then abandoned; 4 failures then success delivers once; HTTP 5xx and 429 stay transient; rejected 4xx stay bounded"
    requirement: MEAS-05
    verification:
      - kind: unit
        ref: "tests/test_core.py#AlertRecordingTests (bounded_at_five_attempts, four_failures_then_success, http_5xx_and_429, rejected_alert_requests_are_bounded)"
        status: pass
    human_judgment: false
  - id: D3
    description: "The bot token, chat id and webhook URL never appear in the stored error detail, Runs.Notes or log records; empty exception text is recorded as the exception type"
    requirement: MEAS-05
    verification:
      - kind: unit
        ref: "tests/test_core.py#AlertRecordingTests.test_alert_failure_text_never_contains_the_bot_token"
        status: pass
      - kind: unit
        ref: "tests/test_core.py#AlertRecordingTests.test_alert_failure_with_empty_message_records_the_exception_type"
        status: pass
    human_judgment: false
  - id: D4
    description: "Telegram message text never cuts a tag or entity and fits 4,096 UTF-16 code units"
    requirement: MEAS-05
    verification:
      - kind: unit
        ref: "tests/test_hunter.py#AlertTests.test_alert_message_caps_free_text_before_escaping_and_keeps_tags_whole"
        status: pass
      - kind: unit
        ref: "tests/test_hunter.py#AlertTests.test_alert_message_fits_telegram_limit_in_utf16_units"
        status: pass
    human_judgment: false
  - id: D5
    description: "SPEC State model and DECISIONS D-49 describe the policy, the accepted 5-run outage risk and the AGENTS rule 4 exception"
    requirement: MEAS-05
    verification: []
    human_judgment: true
    rationale: "Document wording and the owner-facing flag of the AGENTS rule 4 exception need the owner's reading; greps only prove the text exists"

duration: 7min
completed: 2026-10-26
status: complete
---

# Phase 2 Plan 02: Alert recording and bounded alert failures Summary

**`alerted` now means a channel accepted the message: no accepting channel leaves the job alert-pending and the run degraded, alert sends without an HTTP response stop after 5 attempts (owner decision P2-18), secrets are redacted from everything stored or logged, and Telegram free text is capped before escaping.**

## Performance

- **Duration:** about 7 min (start time was not captured at spawn; estimated from the previous plan's end, 17:42Z, to 17:49Z)
- **Started:** about 2026-10-26T17:42:00Z
- **Completed:** 2026-10-26T17:49:00Z
- **Tasks:** 3
- **Files modified:** 8

## Accomplishments

- **Tracer (Task 1).** Stage 4 of `run_cycle` writes `alerted` (channel `telegram`) only when `send_alert` returned True. With no accepting channel it writes no event, uses no attempt, counts `Runs.Alerts_Failed`, appends the note "no alert channel configured or accepted the message; " and the run is `degraded`. The next run with a working channel delivers exactly once. Legacy `channel: none` events still load as "recorded but not delivered" (no reporting edit).
- **Bounded no-response failures (Task 2).** `classify_alert_failure` keeps HTTP 5xx and 429 transient (no `error` event, no attempt, retried every run) and bounds everything else, including connection errors, timeouts, malformed rows and code errors: one `error` event with stage `alert` per run, `abandoned` at attempt 5, no send on run 6. Four failures then a working channel deliver once with no `abandoned` event.
- **Redaction (Task 2).** `redact` replaces each secret of 4+ characters with `***` and removes any remaining `bot<digits>:<token>` with `bot***`; `hunter.main` passes the Telegram token, chat id and webhook URL as `Deps.secrets`. An empty exception text is stored as the exception type name.
- **Telegram caps (Task 3).** `ALERT_FIELD_CHARS` and `_cap` limit title 200, company 150, location 200, verdict 400, gaps 600 and late 200 characters before `html.escape`; the joined HTML is no longer sliced to 4,096 characters, so no tag or entity can be cut and the visible text stays under 4,096 UTF-16 code units even for astral characters.
- **Documents (Task 3).** SPEC "State model" (Alerted bullet, transient/bounded sentence, at-least-once clause, accepted risk), DECISIONS D-49 with D-07 and D-21 amendment notes, and the INGEST-CONFLICTS warning marked resolved.

## Task Commits

1. **Task 1: Tracer, no channel accepted leaves the job alert-pending** - `1fb26a6` (fix)
2. **Task 2: Bound no-response alert failures at 5 and redact secrets** - RED `514fa89` (test), GREEN `54b3d42` (feat)
3. **Task 3: Telegram free text capped before escaping; SPEC and D-49** - RED `81cc617` (test), GREEN `6083833` (feat), documents `2736b52` (docs)

**Plan metadata:** recorded in the `docs(02-02): complete` commit that follows this file.

## TDD Gate Compliance

RED and GREEN gate commits are present for both TDD tasks (test commits precede their feat commits); no REFACTOR commit was needed. The tracer task (Task 1) was a single fix commit (test and code together), as a tracer is production code.

**RED, Task 2 (`514fa89`).** Command `NO_COLOR=1 .venv/bin/python -m unittest tests.test_core.AlertRecordingTests`, exit 1, 7 tests, 4 failing: the target `test_alert_without_http_response_is_bounded_at_five_attempts` (all four subTests), `..._four_failures_then_success_delivers_once_without_abandoning`, `..._with_empty_message_records_the_exception_type`, and `..._never_contains_the_bot_token`. `gsd check tdd-red-evidence` returned `RED_EVIDENCE_OK` (`target_test_failed`). Semantic assessment: the target ran and failed on its planned assertion (expected `error` events with attempts 1..5 and one `abandoned`, observed none because no-response failures were retried without bound). The bot-token test failed with `TypeError: Deps.__init__() got an unexpected keyword argument 'secrets'`, i.e. the planned interface did not exist yet, not a syntax or import fault. The 5xx/429 and 400 tests passed in RED, as expected, because that behaviour is unchanged.

**RED, Task 3 (`81cc617`).** Both new tests failed on their planned assertions: `'Apply here</a>' not found` (the 4,096-character slice cut the link off) and `8185 not less than or equal to 4096`. Both then passed in GREEN.

## Mutation checks (each applied, observed failing, then reverted)

| Mutation | Result |
| --- | --- |
| Write the `alerted` event even when `send_alert` returned False (Task 1) | `AlertRecordingTests` failed: `(0, 1, 'ok') != (1, 0, 'degraded')` |
| Classify no-response exceptions as transient (Task 2) | the bounded-at-five test (all 4 subTests), four-failures, empty-message, token and rejected-400 tests failed |
| Classify non-int status as transient (variant) | bounded and related tests failed |
| Skip `redact` | `test_alert_failure_text_never_contains_the_bot_token` failed |
| Treat 503 as bounded (`>= 600`) | `test_alert_http_5xx_and_429_stay_transient_and_use_no_attempt` failed (status=503) |

## Files Created/Modified

- `pipeline.py` - stage-4 rewrite, `classify_alert_failure`, `redact`, `Deps.secrets`, docstring rule 3
- `hunter.py` - `ALERT_FIELD_CHARS`, `_cap`, `send_alert` caps and no final slice, `secrets=` wiring in `main`
- `tests/test_core.py` - `Harness.alert_result` and `alert_calls`, `fresh_setup` moved into `HarnessCase`, `AlertRecordingTests`, renamed rejected-request test
- `tests/test_hunter.py` - two `AlertTests` for caps and UTF-16 limit
- `.github/workflows/job_hunter.yml` - comment only (Telegram requirement now says alerts wait and the run is degraded, D-49)
- `SPEC.md`, `DECISIONS.md`, `.planning/INGEST-CONFLICTS.md` - policy documents

## Decisions Made

- D-49 recorded as planned. The owner decision P2-18 (network errors) overrides the research default.
- **For the owner:** AGENTS.md rule 4 ("Do not turn transient errors into permanent records") now has a recorded, owner-approved exception for the alert stage only: a send that fails without an HTTP response can end `abandoned`. AGENTS.md was not edited; D-49 is the record. HTTP 5xx, 429 and a missing channel remain retryable. **Accepted risk:** an alert-channel outage lasting 5 runs abandons the alerts pending during it (about 5 hours at the intended hourly cadence, about 22 hours at GitHub's observed 4.4 h schedule); their tracker rows stay.
- A missing channel uses no attempt (CONTEXT discretion), so a deployment without Telegram never abandons alerts; it reports every run `degraded` instead.

## Deviations from Plan

### Auto-fixed Issues

None to code. Small documented differences:

**1. [Interpretation] Runs.Notes carries no alert failure text**
- **Found during:** Task 2 (token test)
- **Issue:** the plan's behavior line says the stored detail, `run.notes` and the log records "contain `***` and not the token". The plan's own truth says no `Runs.Notes` text written by the alert stage contains the secret, and the failure path writes no failure text to notes (only the idempotent no-channel note).
- **Fix:** the test asserts `***` in the stored `error` detail and in the log, and the absence of the token and chat id in all three (detail, notes, log). Notes simply contain neither.
- **Files modified:** tests/test_core.py

**2. [Rule 1 - consistency under AGENTS rule 1] Extra SPEC and D-07 sentences**
- **Found during:** Task 3
- **Issue:** SPEC's Telegram bullet and D-07 would otherwise contradict the change (message slicing, "alerts are at-least-once" without the D-49 caveat).
- **Fix:** one added sentence on the caps in the SPEC Telegram bullet and an amendment note on D-07, alongside the D-21 note the plan required.
- **Files modified:** SPEC.md, DECISIONS.md
- **Committed in:** 2736b52

**3. [Test helper] `tearDown_harness`** in `AlertRecordingTests` gives each subTest a fresh Harness and state directory (the plan asked for fresh Harness per subTest but named no helper).

---

**Total deviations:** 0 code deviations; 3 small documentation or test-structure additions.
**Impact on plan:** none on behavior or scope. No other test needed changing: the existing outage tests (`ConnectionError` recovering within fewer than 5 runs) pass unchanged, and no alerted / no-duplicate assertion was weakened.

## Issues Encountered

- **Stale bytecode after a mutation check.** A same-size mutation (`500` to `600`) restored within the same second left a stale `.pyc`, so the next full-suite run failed on the 503 test although the committed source was correct. Clearing `__pycache__` fixed it and the suite then passed (533 tests). The feat commit `6083833` was made before that full-suite run (the plan's verify chain ran filtered tests first); the committed source was verified green afterwards and nothing needed changing.
- The BSD `sed -i` form failed once for the first mutation; mutations were then applied with Python.

## Known Stubs

None.

## Threat Flags

None. T-02-03 (redaction), T-02-04 (alerted only on acceptance) and T-02-06 (escape after cap, no final slice) are mitigated and tested; T-02-05 (5-run outage abandons alerts) is the accepted risk recorded in D-49.

## Verification Evidence (mocked vs live)

- `.venv/bin/python -m unittest tests.test_core -k alert -q` (14 tests) and `tests.test_hunter -k alert_message -q` (2 tests) pass.
- `.venv/bin/python -m unittest discover -s tests`: 533 tests, OK, offline (baseline before the plan was 525).
- **Mocked only.** No live Telegram, Groq or Sheets call was made; the live check is the `delivery_test` in plan 02-07. One consequence not covered live: the real `requests` HTTPError text for a 400 embeds the request URL; redaction is tested with a synthetic exception text of the same shape.
- Note for the dashboard and reports: webhook-only deliveries are still labelled channel `telegram` (as before this plan), so reporting counts them as delivered; a webhook-only deployment is unchanged.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Ready for the next Phase 2 plan. The delivery contract now holds in offline tests (ROADMAP criterion 4), pending the live `delivery_test` in 02-07.
- Existing production `channel: none` alerted events (legacy) remain "recorded but not delivered"; no backfill was done.

## Self-Check: PASSED

All eight modified files exist; commits `1fb26a6`, `514fa89`, `54b3d42`, `81cc617`, `6083833` and `2736b52` are ancestors of HEAD; `classify_alert_failure`, `redact` and the `secrets=` wiring are present; RED (`test(02-02)`) and GREEN (`feat(02-02)`) gate commits exist.

---
*Phase: 02-measurement-governors-and-owner-decisions*
*Completed: 2026-10-26*
