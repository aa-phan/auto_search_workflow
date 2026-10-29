---
phase: 02-measurement-governors-and-owner-decisions
verified: 2026-10-28T23:55:00Z
status: passed
score: 5/5 must-haves verified
covered_files:
  - ".github/workflows/inventory.yml"
  - ".github/workflows/job_hunter.yml"
  - ".planning/phases/02-measurement-governors-and-owner-decisions/02-01-PLAN.md"
  - ".planning/phases/02-measurement-governors-and-owner-decisions/02-01-SUMMARY.md"
  - ".planning/phases/02-measurement-governors-and-owner-decisions/02-02-PLAN.md"
  - ".planning/phases/02-measurement-governors-and-owner-decisions/02-02-SUMMARY.md"
  - ".planning/phases/02-measurement-governors-and-owner-decisions/02-03-PLAN.md"
  - ".planning/phases/02-measurement-governors-and-owner-decisions/02-03-SUMMARY.md"
  - ".planning/phases/02-measurement-governors-and-owner-decisions/02-04-PLAN.md"
  - ".planning/phases/02-measurement-governors-and-owner-decisions/02-04-SUMMARY.md"
  - ".planning/phases/02-measurement-governors-and-owner-decisions/02-05-PLAN.md"
  - ".planning/phases/02-measurement-governors-and-owner-decisions/02-05-SUMMARY.md"
  - ".planning/phases/02-measurement-governors-and-owner-decisions/02-06-PLAN.md"
  - ".planning/phases/02-measurement-governors-and-owner-decisions/02-06-SUMMARY.md"
  - ".planning/phases/02-measurement-governors-and-owner-decisions/02-07-PLAN.md"
  - ".planning/phases/02-measurement-governors-and-owner-decisions/02-07-SUMMARY.md"
  - ".planning/phases/02-measurement-governors-and-owner-decisions/02-08-PLAN.md"
  - ".planning/phases/02-measurement-governors-and-owner-decisions/02-08-SUMMARY.md"
  - ".planning/phases/02-measurement-governors-and-owner-decisions/02-09-PLAN.md"
  - ".planning/phases/02-measurement-governors-and-owner-decisions/02-09-SUMMARY.md"
  - "DECISIONS.md"
  - "SPEC.md"
  - "STATUS.md"
  - "boards.py"
  - "dashboard.py"
  - "eval_budget.py"
  - "hunter.py"
  - "pilot.py"
  - "pipeline.py"
  - "reporting.py"
  - "state.py"
  - "tests/test_core.py"
  - "tests/test_deployment.py"
  - "tests/test_governors.py"
  - "tests/test_hunter.py"
  - "tests/test_pilot.py"
  - "tests/test_reporting.py"
covered_digest: "v3:sha256:af1b3e098e27ee0b1f6c44fcdbb63e38b891f13fe26b63452fe8703b11816c28"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 4/5
  gaps_closed:
    - "SC1 'checked in the real Sheet': owner UAT tests 1-3 passed (02-UAT.md)"
    - "Human items 1-5 of the previous report: all resolved by 02-UAT.md (5 passed, 0 issues)"
    - "WR-01..WR-04 (open warnings in the previous report): fixed in 60c6ad1, 5c6ae3f, 0878ce6, 3fc4e21 with offline tests"
  gaps_remaining: []
  regressions: []
coincidental_reliance_items:
  - truth: "The evaluation path stays inside a daily Groq budget (default 100,000 per model)"
    reason: undeclared-precondition
    harden: "The 50% default assumes Groq's tokens-per-day window is rolling. That is an inference from the requests-per-day header, not a measurement (D-53 says so). WR-01's expiry also assumes Groq's retry-after on a daily-limit 429 is honest. Read the console's TPD reset behaviour or a real 429 body once, then record it in STATUS."
---

# Phase 2: Measurement, governors and owner decisions Verification Report

**Phase Goal:** The owner can see how many recent relevant jobs reach the tracker each day and what Groq can really evaluate, and the evaluation and alert paths stay inside the Groq budget, the run timeout and the delivery contract before any change adds load.
**Verified:** 2026-10-28T23:55:00Z
**Status:** passed
**Re-verification:** Yes. Refreshed after the doc-only commit 42a7083 (STATUS.md, DECISIONS.md D-48 Consequences and REQUIREMENTS.md corrected; no code or verdict change). The previous report (`human_needed`, 4/5) was stale: `eval_budget.py`, `hunter.py`, `reporting.py` and `DECISIONS.md` changed after it (code-review fixes WR-01..WR-04), and the five human checks have since been completed by the owner.

## Mocked versus live (AGENTS rule 5)

- **Mocked / offline, run by the verifier in this session:** `.venv/bin/python -m unittest discover -s tests` gives `Ran 629 tests ... OK` (621 before the review fixes plus 8 new offline tests). The named-test commands below were each re-run and pass.
- **Live, owner-run (02-UAT.md, 2026-10-28):** Dashboard tab in the real Sheet, reconciliation row, Runs tab Notes and 77-column header, and Telegram arrival of the TEST FIXTURE message: 4 of 4 passed. The verifier cannot see the Sheet or Telegram; these rest on the owner's "pass" replies recorded in 02-UAT.md.
- **Live, public logs and read-only pilot report (STATUS.md):** token columns, budget log line, tokens per call (2,653.9, n = 95), the 2026-10-27 budget-driven fallback, 0 HTTP 429, run duration p95 343 s and max 941 s.
- **Not observed live, covered offline only:** the 15 / 20 / 22 minute cutoffs, the 5-attempt bound on alert sends without an HTTP response, the Groq budget-skip path, the WR-01 lock expiry against a real Groq daily-limit 429, and the rolling tokens-per-day window. UAT test 5 was marked "pass" by the owner on the basis that none has fired in production; this report records it as not observed live.

## Goal Achievement

### Observable Truths (ROADMAP success criteria are the contract)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Dashboard shows tracker rows per day, age when found, My_Feedback mix; "Recent" apart from verified-fresh; row count reconciles with the ledger's kept jobs (checked in the real Sheet) | ✓ VERIFIED | Code: yield trend and age buckets in `dashboard.py`, `reporting.reconcile` and `tracker_join` name missing ledger-kept keys. Offline `-k yield` (10) and `-k dashboard` (11) pass. Live: pilot report found tracker 97 rows = 2 fixtures + 95 real, 54 of 55 ledger-kept present, missing key named (`greenhouse|nadiacare|4459849009`). Real-Sheet check: 02-UAT.md tests 1 and 2 passed (owner). Residual: the owner did not state whether to keep that row deleted or restore it (UAT test 2 note); that is a follow-up decision, not a failed check. |
| 2 | Groq limits (tier, requests, tokens per minute and day) and measured tokens per call written with source; plan decision recorded; STATUS states evaluations per day and honest tracker rows per day | ✓ VERIFIED | STATUS.md "Groq limits and plan (MEAS-02)": free tier, per-model 30 RPM / 1,000 RPD / 8,000 TPM / 200,000 TPD labelled owner-read; 2,653.9 tokens per call (n = 95, live); about 75 evaluations a day and about 12 tracker rows a day at the 100,000 budget; the 20-30 target stated as conditional. DECISIONS D-53 records the plan decision, data handling and the rolling-window assumption. |
| 3 | Every run records Groq tokens; evaluation stops at a daily budget below the Groq limit; poll and eval stop before the 25-minute timeout; verified-fresh scored first; unscored jobs stay pending and are picked up next run (forced-limit test and live-run figures) | ✓ VERIFIED | `eval_budget.GroqBudget` (per-model, 20% fresh reserve, persisted via `restore(..., now)` at `pipeline.py:287`); default 100,000 against a 200,000 limit; cutoffs 15/20/22 min in `pipeline.py`; deferred jobs record no event and no attempt; verified-fresh sorted first. Tests: `test_governors -k forced` (8), `-k poll` (6), `-k outcome` (4), `test_hunter -k deadline` (11), `-k Groq` (40), `-k budget` (12) all OK. WR-01 behaviour (lock ends at Groq's retry-after, one hour when none, UTC-day end as ceiling) is exercised by `test_exhaustion_expires_at_the_retry_after_instant_not_at_utc_midnight`, `test_daily_limit_lock_lasts_as_long_as_retry_after_or_an_hour` and the reporting SPENT-expiry test, so this behaviour-dependent truth has behavioral evidence. Live: Runs token columns and budget log line, first live budget-driven fallback on 2026-10-27. Cutoffs and the new lock expiry have not fired live (mocked only). |
| 4 | `alerted` only after a channel accepted; a send failing with no HTTP response leaves the job unalerted, is retried, and stops after 5 attempts | ✓ VERIFIED (mocked) | `ALERTED` appended only when the send returned True; no-response failures are bounded at `MAX_ATTEMPTS = 5` then abandoned; 5xx/429 are transient. `test_core -k alert` (14) OK including the five-attempt bound, four-failures-then-success, and not-accepted-is-not-recorded tests. The bound has not fired live. |
| 5 | Every owner decision is recorded in DECISIONS.md or listed with needed-by phase and default; storage design approval surfaced | ✓ VERIFIED | D-48 table lists all 11 decisions with state, needed-by and default (decided: Groq plan D-53, fallback model, SmartRecruiters D-54, repository public, date-only alerts, alert-send bound D-49, Groq data handling D-53; pending with defaults: D-05 amendment, rule-7 lift, per-ATS policy, storage approval before Phase 3). |

**Score:** 5/5 truths verified (0 present-but-behavior-unverified).

### Plan 02-09 and GOV-01 judged against D-54

Plan 02-09 (deploy SmartRecruiters parking) was superseded by owner decision D-54 ("i want to keep smartrecruiters"). Its original must-haves (override removed, parking deployed, PILOT_LOG row, live parking log) are intentionally unmet and are not scored. Judged against D-54:

- D-54 exists (`DECISIONS.md:406`); D-48 row 3 reads "Superseded by D-54 (2026-10-28): kept, stays polled".
- Deployed config matches: `ALLOW_SMARTRECRUITERS_BULK: "1"` in `.github/workflows/job_hunter.yml:74` and `.github/workflows/inventory.yml:76` (the latter's comment now cites D-54). `tests.test_deployment -k smartrecruiters` OK (asserts the override, 1.0 s spacing and parked code default).
- 02-09-SUMMARY says `outcome: superseded`, `requirements-completed: []` and leaves the GOV-01 call to this verification. GOV-01 is satisfied for Phase 2 scope through truth 5 and D-54. The later-gated pending rows are listed with needed-by and default, as REQUIREMENTS.md line 166 and the ROADMAP owner table define for this phase.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `eval_budget.py` | Per-model budget with reserve, persistence, expiring lock | ✓ VERIFIED | `still_spent`, `exhaust(model, until)`, `to_json` with optional `exhausted_until`; used by `hunter.py`, `pipeline.py`, `reporting.py` |
| `pipeline.py` | Cutoffs, deferral without record, alert bounding | ✓ VERIFIED | `restore(..., now)` wired at line 287 |
| `hunter.py` | GroqClient charging and deadline, budget Settings, `_daily_lock_until`, WR-02/03/04 fixes | ✓ VERIFIED | `_int_or` catches `OverflowError`; thousands-separator parse; `groq_budget_note` names an unreadable value; delivery-test send wrapped and redacted; Groq response body no longer logged |
| `reporting.py`, `dashboard.py` | Yield view, reconcile, Groq line | ✓ VERIFIED | `_budget_today` uses `eval_budget.still_spent`; real-Sheet render confirmed by owner UAT |
| `state.py` | 77-column Runs header | ✓ VERIFIED | Live read by the pilot report; owner UAT test 3 |
| `pilot.py` | Groq lines in limits audit | ✓ VERIFIED | Live report run 40606970912 |
| `DECISIONS.md` D-48..D-54 | Decision records | ✓ VERIFIED | D-50 carries the WR-01 amendment |
| `STATUS.md` Groq section | Limits, tokens per call, evaluations per day | ✓ VERIFIED | Labelled owner-read, live or derived |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| `hunter.main` | `pipeline.run_cycle` | `can_score`, `groq_budget`, `process_t0`, cutoffs in `Deps` | WIRED |
| `GroqClient` | `GroqBudget` | `_spend`; daily-limit 429 calls `exhaust(model, _daily_lock_until(...))` | WIRED |
| `pipeline` (run start) | `GroqBudget.restore` | `d.groq_budget.restore(discovery_state.get(GROQ_BUDGET_KEY), now)` (`pipeline.py:287`) | WIRED |
| `pipeline` eval loop | ledger | deferred outcome records nothing, no attempt | WIRED |
| `pipeline` alert loop | `send_alert` / `classify_alert_failure` / `failure_events` | `ALERTED` only after acceptance | WIRED |
| `reporting` yield / reconcile / budget | `dashboard` | `sm["yield"]`, `_budget_today` via `still_spent` | WIRED |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Real Data | Status |
|----------|---------------|--------|-----------|--------|
| Dashboard yield chart | `Y["trend"]` | Events ledger plus tracker via `job_facts` / `tracker_join` | Yes (pilot report computed 97 rows, 54/55; owner saw the render) | FLOWING |
| Runs Groq columns | `groq_tokens_*` | `METER` counters from `GroqClient._spend` | Yes (live Runs read; owner UAT test 3) | FLOWING |

### Behavioral Spot-Checks (all mocked)

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full offline suite | `.venv/bin/python -m unittest discover -s tests` | 629 tests OK | PASS |
| Alert bound and recording | `tests.test_core -k alert` | 14 OK | PASS |
| Forced limit stays pending, scored next day | `tests.test_governors -k forced` | 8 OK | PASS |
| Poll cutoff / order, outcome split | `tests.test_governors -k poll`, `-k outcome` | 6 + 4 OK | PASS |
| Client deadline | `tests.test_hunter -k deadline` | 11 OK | PASS |
| Groq client, budget parsing, lock expiry | `tests.test_hunter -k Groq`, `-k budget` | 40 + 12 OK | PASS |
| Yield and Dashboard | `tests.test_reporting -k yield`, `-k dashboard` | 10 + 11 OK | PASS |
| Budget default is half the limit | `tests.test_hunter -k groq_budget_default` | 1 OK | PASS |
| SmartRecruiters override kept (D-54) | `tests.test_deployment -k smartrecruiters` | 1 OK | PASS |
| Telegram text cap | `tests.test_hunter -k alert_message` | 2 OK | PASS |

### Probe Execution

Step 7c: SKIPPED. No probes declared in the phase plans and no `scripts/*/tests/probe-*.sh`.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| MEAS-01 | 02-05, 02-07 | Dashboard yield, age, feedback, cohort separation | ✓ SATISFIED | Truth 1; owner UAT tests 1 and 2 |
| MEAS-02 | 02-06, 02-08 | Real Groq limits and tokens per call measured; plan decision recorded | ✓ SATISFIED | Truth 2, D-53. Ticked in REQUIREMENTS.md (commit 42a7083) |
| MEAS-03 | 02-03, 02-06, 02-07 | Tokens recorded per run; daily budget keeps runs under the limit | ✓ SATISFIED | Truth 3 |
| MEAS-04 | 02-04, 02-07 | Stop before the 25-minute timeout; fresh first; unscored retryable | ✓ SATISFIED (mocked) | Truth 3; cutoffs never fired live |
| MEAS-05 | 02-02, 02-07 | `alerted` only on acceptance; no-response failures bounded at 5 | ✓ SATISFIED (mocked) | Truth 4 |
| GOV-01 | 02-01, 02-08, 02-09 | Owner decisions recorded | ✓ SATISFIED for Phase 2 scope | Truth 5 and D-54. Ticked in REQUIREMENTS.md (commit 42a7083) |

All six phase IDs appear in plan frontmatter and in REQUIREMENTS.md. No orphaned requirements.

### Anti-Patterns Found

No `TBD` / `FIXME` / `XXX` markers in `eval_budget.py`, `hunter.py`, `reporting.py`, `dashboard.py`, `pipeline.py`, `state.py`, `boards.py` or `pilot.py`. No stubs on the traced paths.

Code review (02-REVIEW.md, 02-REVIEW-DISPOSITION.md): WR-01..WR-04 are `fixed` and re-confirmed in code and tests (WR-01 lock expiry, WR-02 token redaction on the delivery-test send with a test asserting the token is absent, WR-03 `inf` and unreadable-budget note, WR-04 Groq response body no longer logged). The previously flagged WR-02 prohibition (MUST NOT write the bot token into the public log) is now enforced by a test. IN-01..IN-06 remain `open` (info only: stale "15% headroom" wording, SPEC layout claim, `channel: "telegram"` label, triple Settings read, no cutoff ordering check, `tracker_join` URL fallback). None touches a success criterion.

### Human Verification Required

None outstanding. All five human items of the previous report were completed in 02-UAT.md (5 passed, 0 issues). Two notes:

- UAT test 5 ("governors not yet fired in production") is a pass by owner acceptance, not an observation. The cutoffs, the five-attempt bound and the WR-01 expiry remain mocked.
- UAT test 2: the owner did not say whether `greenhouse|nadiacare|4459849009` should stay deleted or be restored. This is an open owner decision, not a verification failure.

### Warnings (non-blocking)

1. **Not deployed:** local `main` is ahead of `origin/main` (`1d63416`). The WR-01..WR-04 fixes, the D-54 workflow comment change and the phase docs are unpushed (the push is about to happen), so production still runs the pre-fix code until then. Offline-verified only. The 100,000 budget default is on `origin/main` (pushed 2026-10-28 20:02 UTC).
2. **Reliance advisory:** see `coincidental_reliance_items` in the frontmatter (rolling TPD window is an inference; WR-01 trusts Groq's `retry-after`). Advisory only; does not change score or status.
3. **Pre-existing, out of scope** (`deferred-items.md`): `TokenBudget.wait` IndexError and the pilot `completions per day` divisor.

### Gaps Summary

No failed truth, no missing or stubbed artifact, no broken link, no outstanding human item. The phase goal is achieved in code, offline tests (629 OK) and the owner's live UAT. What remains is deployment of the review fixes (the push is about to happen) and the owner's keep-or-restore call on the one missing tracker row.

---

_Verified: 2026-10-28T23:55:00Z_
_Verifier: Claude (gsd-verifier)_
