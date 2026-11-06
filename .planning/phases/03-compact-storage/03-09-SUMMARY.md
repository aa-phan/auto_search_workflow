---
phase: 03-compact-storage
plan: 09
subsystem: live-operations
tags: [cutover, fold, storage-report, success-criteria, pilot-log]

requires:
  - phase: 03-compact-storage
    provides: "plan 03-08: cutover tooling live on main (2556c41); plans 03-06 and 03-07: storage_cutover, the 7-day fold, the storage report"
provides:
  - "Live cutover 2026-11-02 01:36 UTC (run 41373351559): Events 235,785 -> 25,531 rows, Events_Legacy kept hidden and protected, mode compact"
  - "First 7-day fold 2026-11-03 00:03 UTC (run 41549615660): 2866 rows folded; four daily folds so far, 16,752 rows, 0 kept, no failure"
  - "Measured before/after storage figures from storage report run 42300947285 and the closing Phase 3 success criteria table (SC1-SC4) in STATUS with live / mocked / owner-check labels"
affects: [Phase 4 and later board growth (parity accepted), a later steady-state re-read of --storage-report]

actuals:
  tokens: 9000
  tasks: 3
  commits: 2
plan_head_before: 68a7253c938cdabe692090d7e65ee3568c69e527
plan_head_after: 77fc48628bab84ea0612893b2ef9a31aa079eef9
commits: 2

tech-stack:
  added: []
  patterns:
    - "a live claim names a public run id; Sheet-only facts stay owner checks; a measurement is never replaced by the report's projection lines"

key-files:
  created: []
  modified:
    - PILOT_LOG.md
    - STATUS.md

key-decisions:
  - "Task 1 (owner decision): agent-dispatches; the cutover was dispatched by the agent's orchestrator, not by the owner by hand"
  - "The agent dispatched only read-only runs after the cutover (storage_report 42300947285, storage_parity 42301084151); storage_cutover and storage_restore were never dispatched by this agent"
  - "The daily-growth ratio is not claimed as an order-of-magnitude drop: the after figure is negative over only 2 complete days (a transitional measurement)"

requirements-completed: []  # STOR-01: SC1-SC3 live with the caveats below, SC4 mocked; owner checks in the Sheet pending. Not marked complete by the agent.

coverage:
  - id: D1
    description: "The storage cutover ran on the owner's choice (agent-dispatches) after the bar was met; run log shows `done`, 25,531 rows in Events, 235,785 in Events_Legacy"
    requirement: STOR-01
    verification:
      - kind: manual
        ref: "public logs of runs 41364810371 (bar 3 of 3), 41373351559 (cutover), 41375348321 (first compact run), 41375689814 (parity)"
        status: pass
    human_judgment: false
  - id: D2
    description: "The first fold and the later daily folds ran without failure; the integrity check read 0 counted differences in 107 of 108 runs since"
    requirement: STOR-01
    verification:
      - kind: manual
        ref: "public logs of runs 41549615660, 41743488450, 41938020379, 42133570806 and all 108 poller runs 2026-11-03 to 2026-11-06 (grep: 0 `storage fold failed`, 0 storage notes)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Measured before/after storage figures and the Phase 3 success criteria table with live / mocked / owner-check labels"
    requirement: STOR-01
    verification:
      - kind: manual
        ref: "storage report run 42300947285; grep -c 'Phase 3 success criteria' STATUS.md = 2; grep -ci 'first fold' PILOT_LOG.md = 1"
        status: pass
    human_judgment: false
  - id: D4
    description: "Everything inside the Sheet (hidden tabs, Events_Legacy protection prompt, Dashboard Storage line, Discovery key, Telegram chat), the 500-request deleteDimension batch (A5) and a steady-state growth figure"
    requirement: STOR-01
    verification: []
    human_judgment: true
    rationale: "The agent has no Sheet credentials; A5 is not printed in any log; the steady state needs about 7 more complete UTC days"

duration: Task 3 about 25 min of agent time (log scan of 108 runs, two read-only dispatches, two documents)
completed: 2026-11-06
status: complete
---

# Phase 3 Plan 09: Owner cutover and first fold Summary

**Compact storage is live: the ledger was cut over on 2026-11-02 (run 41373351559), the first fold deleted 2866 week-old rows on 2026-11-03 (run 41549615660), and the storage report (run 42300947285) measures Events at 30,613 rows (from 235,785), median load time 5.0 s (from 12.0 s) and daily growth of -2,658 cells (from +35,511) over only two complete days, so an order-of-magnitude drop at steady state is not claimed.**

## Performance

- **Tasks:** 3 of 3 (Task 1 decision and Task 2 cutover ran earlier in the orchestrator and an earlier commit, f3c55e9; Task 3 here)
- **Tests:** `Ran 910 tests ... OK` (offline, before the Task 3 commit; no code changed in this plan)

## Accomplishments

- **Task 1 (owner decision):** the bar was read as met from run 41364810371 (`3 of 3 complete days toward the bar`); the owner chose `agent-dispatches`.
- **Task 2 (commit f3c55e9):** `storage_cutover=true` dispatched by the agent's orchestrator, run **41373351559** (2026-11-02 01:36:21 UTC, `success`): `STORAGE CUTOVER done at 2026-11-02T01:36:38Z: mode compact`, 25,531 rows in `Events`, 235,785 in `Events_Legacy`. First compact-mode poller run **41375348321** (02:00 UTC): 0 counted and 0 declared differences, `new jobs 30`, `alerts 0 sent`, no storage note. Read-only parity run **41375689814**: 0 counted differences. PILOT_LOG row and STATUS "Phase 3 cutover (live)" written in f3c55e9.
- **Task 3 (commit 77fc486):**
  - Scanned all 108 poller runs from 2026-11-03 00:00 UTC to 2026-11-06 21:00 UTC (not sampled; 107 `success`, 1 `failure`): **0** `storage fold failed`, **0** storage notes or integrity-check failures, 107 `Storage: mode=compact, 0 counted and 0 declared differences` lines.
  - Folds, one a UTC day: run 41549615660 (2026-11-03) **2866 rows in 94 ranges**; 41743488450 5153 in 131; 41938020379 4512 in 88; 42133570806 4221 in 106; 16,752 in total, 0 kept each day.
  - The one failed run, 41669619936 (2026-11-03 16:00 UTC): transient `gspread APIError [500]` in the tracker append inside the write stage (not a storage note); the next run 41679862493 recovered (0 counted differences, 367 new jobs against 236 before and 238 after, consistent with the retry; an inference from counts).
  - Read-only dispatches on the owner's allowance: `storage_report` run **42300947285** and `storage_parity` run **42301084151** (0 counted differences, 2.47 s).
  - Report figures as printed: Events 235,785 -> 30,613 rows; Events cells 1,650,502 -> 214,298; total allocated cells 2,471,757 -> 2,689,420 (26.9% of the 10M limit; up because `Events_Legacy`, 1,650,502 cells, is kept); median `Load_S` 12.0 s -> 5.0 s; median daily growth 35,511 -> **-2,658** cells over 2 complete UTC days (2026-11-04, 2026-11-05).
  - PILOT_LOG first-fold row; STATUS fold section, before/after figures, "Phase 3 success criteria" table and "Last updated".

## The growth ratio (ROADMAP SC3)

Before ÷ after = 35,511 / (-2,658) = **-13.4**, which is not a drop factor because the after figure is negative. The after figure is below one tenth of the before figure (3,551), but it rests on exactly two complete UTC days, both with a fold still working off rows retained at the cutover; it is a transitional measurement. **The order-of-magnitude drop at steady state is not claimed.** The report's `~2,381 cells a day` compact-design line is a projection and was not used. A steady-state re-read is due after about 7 more complete UTC days.

## Success criteria labels (as written in STATUS)

| SC | Label |
|---|---|
| SC1 | live (public logs: 40924656021, 40926644214, 41373351559, 41375348321, 107 of 108 compact runs) for writes, reads and the zero-difference check; mocked for "no alert twice" and chunk limits (`test_storage_pipeline` tests named in STATUS); owner check pending for the hidden tabs and Telegram |
| SC2 | live (public logs: 40927423338, 41364810371 `3 of 3`, 41375689814, 42301084151); owner check pending for the Dashboard figures |
| SC3 | live for the swap, row counts, cells and load time (41373351559, 41549615660, 42300947285); the order-of-magnitude drop is not claimed; mocked for the >=10x test on synthetic data |
| SC4 | mocked (`test_a_cut_off_compact_baseline_is_a_baseline_pass_again_with_nothing_alerted`, `test_a_seed_whose_tally_append_fails_is_completed_by_the_next_run_with_nothing_written_twice`); never produced live |

## Task Commits

1. **Task 2: PILOT_LOG cutover row and STATUS "Phase 3 cutover (live)"** - `f3c55e9` (docs)
2. **Task 3: first fold, measured growth, success criteria** - `77fc486` (docs)

Task 1 changed no files.

## Mocked versus live

- **Live (public GitHub data):** the cutover, the folds, the integrity-check lines, the storage report and parity runs named above, all read from public Actions logs (secret-pattern scan of every log quoted: 0 matches).
- **Mocked / offline only:** SC4, "no alert twice", the 500-request `deleteDimension` batch (research A5; the log prints ranges, not batch sizes), the chunk limits.
- **Not verified (no Sheet credentials):** anything inside the Sheet (hidden tabs, `Events_Legacy` protection prompt, Dashboard Storage line and READY TO CUT OVER text, `Discovery` key `storage`, Telegram chat); EDGE-STOR-01 stays open for manual review.

## Deviations from Plan

**1. [Process] Task 3 precondition read as met with the minimum of two days.** The precondition asks for a fold run and two complete UTC days since it; the days used are 2026-11-04 and 2026-11-05 (the report's own minimum), so the run happened on 2026-11-06 with no more than two days in the after figure. The result is recorded as transitional rather than waiting, as the dispatching orchestrator instructed. No code, workflow or setting changed.

**2. [Process] Worktree base.** The worktree started at 68a7253, not at f3c55e9; it was fast-forwarded to f3c55e9 (Task 2's commit) before any change.

## Issues Encountered

None in storage. One failed poller run (41669619936), a transient Google Sheets 500 in the tracker append, recorded in STATUS and PILOT_LOG; nothing was fixed or restored.

## Threat Flags

None. No code, workflow or endpoint changed.

## Known Stubs

None.

## Next Phase Readiness

STOR-01 parity is accepted for board growth gating (zero differences on every logged check since the seed). Open before calling Phase 3 fully verified: the owner's Sheet checks, a steady-state `--storage-report` after about 7 more complete UTC days, A5 and EDGE-STOR-01, and the owner's decision whether to delete `Events_Legacy` to return its 1,650,502 cells.

## Self-Check: PASSED

- FOUND: PILOT_LOG.md first-fold row (`grep -ci "first fold"` = 1), STATUS.md closing table (`grep -c "Phase 3 success criteria"` = 2)
- FOUND: commits f3c55e9 and 77fc486 on the branch (`git merge-base --is-ancestor`)
- FOUND: `Ran 910 tests ... OK`
