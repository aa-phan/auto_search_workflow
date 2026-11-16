---
status: testing
phase: 03-compact-storage
source: [03-VERIFICATION.md]
started: 2026-11-06T22:24:12Z
updated: 2026-11-16T00:00:00Z
---

## Current Test

number: 1
name: Hidden tabs and protection
expected: |
  All three tabs exist and are hidden. Each edit attempt shows a warning/confirmation prompt (warning-only whole-sheet protection). Cancel the edit.
awaiting: user response

## Tests

### 1. Hidden tabs and protection
Hidden tabs and protection. In the real Sheet use right-click on a tab name > Show hidden sheets. Confirm Identity, Tally and Events_Legacy exist and are hidden by default. Then, without saving, try to edit one cell in Identity and one in Events_Legacy.
expected: All three tabs exist and are hidden. Each edit attempt shows a warning/confirmation prompt (warning-only whole-sheet protection). Cancel the edit.
result: [pending]

### 2. Dashboard Storage line
Dashboard Storage line. Open the Dashboard tab SYSTEM section and NEEDS ATTENTION list.
expected: Storage line reads compact since 2026-11-02 (mode compact, last check 0 counted differences). No 'storage parity difference' row under NEEDS ATTENTION. The Dashboard figures (tracker rows, new jobs this week, baseline totals) are plausible next to the pre-cutover Dashboard, and the muted P3-11 note says baseline and older gated/stale totals come from the Tally tab.
result: [pending]

### 3. Discovery storage key
Discovery key. Open the Discovery tab and find the key 'storage' (read only; do not edit).
expected: mode compact, seeded_at 2026-10-29T17:47:52Z, a cutover record (retained_rows 25531, legacy_rows 235785, the logged checksum 33bdd796...), a fold record (rows_total 16752 or more, first_day 2026-11-03). The key is below the 45,000-character cell cap.
result: [pending]

### 4. No duplicate Telegram alerts
Telegram. Scan the chat from 2026-11-02 01:00 UTC to now for repeated alerts of the same job.
expected: No job alerted twice, no flood of old jobs around the cutover (2026-11-02 02:00 UTC) or the folds (00:03 UTC on 11-03, 11-04, 11-05, 11-06).
result: [pending]

### 5. Steady-state growth re-read (about 2026-11-14)
Steady-state growth re-read (calendar item, about 2026-11-14). Owner or agent, with the owner's allowance, dispatch the read-only storage_report input after about 7 more complete UTC days of folds, and record the 'median daily growth in allocated cells' line.
expected: A positive or near-zero daily growth in allocated cells that is at least 10 times below the 35,511 cells/day before figure (that is, 3,551 or fewer), measured over 2 or more complete UTC days that are NOT dominated by catching up the cutover's retained rows. The report's own projection is about 2,381 cells a day (a model, not a measurement).
result: [pending]

### 6. Fold batch size (A5)
Fold batch size (research A5). Decide whether to accept A5 as mocked, or to confirm on the first large fold (for example after board growth) that a batch of 500 deleteDimension requests is accepted.
expected: Either an explicit owner acceptance that A5 stays mocked, or a log of a fold with at least 500 ranges that did not raise. The four live folds used 94, 131, 88 and 106 ranges, all under 500, so a full-size batch has never been sent live.
result: [pending]

### 7. Deploy decision for the review fixes WR-01..WR-09 and open warning WR-10
Deploy decision for the review fixes WR-01..WR-09 (updated by the 2026-11-16 re-verification). The commits are on branch gsd/phase-03-compact-storage only; production runs 68a7253 without them. Owner decides whether and when to push. After a deploy, read the first two compact poller runs and one --storage-parity run. WR-06..WR-09 are fixed on the branch (WR-09, e86993e: the identity count is exactly the set of keys the dedupe holds). Open: WR-10 (a bare kind letter with no posting ID, e.g. `b`, is counted as a held key; it can never match a posting, its only repair is deletion, and deleting it raises a permanent identity_shrunk that holds the fold back). Decide: fix WR-10 first (skip the empty posting ID in `IdentitySet._reindex`: `if pid: kinds.setdefault(pid, kind)`), or accept it and add a runbook line for clearing a stuck mark (IN-10).
expected: No 'storage write failed', 'storage parity:' or 'storage fold skipped' note; the first compact check records the distinct held-key count (shrink detection starts from the second check); the next fold still runs. Until then every WR-01..WR-09 behaviour is mocked only.
result: [pending]

## Summary

total: 7
passed: 0
issues: 0
pending: 7
skipped: 0
blocked: 0

## Gaps
