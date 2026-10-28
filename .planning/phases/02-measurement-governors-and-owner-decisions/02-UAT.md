---
status: complete
phase: 02-measurement-governors-and-owner-decisions
source: [02-VERIFICATION.md]
started: 2026-10-28T22:04:03Z
updated: 2026-10-28T23:43:00.170Z
---

## Current Test

[testing complete]

## Tests

### 1. Dashboard tab in the real Sheet
expected: Chart "Tracker rows per day · target 20-30" with three cohort colours and two dashed lines flat at 20 and 30 (upper line near 50 = "band stacked"); age-when-found chart; "TRACKER ROWS · 7 DAYS" table with the My_Feedback mix per cohort; the Groq SYSTEM line.
result: pass

### 2. Reconciliation row (NEEDS ATTENTION) and the tracker
expected: "tracker missing kept jobs" names greenhouse|nadiacare|4459849009 (54 of 55 ledger-kept jobs in the tracker). Owner says whether the row was deleted by hand and whether to keep it deleted or restore it.
result: pass
note: "Owner replied 'pass'; keep-deleted vs restore decision not stated."

### 3. Runs tab newest rows, Notes column
expected: 77-column header; Groq_Tokens_* .. Alerts_Deferred filled; Notes contain "Groq daily token budget ... per UTC day from <source>". A run after the 2026-10-28 20:02 UTC push reports 100000 / 100000 and "from default" (or "from Settings tab" once the owner sets the row to 100000).
result: pass

### 4. Telegram arrival of the labelled TEST FIXTURE message (delivery test run 40385017743)
expected: Message arrived, no line cut off.
result: pass

### 5. Governors not yet fired in production (15/20/22 minute cutoffs; 5-attempt bound on alert sends without an HTTP response)
expected: Not triggered deliberately. When one occurs in a real run, the Runs row shows the cut counters and the job stays pending (poll cut = degraded, evaluation cut = ok). May be marked skipped until observed.
result: pass
note: "Owner replied 'pass'. No governor has fired in production yet; behaviour is covered by offline tests only."

## Summary

total: 5
passed: 5
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
