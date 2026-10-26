---
gsd_state_version: "1.0"
milestone: v2.0
milestone_name: Search-substitute volume
current_phase: 02
current_phase_name: Measurement, governors and owner decisions
status: executing
stopped_at: Completed 02-07-PLAN.md
last_updated: "2026-10-26T19:26:04.960Z"
last_activity: 2026-10-26
last_activity_desc: Phase 02 execution started
state_head: 6e2012f2e7e6e47c9f847ebbfce7abfe96812d44
progress:
  total_phases: 6
  completed_phases: 1
  total_plans: 9
  completed_plans: 7
  percent: 17
---

# Project State

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-10-25)

**Core value:** A relevant job reaches the user within 12 hours of its source publication, and nothing of unverified age is ever presented as fresh.
**Current focus:** Phase 02 — Measurement, governors and owner decisions

## Current Position

Phase: 02 (Measurement, governors and owner decisions) — EXECUTING
Plan: 8 of 9
Status: Ready to execute
Last activity: 2026-10-26 — Phase 02 execution started

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
**Per-Plan Metrics:**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 02 P01 | 3 min | 2 tasks | 8 files |
| Phase 02 P02 | 7 min | 3 tasks | 8 files |
| Phase 02 P03 | 7 min | 3 tasks | 10 files |
| Phase 02 P04 | 7 min | 3 tasks | 9 files |
| Phase 02 P05 | 5 min | 3 tasks | 5 files |
| Phase 02 P06 | 12 min | 2 tasks | 7 files |
| Phase 02 P07 | 1h | 3 tasks | 2 files |

## Accumulated Context

### Decisions

Authoritative log: `DECISIONS.md` (D-01..D-47). Recent: D-45 graduation floor, D-46 tracker header refusal, D-47 early release and 5,000 re-checks per inventory run.

Roadmap decisions for v2.0 (2026-10-25):
- Order is governors, compact storage, backfill, board growth, adapters, search; storage is Phase 3 because Events passes the D-03 200k point about 2026-10-29 and nothing that adds rows or load runs before parity.
- Phases 3 and 4 never overlap (both touch `ledger.observe_new` and the run-cycle observation block); board growth waits for backfill so admitted boards' recent jobs are scored.
- The 20-30 a day target is conditional on the Groq plan decision (MEAS-02).
- [Phase 02]: D-48 is one entry listing all eleven GOV-01 owner decisions with state, needed-by and default; pending items get their own D-number when decided — Keeps the list in one place and leaves undecided items labelled pending with their default (AGENTS rule 1, GOV-01)
- [Phase 02]: Repository stays public; DEPLOY, README, D-37 note, STATUS, CONCERNS and INGEST-CONFLICTS corrected to say so (P2-15) — History check found no CSV, resume or PDF paths in any commit
- [Phase 02]: D-49: an alert is recorded only when a channel accepted it; alert sends without an HTTP response are bounded at 5 (owner decision P2-18) — Amends D-07 and D-21 for the alert stage; recorded exception to AGENTS rule 4 (AGENTS.md not edited); accepted risk: a 5-run alert-channel outage abandons pending alerts
- [Phase 02]: D-50: per-model UTC-day Groq token budget (170000 default, provisional) with a 20% verified-fresh reserve; budget skips record nothing and use no attempt — Groq daily token limit is not in any header; budget-driven fallback accepted by the owner as the D-16 OK; scoring rule, prompt and Min_Alert_Score unchanged (AGENTS rule 7)
- [Phase 02]: D-51: run deadlines from process start (poll 15, Groq 20, alerts 22 min) and longest-unpolled-first polling — Keeps every run inside the 25-minute workflow timeout; poll and alert cuts degrade the run, an evaluation cut leaves it ok; nothing is recorded against a cut board, job or alert
- [Phase 02]: Alert cutoff cut makes the run degraded (discretion choice, not part of P2-07) — A fresh alert waiting another hour deserves the owner's attention; keep EVAL_CUTOFF_MINUTES below 22
- [Phase 02]: D-52: day of a tracker row comes from the ledger evaluated instant in the display time zone, not the user-formatted Date_Found text — Date_Found is display text Sheets may re-render; the evaluated event is the same moment it was written. Flagged for the owner's acceptance
- [Phase 02]: D-52: the NEEDS ATTENTION row for ledger-kept jobs missing from the tracker is applied literally (P2-12); the 20-30 band is two constant LINE series with BAND_LINES_STACK as the switch — Shows whenever the all-time mismatch is not 0, so the 2 jobs flagged on 2026-10-25 stay visible until resolved; Sheets stacking of LINE series is unverified (A7), checked live in plan 02-07
- [Phase 02]: 02-06: scored_by_model counts only evaluations that reached scoring; Groq budget record from an earlier UTC day shows 0 used today — gate rejections never call Groq; eval_budget rolls the budget at UTC midnight
- [Phase 02]: 02-06: public pilot log prints only x-ratelimit-* values and model ids matching strict allow patterns — T-02-16: a damaged or hand-edited Groq_Limits record must not leak text into a public log
- [Phase 02]: 02-07: Phase 2 deployed 2026-10-26 18:25 UTC (fc197c1); first run success with no cut, pilot report and one delivery test (telegram_sent true) live; Sheet render, Telegram arrival and the missing tracker row greenhouse|nadiacare|4459849009 are owner checks

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
- 02-08 waits for one full UTC day of production runs on fc197c1 (owner chose wait, 2026-10-26); resume /gsd-execute-phase 2 at or after 2026-10-28 00:05 UTC. 02-09 also waits for the first weekly rebalance (~2026-10-29 01:00 UTC).

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

Last session: 2026-10-26T19:17:30.667Z
Stopped at: Completed 02-07-PLAN.md
Resume file: None
