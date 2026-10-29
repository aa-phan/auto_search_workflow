---
gsd_state_version: "1.0"
milestone: v2.0
milestone_name: Search-substitute volume
current_phase: 3
current_phase_name: Compact storage
status: planning
stopped_at: Phase 02 complete, ready to plan Phase 3
last_updated: "2026-10-29T00:04:10.796Z"
last_activity: 2026-10-28
last_activity_desc: Phase 02 complete, transitioned to Phase 3
state_head: d5f3857639b1d3bbcb1160a7da99c4e50d5bc57a
progress:
  total_phases: 6
  completed_phases: 2
  total_plans: 9
  completed_plans: 9
  percent: 29
---

# Project State

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-10-28)

**Core value:** A relevant job reaches the user within 12 hours of its source publication, and nothing of unverified age is ever presented as fresh.
**Current focus:** Phase 3 — Compact storage

## Current Position

Phase: 3 — Compact storage
Plan: Not started
Status: Ready to plan
Last activity: 2026-10-28 — Phase 02 complete, transitioned to Phase 3

Progress: [███░░░░░░░] 29%

## Performance Metrics

**Velocity:**
- Total plans completed: 9 (v2.0)
- Average duration: -
- Total execution time: -

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 02 | 9 | - | - |

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
| Phase 02 P08 | ~1h across two invocations | 3 tasks | 6 files |

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
- [Phase 02]: Owner-read Groq console figures (read 2026-10-26, recorded in D-53): free plan; openai/gpt-oss-120b and openai/gpt-oss-20b each 30 RPM, 1K RPD, 8K TPM, 200K TPD; zero data retention not enabled (neither global nor inference API). Plan choice and resume-to-Groq answer given 2026-10-28 (D-53).
- [Phase 02]: D-53: Groq plan free-revisit (stay free, revisit before Phase 4); resume to Groq ok; Groq_Daily_Token_Budget default 100000 per model (half the owner-read 200,000, rolling window); 20-30 a day target conditional (about 75 evaluations / 12 rows a day)
- [Phase 02]: D-54 (2026-10-28): owner keeps SmartRecruiters polled; P2-14 parking withdrawn; plan 02-09 superseded, nothing deployed.

### Pending Todos

- Daily check scheduled for 2026-10-25 12:00 UTC ran; findings are in STATUS.md. Repeat daily until Phase 3 lands.
- First weekly rebalance about 2026-10-29 01:00 UTC: watch it in the daily checks; the formal read is EVID-01 in Phase 5.
- Owner: decide whether tracker row greenhouse|nadiacare|4459849009 stays deleted or is restored (02-UAT test 2 left it open).
- User to check that the employer behind 6 of 14 recent tracker rows (Alphabe Insight Inc, SmartRecruiters) is genuine.

### Blockers/Concerns

- [Phase 2] Groq plan D-53: free, budget default 100,000 per model, pushed 2026-10-28 (1d63416) and read by the owner in the Runs tab; revisit the plan before Phase 4; the 20-30 target stays conditional (about 75 evaluations / 12 rows a day).
- [Phase 2] Governors (15/20/22 min cutoffs, 5-attempt alert bound, WR-01 lock expiry) are offline-verified only; none has fired in production yet.
- [Phase 2] 1 ledger-kept job is missing from the tracker (greenhouse|nadiacare|4459849009, 54 of 55); owner keep-or-restore decision pending.
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

Last session: 2026-10-29T00:10:00Z
Stopped at: Phase 02 complete, ready to plan Phase 3
Resume file: None
