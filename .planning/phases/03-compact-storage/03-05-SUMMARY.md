---
phase: 03-compact-storage
plan: 05
subsystem: storage
tags: [deployment, live-verification, dual-write, seed, parity, pilot-log]

requires:
  - phase: 03-compact-storage
    provides: "plans 03-01..03-04: Identity and Tally dual write, seed, in-run parity, Storage line, storage_parity input"
provides:
  - "Dual-write storage running in production from f8c8263 (pushed 2026-10-29 17:46:37 UTC)"
  - "Live evidence: seed run 40924656021, first check run 40926644214, read-only parity run 40927423338"
  - "PILOT_LOG.md timeline row for D-57 and STATUS.md section 'Phase 3 live verification (dual write)'"
  - "The parity clock's first countable day: 2026-10-30"
affects: [03-06 cutover and restore, 03-07 fold, owner Sheet checks]

actuals:
  tokens: 2232
  tasks: 3
  commits: 1
plan_head_before: f8c826319931a90d8bd6013479913c91cc364759
plan_head_after: edd52c33368c0b680cbfe3886d922e3cf7cf036a
commits: 1

tech-stack:
  added: []
  patterns:
    - "live evidence is read from public Actions logs only (counts, run ids, setting names), scanned for secret patterns before quoting; Sheet-side facts stay owner checks"

key-files:
  created: []
  modified:
    - PILOT_LOG.md
    - STATUS.md

key-decisions:
  - "Owner chose deploy-and-dispatch: one normal poller run right after the push and one read-only storage_parity run after the next poller run"
  - "The clock's first countable day is 2026-10-30 (seed at 2026-10-29T17:47:52Z; the seed day never counts); earliest READY TO CUT OVER is 2026-11-02 00:00 UTC"

requirements-completed: [STOR-01]

coverage:
  - id: D1
    description: "Dual writing deployed with the owner's explicit choice; PILOT_LOG row with push time, commit, what changed and what is not comparable"
    requirement: STOR-01
    verification:
      - kind: command
        ref: "git fetch origin main && git rev-parse origin/main = f8c8263; grep -c D-57 PILOT_LOG.md = 1"
        status: pass
    human_judgment: false
  - id: D2
    description: "The seed on the real ledger and the first in-run check, read from the public logs: no storage failure note, 0 counted and 0 declared differences, check about 25 s"
    requirement: STOR-01
    verification:
      - kind: command
        ref: "gh run view 40924656021 / 40926644214 / 40927423338 --log, filtered for storage lines; secret-pattern scan 0 matches"
        status: pass
    human_judgment: false
  - id: D3
    description: "Sheet-side facts (hidden Identity and Tally tabs, confirmation prompt on Identity, Events row count, Storage line render, Discovery key) are not readable without Sheet credentials"
    requirement: STOR-01
    verification: []
    human_judgment: true
    rationale: "AGENTS rule 5: no live claim without evidence; the six owner checks are listed in STATUS 'Phase 3 live verification (dual write)'"
---

# Phase 3 Plan 05: Live dual-write deployment Summary

**Dual-write storage deployed to production (f8c8263, 2026-10-29 17:46:37 UTC): the first run seeded 201,789 posting IDs, 991 Identity rows and 424 historical Tally runs with no storage failure, and the first in-run check and the read-only parity run both counted 0 differences in about 25 s**

## Accomplishments

- **Pre-deploy gate (Task 1, by the orchestrator, no files).** Suite `Ran 787 tests ... OK`; 28 commits `origin/main..HEAD`; the secret-pattern scan matched only the regex text inside two PLAN files (false positive, no code file); the file-name scan was clean.
- **Owner decision (Task 2).** The owner chose `deploy-and-dispatch`. The orchestrator fast-forwarded local `main` and pushed `c8c559d..f8c8263` at 17:46:37 UTC; this continuation did not push again.
- **Seed run 40924656021** (manual dispatch 17:47:21 UTC, on f8c8263): workflow `success`; log `Storage seed: 201789 IDs written in 991 Identity rows for 947 boards, 424 Tally runs written`; the seed took about 30 s; `Run: boards 693 ok / 7 failed of 700, new jobs 211 (190 verified fresh), evaluated 4, alerts 0 sent / 0 failed`; no `storage write failed` or `storage repair failed`; process about 4 min 25 s. The warning-only protection on Identity did not stop the service account's writes (assumption A2 confirmed for the writes; the confirmation prompt is an owner check).
- **First check run 40926644214** (external hourly dispatch 18:00:08 UTC): `Storage: mode=dual, 0 counted and 0 declared differences, 203200 job keys and 425 Tally runs compared, 1 checked runs today, 0 of 3 complete days toward the bar, admission seen no, check took 24.6 s`.
- **Read-only parity run 40927423338** (`storage_parity=true`, 18:05:01 UTC): exit 0, `0 counted differences, 0 declared`, seen_keys 203234, identity_entries 202028, tally_groups 426, check 24.75 s, `clock: 0 of 3 ... bar met no`, nothing written.
- **Records.** PILOT_LOG.md timeline row (push time, commit, what changed, what is not comparable: `Runs.Load_S` and `Duration_S` now include the Identity and Tally reads and the check; the seed run is a one-off; two hand-dispatched runs). STATUS.md section `## Phase 3 live verification (dual write)` with the live/mocked table, the clock (first countable day 2026-10-30, earliest ready 2026-11-02 00:00 UTC) and six owner checks pending. The STATUS header lines now say deployed instead of not deployed.

## Task Commits

| Task | Name | Commit |
|---|---|---|
| 1 | Pre-deploy gate | no commit (orchestrator, no files changed) |
| 2 | Owner decision | no commit (checkpoint, resolved deploy-and-dispatch) |
| 3 | Push (orchestrator), read the logs, record | `edd52c3` (docs: PILOT_LOG row and STATUS section) |

The deployed code commit is f8c8263 (pushed by the orchestrator before this agent started; `plan_head_before` is that commit, so `commits: 1` counts only this agent's docs commit).

## Deviations from Plan

**1. Task 3 verify `origin/main == HEAD` does not hold after the docs commit.** Docs commits stay on `gsd/phase-03-compact-storage` and the orchestrator fast-forwards and pushes main afterwards (instruction of the sequential run). Verified instead: `git rev-parse origin/main` is f8c8263 (the deployed commit) and both greps print 1. **Total deviations:** 1 (procedural). **Impact:** none on production.

## Authentication Gates

None. The agent used only `gh` against public logs; it read no `.env`, no service-account file and no Sheet.

## Issues Encountered

None. Three runs, all `success`; no storage note; no secret pattern in any log (0 matches in each).

## Known Stubs

None.

## Threat Flags

None. No code changed in this plan.

## Next Phase Readiness

- The clock is running: first countable UTC day 2026-10-30; needs three clean complete days with 12 checked runs each and one admission; the earliest `READY TO CUT OVER` is 2026-11-02 00:00 UTC. Any counted difference restarts it.
- Owner checks pending in the Sheet (listed in STATUS): hidden `Identity` and `Tally` tabs, the confirmation prompt on Identity, Events row count not reduced, the Dashboard Storage line and absence of a `storage parity difference` row, the Discovery key `storage`, no storage note in `Runs.Notes`.
- The live check takes about 25 s against about 6.4 s measured offline on a synthetic ledger; it is far below the 22 min skip limit but worth knowing for run-time statistics.
- Ready for plans 03-06 (cutover and restore) and 03-07 (fold) once the bar is met and the owner decides.

## Self-Check: PASSED

- `PILOT_LOG.md` and `STATUS.md` exist and carry the row and the section (`grep -c D-57 PILOT_LOG.md` 1, `grep -c "## Phase 3 live verification (dual write)" STATUS.md` 1).
- Commit `edd52c3` is an ancestor of HEAD; `git rev-parse origin/main` is f8c8263.
- Suite after the edits: `Ran 787 tests ... OK`.
