# Auto Search Workflow

## What This Is

Fresh-job alerts for one non-technical job seeker (entry-level marketing, content and design roles; Texas, New York and US remote/hybrid). The system polls public ATS job boards hourly (Greenhouse, Lever, Ashby, Workable, SmartRecruiters), detects new postings, verifies their freshness from source publication evidence, filters and scores them against the resume with Groq, and delivers matches to a Google Sheet (the only interface: settings in, tracker out) and Telegram. It runs entirely on GitHub Actions with the Sheet as its datastore.

Contract and rationale live outside `.planning/` and win over anything here: `SPEC.md` (contract), `DECISIONS.md` (why, D-01..D-47), `STATUS.md` (what is verified live vs mocked), `AGENTS.md` (agent rules), `PILOT_LOG.md` (deployments that affect measurements). Code map: `.planning/codebase/`.

## Current Milestone: v2.0 Search-substitute volume

**Goal:** 20-30 relevant jobs posted within the last 72 hours reach the Job Tracker every day, enough to replace manual searching, while Telegram alerts stay verified-fresh within 12 hours.

**Target features:**
- Recent backfill: a newly admitted board's jobs posted within 72 h (with a source publication time) are scored and labelled with their real age instead of silently baselined (changes D-05)
- 72-hour tracker window for relevant jobs, age always shown; alerts unchanged
- Scale monitored boards past 700 within measured limits, enabled by the Events storage migration (D-43)
- Faster board cycling from recent relevant posting activity and the user's feedback (lifts the rule-7 gate for board-cycling scores only)
- New ATS adapters for big-employer job sites (Workday, iCIMS, ...; research picks which)
- Wider web search (more roles, fuller use of the credit budget) for jobs on unmonitored boards
- Measurement: tracker rows per day, their age, and My_Feedback evaluation prove the target

**Principle (user, 2026-10-25):** volume over precision as long as every job is recent: skimming a pile of recent jobs is easy, finding recent jobs manually is the hard part.

## Core Value

A relevant job reaches the user within 12 hours of its source publication, and nothing of unverified age is ever presented as fresh.

## Requirements

Full list with verification state: `.planning/REQUIREMENTS.md`.

### Validated

<!-- Shipped in v1.0 and confirmed; pilot week 1 passed 2026-10-15..22. -->

- ✓ Hourly board polling with new-ID detection and baselining (POLL-01..03) — v1.0
- ✓ Freshness classes from source publication evidence; only verified-fresh alerts (FRESH-01..02) — v1.0
- ✓ Separate retryable seen / evaluated / alerted stages, one writer at a time (STATE-01..02; offline-verified) — v1.0
- ✓ Job Tracker by header name and Telegram alerts (DLVR-01..02) — v1.0
- ✓ Title gate, hard rules and Groq scoring (FILT-01..02) — v1.0
- ✓ Board registry from public inventories, single admission path, pools with weekly rebalance, floor and early release, Tavily discovery, provider limits (BRD-01..05) — v1.0
- ✓ Dashboard, missed-run watchdog, pilot / storage / rebalance reports (OPS-01..03) — v1.0
- ✓ Secrets and personal data hygiene (SEC-01) — v1.0

### Active

<!-- v2.0 scope; REQ-IDs in .planning/REQUIREMENTS.md once defined. -->

- [ ] 20-30 recent (<= 72 h) relevant jobs per day in the tracker
- [ ] Recent backfill on board admission (D-05 change)
- [ ] More boards (past 700) with storage that scales
- [ ] Faster, feedback-informed board cycling
- [ ] New ATS adapters
- [ ] Wider web search
- [ ] Measured outcome: rows per day, age, feedback

### Out of Scope

- Tuning the job scorer (Groq score, Min_Alert_Score) — still gated by AGENTS.md rule 7 unless My_Feedback evidence (EVID-05) supports a change; board-cycling scores are in v2.0 scope
- Non-US markets — excluded by design (D-08)
- Alerting on anything not verified fresh within 12 h — the core value
- Email / SMS, web UI — the Sheet and Telegram are the only interfaces
- Parity with job boards — only polled boards have the hourly guarantee (SPEC "Honest limits")

## Context

- **Live state (2026-10-24):** 700 boards monitored (all trials until the first weekly cycle about 2026-10-29), about 700 relevant boards waiting, relevant-board coverage about 53%; Events tab about 150k rows and growing with each admitted board's baseline.
- **Pilot week 1 (live):** 168/168 hourly intervals polled; 20 alerts, 0 duplicates, 0 failed sends; publication -> detection median 29 min. About 3 alerts and 7 tracker rows a day; target after the 2026-10-23 Settings change is 20-30 tracker rows a day.
- **Settings live in the Sheet** (`Settings` tab); the code defaults in `hunter.py` apply only to missing rows. The user's live roles, levels, exclusions and locations differ from the defaults.
- **Hourly cadence depends on an external trigger** (GitHub's own schedule fired only about every 4.4 h).
- **Known concerns:** `.planning/codebase/CONCERNS.md` (alert-path contract bugs, Events growth, SmartRecruiters override past the pilot, 1,981-line `hunter.py`, non-atomic Sheet lease).

## Constraints

- **Freshness**: never use update, crawl or search-engine time as publication time — the product (AGENTS rule 2)
- **Identity**: ATS + board + posting ID; never dedupe on URL strings (AGENTS rule 3)
- **State**: seen / evaluated / alerted separate; failures leave later stages retryable (AGENTS rule 4)
- **Honesty**: say what was mocked vs live; no live claims without credentials (AGENTS rule 5)
- **Secrets**: never read, print or commit `.env`, `Resume.pdf`, `resume.txt`, service-account JSON (AGENTS rule 6)
- **Scope gate**: no score tuning or new features until the evidence is read (AGENTS rule 7)
- **Tests**: `.venv/bin/python -m unittest discover -s tests`, offline, before finishing (AGENTS rule 8)
- **Docs**: a deliberate behaviour change updates SPEC / DECISIONS / STATUS in the same change (AGENTS rule 1)
- **Runtime**: GitHub Actions (25 min poller timeout), Google Sheets quotas and the 10M-cell limit, Groq and Tavily free tiers

## Key Decisions

All 47 decisions are in `DECISIONS.md` (locked; later entries amend earlier ones, see `.planning/intel/decisions.md` for the chains). The ones that most constrain v2:

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| D-03 append-only Events ledger in the Sheet | Durable, auditable state without a database | ⚠️ Revisit (D-43 storage, STOR-01) |
| D-16 Groq models `gpt-oss-120b` / `20b` | Requested models no longer exist | — Pending owner OK (GOV-01) |
| D-30 pool parameters (80/20, 7-day trials, margin 1.0, ...) | Initial operating choices | — Pending first weekly evidence (EVID-01) |
| D-38 SmartRecruiters unparked for the pilot | Owner decision despite robots.txt | ⚠️ Revisit: pilot ended (GOV-01) |
| D-45 graduation floor 2.0 | Stop score-0 trials taking established slots at 700 | — Pending EVID-01 |
| D-46 tracker without header is refused | Prevent writes by position | ✓ Good (verified live) |
| D-47 early release + 5,000 re-checks per run | Free slots held by failed trials | ✓ Good so far (220 released, refilled to 679/700) |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-10-25 after starting milestone v2.0*
