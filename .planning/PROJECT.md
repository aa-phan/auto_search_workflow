# Auto Search Workflow

## What This Is

Fresh-job alerts for one non-technical job seeker (entry-level marketing, content and design roles; Texas, New York and US remote/hybrid). The system polls public ATS job boards hourly (Greenhouse, Lever, Ashby, Workable, SmartRecruiters), detects new postings, verifies their freshness from source publication evidence, filters and scores them against the resume with Groq, and delivers matches to a Google Sheet (the only interface: settings in, tracker out) and Telegram. It runs entirely on GitHub Actions with the Sheet as its datastore.

Contract and rationale live outside `.planning/` and win over anything here: `SPEC.md` (contract), `DECISIONS.md` (why, D-01..D-47), `STATUS.md` (what is verified live vs mocked), `AGENTS.md` (agent rules), `PILOT_LOG.md` (deployments that affect measurements). Code map: `.planning/codebase/`.

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

<!-- v2 candidates; the milestone scope is chosen by /gsd-new-milestone. -->

- [ ] Read the evidence first: weekly rebalance, limits at 700, effect of the broadened Settings, D-47 follow-up, My_Feedback vs score, re-check interval (EVID-01..06)
- [ ] Contract and reliability fixes on the alert path, watchdog trigger, live-test gaps (REL-01..05)
- [ ] Events storage decision and migration (STOR-01)
- [ ] Daily digest and title-gate leaks (FEAT-01, FILT-03) — gated by AGENTS.md rule 7
- [ ] Split `hunter.py`, pin dependencies (MAINT-01..02)
- [ ] Record open owner decisions (GOV-01)

### Out of Scope

- Tuning scores — gated by AGENTS.md rule 7 and SPEC "Out of scope for now"; needs EVID-05 and an owner decision
- Additional ATSs, non-US markets — SPEC scope; no adapters, non-US excluded by design (D-08)
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

---
*Last updated: 2026-10-24 after /gsd-ingest-docs (merge) and codebase map refresh*
