---
phase: 03-compact-storage
plan: 08
subsystem: deployment
tags: [deploy, cutover-tooling, dual-mode, parity-clock, pilot-log]

requires:
  - phase: 03-compact-storage
    provides: "plans 03-06 and 03-07: storage_cutover and storage_restore inputs, the fold, the storage report, the compact integrity check"
provides:
  - "Cutover tooling live on main (2eedc23..2556c41, pushed 2026-10-30T00:59:02Z on the owner's choice deploy, restore input kept)"
  - "Confirmation from run 40983170540 that dual mode is unchanged: 0 counted and 0 declared differences, a check recorded, no storage note, no fold"
  - "PILOT_LOG timeline row and a STATUS paragraph with the parity clock as read and the owner's next step"
affects: [03-09 live cutover and first fold]

actuals:
  tokens: 4000
  tasks: 3
  commits: 1
plan_head_before: 2556c41f7fc9c90b67ed73b76f723e80b276ef45
plan_head_after: cb8278356bb43b3b6a12d0c1d4cd32969d8a42ce
commits: 1

tech-stack:
  added: []
  patterns:
    - "a deployment is confirmed from the next hourly run's public log (counts, run id, setting names only, scanned for secret patterns before quoting), not from the push itself"

key-files:
  created: []
  modified:
    - PILOT_LOG.md
    - STATUS.md

key-decisions:
  - "The owner chose deploy (restore input kept); job_hunter.yml and tests/test_deployment.py were not edited"
  - "No workflow run was dispatched for this plan; the confirming run is the hourly external dispatch"
  - "The restore input is recorded in STATUS as the P3-06 refinement the owner accepted at deploy"

requirements-completed: []  # STOR-01 stays open: the owner's cutover and first fold are plan 03-09

coverage:
  - id: D1
    description: "The cutover tooling reaches production only by a push after the owner's explicit deploy choice; the push is main 2eedc23..2556c41 at 2026-10-30T00:59:02Z"
    requirement: STOR-01
    verification:
      - kind: manual
        ref: "git rev-parse --short origin/main = 2556c41; gh run list headSha of run 40983170540 = 2556c41"
        status: pass
    human_judgment: false
  - id: D2
    description: "Dual mode is unchanged on the first run after the deploy: mode=dual, 0 counted and 0 declared differences, a check recorded, no storage note, no fold"
    requirement: STOR-01
    verification:
      - kind: manual
        ref: "public log of run 40983170540 (workflow success): Storage line and Run line; grep for fold = 0"
        status: pass
    human_judgment: false
  - id: D3
    description: "PILOT_LOG row naming storage_cutover and the D-57 cutover tooling; STATUS paragraph with the confirming run, the clock reading and the owner's next step"
    requirement: STOR-01
    verification:
      - kind: manual
        ref: "grep -c storage_cutover PILOT_LOG.md = 1; grep -ci 'cutover tooling' STATUS.md = 2"
        status: pass
    human_judgment: false
  - id: D4
    description: "The cutover, restore, fold and compact integrity check running against the real Sheet"
    requirement: STOR-01
    verification: []
    human_judgment: true
    rationale: "Compact mode needs the owner's cutover (plan 03-09); until then every check of that code is mocked"

duration: about 10min (continuation: wait for the confirming run plus the two documents)
completed: 2026-10-30
status: complete
---

# Phase 3 Plan 08: Deploy the cutover tooling and confirm dual mode is unchanged Summary

**The cutover, restore, fold, storage-report and compact-integrity-check code is live on `main` (2556c41, pushed 2026-10-30 00:59:02 UTC on the owner's choice `deploy`), and the first run on it (40983170540) still wrote as dual with 0 counted and 0 declared differences, a check recorded and no storage note or fold.**

## Performance

- **Tasks:** 3 of 3 (Task 1 gate and Task 2 owner decision ran in the orchestrator; Task 3 here)
- **Tests:** `Ran 910 tests ... OK` (re-run before the commit; gate result from Task 1 identical)

## Accomplishments

- Task 1 (orchestrator): suite OK, 12 commits `origin/main..HEAD` from plans 03-06 and 03-07, secret-pattern and file-name scan of the outgoing diff clean, clock read from run 40936035396 (2026-10-29T19:00:08Z).
- Task 2 (owner decision): `deploy`, restore input kept. The orchestrator fast-forwarded `main` and pushed `2eedc23..2556c41` at 2026-10-30T00:59:02Z. This agent did not push.
- Task 3: waited for the next poller run on 2556c41 and read its public log (secret-pattern scan: 0 matches). Run 40983170540 (hourly external dispatch, created 01:00:08 UTC, completed `success`):
  - `Storage: mode=dual, 0 counted and 0 declared differences, 204000 job keys and 433 Tally runs compared, 2 checked runs today, 0 of 3 complete days toward the bar, admission seen no, check took 24.1 s`
  - `Run: boards 695 ok / 5 failed of 700 (+0 new) | new jobs 65 (65 verified fresh) | evaluated 1 | alerts 0 sent / 0 failed | gap since previous run 59 min, worst board gap 119 min`
  - no `storage` note and no `fold` text anywhere in the log; the only WARNING is the existing SmartRecruiters setting notice.
- PILOT_LOG.md: one timeline row for 2026-10-30 00:59 (2556c41), naming `storage_cutover` and `storage_restore`.
- STATUS.md: a dated "Cutover tooling deployed" subsection under the Phase 3 live section, with the confirming run id, the counted differences as read (0), the clock reading (`0 of 3 complete days`, 2 checked runs on 2026-10-30, earliest READY TO CUT OVER still 2026-11-02 00:00 UTC), the note that the restore input is the P3-06 refinement the owner accepted at deploy, and the owner's next step (dispatch `storage_cutover` when the Dashboard says READY TO CUT OVER; see DEPLOY.md).

## Task Commits

1. **Task 3: PILOT_LOG row and STATUS paragraph** - `cb82783` (docs)

Tasks 1 and 2 changed no files.

## Mocked versus live

- **Live (public GitHub data):** the push (git, `gh run list` headSha), run 40983170540's workflow conclusion and its Storage and Run log lines.
- **Mocked / offline only:** the cutover, restore, fold, compact integrity check and the before/after storage report. They have never run against the real Sheet because compact mode needs the owner's cutover.
- **Not verified (no Sheet credentials):** anything inside the Sheet (Dashboard Storage line, `Runs.Notes`, hidden tabs, `Discovery.storage`); the six owner checks listed in STATUS stay pending.

## Deviations from Plan

None. The plan's Task 3 verify `origin/main == HEAD` does not hold after the docs commit by design (the orchestrator pushes docs commits afterwards); `origin/main` is 2556c41 as required and both greps pass (1 and 2).

## Issues Encountered

None. The wait was short: the hourly dispatch started 61 s after the push and finished about 3.5 minutes later.

## Threat Flags

None. No code, workflow or endpoint changed in this plan.

## Known Stubs

None.

## Next Phase Readiness

Plan 03-09 is the owner's live cutover. The parity bar is not met: 0 of 3 clean complete UTC days, the first countable day (2026-10-30) is running, earliest READY TO CUT OVER 2026-11-02 00:00 UTC. Nothing was dispatched here (`storage_cutover` and `storage_restore` remain untouched).

## Self-Check: PASSED

- FOUND: PILOT_LOG.md row (`grep -c storage_cutover` = 1), STATUS.md paragraph (`grep -ci "cutover tooling"` = 2)
- FOUND: commit cb82783 on gsd/phase-03-compact-storage; `origin/main` = 2556c41
