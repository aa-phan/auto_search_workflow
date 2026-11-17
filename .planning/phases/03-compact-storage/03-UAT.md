---
status: complete
phase: 03-compact-storage
source: [03-VERIFICATION.md]
started: 2026-11-06T22:24:12Z
updated: 2026-11-17T09:07:24.251Z
---

## Current Test

[testing complete]

## Tests

### 1. Hidden tabs and protection
Hidden tabs and protection. In the real Sheet use right-click on a tab name > Show hidden sheets. Confirm Identity, Tally and Events_Legacy exist and are hidden by default. Then, without saving, try to edit one cell in Identity and one in Events_Legacy.
expected: All three tabs exist and are hidden. Each edit attempt shows a warning/confirmation prompt (warning-only whole-sheet protection). Cancel the edit.
result: pass

### 2. Dashboard Storage line
Dashboard Storage line. Open the Dashboard tab SYSTEM section and NEEDS ATTENTION list.
expected: Storage line reads compact since 2026-11-02 (mode compact, last check 0 counted differences). No 'storage parity difference' row under NEEDS ATTENTION. The Dashboard figures (tracker rows, new jobs this week, baseline totals) are plausible next to the pre-cutover Dashboard, and the muted P3-11 note says baseline and older gated/stale totals come from the Tally tab.
result: pass

### 3. Discovery storage key
Discovery key. Open the Discovery tab and find the key 'storage' (read only; do not edit).
expected: mode compact, seeded_at 2026-10-29T17:47:52Z, a cutover record (retained_rows 25531, legacy_rows 235785, the logged checksum 33bdd796...), a fold record (rows_total 16752 or more, first_day 2026-11-03). The key is below the 45,000-character cell cap.
result: pass

### 4. No duplicate Telegram alerts
Telegram. Scan the chat from 2026-11-02 01:00 UTC to now for repeated alerts of the same job.
expected: No job alerted twice, no flood of old jobs around the cutover (2026-11-02 02:00 UTC) or the folds (00:03 UTC on 11-03, 11-04, 11-05, 11-06).
result: pass

### 5. Steady-state growth re-read (about 2026-11-14)
Steady-state growth re-read (calendar item, about 2026-11-14). Owner or agent, with the owner's allowance, dispatch the read-only storage_report input after about 7 more complete UTC days of folds, and record the 'median daily growth in allocated cells' line.
expected: A positive or near-zero daily growth in allocated cells that is at least 10 times below the 35,511 cells/day before figure (that is, 3,551 or fewer), measured over 2 or more complete UTC days that are NOT dominated by catching up the cutover's retained rows. The report's own projection is about 2,381 cells a day (a model, not a measurement).
result: pass
evidence: "Live, read-only storage_report run 43990083983 (2026-11-17 00:44 UTC, production 68a7253): median daily growth in allocated cells 447 over 7 complete UTC days 2026-11-10..2026-11-16 (35,511 before, 79.4x smaller, Identity and Tally growth included); median Runs.Load_S 7.0 s (12.0 s before); Events 28,307 rows (235,785 before)."

### 6. Fold batch size (A5)
Fold batch size (research A5). Decide whether to accept A5 as mocked, or to confirm on the first large fold (for example after board growth) that a batch of 500 deleteDimension requests is accepted.
expected: Either an explicit owner acceptance that A5 stays mocked, or a log of a fold with at least 500 ranges that did not raise. The four live folds used 94, 131, 88 and 106 ranges, all under 500, so a full-size batch has never been sent live.
result: pass
evidence: "Owner accepts A5 as mocked (2026-11-16): a 500-request deleteDimension batch has not been sent live; live folds used 94-131 ranges."

### 7. Deploy decision for the review fixes WR-01..WR-09 and open warning WR-10
Deploy decision for the review fixes WR-01..WR-09 (updated by the 2026-11-16 re-verification). The commits are on branch gsd/phase-03-compact-storage only; production runs 68a7253 without them. Owner decides whether and when to push. After a deploy, read the first two compact poller runs and one --storage-parity run. WR-06..WR-09 are fixed on the branch (WR-09, e86993e: the identity count is exactly the set of keys the dedupe holds). Open: WR-10 (a bare kind letter with no posting ID, e.g. `b`, is counted as a held key; it can never match a posting, its only repair is deletion, and deleting it raises a permanent identity_shrunk that holds the fold back). Decide: fix WR-10 first (skip the empty posting ID in `IdentitySet._reindex`: `if pid: kinds.setdefault(pid, kind)`), or accept it and add a runbook line for clearing a stuck mark (IN-10).
expected: No 'storage write failed', 'storage parity:' or 'storage fold skipped' note; the first compact check records the distinct held-key count (shrink detection starts from the second check); the next fold still runs. Until then every WR-01..WR-09 behaviour is mocked only.
result: issue
reported: "fix wr-10 first"
severity: major

### 8. Deploy decision after the WR-10 fix (open warning WR-11)
Deploy decision for branch gsd/phase-03-compact-storage after gap-closure plan 03-10 fixed WR-10 (added by the 2026-11-17 re-verification). Production runs 68a7253 without WR-01..WR-10. Open: WR-11 (a hand-edited Identity stem that no job key can produce, such as no `|`, an extra `|` or upper case, still holds keys and counts toward the identity mark; deleting it raises a permanent identity_shrunk in compact mode). Decide: (a) fix WR-11 first (a `stem_holds_keys` predicate in `IdentitySet._reindex` plus an `identity_stem` counted difference), (b) accept WR-11, add the IN-10 runbook line and deploy, or (c) defer the branch.
expected: After a deploy: no 'storage write failed', 'storage parity:' or 'storage fold skipped' note; the first compact check records the distinct held-key count; the next fold still runs. Until then every WR-01..WR-10 behaviour is mocked only.
result: pass
evidence: "Owner chose option b (2026-11-17): accept WR-11, add the IN-10 runbook note (5d1d421), deploy. main fast-forwarded 68a7253..bc3bea2 at 07:07 UTC. Live: poller run 44043039789 and 44051541803 compact, 0 counted and 0 declared differences, no storage write failed / storage parity: / storage fold skipped note; read-only storage_parity run 44044724225 0 differences (identity_entries 295385). Not yet observed: the first fold on bc3bea2 (first run after 00:00 UTC 2026-11-18)."

## Summary

total: 8
passed: 7
issues: 1
pending: 0
skipped: 0
blocked: 0

## Gaps

- gap_id: G-3-7
  truth: "Before the review fixes WR-01..WR-09 are deployed, WR-10 is fixed: an Identity entry with no posting ID (a bare kind letter such as `b`) holds no key, is flagged identity_entry, and deleting it is not a counted identity_shrunk"
  status: resolved
  resolved_by: 03-10-PLAN.md
  resolved_at: 2026-11-17
  reason: "User reported: fix wr-10 first"
  severity: major
  test: 7
  root_cause: "IdentitySet._reindex stores the empty posting ID from decode_entry('b') == ('b', '') as key 'stem|', so distinct_count() counts it; it can never match a posting (stem_and_id returns None for an empty ID) and deleting it raises the high-water identity_shrunk mark permanently (03-REVIEW.md WR-10)"
  artifacts:
    - path: "compact.py"
      issue: "IdentitySet._reindex keeps the empty posting ID as a held key"
    - path: "tests/test_storage_parity.py"
      issue: "a test pins (3, 3) with the empty key counted; no test deletes a bare entry after the mark is recorded"
  missing:
    - "In IdentitySet._reindex, skip an empty posting ID (if pid: kinds.setdefault(pid, kind))"
    - "Update the pinning test to (2, 2) and add a test that deleting a bare entry is not a shrink"
    - "Update SPEC, D-57 and STATUS where they say a bare letter counts as a held key"
