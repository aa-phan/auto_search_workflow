---
status: testing
phase: 02-measurement-governors-and-owner-decisions
source: [02-VERIFICATION.md]
started: 2026-10-28T22:04:03Z
updated: 2026-10-28T22:04:03Z
---

## Current Test

number: 1
name: Dashboard tab in the real Sheet
expected: |
  Chart "Tracker rows per day · target 20-30" with three cohort colours and two dashed lines flat at 20 and 30 (if the upper line rides near 50, reply "band stacked": flip BAND_LINES_STACK in dashboard.py); chart "How old jobs were when found · 7d"; "TRACKER ROWS · 7 DAYS" table with verified fresh / Recent / Other rows and Would apply / Maybe / Irrelevant / Unlabelled columns; the Groq SYSTEM line.
awaiting: user response

## Tests

### 1. Dashboard tab in the real Sheet
expected: Chart "Tracker rows per day · target 20-30" with three cohort colours and two dashed lines flat at 20 and 30 (upper line near 50 = "band stacked"); age-when-found chart; "TRACKER ROWS · 7 DAYS" table with the My_Feedback mix per cohort; the Groq SYSTEM line.
result: [pending]

### 2. Reconciliation row (NEEDS ATTENTION) and the tracker
expected: "tracker missing kept jobs" names greenhouse|nadiacare|4459849009 (54 of 55 ledger-kept jobs in the tracker). Owner says whether the row was deleted by hand and whether to keep it deleted or restore it.
result: [pending]

### 3. Runs tab newest rows, Notes column
expected: 77-column header; Groq_Tokens_* .. Alerts_Deferred filled; Notes contain "Groq daily token budget ... per UTC day from <source>". A run after the 2026-10-28 20:02 UTC push reports 100000 / 100000 and "from default" (or "from Settings tab" once the owner sets the row to 100000).
result: [pending]

### 4. Telegram arrival of the labelled TEST FIXTURE message (delivery test run 40385017743)
expected: Message arrived, no line cut off.
result: [pending]

### 5. Governors not yet fired in production (15/20/22 minute cutoffs; 5-attempt bound on alert sends without an HTTP response)
expected: Not triggered deliberately. When one occurs in a real run, the Runs row shows the cut counters and the job stays pending (poll cut = degraded, evaluation cut = ok). May be marked skipped until observed.
result: [pending]

## Summary

total: 5
passed: 0
issues: 0
pending: 5
skipped: 0
blocked: 0

## Gaps
