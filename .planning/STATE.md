---
gsd_state_version: "1.0"
milestone: v2.0
milestone_name: Search-substitute volume
current_phase: 2
current_phase_name: Measurement, governors and owner decisions
status: planning
stopped_at: Phase 2 context gathered
last_updated: "2026-10-26T04:44:07.779Z"
last_activity: 2026-10-25
last_activity_desc: v2.0 roadmap created (6 phases, 26 of 26 requirements mapped)
state_head: af8d9e90e4142452164bd8b998636f1fe7aeac4f
progress:
  total_phases: 6
  completed_phases: 1
  total_plans: 0
  completed_plans: 0
  percent: 17
---

# Project State

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-10-25)

**Core value:** A relevant job reaches the user within 12 hours of its source publication, and nothing of unverified age is ever presented as fresh.
**Current focus:** Phase 2: Measurement, governors and owner decisions (first of the 6 v2.0 phases, Phases 2-7)

## Current Position

Phase: 2 of 7 (Measurement, governors and owner decisions); 1 of 6 in milestone v2.0
Plan: not planned yet
Status: Ready to plan
Last activity: 2026-10-25 — v2.0 roadmap created (6 phases, 26 of 26 requirements mapped)

Progress: [██░░░░░░░░] 17%

## Performance Metrics

**Velocity:**
- Total plans completed: 0 (v2.0)
- Average duration: -
- Total execution time: -

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

*Updated after each plan completion*

## Accumulated Context

### Decisions

Authoritative log: `DECISIONS.md` (D-01..D-47). Recent: D-45 graduation floor, D-46 tracker header refusal, D-47 early release and 5,000 re-checks per inventory run.

Roadmap decisions for v2.0 (2026-10-25):
- Order is governors, compact storage, backfill, board growth, adapters, search; storage is Phase 3 because Events passes the D-03 200k point about 2026-10-29 and nothing that adds rows or load runs before parity.
- Phases 3 and 4 never overlap (both touch `ledger.observe_new` and the run-cycle observation block); board growth waits for backfill so admitted boards' recent jobs are scored.
- The 20-30 a day target is conditional on the Groq plan decision (MEAS-02).

### Pending Todos

- Daily check scheduled for 2026-10-25 12:00 UTC ran; findings are in STATUS.md. Repeat daily until Phase 3 lands.
- First weekly rebalance about 2026-10-29 01:00 UTC: watch it in the daily checks; the formal read is EVID-01 in Phase 5.
- Surface the GOV-01 decisions to the owner at the start of Phase 2 (table in ROADMAP.md).
- User to check that the employer behind 6 of 14 recent tracker rows (Alphabe Insight Inc, SmartRecruiters) is genuine.

### Blockers/Concerns

- Phase 2: Groq tier, limits and tokens per call are unverified; the target depends on them.
- Phase 2: 2 ledger-kept jobs are missing from the tracker (should be 0), not investigated; MEAS-01 counts tracker rows.
- Phase 3: Events 186,430 rows on 2026-10-25, about 3,355 rows a day, so the D-03 200k point arrives about 2026-10-29.
- Open owner decisions (GOV-01) and the 6 ingest warnings: `.planning/INGEST-CONFLICTS.md`.
- Hourly cadence depends on an external trigger (GitHub's own schedule fires about every 4.4 h).

## Deferred Items

Items acknowledged and deferred at milestone close, most recent first:

| Category | Item | Status | Deferred At | Milestone |
|----------|------|--------|-------------|-----------|
| *(none)* | | | | |

Future requirements (FEAT-01, FILT-03, MAINT-01..02, REL-03..05, EVID-06, ADPT-08, SCALE-02) are listed in REQUIREMENTS.md.

## Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 261014-olj | Board slot allocation (pools, evidence refresh, bounded weekly rebalance, queues, SR parking) | 2026-10-14 | f5d9fda | [261014-olj-board-slot-allocation](./quick/261014-olj-board-slot-allocation/) |

## Session Continuity

Last session: 2026-10-26T04:44:07.767Z
Stopped at: Phase 2 context gathered
Resume file: .planning/phases/02-measurement-governors-and-owner-decisions/02-CONTEXT.md
