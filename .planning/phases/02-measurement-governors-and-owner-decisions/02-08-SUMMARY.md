---
phase: 02-measurement-governors-and-owner-decisions
plan: 08
subsystem: groq-limits-and-plan
tags: [groq, meas-02, gov-01, d-53, budget-default, owner-decision]

requires:
  - phase: 02-measurement-governors-and-owner-decisions
    provides: "D-50 per-model Groq budget (plan 02-03) and the production Runs columns verified in plan 02-07"
provides:
  - "STATUS section 'Groq limits and plan (MEAS-02)': measured usage (live, pilot_report run 40606970912), owner-read account limits, reset behaviour, evaluations and tracker rows a day, the conditional 20-30 target sentence"
  - "DECISIONS D-53: Groq plan free-revisit, resume to Groq ok, budget 100,000 per model; D-48 rows 1 and 11 'decided in D-53'; D-50 default amended"
  - "hunter.GROQ_TPD_PRIMARY / GROQ_TPD_FALLBACK and the Groq_Daily_Token_Budget default 100000 (committed, not deployed)"
affects: [02-09, phase-04-entry-gate, status, settings]

actuals:
  tokens: 14000
  tasks: 3
  commits: 4
plan_head_before: 1d00648db0c8d5d11b52b51ef8adaf2576f3df7e
plan_head_after: fd3bb15c6ba51259c70494060cff6435a10a9d60

tech-stack:
  added: []
  patterns:
    - "A budget default is derived from a named constant that holds the owner-read limit, so the default and its source cannot drift apart"
    - "Reset behaviour is read from recorded x-ratelimit-reset-requests values (86.4 s per request = 24 h / 1000), not assumed"

key-files:
  created: []
  modified:
    - STATUS.md
    - DECISIONS.md
    - hunter.py
    - tests/test_hunter.py
    - README.md
    - .planning/ROADMAP.md

key-decisions:
  - "D-53: free-revisit (stay free now, revisit before Phase 4); resume to Groq: ok; budget 100,000 per model per UTC day (half the owner-read 200,000, because the daily window rolls)"
  - "The default is half the limit, not 85%: the plan's rolling-window rule, accepted by the owner knowing it lowers the free ceiling to about 75 evaluations and about 12 tracker rows a day"
  - "Groq_Fallback_Daily_Token_Budget stays blank (= same) because both models' limits are equal"
  - "The 20-30 a day target is recorded as conditional and not reachable on the free plan at this budget"

requirements-completed: []

coverage:
  - id: D1
    description: "STATUS records measured Groq usage with source (run id, window) labelled live, and the owner-read account limits with their date"
    requirement: "MEAS-02"
    verification:
      - kind: command
        ref: "grep -c '## Groq limits and plan (MEAS-02)' STATUS.md; grep -c 'owner-read from the account limits page' STATUS.md; grep -c 'public table, not this account' STATUS.md"
        status: pass
    human_judgment: false
  - id: D2
    description: "D-53 records the plan decision, limits and source, measured tokens per call with n, evaluations and rows a day, reset behaviour, new defaults and data handling; D-48 rows 1 and 11 say 'decided in D-53'; ROADMAP owner row says 'Recorded: D-53'"
    requirement: "GOV-01"
    verification:
      - kind: command
        ref: "grep -c '^## D-53' DECISIONS.md; grep -c 'decided in D-53' DECISIONS.md; grep -c 'Recorded: D-53' .planning/ROADMAP.md"
        status: pass
    human_judgment: false
  - id: D3
    description: "Budget default follows the recorded limit (GROQ_TPD_PRIMARY // 2) and its wording names the limits page and date"
    requirement: "MEAS-02"
    verification:
      - kind: test
        ref: "tests.test_hunter GroqSettingsTests (36 Groq tests); full suite 621 tests OK offline"
        status: pass
    human_judgment: false
  - id: D4
    description: "The new default in a production run, and that Groq's token window rolls"
    requirement: "MEAS-02"
    verification: []
    human_judgment: true
    rationale: "Not pushed (the plan authorizes no push for Task 3) and the token window is in no response header; the owner must also add or edit the Settings row. Until then production keeps the provisional 170000 default."

duration: "Task 1 on 2026-10-28 (earlier invocation); Tasks 2-3 on 2026-10-28 (about 20 min of execution after the owner's reply)"
completed: 2026-10-28
status: complete
---

# Phase 2 Plan 08: Groq limits, plan decision D-53 and measured budget default Summary

**The owner stays on the free Groq plan and revisits before Phase 4 (D-53); the per-model daily token budget default becomes 100,000 (half of the owner-read 200,000, because the window rolls), which supports about 75 evaluations and about 12 tracker rows a day, so the 20-30 a day target is recorded as conditional.**

## Owner decision (Task 2), verbatim

- Plan: **"free-revisit"** (stay free now, revisit before Phase 4 starts).
- **"resume to Groq: ok"**.
- Budget: **"100,000 (plan rule)"**: the owner accepts the plan's rolling-window rule (half the limit, not 85%): default `Groq_Daily_Token_Budget` 100,000 per model, primary and fallback each, replacing the provisional 170,000. The owner was shown that this lowers the free ceiling to about 75 evaluations and about 12 tracker rows a day with both models.
- Account limits as the owner read them on 2026-10-26 from console.groq.com (figures only, no key): free plan; `openai/gpt-oss-120b` and `openai/gpt-oss-20b` each 30 RPM, 1K RPD, 8K TPM, 200K TPD; zero data retention not enabled (neither global nor inference API). No key material appeared in any reply.

## Task 1 (earlier invocation, commit de0c599)

Read-only `pilot_report` run 40606970912: 2,653.9 tokens per scoring call (n = 95); 2026-10-27 primary 171,329 and fallback 26,564 tokens (about 75 calls); keep rate 16.3% (52 of 319); 0 HTTP 429; daily request window rolling (reset 86.4 s per request); the token window is inferred, not measured.

## Task 3 (TDD: RED a10a343, GREEN 0762df7, docs fd3bb15)

- **RED (a10a343):** tests updated to the new default and a new test asserting `SETTING_DEFAULTS["Groq_Daily_Token_Budget"] == str(GROQ_TPD_PRIMARY // 2)`; observed failing (3 failures, 1 error for the missing constant).
- **GREEN (0762df7):** `GROQ_TPD_PRIMARY` and `GROQ_TPD_FALLBACK` (200000, owner-read 2026-10-26); `DEFAULT_GROQ_DAILY_TOKENS = GROQ_TPD_PRIMARY // 2`; the Settings row default derives from it; the description names the account limits page, its date and D-53 and says why half; the `Runs.Notes` default-source wording changed from "provisional: 85% of the public ..." to "50% of this account's 200,000 tokens/day per model, D-53"; README Settings table updated. Fallback row stays blank (limits equal).
- **Docs (fd3bb15):** DECISIONS D-53 and the D-48 row 1 and 11 annotations (plus an amendment sentence on D-50's default); STATUS Groq section (account limits, decision, the target sentence, Target status line updated, stale "about 7-20" and "about 40 a day" corrected to the measured about 45.6 a day over 7 days and about 75 on 2026-10-27); ROADMAP owner row "Recorded: D-53".
- **Full suite:** `.venv/bin/python -m unittest discover -s tests` 621 tests OK (cache cleared first); Groq-filtered run 36 tests OK. All offline and mocked.

## What the figures say

With the free plan the app can evaluate about 75 jobs a day (100,000 tokens per model, both models, 2,653.9 tokens per call), which at the measured keep rate of 16.3% supports about 12 tracker rows a day (about 15 at the pilot's 19.6%). The 20-30 a day target needs about 123-184 evaluations a day, so it is conditional, not met. Today the inflow is about 7.4 kept rows a day because scoring volume (about 45.6 a day), not Groq, is the limit.

## Live versus mocked

- **Live (read-only, public log):** the usage figures, the keep rate and the rolling request window (Task 1, run 40606970912).
- **Owner-read (not seen by the agent):** the account's plan and limits and the retention setting (2026-10-26, confirmed 2026-10-28).
- **Mocked / offline:** the new default and its wording (`GroqSettingsTests`, full suite).
- **Not verified:** that the token-per-day window rolls (inference from the request window); the new default in production.

## Owner follow-up (not done without the owner's request)

1. **Nothing was pushed.** The new default reaches production only after a push of `main`; until then production runs on the 170000 default.
2. The live Settings tab does not get the new default automatically: add or edit the `Groq_Daily_Token_Budget` row to **100000** (or ask for it to be written through the Sheets connector, as in D-46). The next run's note should then say "from Settings tab" (it says "from default" while the row is absent; that note is in `Runs.Notes`, not in the public log).
3. Revisit the plan choice (the paid Developer plan) before Phase 4 starts: backfill competes for the same budget, and the D-05 amendment (D-48 row 6) depends on it.

## Deviations from Plan

### Auto-fixed Issues

None.

### Judgment calls

1. The plan's named test `test_groq_budget_default_is_85_percent_of_the_recorded_daily_limit` was added as `test_groq_budget_default_is_half_of_the_recorded_daily_limit_because_the_window_rolls`: the plan allows the half-limit assertion when the window is rolling, and an "85_percent" name would misdescribe what it asserts.
2. README.md was changed too (it documented the 170000 default); the plan's file list did not include it.
3. `requirements.ready-ids` returned nothing ready for MEAS-02 and for GOV-01 queried separately (a combined query listed GOV-01 as ready), so neither requirement is marked complete here; GOV-01 still has plan 02-09 and pending owner decisions.

**Total deviations:** 0 auto-fixed; 3 judgment calls. **Impact:** none on the plan's goal.

## Authentication Gates

None.

## Known Stubs

None.

## Threat Flags

None (no new endpoints, auth paths or file access; the owner's figures only, no key or screenshot copied: T-02-22 held; resume-to-Groq acceptance recorded in D-53: T-02-23).

## Self-Check: PASSED

- Commits found in history: de0c599, a10a343, 0762df7, fd3bb15.
- Files found: DECISIONS.md (`## D-53`), STATUS.md, hunter.py (`GROQ_TPD_PRIMARY`), tests/test_hunter.py, .planning/ROADMAP.md (`Recorded: D-53`).
