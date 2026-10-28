---
phase: 02-measurement-governors-and-owner-decisions
verified: 2026-10-28T23:30:00Z
status: human_needed
score: 4/5 must-haves verified
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
covered_digest: "v3:sha256:3e3163cfcacc91797a62147c7e6a41cac83943ccd185723c4535bba204400cce"
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "Open the Dashboard tab in the real Sheet"
    expected: "Chart 'Tracker rows per day - target 20-30' with three cohort colours and two dashed lines flat at 20 and 30 (if the upper line rides near 50, flip BAND_LINES_STACK in dashboard.py); chart 'How old jobs were when found'; 'TRACKER ROWS - 7 DAYS' table with verified fresh / Recent / Other rows and Would apply / Maybe / Irrelevant / Unlabelled columns; the Groq SYSTEM line"
    why_human: "Roadmap SC1 says 'checked in the real Sheet'. The agent has no Sheet credentials. Rendering is mocked only (fake spreadsheet, requests checked offline); assumption A7 is unverified."
  - test: "Reconciliation line on the Dashboard (NEEDS ATTENTION) and the tracker"
    expected: "'tracker missing kept jobs' names greenhouse|nadiacare|4459849009 (the one ledger-kept job the live report found missing, 54 of 55 in tracker). Owner says whether the row was deleted by hand and what rule applies."
    why_human: "Reconciliation was read live only through the public pilot report; the owner decision on the missing row and the Sheet view are not confirmed."
  - test: "Runs tab newest rows, Notes column"
    expected: "77-column header; Groq_Tokens_* .. Alerts_Deferred filled; Notes contain 'Groq daily token budget ... per UTC day from <source>'. After the 2026-10-28 push, a post-push run should report 100000 / 100000 and 'from default' (or 'from Settings tab' once the owner adds the row)."
    why_human: "The budget-source note is written only to Runs.Notes, never to the public log; the post-push production budget has not been read in any run."
  - test: "Telegram arrival of the labelled TEST FIXTURE message (delivery test run 40385017743)"
    expected: "Message arrived, no line cut off, within 4,096 characters"
    why_human: "telegram_sent: true records HTTP-level acceptance only; arrival is an owner check."
  - test: "Governors that have not fired in production: the 15/20/22 minute cutoffs and the 5-attempt bound on alert sends without an HTTP response"
    expected: "Not required to trigger deliberately. When one occurs in a real run, the Runs row shows the cut counters and the job stays pending (poll cut makes the run degraded, evaluation cut leaves it ok)."
    why_human: "Proven only by offline tests with an injected clock and mocked sends (AGENTS rule 5). Largest observed run was 941 s, 62.7% of the 1,500 s timeout, so none has fired."
coincidental_reliance_items:
  - truth: "The evaluation path stays inside a daily Groq budget (default 100,000 per model)"
    reason: undeclared-precondition
    harden: "The 50% default assumes Groq's tokens-per-day window is rolling. That is an inference from the requests-per-day header, not a measurement (D-53 says so). Read the console's TPD reset behaviour or a 429 body once, then record it in STATUS."
---

# Phase 2: Measurement, governors and owner decisions Verification Report

**Phase Goal:** The owner can see how many recent relevant jobs reach the tracker each day and what Groq can really evaluate, and the evaluation and alert paths stay inside the Groq budget, the run timeout and the delivery contract before any change adds load.
**Verified:** 2026-10-28T23:30:00Z
**Status:** human_needed
**Re-verification:** No, initial verification

Offline suite run by the verifier: `.venv/bin/python -m unittest discover -s tests` gives `Ran 621 tests ... OK`. Every Automated Command in 02-VALIDATION.md was re-run and passed (counts: alert 14, forced 8, poll 6, outcome 4, deadline 11, yield 10, dashboard 11, groq_budget_default 1, smartrecruiters 1, groq read-outs 8). All of this is **mocked**. Live evidence is limited to public GitHub Actions logs and the read-only pilot report, as recorded in STATUS.md.

## Goal Achievement

### Observable Truths (ROADMAP success criteria are the contract)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Dashboard shows tracker rows per day, age when found, My_Feedback mix; "Recent" apart from verified-fresh; row count reconciles with the ledger's kept jobs (checked in the real Sheet) | ? UNCERTAIN (human) | Code exists and is wired: `dashboard.py:203-222` (yield trend with Verified fresh / Recent / Other series and Target 20/30 columns, age bucket block), `dashboard.py:281-297` (7-day rows and My_Feedback mix per cohort), `reporting.reconcile` + `tracker_join` (`reporting.py:823,1038`) name missing ledger-kept keys. Offline `-k yield` (10) and `-k dashboard` (11) pass. Live: the read-only pilot report found tracker 97 rows = 2 fixtures + 95 real; 54 of 55 ledger-kept present; the one missing key is named. The real-Sheet render and the owner's answer on the missing row are not confirmed (STATUS "Owner checks" 1 and 3). The parenthetical "checked in the real Sheet" is not met yet. |
| 2 | Groq limits (tier, requests, tokens per minute and day) and measured tokens per call written with source; plan decision recorded; STATUS states evaluations per day and honest tracker rows per day | ✓ VERIFIED | STATUS.md "Groq limits and plan (MEAS-02)": free tier; each model 30 RPM, 1,000 RPD, 8,000 TPM, 200,000 TPD, labelled "owner-read from the account limits page, 2026-10-26; not seen by the agent"; 2,653.9 tokens per call (n = 95, live report run 40606970912); about 75 evaluations a day and about 12 tracker rows a day at the chosen 100,000 budget; target stated as "conditional, not met". D-53 records the plan decision ("free-revisit"), data handling and the rolling-window assumption. |
| 3 | Every run records Groq tokens; evaluation stops at a daily budget below the Groq limit; poll and eval stop before the 25-minute timeout; verified-fresh scored first; unscored jobs stay pending and are picked up next run (forced-limit test and live-run figures) | ✓ VERIFIED | `eval_budget.GroqBudget` (per-model, 20% fresh reserve, persisted); wired in `hunter.main` (`hunter.py:2081,2100-2106`: `groq_budget`, `can_score`, `process_t0`, cutoffs); `pipeline.py:48-50` cutoffs 15/20/22 min; `pipeline.py:622-660` eval loop leaves deferred jobs unrecorded with no attempt; `ledger.priority` sorts verified-fresh first (`ledger.py:128`). Default 100,000 against a 200,000 limit (`hunter.py:142-144`). Tests: `test_governors -k forced` (8), `-k poll` (6), `-k outcome` (4), `test_hunter -k deadline` (11) all pass; the forced-limit tests assert no events and no attempts and that the job is scored the next UTC day. Live: Runs token columns and the budget log line (run 40382764588); tokens per UTC day 2026-10-27 primary 171,329 and fallback 26,564 with the first live budget-driven fallback. The cutoffs have not fired live (human item 5). The Groq-limit behaviour is covered by the named offline tests, so this is not left behavior-unverified. |
| 4 | `alerted` only after a channel accepted; a send failing with no HTTP response leaves the job unalerted, is retried, and stops after 5 attempts | ✓ VERIFIED | `pipeline.py:679-735`: `ALERTED` event appended only after `sent is True`; `classify_alert_failure` (`pipeline.py:138`) returns "bounded" for anything without a 5xx/429 response; `lg.failure_events` + `MAX_ATTEMPTS = 5` emit ABANDONED at attempt 5; `needs_alert` stops at `STAGE_ALERT in abandoned`. `send_alert` raises on HTTP error and returns False when no channel is configured. Tests: `test_core -k alert` (14) incl. `test_alert_without_http_response_is_bounded_at_five_attempts`, `..._four_failures_then_success_delivers_once...`, `..._not_accepted_by_any_channel_is_not_recorded_alerted`, 5xx/429 transient. Mocked only; the 5-attempt bound has not fired live. |
| 5 | Every owner decision is recorded in DECISIONS.md or listed with needed-by phase and default; storage design approval surfaced | ✓ VERIFIED | DECISIONS.md D-48 table lists all 11 decisions with state, needed-by and default: Groq plan (decided, D-53), fallback model (decided), SmartRecruiters (decided, D-54), repository public (decided), date-only alerts (decided 2026-10-25, needed by Phase 6), D-05 amendment (pending, Phase 4, default no backfill), rule-7 lift (pending, before CYC-02 / Phase 5, default shadow), per-ATS policy (pending, Phase 6/7, default build only decided providers), storage approval (pending, before Phase 3 executes), alert-send bound (decided, D-49), Groq data handling (decided, D-53). ROADMAP "Owner Decisions" table matches. |

**Score:** 4/5 truths verified (0 present, behavior-unverified). Truth 1 is code-verified but its real-Sheet check is outstanding.

### Plan 02-09 (superseded by D-54)

Not a roadmap truth. Its must_haves (no SmartRecruiters override, parking deployed, PILOT_LOG row, live parking log) are intentionally unmet. Verified instead:
- D-54 exists (`DECISIONS.md:406`), quoting the owner: "i want to keep smartrecruiters"; D-48 row 3 is marked "Superseded by D-54"; ROADMAP owner table says "Recorded: D-54".
- Deployed config matches D-54: `ALLOW_SMARTRECRUITERS_BULK: "1"` is present in both workflows on `origin/main` (`job_hunter.yml:74`, `inventory.yml:76`) and in the local tree (comment-only change citing D-54, unpushed). `tests/test_deployment.py -k smartrecruiters` passes.
- 02-09-SUMMARY says `outcome: superseded`, `requirements-completed: []`, and does not claim GOV-01.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `eval_budget.py` | Pure per-model budget with reserve, persistence | ✓ VERIFIED | 101 lines, substantive, imported and used by `hunter.py` and `pipeline.py` |
| `pipeline.py` | Cutoffs, deferral without record, alert bounding | ✓ VERIFIED | Wired from `hunter.main` via `Deps` |
| `hunter.py` | GroqClient charging/deadline, Settings budget rows, cutoff config | ✓ VERIFIED | Wired; `can_score` lambda uses the shared budget |
| `reporting.py`, `dashboard.py` | Yield view, reconcile, Groq line | ✓ VERIFIED (offline) | Wired; render in real Sheet not confirmed |
| `state.py` | 77-column Runs header with Groq columns | ✓ VERIFIED | Live: report read the columns (STATUS) |
| `pilot.py` | Groq lines in limits audit | ✓ VERIFIED | Live: report run 40606970912 printed them |
| `DECISIONS.md` D-48..D-54 | Decision records | ✓ VERIFIED | Present and consistent with ROADMAP |
| `STATUS.md` Groq section | Limits, tokens per call, evaluations per day | ✓ VERIFIED | Labelled owner-read / live / derived |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| `hunter.main` | `pipeline.run_cycle` | `can_score`, `groq_budget`, `process_t0`, cutoffs in `Deps` (`hunter.py:2100-2106`) | WIRED |
| `GroqClient` | `GroqBudget` | `_spend(model, usage.total_tokens)`; daily-limit 429 exhausts the model | WIRED (see WR-01) |
| `pipeline` eval loop | ledger | deferred outcome records nothing, no attempt (`pipeline.py:646-653`) | WIRED |
| `pipeline` alert loop | `send_alert` / `classify_alert_failure` / `failure_events` | `pipeline.py:679-735` | WIRED |
| `reporting` yield / reconcile | `dashboard` | `sm["yield"]` consumed at `dashboard.py:203,284` | WIRED |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Real Data | Status |
|----------|---------------|--------|-----------|--------|
| Dashboard yield chart | `Y["trend"]` | Events ledger + tracker via `job_facts` / `tracker_join` | Yes (the live pilot report computed from the same functions: 97 rows, 54/55 reconcile) | FLOWING (render unseen) |
| Runs Groq columns | `groq_tokens_*` | `METER` counters from `GroqClient._spend` | Yes (live Runs read by report) | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full offline suite | `.venv/bin/python -m unittest discover -s tests` | 621 tests OK | PASS |
| Forced-limit stays pending / retried next day | `-m unittest tests.test_governors -k forced` | 8 OK | PASS |
| Deadline / poll order | `tests.test_governors -k poll`, `tests.test_hunter -k deadline` | 6 + 11 OK | PASS |
| Alert bound and recording | `tests.test_core -k alert` | 14 OK | PASS |
| WR-03 reproduced | `hunter._int_or('inf', 1)` | raises `OverflowError` | confirmed defect |

### Probe Execution

Step 7c: SKIPPED. No probes declared in the phase plans and no `scripts/*/tests/probe-*.sh` in the repository.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| MEAS-01 | 02-05, 02-07 | Dashboard yield, age, feedback, cohort separation | ? NEEDS HUMAN | Built and offline-tested; real Sheet render and reconciliation row owner checks pending (REQUIREMENTS.md already ticks it; the tick is ahead of the evidence) |
| MEAS-02 | 02-06, 02-08 | Real Groq limits and tokens per call measured; plan decision recorded | ✓ SATISFIED | STATUS Groq section and D-53. **REQUIREMENTS.md still shows `[ ]` / Pending; it should be ticked.** |
| MEAS-03 | 02-03, 02-06, 02-07 | Tokens recorded per run; daily budget keeps runs under the limit | ✓ SATISFIED | Truth 3 |
| MEAS-04 | 02-04, 02-07 | Stop before the 25-minute timeout; fresh first; unscored retryable | ✓ SATISFIED (mocked) | Truth 3; cutoffs never fired live |
| MEAS-05 | 02-02, 02-07 | `alerted` only on acceptance; no-response failures bounded at 5 | ✓ SATISFIED (mocked) | Truth 4 |
| GOV-01 | 02-01, 02-08, 02-09 | Owner decisions recorded | ✓ SATISFIED for Phase 2 scope | Truth 5; the pending rows (D-05, rule-7, per-ATS, storage) are listed with needed-by and default, as REQUIREMENTS.md line 166 and ROADMAP define for this phase. **REQUIREMENTS.md still shows `[ ]` / Pending; it should be ticked.** |

All six phase IDs appear in plan frontmatter (02-01 GOV-01; 02-02 MEAS-05; 02-03 MEAS-03; 02-04 MEAS-04; 02-05 MEAS-01; 02-06 MEAS-02/03; 02-07 MEAS-01/03/04/05; 02-08 MEAS-02/GOV-01; 02-09 GOV-01) and in REQUIREMENTS.md. No orphaned requirements.

### Anti-Patterns Found

No TBD / FIXME / XXX markers in files changed by this phase (grep of the changed `.py`, `.yml`, `.md`). No stubs on the traced paths.

Open code-review findings (02-REVIEW.md; 02-REVIEW-DISPOSITION.md has all 10 `open`). I re-confirmed WR-02, WR-03 and WR-04 in the code:

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `eval_budget.py` / `hunter.py:936-940` | 84-88 | WR-01: persisted "spent per Groq" flag cleared only at UTC midnight; detector also fires on a long `retry-after` alone | WARNING | A model can stay locked up to a day although Groq's window is rolling. Jobs remain pending and retryable, so no data is lost and SC3 holds, but yield (the owner's goal) suffers. |
| `hunter.py:1875` | | WR-02: `send_alert` in `run_delivery_test` has no try/except; the `requests` error text embeds the bot-token URL | WARNING | Flagged prohibition (02-02: MUST NOT write the bot token into the public Actions log). Mitigated by GitHub secret masking; local runs unmasked. Unverified-prohibition, human review recommended. |
| `hunter.py:77-86, 227-231, 329-335` | | WR-03: unparseable budget (e.g. "150,000") silently becomes the default while `Runs.Notes` says "from Settings tab"; `_int_or("inf")` raises `OverflowError` (reproduced) | WARNING | Owner-visible budget source note can be wrong; startup crash possible from a bad Settings cell. |
| `hunter.py:1089` | | WR-04: first 240 characters of a Groq `json_validate_failed` body (model output about a job) logged in a now-public repository | WARNING | Contradicts the DEPLOY.md statement "logs carry counts and job keys only". Pre-existing line, new exposure from D-48 repository-public decision. |
| various | | IN-01..IN-06 (stale "15% headroom" wording, SPEC "checked in a real Sheet" overstated for the new charts, channel label, triple Settings read, no cutoff ordering check, `tracker_join` URL fallback) | INFO | Documentation drift and diagnostics; none touches a success criterion. |

Documentation drift found by the verifier (not in the review): STATUS.md lines 10 and 121 and D-53 "Owner follow-up" still say the 100,000 default is "not pushed / not deployed", but `0762df7` is on `origin/main`. The caller reports the push at 2026-10-28 20:02 UTC; no production run after it has been read, so what production actually uses is unconfirmed (human item 3). Update STATUS after the first post-push run.

### Human Verification Required

See the `human_verification` frontmatter list: (1) Dashboard render in the real Sheet, (2) reconciliation row and the owner's answer about the missing tracker row, (3) Runs.Notes budget-source note and post-push budget, (4) Telegram arrival of the test fixture, (5) governors not yet fired live (15/20/22 minute cutoffs and the 5-attempt bound).

### Gaps Summary

No failed truth, no missing or stubbed artifact, no broken link. Phase goal is met in code and offline tests; the roadmap's explicit "checked in the real Sheet" clause for SC1 and the owner-only live checks keep the status at `human_needed`.

Bookkeeping to do before closing: tick MEAS-02 and GOV-01 in REQUIREMENTS.md (traceability table too); correct the stale "not pushed" statements in STATUS.md and D-53; decide whether the four open warnings (WR-01..WR-04) are fixed in this phase or deferred, and record the disposition in 02-REVIEW-DISPOSITION.md. The two deferred-items.md notes (`TokenBudget.wait` IndexError, pilot `completions per day` divisor) are pre-existing, outside MEAS-04's scope, and not blockers.

Not live-verified and still mocked (AGENTS rule 5): Sheet render, Runs.Notes source note, Telegram arrival, 15/20/22 minute cutoffs, the 5-attempt alert bound, the rolling TPD window, and the 100,000 default in production.

---

_Verified: 2026-10-28T23:30:00Z_
_Verifier: Claude (gsd-verifier)_
