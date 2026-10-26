---
phase: 02-measurement-governors-and-owner-decisions
plan: 01
subsystem: governance
tags: [decisions, owner-decisions, docs, repository-visibility]

requires:
  - phase: 01-foundation
    provides: DECISIONS.md D-01..D-47 and the v2.0 ROADMAP Owner Decisions table
provides:
  - "DECISIONS.md D-48: one table of the eleven GOV-01 owner decisions (state, needed-by phase, default, source)"
  - "ROADMAP Owner Decisions section and Phase 4 entry gate pointing at D-48"
  - "DEPLOY, README, D-37 note, STATUS, CONCERNS and INGEST-CONFLICTS saying the repository is public"
affects: [02-02, 02-08, 02-09, phase-03, phase-04, phase-05, phase-06, phase-07]

actuals:
  tokens: 6000
  tasks: 2
  commits: 2
plan_head_before: 248db701d7fbcc2c9b0be1f5c952ce6a60e2be08
plan_head_after: c641d3e6ba5c72533aee7707f458a9907c2250b0

tech-stack:
  added: []
  patterns:
    - "Pending owner decisions are listed in one D-entry with needed-by and default; the row is annotated 'decided in D-NN' when the owner decides"

key-files:
  created: []
  modified:
    - DECISIONS.md
    - .planning/ROADMAP.md
    - DEPLOY.md
    - README.md
    - STATUS.md
    - .planning/codebase/CONCERNS.md
    - .planning/INGEST-CONFLICTS.md

key-decisions:
  - "D-48 is one entry with an eleven-row table, not eleven D-numbers; later decisions get their own D-number and the row is annotated"
  - "Only items the owner has decided are marked decided (fallback model, SmartRecruiters parked, repository public, date-only alerts, alert network errors bounded); Groq plan, D-05 amendment, rule-7 lift, per-ATS policy, storage approval and Groq data handling stay pending with a default"

patterns-established:
  - "Owner-decision inventory: Decision / State / Needed by / Default if unanswered / Source, each decided row citing its CONTEXT P2-xx ID"

requirements-completed: []

coverage:
  - id: D1
    description: "DECISIONS.md D-48 lists all eleven GOV-01 owner decisions with state, needed-by phase, default and CONTEXT source; ROADMAP points at it"
    requirement: "GOV-01"
    verification:
      - kind: other
        ref: "grep -c '^## D-48 Owner decisions for v2.0' DECISIONS.md (1); D-48 table has 13 lines starting '| ' (header, separator, 11 rows) and contains all 16 required strings; ROADMAP has 'listed as pending in D-48' and 'DECISIONS.md D-48' and no 'D-05 amendment (D-48)'"
        status: pass
    human_judgment: true
    rationale: "Whether each row's state (decided or pending) and default matches what the owner actually decided is a judgment only the owner can confirm; grep proves the entry exists and is complete in shape"
  - id: D2
    description: "No document still says the repository is or must be private (DEPLOY, README, D-37 note, STATUS, CONCERNS, INGEST-CONFLICTS)"
    requirement: "GOV-01"
    verification:
      - kind: other
        ref: "history check `git log --all --name-only -- '*.csv' 'tracked_jobs*' 'resume*' 'Resume*' '*.pdf'` prints no paths; grep checks for 'Use a private repository' (0), '--private' in DEPLOY.md (0), 'The repository is public' in README.md and DEPLOY.md, 'Amended by D-48', 'public repo (D-48)', 'Resolved 2026-10-26 (D-48)', and 3 'RESOLVED 2026-10-26' lines in INGEST-CONFLICTS.md with 0 deleted lines"
        status: pass
    human_judgment: false

duration: 3min
completed: 2026-10-26
status: complete
---

# Phase 2 Plan 01: Owner-decision inventory and public-repository corrections Summary

**DECISIONS.md D-48 lists all eleven GOV-01 owner decisions with state, needed-by phase and default, ROADMAP points at it, and six documents now say the repository is public.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-10-26T17:39:59Z
- **Completed:** 2026-10-26T17:43:00Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- D-48 (2026-10-26) records five decided items with their CONTEXT source (fallback model P2-03, SmartRecruiters parked P2-14 with its costly reversibility, repository public P2-15, date-only alerts P2-16, alert network errors bounded at 5 P2-18) and six pending items each with needed-by and default (Groq plan, D-05 amendment, rule-7 lift, per-ATS policy, storage approval, Groq data handling).
- ROADMAP's Owner Decisions section names D-48 as the list; the Phase 4 entry gate no longer reserves D-48 for the D-05 amendment.
- Read-only history check passed (no CSV, resume or PDF paths in any of the 56 commits, all refs). DEPLOY.md, README.md, the D-37 note, STATUS.md and CONCERNS.md were corrected to the public-repository decision; three INGEST-CONFLICTS warnings were marked RESOLVED without deleting text.

## Task Commits

1. **Task 1: D-48 owner-decision inventory (tracer)** - `0ee79f3` (docs)
2. **Task 2: Repository-visibility documents** - `c641d3e` (docs)

**Plan metadata:** committed with this summary (docs: complete plan)

## Files Created/Modified

- `DECISIONS.md` - new D-48 entry with the eleven-row owner-decision table; amendment sentence appended to D-37 "Repository hygiene"
- `.planning/ROADMAP.md` - Owner Decisions sentence and Phase 4 entry gate reference D-48
- `DEPLOY.md` - section 0 bullet, section 1 heading and `gh repo create ... --public`, "Approval needed" wording
- `README.md` - private-repository callout replaced by the public-repository callout
- `STATUS.md` - "private-then-public repo" replaced by "public repo (D-48)"
- `.planning/codebase/CONCERNS.md` - "Repository visibility" marked resolved
- `.planning/INGEST-CONFLICTS.md` - three `RESOLVED 2026-10-26:` lines added

## Decisions Made

- D-48 is a single entry with a table; the flagged assumption in the plan (one entry satisfies "recorded or listed") was followed. If the owner wants one D-number per decision now, the table splits without other changes.
- Pending rows were not promoted to decided; each carries its default (target stays conditional, no backfill, feedback score stays in shadow, build only providers with a recorded decision, proceed with D-43 and delete nothing before parity, keep as is and record the retention setting).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] D-48 table separator row did not match the plan's own check**
- **Found during:** Task 1 verification
- **Issue:** the plan's automated check counts lines starting with `| ` (13 required: header, separator, 11 rows). A separator written `|---|---|...` starts with `|-`, so only 12 lines matched.
- **Fix:** wrote the separator as `| --- | --- | --- | --- | --- |`, which is equally valid markdown.
- **Files modified:** DECISIONS.md
- **Verification:** the Task 1 automated check passes (13 table lines).
- **Committed in:** `0ee79f3`

---

**Total deviations:** 1 auto-fixed (1 bug in check/format match)
**Impact on plan:** None on content.

### Execution-environment note (not a plan deviation)

The pre-commit protected-branch assertion reports `main` as protected. This plan ran in sequential mode on the main working tree as the orchestrator dispatched it (and the project's earlier planning commits are also on `main`), so commits were made on `main`. No `git.allow_default_branch_commits` setting was changed.

## Issues Encountered

- `DECISIONS.md` D-37 and `.planning/INGEST-CONFLICTS.md` said the history "still contains" job-search CSVs. The history check found no such paths (`git log --all --name-only` with the plan's patterns prints nothing). The documents now say so, with the D-37 sentence marked as an amendment; the old D-37 text was left in place.
- `GOV-01` was not marked complete in REQUIREMENTS.md: plans 02-08 and 02-09 also declare it, so the shared-ID gate (`requirements.ready-ids`, 0 of 1 ready) correctly holds it until they finish.

## Known Stubs

None. No code was touched.

## Verification Results

- Task 1 and Task 2 automated checks and every acceptance criterion: PASS (see coverage above).
- `.venv/bin/python -m unittest discover -s tests`: Ran 525 tests, OK (offline, no code changed).
- Mocked vs live: nothing here touched Sheets, Groq or Telegram; the history check is a read-only local `git log`.

## Threat Flags

None. Edits name decision IDs, setting names and counts only; `.env`, `Resume.pdf`, `resume.txt`, `tracked_jobs*.csv` and service-account JSON were never opened or staged.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 02-02 can use D-49 (alert recording); 02-03 D-50, 02-04 D-51, 02-05 D-52, 02-08 D-53 as allocated.
- Owner action still open: the six pending D-48 rows. The earliest are the Groq plan (end of Phase 2) and the storage design approval (before Phase 3 executes; Events passes 200k rows about 2026-10-29).
- Plan 02-09 deploys the SmartRecruiters parking after the first weekly rebalance report (about 2026-10-29 01:00 UTC) is read.

## Self-Check: PASSED

- FOUND: DECISIONS.md `## D-48 Owner decisions for v2.0`, DEPLOY.md, README.md, STATUS.md, `.planning/codebase/CONCERNS.md`, `.planning/INGEST-CONFLICTS.md`, `.planning/ROADMAP.md`
- FOUND commits: `0ee79f3`, `c641d3e` (both ancestors of HEAD)

---
*Phase: 02-measurement-governors-and-owner-decisions*
*Completed: 2026-10-26*
